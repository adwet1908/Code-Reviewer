"""Background ingestion: zip -> files -> chunks -> embeddings."""

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import MAX_PROJECT_CHUNKS, MAX_PROJECT_FILES
from app.models import Chunk, Project, ProjectFile
from app.services.chunker import chunk_file, language_for_path
from app.services.embeddings import EmbeddingError, embed_documents
from app.config import CONTEXT_EXTENSIONS
from app.services.ingest import IngestError, ingest_bytes, ingest_project_zip_bytes


@dataclass
class IngestedFile:
    path: str
    text: str
    source_type: str  # code | doc


def run_project_ingestion(db: Session, project_id: int, repo_zip: bytes, doc_uploads: list[tuple[str, bytes]]) -> None:
    project = db.get(Project, project_id)
    if project is None:
        return

    project.status = "ingesting"
    project.status_message = "Unpacking archive…"
    project.warning_message = None
    db.commit()

    try:
        files = _collect_files(repo_zip, doc_uploads)
        if not files:
            raise IngestError("No source files found in the upload.")

        truncated_files = False
        if len(files) > MAX_PROJECT_FILES:
            files = files[:MAX_PROJECT_FILES]
            truncated_files = True

        project.status_message = f"Saving {len(files)} files…"
        db.commit()

        file_rows: list[ProjectFile] = []
        for item in files:
            content_hash = hashlib.sha256(item.text.encode("utf-8")).hexdigest()
            row = ProjectFile(
                project_id=project.id,
                path=item.path,
                language=language_for_path(item.path),
                content_hash=content_hash,
                content=item.text,
            )
            db.add(row)
            file_rows.append(row)
        db.flush()
        project.file_count = len(file_rows)

        all_drafts: list[tuple[ProjectFile, object]] = []
        for row in file_rows:
            source_type = _source_type_for_path(row.path)
            for draft in chunk_file(row.path, row.content, source_type):
                all_drafts.append((row, draft))

        truncated_chunks = False
        if len(all_drafts) > MAX_PROJECT_CHUNKS:
            all_drafts = all_drafts[:MAX_PROJECT_CHUNKS]
            truncated_chunks = True

        project.status_message = f"Embedding {len(all_drafts)} chunks…"
        db.commit()

        hash_to_embedding: dict[str, list[float]] = {}
        existing = db.execute(
            select(Chunk.content_hash, Chunk.embedding).where(Chunk.project_id == project.id)
        ).all()
        for content_hash, embedding in existing:
            if embedding is not None:
                hash_to_embedding[content_hash] = list(embedding)

        pending_texts: list[str] = []
        pending_meta: list[tuple[ProjectFile, object]] = []
        for row, draft in all_drafts:
            if draft.content_hash in hash_to_embedding:
                _save_chunk(db, project.id, row, draft, hash_to_embedding[draft.content_hash])
                continue
            pending_texts.append(draft.content)
            pending_meta.append((row, draft))

        if pending_texts:
            vectors = embed_documents(pending_texts)
            for (row, draft), vector in zip(pending_meta, vectors, strict=True):
                hash_to_embedding[draft.content_hash] = vector
                _save_chunk(db, project.id, row, draft, vector)

        db.flush()
        project.chunk_count = len(all_drafts)
        project.status = "ready"
        project.status_message = "Ingestion complete."
        warnings: list[str] = []
        if truncated_files:
            warnings.append(f"Only the first {MAX_PROJECT_FILES} files were ingested.")
        if truncated_chunks:
            warnings.append(f"Only the first {MAX_PROJECT_CHUNKS} chunks were embedded.")
        project.warning_message = " ".join(warnings) if warnings else None
        db.commit()
    except (IngestError, EmbeddingError) as exc:
        project.status = "failed"
        project.status_message = str(exc)
        db.commit()
    except Exception as exc:
        project.status = "failed"
        project.status_message = f"Ingestion failed: {exc}"
        db.commit()


def _source_type_for_path(path: str) -> str:
    if path.startswith("docs/"):
        return "doc"
    lower = path.lower()
    if any(lower.endswith(ext) for ext in CONTEXT_EXTENSIONS):
        return "doc"
    return "code"


def _collect_files(repo_zip: bytes, doc_uploads: list[tuple[str, bytes]]) -> list[IngestedFile]:
    out: list[IngestedFile] = []
    for doc in ingest_project_zip_bytes("repo.zip", repo_zip):
        out.append(IngestedFile(path=doc.name, text=doc.text, source_type=doc.kind))
    for name, data in doc_uploads:
        safe_name = name.split("/")[-1].split("\\")[-1]
        path = f"docs/{safe_name}"
        for doc in ingest_bytes(safe_name, data):
            out.append(IngestedFile(path=path, text=doc.text, source_type="doc"))
    # Deduplicate paths, keep first.
    seen: set[str] = set()
    unique: list[IngestedFile] = []
    for item in out:
        if item.path in seen:
            continue
        seen.add(item.path)
        unique.append(item)
    return unique


def _save_chunk(db: Session, project_id: int, row: ProjectFile, draft, vector: list[float]) -> None:
    db.add(
        Chunk(
            project_id=project_id,
            file_id=row.id,
            source_type=draft.source_type,
            path=draft.path,
            start_line=draft.start_line,
            end_line=draft.end_line,
            symbol_name=draft.symbol_name,
            kind=draft.kind,
            content=draft.content,
            content_hash=draft.content_hash,
            embedding=vector,
        )
    )
