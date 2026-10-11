"""Retrieve related code and doc chunks for a target file."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import (
    CHAT_RETRIEVAL_TOP_K,
    DATABASE_URL,
    RETRIEVAL_CODE_TOP_K,
    RETRIEVAL_CONTEXT_MAX_CHARS,
    RETRIEVAL_DOC_TOP_N,
)
from app.models import Chunk
from app.services.vectors import cosine_similarity


@dataclass
class RetrievedChunk:
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    source_type: str
    content: str
    score: float


def retrieve_for_file(
    db: Session,
    project_id: int,
    target_path: str,
    code_top_k: int = RETRIEVAL_CODE_TOP_K,
    doc_top_n: int = RETRIEVAL_DOC_TOP_N,
) -> list[RetrievedChunk]:
    target_chunks = db.execute(
        select(Chunk).where(
            Chunk.project_id == project_id,
            Chunk.path == target_path,
            Chunk.embedding.is_not(None),
        )
    ).scalars().all()
    if not target_chunks:
        return []

    code_scores: dict[int, tuple[Chunk, float]] = {}
    doc_scores: dict[int, tuple[Chunk, float]] = {}

    for query_chunk in target_chunks:
        query_vec = list(query_chunk.embedding)
        _search(
            db,
            project_id,
            query_vec,
            source_type="code",
            exclude_path=target_path,
            scores=code_scores,
        )
        _search(
            db,
            project_id,
            query_vec,
            source_type="doc",
            exclude_path=None,
            scores=doc_scores,
        )

    code_ranked = sorted(code_scores.values(), key=lambda item: item[1], reverse=True)[:code_top_k]
    doc_ranked = sorted(doc_scores.values(), key=lambda item: item[1], reverse=True)[:doc_top_n]
    merged = code_ranked + doc_ranked

    results: list[RetrievedChunk] = []
    used_chars = 0
    for chunk, score in sorted(merged, key=lambda item: item[1], reverse=True):
        block = _format_block(chunk, score)
        if used_chars + len(block) > RETRIEVAL_CONTEXT_MAX_CHARS:
            continue
        used_chars += len(block)
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                path=chunk.path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                source_type=chunk.source_type,
                content=chunk.content,
                score=score,
            )
        )
    return sorted(results, key=lambda item: item.score, reverse=True)


def retrieve_for_question(
    db: Session,
    project_id: int,
    query: str,
    top_k: int = CHAT_RETRIEVAL_TOP_K,
) -> list[RetrievedChunk]:
    """Embed the user question and pull the best-matching chunks across the repo."""
    from app.services.embeddings import embed_query

    query_vec = embed_query(query)
    scores: dict[int, tuple[Chunk, float]] = {}
    _search(db, project_id, query_vec, source_type=None, exclude_path=None, scores=scores)
    ranked = sorted(scores.values(), key=lambda item: item[1], reverse=True)[: top_k * 2]

    results: list[RetrievedChunk] = []
    used_chars = 0
    for chunk, score in ranked:
        block = _format_block(chunk, score)
        if used_chars + len(block) > RETRIEVAL_CONTEXT_MAX_CHARS:
            continue
        used_chars += len(block)
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                path=chunk.path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                source_type=chunk.source_type,
                content=chunk.content,
                score=score,
            )
        )
        if len(results) >= top_k:
            break
    return results


def search_project(
    db: Session,
    project_id: int,
    query: str,
    k: int = 5,
) -> list[RetrievedChunk]:
    from app.services.embeddings import embed_query

    query_vec = embed_query(query)
    scores: dict[int, tuple[Chunk, float]] = {}
    _search(db, project_id, query_vec, source_type=None, exclude_path=None, scores=scores)
    ranked = sorted(scores.values(), key=lambda item: item[1], reverse=True)[:k]
    return [
        RetrievedChunk(
            chunk_id=chunk.id,
            path=chunk.path,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            source_type=chunk.source_type,
            content=chunk.content,
            score=score,
        )
        for chunk, score in ranked
    ]


def _search(
    db: Session,
    project_id: int,
    query_vec: list[float],
    source_type: str | None,
    exclude_path: str | None,
    scores: dict[int, tuple[Chunk, float]],
) -> None:
    if DATABASE_URL.startswith("sqlite"):
        stmt = select(Chunk).where(
            Chunk.project_id == project_id,
            Chunk.embedding.is_not(None),
        )
        if source_type:
            stmt = stmt.where(Chunk.source_type == source_type)
        if exclude_path:
            stmt = stmt.where(Chunk.path != exclude_path)
        for chunk in db.execute(stmt).scalars():
            score = cosine_similarity(query_vec, list(chunk.embedding))
            prev = scores.get(chunk.id)
            if prev is None or score > prev[1]:
                scores[chunk.id] = (chunk, score)
        return

    distance = Chunk.embedding.cosine_distance(query_vec)
    stmt = select(Chunk, distance.label("distance")).where(
        Chunk.project_id == project_id,
        Chunk.embedding.is_not(None),
    )
    if source_type:
        stmt = stmt.where(Chunk.source_type == source_type)
    if exclude_path:
        stmt = stmt.where(Chunk.path != exclude_path)
    stmt = stmt.order_by(distance).limit(50)
    for chunk, dist in db.execute(stmt):
        score = 1.0 - float(dist)
        prev = scores.get(chunk.id)
        if prev is None or score > prev[1]:
            scores[chunk.id] = (chunk, score)


def _format_block(chunk: Chunk, score: float) -> str:
    return (
        f"[{chunk.path}:{chunk.start_line}-{chunk.end_line} score={score:.3f}]\n"
        f"{chunk.content}\n"
    )


def format_retrieved_context(chunks: list[RetrievedChunk]) -> tuple[str, str]:
    code_parts: list[str] = []
    doc_parts: list[str] = []
    for item in chunks:
        block = (
            f"### {item.path} (lines {item.start_line}-{item.end_line}, score {item.score:.3f})\n"
            f"{item.content}"
        )
        if item.source_type == "doc":
            doc_parts.append(block)
        else:
            code_parts.append(block)
    return "\n\n".join(code_parts), "\n\n".join(doc_parts)
