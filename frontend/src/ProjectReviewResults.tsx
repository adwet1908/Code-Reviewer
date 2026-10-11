import { useState } from "react";
import { Results } from "./Results";
import type { ProjectReviewResponse, StoredReview } from "./types";

export function ProjectReviewResults({ response }: { response: ProjectReviewResponse }) {
  const panels = [
    response.with_retrieval ? { label: "With RAG", data: response.with_retrieval } : null,
    response.without_retrieval ? { label: "Without RAG", data: response.without_retrieval } : null,
  ].filter((item): item is { label: string; data: StoredReview } => item !== null);

  return (
    <section className="compare-grid">
      {panels.map((panel) => (
        <div key={panel.label} className="panel">
          <h2>{panel.label}</h2>
          <Results
            response={{
              model: panel.data.model,
              files: [{ filename: response.file_path, review: panel.data.review }],
            }}
          />
          <ContextPanel chunks={panel.data.context_used} findings={panel.data.review.findings} />
        </div>
      ))}
    </section>
  );
}

function ContextPanel({
  chunks,
  findings,
}: {
  chunks: StoredReview["context_used"];
  findings: StoredReview["review"]["findings"];
}) {
  const [open, setOpen] = useState(false);
  if (chunks.length === 0) return null;
  const cited = new Set(
    findings.flatMap((f) => (f.evidence ?? []).map((e) => `${e.path}:${e.start_line}-${e.end_line}`)),
  );
  return (
    <div className="context-panel">
      <button type="button" className="text" onClick={() => setOpen((v) => !v)}>
        {open ? "Hide" : "Show"} context used ({chunks.length})
      </button>
      {open && (
        <ul className="context-list">
          {chunks.map((chunk) => {
            const key = `${chunk.path}:${chunk.start_line}-${chunk.end_line}`;
            return (
              <li key={chunk.chunk_id} className={cited.has(key) ? "cited" : ""}>
                <strong>{chunk.path}</strong> ({chunk.start_line}-{chunk.end_line}) · score {chunk.score.toFixed(3)}
                <pre>{chunk.content.slice(0, 400)}{chunk.content.length > 400 ? "…" : ""}</pre>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
