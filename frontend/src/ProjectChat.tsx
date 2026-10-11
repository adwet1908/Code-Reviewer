import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { chatProject, fetchModels } from "./api";
import { ModelSelect } from "./ModelSelect";
import type { ChatTurn, ModelOption, RetrievedChunk } from "./types";

type Message = ChatTurn & { sources?: RetrievedChunk[] };

type Props = {
  projectId: number;
  ready: boolean;
  chunkCount: number;
  statusMessage: string | null;
};

export function ProjectChat({ projectId, ready, chunkCount, statusMessage }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchModels()
      .then((r) => {
        setModels(r.models);
        setSelectedModel(r.default);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send() {
    const text = draft.trim();
    if (!text || loading || !ready || chunkCount < 1) return;

    const userMessage: Message = { role: "user", content: text };
    const history = messages.map(({ role, content }) => ({ role, content }));
    setMessages((prev) => [...prev, userMessage]);
    setDraft("");
    setLoading(true);
    setError(null);

    try {
      const response = await chatProject(projectId, {
        message: text,
        history,
        model: selectedModel,
      });
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: response.answer, sources: response.sources },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chat failed.");
      setMessages((prev) => prev.slice(0, -1));
      setDraft(text);
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  }

  return (
    <section className="panel chat-panel">
      <div className="chat-header">
        <h2>Ask about this codebase</h2>
        <label className="model-picker chat-model">
          <span>Model</span>
          <ModelSelect models={models} value={selectedModel} onChange={setSelectedModel} />
        </label>
      </div>
      {!ready && (
        <p className="hint">
          Chat waits until this project is indexed. {statusMessage ?? "Status is not ready yet."}
        </p>
      )}
      {ready && chunkCount < 1 && (
        <p className="hint">
          Status is ready, but this project has 0 chunks. Re-upload the repo zip so the files can be
          chunked and embedded.
        </p>
      )}
      {error && <p className="banner error">{error}</p>}

      <div className="chat-thread" aria-live="polite">
        {messages.length === 0 && (
          <p className="hint chat-empty">
            Example: “How does authentication work?” or “Where is the database configured?”
          </p>
        )}
        {messages.map((msg, index) => (
          <div key={index} className={`chat-bubble chat-${msg.role}`}>
            <p className="chat-role">{msg.role === "user" ? "You" : "Assistant"}</p>
            <div className="chat-body">{msg.content}</div>
            {msg.sources && msg.sources.length > 0 && (
              <details className="chat-sources">
                <summary>{msg.sources.length} source snippet{msg.sources.length === 1 ? "" : "s"}</summary>
                <ul>
                  {msg.sources.map((src) => (
                    <li key={src.chunk_id}>
                      <strong>{src.path}</strong> ({src.start_line}–{src.end_line}) · score {src.score.toFixed(3)}
                      <pre>{src.content}</pre>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        ))}
        {loading && <p className="hint chat-thinking">Thinking…</p>}
        <div ref={bottomRef} />
      </div>

      <div className="chat-compose">
        <textarea
          rows={3}
          placeholder={
            !ready
              ? "Waiting for project to finish indexing…"
              : chunkCount < 1
                ? "No chunks indexed yet…"
                : "Ask a question about this repo…"
          }
          value={draft}
          disabled={!ready || chunkCount < 1 || loading}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="button" className="primary" disabled={!ready || chunkCount < 1 || loading || !draft.trim()} onClick={send}>
          Send
        </button>
      </div>
    </section>
  );
}
