import { clearSession, getToken } from "./authStorage";
import type { AuthUser } from "./authStorage";
import type {
  ChatTurn,
  ModelsResponse,
  Project,
  ProjectChatResponse,
  ProjectFile,
  ProjectReviewResponse,
  ReviewResponse,
  UserModel,
} from "./types";

export type AgentProgressEvent = {
  type: "agent";
  agent: string;
  status: string;
  detail?: string | null;
};

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");

export function apiBaseUrl(): string {
  return API_BASE;
}

export type TokenResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
};

export async function register(email: string, password: string): Promise<TokenResponse> {
  return postJson<TokenResponse>("/auth/register", { email, password });
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  return postJson<TokenResponse>("/auth/login", { email, password });
}

export async function fetchMe(): Promise<AuthUser> {
  return requestJson<AuthUser>("/auth/me", { method: "GET" });
}

export async function fetchModels(): Promise<ModelsResponse> {
  return requestJson<ModelsResponse>("/models", { method: "GET" });
}

export async function fetchUserModels(): Promise<UserModel[]> {
  return requestJson<UserModel[]>("/settings/models", { method: "GET" });
}

export async function createUserModel(payload: {
  label: string;
  provider: string;
  model_id: string;
  api_key: string;
  base_url: string | null;
}): Promise<UserModel> {
  return postJson<UserModel>("/settings/models", payload);
}

export async function updateUserModel(
  modelPk: number,
  payload: {
    label: string;
    provider: string;
    model_id: string;
    api_key?: string;
    base_url: string | null;
  },
): Promise<UserModel> {
  return requestJson<UserModel>(`/settings/models/${modelPk}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteUserModel(modelPk: number): Promise<UserModel> {
  return requestJson<UserModel>(`/settings/models/${modelPk}`, { method: "DELETE" });
}

export async function updateDefaultModel(model: string): Promise<{ default: string }> {
  return requestJson<{ default: string }>("/settings/default-model", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
}

export async function fetchProjects(): Promise<Project[]> {
  return requestJson<Project[]>("/projects", { method: "GET" });
}

export async function fetchProject(projectId: number): Promise<Project> {
  return requestJson<Project>(`/projects/${projectId}`, { method: "GET" });
}

export async function fetchProjectFiles(projectId: number): Promise<ProjectFile[]> {
  return requestJson<ProjectFile[]>(`/projects/${projectId}/files`, { method: "GET" });
}

export async function createProject(name: string, repoZip: File, docs: File[]): Promise<Project> {
  const body = new FormData();
  body.append("name", name);
  body.append("repo_zip", repoZip);
  for (const doc of docs) body.append("docs", doc);
  return requestJson<Project>("/projects", { method: "POST", body });
}

export async function deleteProject(projectId: number): Promise<Project> {
  return requestJson<Project>(`/projects/${projectId}`, { method: "DELETE" });
}

export async function chatProject(
  projectId: number,
  payload: { message: string; history: ChatTurn[]; model: string },
): Promise<ProjectChatResponse> {
  return postJson<ProjectChatResponse>(`/projects/${projectId}/chat`, payload);
}

export async function reviewProjectFile(
  projectId: number,
  payload: {
    file_path: string;
    use_retrieval: boolean;
    compare_without_rag: boolean;
    model: string;
    pipeline_mode: "simple" | "agentic";
  },
): Promise<ProjectReviewResponse> {
  return postJson<ProjectReviewResponse>(`/projects/${projectId}/review`, payload);
}

export async function reviewProjectFileStream(
  projectId: number,
  payload: {
    file_path: string;
    use_retrieval: boolean;
    compare_without_rag: boolean;
    model: string;
    pipeline_mode: "simple" | "agentic";
  },
  onAgent: (event: AgentProgressEvent) => void,
): Promise<ProjectReviewResponse> {
  const headers = new Headers({ "Content-Type": "application/json", Accept: "text/event-stream" });
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}/projects/${projectId}/review/stream`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error(`Could not reach the API at ${API_BASE}. Is the backend running?`);
  }

  if (response.status === 401) {
    clearSession();
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    throw new Error(messageFromDetail(body?.detail, response.status));
  }
  if (!response.body) {
    throw new Error("Streaming response had no body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: ProjectReviewResponse | null = null;
  let streamError: string | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const block of parts) {
      const parsed = parseSseBlock(block);
      if (!parsed) continue;
      if (parsed.event === "agent" && parsed.data && typeof parsed.data === "object") {
        onAgent(parsed.data as AgentProgressEvent);
      } else if (parsed.event === "result" && parsed.data && typeof parsed.data === "object") {
        const payload = parsed.data as { data?: ProjectReviewResponse };
        result = payload.data ?? (parsed.data as ProjectReviewResponse);
      } else if (parsed.event === "error") {
        const detail = (parsed.data as { detail?: string } | null)?.detail;
        streamError = detail || "Agentic review failed.";
      }
    }
  }

  if (streamError) throw new Error(streamError);
  if (!result) throw new Error("Stream ended without a review result.");
  return result;
}

function parseSseBlock(block: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return { event, data: dataLines.join("\n") };
  }
}

export async function requestReview(files: File[], model: string): Promise<ReviewResponse> {
  const body = new FormData();
  for (const file of files) {
    body.append("files", file);
  }
  body.append("model", model);
  return requestJson<ReviewResponse>("/review", { method: "POST", body });
}

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new Error(`Could not reach the API at ${API_BASE}. Is the backend running?`);
  }

  if (response.status === 401 && path !== "/auth/login") {
    clearSession();
  }

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    throw new Error(messageFromDetail(payload?.detail, response.status));
  }
  return response.json() as Promise<T>;
}

function messageFromDetail(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === "object" && "msg" in item) {
        return String((item as { msg: unknown }).msg);
      }
      return String(item);
    });
    if (parts.length > 0) return parts.join(" ");
  }
  return `Request failed (${status}).`;
}
