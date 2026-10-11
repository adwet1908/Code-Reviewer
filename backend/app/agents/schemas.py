"""Structured I/O for agentic pipeline nodes (not the public API Review schema)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas import Finding


class AnalysisResult(BaseModel):
    purpose: str = ""
    external_symbols_used: list[str] = Field(default_factory=list)
    risk_hypotheses: list[str] = Field(default_factory=list)
    retrieval_queries: list[str] = Field(default_factory=list)


class AgentFinding(Finding):
    """Finding plus chunk ids when the claim relies on retrieved context."""

    evidence_chunk_ids: list[int] | None = None


class AgentReviewDraft(BaseModel):
    summary: str = ""
    findings: list[AgentFinding] = Field(default_factory=list)


class CritiqueItem(BaseModel):
    finding_index: int
    verdict: Literal["keep", "drop", "needs_more_context"]
    reason: str = ""
    retrieval_query: str | None = None


class CritiqueResult(BaseModel):
    items: list[CritiqueItem] = Field(default_factory=list)


class DroppedFindingOut(BaseModel):
    location: str
    issue: str
    reason: str
    verdict: str | None = None
