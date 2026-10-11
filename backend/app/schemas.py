"""Response shapes shared by the API and the Gemini schema."""

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

Severity = Literal["critical", "high", "medium", "low"]
Category = Literal["bug", "edge_case", "security", "performance", "readability"]


class EvidenceRef(BaseModel):
    path: str
    start_line: int
    end_line: int


class Finding(BaseModel):
    severity: Severity
    category: Category
    location: str = Field(description="Line number or range from the numbered source, e.g. '12' or '12-18'.")
    issue: str
    suggestion: str
    evidence: list[EvidenceRef] | None = None
    # Used by the agentic pipeline when a finding relies on retrieved chunks.
    evidence_chunk_ids: list[int] | None = None


class Review(BaseModel):
    summary: str
    findings: list[Finding]


class FileReview(BaseModel):
    """One independent review. Phase 1 does not merge findings across files."""

    filename: str
    review: Review


class ReviewResponse(BaseModel):
    files: list[FileReview]
    model: str


class ModelOption(BaseModel):
    id: str
    label: str
    source: Literal["builtin", "custom"] = "builtin"
    provider: str = "gemini"


class ModelsResponse(BaseModel):
    default: str
    models: list[ModelOption]


ProviderName = Literal["gemini", "openai", "anthropic"]


class UserModelCreate(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    provider: ProviderName
    model_id: str = Field(min_length=1, max_length=128)
    api_key: str = Field(min_length=1, max_length=512)
    base_url: str | None = Field(default=None, max_length=512)


class UserModelUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    provider: ProviderName | None = None
    model_id: str | None = Field(default=None, min_length=1, max_length=128)
    api_key: str | None = Field(default=None, min_length=1, max_length=512)
    base_url: str | None = Field(default=None, max_length=512)


class UserModelOut(BaseModel):
    id: int
    selection_id: str
    label: str
    provider: str
    model_id: str
    api_key_hint: str
    base_url: str | None

    model_config = {"from_attributes": True}


class DefaultModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: int
    email: EmailStr

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ProjectOut(BaseModel):
    id: int
    name: str
    status: str
    file_count: int
    chunk_count: int
    status_message: str | None
    warning_message: str | None

    model_config = {"from_attributes": True}


class ProjectFileOut(BaseModel):
    id: int
    path: str
    language: str

    model_config = {"from_attributes": True}


class RetrievedChunkOut(BaseModel):
    chunk_id: int
    path: str
    start_line: int
    end_line: int
    source_type: str
    content: str
    score: float


PipelineMode = Literal["simple", "agentic"]


class DroppedFinding(BaseModel):
    location: str
    issue: str
    reason: str
    verdict: str | None = None


class ProjectReviewRequest(BaseModel):
    file_path: str
    use_retrieval: bool = True
    model: str | None = None
    compare_without_rag: bool = False
    pipeline_mode: PipelineMode = "simple"


class StoredReviewOut(BaseModel):
    review_id: int
    model: str
    retrieval_enabled: bool
    review: Review
    context_used: list[RetrievedChunkOut]
    pipeline_mode: PipelineMode = "simple"
    call_count: int | None = None
    dropped_findings: list[DroppedFinding] | None = None
    warning: str | None = None


class ProjectReviewResponse(BaseModel):
    file_path: str
    with_retrieval: StoredReviewOut | None = None
    without_retrieval: StoredReviewOut | None = None
    pipeline_mode: PipelineMode = "simple"


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=16000)


class ProjectChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: list[ChatTurn] = Field(default_factory=list)
    model: str | None = None


class ProjectChatResponse(BaseModel):
    answer: str
    sources: list[RetrievedChunkOut]
