export type Severity = "critical" | "high" | "medium" | "low";
export type Category = "bug" | "edge_case" | "security" | "performance" | "readability";

export type EvidenceRef = {
  path: string;
  start_line: number;
  end_line: number;
};

export type Finding = {
  severity: Severity;
  category: Category;
  location: string;
  issue: string;
  suggestion: string;
  evidence?: EvidenceRef[] | null;
};

export type FileReview = {
  filename: string;
  review: {
    summary: string;
    findings: Finding[];
  };
};

export type ReviewResponse = {
  files: FileReview[];
  model: string;
};

export type ModelOption = {
  id: string;
  label: string;
  source?: "builtin" | "custom";
  provider?: string;
};

export type ModelsResponse = {
  default: string;
  models: ModelOption[];
};

export type UserModel = {
  id: number;
  selection_id: string;
  label: string;
  provider: "gemini" | "openai" | "anthropic";
  model_id: string;
  api_key_hint: string;
  base_url: string | null;
};

export type Project = {
  id: number;
  name: string;
  status: string;
  file_count: number;
  chunk_count: number;
  status_message: string | null;
  warning_message: string | null;
};

export type ProjectFile = {
  id: number;
  path: string;
  language: string;
};

export type RetrievedChunk = {
  chunk_id: number;
  path: string;
  start_line: number;
  end_line: number;
  source_type: string;
  content: string;
  score: number;
};

export type PipelineMode = "simple" | "agentic";

export type DroppedFinding = {
  location: string;
  issue: string;
  reason: string;
  verdict?: string | null;
};

export type StoredReview = {
  review_id: number;
  model: string;
  retrieval_enabled: boolean;
  review: { summary: string; findings: Finding[] };
  context_used: RetrievedChunk[];
  pipeline_mode?: PipelineMode;
  call_count?: number | null;
  dropped_findings?: DroppedFinding[] | null;
  warning?: string | null;
};

export type ProjectReviewResponse = {
  file_path: string;
  with_retrieval?: StoredReview | null;
  without_retrieval?: StoredReview | null;
  pipeline_mode?: PipelineMode;
};

export type ChatTurn = {
  role: "user" | "assistant";
  content: string;
};

export type ProjectChatResponse = {
  answer: string;
  sources: RetrievedChunk[];
};
