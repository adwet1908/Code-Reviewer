import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AgentProgress, applyAgentEvent, emptyAgentSteps, type AgentStep } from "../AgentProgress";
import {
  deleteProject,
  fetchModels,
  fetchProject,
  fetchProjectFiles,
  reviewProjectFile,
  reviewProjectFileStream,
} from "../api";
import { ModelSelect } from "../ModelSelect";
import { ProjectChat } from "../ProjectChat";
import { ProjectReviewResults } from "../ProjectReviewResults";
import type { ModelOption, PipelineMode, Project, ProjectFile, ProjectReviewResponse } from "../types";

export function ProjectDetailPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const id = Number(projectId);
  const [project, setProject] = useState<Project | null>(null);
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [selectedPath, setSelectedPath] = useState<string>("");
  const [useRag, setUseRag] = useState(true);
  const [compare, setCompare] = useState(false);
  const [pipelineMode, setPipelineMode] = useState<PipelineMode>("simple");
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [result, setResult] = useState<ProjectReviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [tab, setTab] = useState<"review" | "chat">("chat");
  const [agentSteps, setAgentSteps] = useState<AgentStep[]>(() => emptyAgentSteps());
  const [activeAgent, setActiveAgent] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const timer = setInterval(() => {
      fetchProject(id).then(setProject).catch(() => undefined);
    }, 2000);
    fetchProject(id).then(setProject).catch((err) => setError(String(err)));
    fetchProjectFiles(id).then((list) => {
      setFiles(list);
      if (list.length > 0) setSelectedPath(list[0].path);
    }).catch(() => undefined);
    fetchModels().then((r) => {
      setModels(r.models);
      setSelectedModel(r.default);
    }).catch(() => undefined);
    return () => clearInterval(timer);
  }, [id]);

  async function runReview() {
    if (!selectedPath) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setAgentSteps(emptyAgentSteps());
    setActiveAgent(null);
    const payload = {
      file_path: selectedPath,
      use_retrieval: useRag,
      compare_without_rag: compare,
      model: selectedModel,
      pipeline_mode: pipelineMode,
    };
    try {
      if (pipelineMode === "agentic") {
        const response = await reviewProjectFileStream(id, payload, (event) => {
          setActiveAgent(event.status === "running" ? event.agent : null);
          setAgentSteps((prev) => applyAgentEvent(prev, event.agent, event.status, event.detail));
        });
        setActiveAgent(null);
        setResult(response);
      } else {
        setResult(await reviewProjectFile(id, payload));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review failed.");
      setActiveAgent(null);
    } finally {
      setLoading(false);
    }
  }

  async function onDelete() {
    if (!project) return;
    if (!window.confirm(`Delete “${project.name}”? This removes its files, chunks, and reviews.`)) {
      return;
    }
    setDeleting(true);
    setError(null);
    try {
      await deleteProject(id);
      navigate("/projects", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete project.");
      setDeleting(false);
    }
  }

  if (!project) return <p className="hint">Loading project…</p>;

  return (
    <>
      <div className="row-between">
        <h1>{project.name}</h1>
        <button type="button" className="text" disabled={deleting} onClick={onDelete}>
          {deleting ? "Deleting…" : "Delete project"}
        </button>
      </div>
      <p className="meta">
        Status: {project.status} · {project.file_count} files · {project.chunk_count} chunks
      </p>
      {project.status_message && <p className="hint">{project.status_message}</p>}
      {project.warning_message && <p className="banner error">{project.warning_message}</p>}
      {error && <p className="banner error">{error}</p>}

      <div className="tab-bar">
        <button
          type="button"
          className={tab === "chat" ? "chip active" : "chip"}
          onClick={() => setTab("chat")}
        >
          Chat
        </button>
        <button
          type="button"
          className={tab === "review" ? "chip active" : "chip"}
          onClick={() => setTab("review")}
        >
          File review
        </button>
      </div>

      {tab === "chat" && (
        <ProjectChat
          projectId={id}
          ready={project.status === "ready"}
          chunkCount={project.chunk_count}
          statusMessage={project.status_message}
        />
      )}

      {tab === "review" && (
      <section className="panel project-layout">
        <div>
          <h2>Files</h2>
          <ul className="file-tree">
            {files.map((file) => (
              <li key={file.id}>
                <button
                  type="button"
                  className={selectedPath === file.path ? "chip active" : "chip"}
                  onClick={() => setSelectedPath(file.path)}
                >
                  {file.path}
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h2>Review</h2>
          <label className="model-picker">
            <span>Model</span>
            <ModelSelect models={models} value={selectedModel} onChange={setSelectedModel} />
          </label>
          <fieldset className="pipeline-mode">
            <legend>Pipeline</legend>
            <label className="toggle">
              <input
                type="radio"
                name="pipeline"
                checked={pipelineMode === "simple"}
                onChange={() => setPipelineMode("simple")}
              />
              Simple (Phase 2)
            </label>
            <label className="toggle">
              <input
                type="radio"
                name="pipeline"
                checked={pipelineMode === "agentic"}
                onChange={() => setPipelineMode("agentic")}
              />
              Agentic (Phase 3)
            </label>
          </fieldset>
          <label className="toggle">
            <input
              type="checkbox"
              checked={useRag}
              disabled={pipelineMode === "agentic"}
              onChange={(e) => setUseRag(e.target.checked)}
            />
            Use repo context (RAG)
          </label>
          <label className="toggle">
            <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
            Compare with and without RAG
          </label>
          <button
            type="button"
            className="primary"
            disabled={loading || project.status !== "ready" || !selectedPath}
            onClick={runReview}
          >
            {loading ? (pipelineMode === "agentic" ? "Agents running…" : "Reviewing…") : "Review file"}
          </button>
        </div>
      </section>
      )}

      {tab === "review" && pipelineMode === "agentic" && loading && (
        <AgentProgress steps={agentSteps} active={activeAgent} />
      )}
      {tab === "review" && pipelineMode === "agentic" && !loading && result && (
        <AgentProgress steps={agentSteps} active={null} />
      )}
      {tab === "review" && result && <ProjectReviewResults response={result} />}
    </>
  );
}
