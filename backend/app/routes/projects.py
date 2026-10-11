"""Phase 2 project ingestion and RAG review routes."""

import json
import queue
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import CHAT_HISTORY_MAX_TURNS
from app.db import SessionLocal, get_db
from app.deps import get_current_user, get_user_project
from app.models import Chunk, Project, ProjectFile, Review, ReviewRetrieval, User
from app.schemas import (
    ProjectFileOut,
    ProjectOut,
    ProjectChatRequest,
    ProjectChatResponse,
    ProjectReviewRequest,
    ProjectReviewResponse,
    RetrievedChunkOut,
    StoredReviewOut,
)
from app.services.agentic_pipeline import run_agentic_review
from app.services.ingest import number_lines
from app.services.llm import LLMError, chat_about_codebase, review_code
from app.services.model_catalog import ModelRuntime, resolve_runtime
from app.services.project_ingest import run_project_ingestion
from app.services.retrieval import (
    format_retrieved_context,
    retrieve_for_file,
    retrieve_for_question,
    search_project,
)
from app.services.review_store import save_review

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Project]:
    projects = list(db.scalars(select(Project).where(Project.user_id == user.id).order_by(Project.id.desc())))
    for project in projects:
        if project.status == "ready" and project.chunk_count == 0:
            _sync_chunk_count(db, project)
    return projects


@router.post("", response_model=ProjectOut)
async def create_project(
    background_tasks: BackgroundTasks,
    name: str = Form(...),
    repo_zip: UploadFile = File(...),
    docs: list[UploadFile] = File(default=[]),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Project:
    if not repo_zip.filename or not repo_zip.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload a .zip archive of the repository.")

    zip_bytes = await repo_zip.read()
    doc_pairs: list[tuple[str, bytes]] = []
    for upload in docs:
        raw = upload.filename or "document"
        doc_pairs.append((Path(raw).name, await upload.read()))

    project = Project(user_id=user.id, name=name.strip() or "Untitled project", status="pending")
    db.add(project)
    db.commit()
    db.refresh(project)

    project_id = project.id

    def ingest_task() -> None:
        session = SessionLocal()
        try:
            run_project_ingestion(session, project_id, zip_bytes, doc_pairs)
        finally:
            session.close()

    background_tasks.add_task(ingest_task)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project: Project = Depends(get_user_project), db: Session = Depends(get_db)) -> Project:
    _sync_chunk_count(db, project)
    return project


@router.delete("/{project_id}", response_model=ProjectOut)
def delete_project(
    project: Project = Depends(get_user_project),
    db: Session = Depends(get_db),
) -> Project:
    """Delete a project and its files, chunks, and project-scoped reviews."""
    out = ProjectOut.model_validate(project)
    project_id = project.id

    review_ids = select(Review.id).where(Review.project_id == project_id)
    chunk_ids = select(Chunk.id).where(Chunk.project_id == project_id)
    db.execute(
        delete(ReviewRetrieval).where(
            (ReviewRetrieval.review_id.in_(review_ids)) | (ReviewRetrieval.chunk_id.in_(chunk_ids))
        )
    )
    db.execute(delete(Review).where(Review.project_id == project_id))
    db.execute(delete(Chunk).where(Chunk.project_id == project_id))
    db.execute(delete(ProjectFile).where(ProjectFile.project_id == project_id))
    db.execute(delete(Project).where(Project.id == project_id))
    db.commit()
    return out


@router.get("/{project_id}/files", response_model=list[ProjectFileOut])
def list_project_files(project: Project = Depends(get_user_project), db: Session = Depends(get_db)) -> list[ProjectFile]:
    return list(
        db.scalars(
            select(ProjectFile)
            .where(ProjectFile.project_id == project.id)
            .order_by(ProjectFile.path)
        )
    )


@router.get("/{project_id}/search", response_model=list[RetrievedChunkOut])
def debug_search(
    q: str,
    k: int = 5,
    project: Project = Depends(get_user_project),
    db: Session = Depends(get_db),
) -> list[RetrievedChunkOut]:
    if project.status != "ready":
        raise HTTPException(status_code=400, detail="Project is not ready for search.")
    try:
        hits = search_project(db, project.id, q, k=k)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [_chunk_out(item) for item in hits]


