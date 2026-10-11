"""Persist reviews and retrieval audit rows."""

import json

from sqlalchemy.orm import Session

from app.models import Review, ReviewRetrieval
from app.schemas import Review as ReviewSchema
from app.services.retrieval import RetrievedChunk


def save_review(
    db: Session,
    user_id: int,
    model: str,
    review: ReviewSchema,
    project_id: int | None,
    file_path: str | None,
    retrieval_enabled: bool,
    retrieved: list[RetrievedChunk],
) -> Review:
    row = Review(
        user_id=user_id,
        project_id=project_id,
        file_path=file_path,
        model=model,
        retrieval_enabled=retrieval_enabled,
        summary=review.summary,
        findings_json=json.dumps([finding.model_dump() for finding in review.findings]),
    )
    db.add(row)
    db.flush()
    for rank, item in enumerate(retrieved, start=1):
        db.add(
            ReviewRetrieval(
                review_id=row.id,
                chunk_id=item.chunk_id,
                score=item.score,
                rank=rank,
            )
        )
    db.commit()
    db.refresh(row)
    return row
