import { useEffect, useRef, useState } from "react";
import { fetchModels, requestReview } from "../api";
import { ModelSelect } from "../ModelSelect";
import { addFiles, formatBytes, kindOf } from "../fileRules";
import { Results } from "../Results";
import type { ModelOption, ReviewResponse } from "../types";

type Props = {
  onLogout: () => void;
};

export function QuickReviewPage({ onLogout }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [result, setResult] = useState<ReviewResponse | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState("");

  useEffect(() => {
    let cancelled = false;
    fetchModels()
      .then((response) => {
        if (cancelled) return;
        setModels(response.models);
        setSelectedModel(response.default);
      })
      .catch(() => {
        if (!cancelled) setFormError("Could not load model list from the API.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function takeFiles(list: FileList | null) {
    if (!list || list.length === 0) return;
    const outcome = addFiles(files, Array.from(list));
    setFiles(outcome.files);
    setFormError(outcome.error);
  }

  async function onSubmit() {
    if (files.length === 0) {
      setFormError("Add at least one file.");
      return;
    }
    const hasSource = files.some((file) => kindOf(file.name) === "code" || kindOf(file.name) === "zip");
    if (!hasSource) {
      setFormError("Add a source file or a zip.");
      return;
    }
    if (!selectedModel) {
      setFormError("Choose a model.");
      return;
    }
    setLoading(true);
    setRequestError(null);
    setFormError(null);
    try {
      setResult(await requestReview(files, selectedModel));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Review failed.";
      setRequestError(message);
      if (message === "Sign in to continue.") onLogout();
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <h1>Quick review (Phase 1)</h1>
      <p className="lede">Upload files without indexing a repo. No retrieval.</p>
      <section className="panel">
        <label className="model-picker">
          <span>Model</span>
          <ModelSelect models={models} value={selectedModel} disabled={loading} onChange={setSelectedModel} />
        </label>
        <div
          className={dragging ? "dropzone dragging" : "dropzone"}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); takeFiles(e.dataTransfer.files); }}
        >
          <p className="drop-title">Drop files here</p>
          <button type="button" onClick={() => inputRef.current?.click()}>Choose files</button>
          <input ref={inputRef} type="file" multiple hidden onChange={(e) => { takeFiles(e.target.files); e.target.value = ""; }} />
        </div>
        {formError && <p className="banner error">{formError}</p>}
        {files.length > 0 && (
          <ul className="file-list">
            {files.map((file, index) => (
              <li key={`${file.name}-${index}`}>
                <div>
                  <strong>{file.name}</strong>
                  <span className="meta">{formatBytes(file.size)}</span>
                </div>
                <button type="button" className="text" onClick={() => setFiles((c) => c.filter((_, i) => i !== index))}>Remove</button>
              </li>
            ))}
          </ul>
        )}
        <div className="actions">
          <button type="button" className="primary" disabled={loading || files.length === 0} onClick={onSubmit}>
            {loading ? "Reviewing…" : "Run review"}
          </button>
        </div>
        {requestError && <p className="banner error">{requestError}</p>}
      </section>
      {result && <Results response={result} />}
    </>
  );
}