@router.post("/{project_id}/chat", response_model=ProjectChatResponse)
def chat_about_project(
    body: ProjectChatRequest,
    project: Project = Depends(get_user_project),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectChatResponse:
    if project.status != "ready":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Project is still {project.status}"
                + (f": {project.status_message}" if project.status_message else "")
                + ". Wait until indexing finishes, or re-upload the zip if it failed."
            ),
        )
    _sync_chunk_count(db, project)
    if project.chunk_count < 1:
        raise HTTPException(
            status_code=400,
            detail="This project has no indexed chunks. Re-upload the repo zip so files can be chunked and embedded.",
        )

    try:
        runtime = resolve_runtime(db, user, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        retrieved = retrieve_for_question(db, project.id, body.message)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    related_code, related_docs = format_retrieved_context(retrieved)
    history = [(turn.role, turn.content) for turn in body.history[-CHAT_HISTORY_MAX_TURNS:]]

    try:
        answer = chat_about_codebase(
            body.message,
            related_code,
            related_docs,
            history,
            runtime,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ProjectChatResponse(
        answer=answer,
        sources=[_chunk_out(item) for item in retrieved],
    )


@router.post("/{project_id}/review", response_model=ProjectReviewResponse)
def review_project_file(
    body: ProjectReviewRequest,
    project: Project = Depends(get_user_project),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectReviewResponse:
    if project.status != "ready":
        raise HTTPException(status_code=400, detail=f"Project is not ready (status={project.status}).")

    file_row = db.scalar(
        select(ProjectFile).where(ProjectFile.project_id == project.id, ProjectFile.path == body.file_path)
    )
    if file_row is None:
        raise HTTPException(status_code=404, detail="File not found in this project.")

    try:
        runtime = resolve_runtime(db, user, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = ProjectReviewResponse(file_path=body.file_path, pipeline_mode=body.pipeline_mode)

    if body.pipeline_mode == "agentic":
        # Agentic graph owns retrieval; optional compare panel still uses simple mode.
        response.with_retrieval = _run_agentic_review(db, user.id, project.id, file_row, runtime)
        if body.compare_without_rag:
            response.without_retrieval = _run_one_review(
                db, user.id, project.id, file_row, runtime, use_retrieval=False
            )
        return response

    if body.compare_without_rag or body.use_retrieval:
        if body.use_retrieval:
            response.with_retrieval = _run_one_review(
                db, user.id, project.id, file_row, runtime, use_retrieval=True
            )
        if body.compare_without_rag or not body.use_retrieval:
            response.without_retrieval = _run_one_review(
                db, user.id, project.id, file_row, runtime, use_retrieval=False
            )
    return response


@router.post("/{project_id}/review/stream")
def review_project_file_stream(
    body: ProjectReviewRequest,
    project: Project = Depends(get_user_project),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """SSE stream of agent progress, then the final ProjectReviewResponse as event `result`."""
    if body.pipeline_mode != "agentic":
        raise HTTPException(status_code=400, detail="Streaming is only supported for pipeline_mode=agentic.")
    if project.status != "ready":
        raise HTTPException(status_code=400, detail=f"Project is not ready (status={project.status}).")

    file_row = db.scalar(
        select(ProjectFile).where(ProjectFile.project_id == project.id, ProjectFile.path == body.file_path)
    )
    if file_row is None:
        raise HTTPException(status_code=404, detail="File not found in this project.")

    try:
        runtime = resolve_runtime(db, user, body.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Snapshot values for the worker thread (request session must not cross threads).
    user_id = user.id
    project_id = project.id
    file_path = file_row.path
    file_content = file_row.content
    compare = body.compare_without_rag

    def event_stream() -> Iterator[str]:
        events: queue.Queue[dict | None] = queue.Queue()

        def on_progress(agent: str, status: str, detail: str | None = None) -> None:
            events.put({"type": "agent", "agent": agent, "status": status, "detail": detail})

        def worker() -> None:
            session = SessionLocal()
            try:
                numbered = number_lines(file_content)
                stored = _run_agentic_review(
                    session,
                    user_id,
                    project_id,
                    _FileShim(file_path, file_content),
                    runtime,
                    on_progress=on_progress,
                    numbered=numbered,
                )
                response = ProjectReviewResponse(
                    file_path=file_path,
                    pipeline_mode="agentic",
                    with_retrieval=stored,
                )
                if compare:
                    file_orm = session.scalar(
                        select(ProjectFile).where(
                            ProjectFile.project_id == project_id,
                            ProjectFile.path == file_path,
                        )
                    )
                    if file_orm is not None:
                        response.without_retrieval = _run_one_review(
                            session, user_id, project_id, file_orm, runtime, use_retrieval=False
                        )
                events.put({"type": "result", "data": response.model_dump(mode="json")})
            except Exception as exc:
                events.put({"type": "error", "detail": str(exc)})
            finally:
                session.close()
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = events.get()
            if item is None:
                break
            event_name = item.get("type", "message")
            yield f"event: {event_name}\ndata: {json.dumps(item)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class _FileShim:
    """Minimal stand-in for ProjectFile when we already have path + content."""

    def __init__(self, path: str, content: str) -> None:
        self.path = path
        self.content = content


def _run_agentic_review(
    db: Session,
    user_id: int,
    project_id: int,
    file_row: ProjectFile | _FileShim,
    runtime: ModelRuntime,
    on_progress: Callable[[str, str, str | None], None] | None = None,
    numbered: str | None = None,
) -> StoredReviewOut:
    numbered_source = numbered if numbered is not None else number_lines(file_row.content)
    try:
        result = run_agentic_review(
            db,
            project_id,
            file_row.path,
            numbered_source,
            runtime,
            on_progress=on_progress,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Agentic review failed: {exc}") from exc

    row = save_review(
        db,
        user_id=user_id,
        model=runtime.model_id,
        review=result.review,
        project_id=project_id,
        file_path=file_row.path,
        retrieval_enabled=True,
        retrieved=result.evidence,
    )
    return StoredReviewOut(
        review_id=row.id,
        model=runtime.model_id,
        retrieval_enabled=True,
        review=result.review,
        context_used=[_chunk_out(item) for item in result.evidence],
        pipeline_mode="agentic",
        call_count=result.call_count,
        dropped_findings=result.dropped_findings,
        warning=result.warning,
    )


def _run_one_review(
    db: Session,
    user_id: int,
    project_id: int,
    file_row: ProjectFile,
    runtime: ModelRuntime,
    use_retrieval: bool,
) -> StoredReviewOut:
    numbered = number_lines(file_row.content)
    related_code = ""
    related_docs = ""
    retrieved = []
    if use_retrieval:
        retrieved = retrieve_for_file(db, project_id, file_row.path)
        related_code, related_docs = format_retrieved_context(retrieved)

    try:
        review = review_code(
            numbered,
            file_row.path,
            context="",
            runtime=runtime,
            related_code=related_code,
            related_docs=related_docs,
            rag_mode=use_retrieval,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    row = save_review(
        db,
        user_id=user_id,
        model=runtime.model_id,
        review=review,
        project_id=project_id,
        file_path=file_row.path,
        retrieval_enabled=use_retrieval,
        retrieved=retrieved,
    )
    return StoredReviewOut(
        review_id=row.id,
        model=runtime.model_id,
        retrieval_enabled=use_retrieval,
        review=review,
        context_used=[_chunk_out(item) for item in retrieved],
        pipeline_mode="simple",
    )


def _sync_chunk_count(db: Session, project: Project) -> None:
    actual = db.scalar(select(func.count(Chunk.id)).where(Chunk.project_id == project.id)) or 0
    if project.chunk_count != actual:
        project.chunk_count = actual
        db.commit()
        db.refresh(project)


def _chunk_out(item) -> RetrievedChunkOut:
    return RetrievedChunkOut(
        chunk_id=item.chunk_id,
        path=item.path,
        start_line=item.start_line,
        end_line=item.end_line,
        source_type=item.source_type,
        content=item.content,
        score=item.score,
    )
