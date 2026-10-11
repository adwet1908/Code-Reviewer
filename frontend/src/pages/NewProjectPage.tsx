import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createProject } from "../api";

export function NewProjectPage() {
  const navigate = useNavigate();
  const zipRef = useRef<HTMLInputElement>(null);
  const docsRef = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [zip, setZip] = useState<File | null>(null);
  const [docs, setDocs] = useState<File[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit() {
    if (!zip) {
      setError("Upload a repository .zip file.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const project = await createProject(name || "Untitled project", zip, docs);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create project.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <h1>New project</h1>
      <section className="panel auth-form">
        <label>
          Project name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="My service repo" />
        </label>
        <label>
          Repository zip
          <button type="button" onClick={() => zipRef.current?.click()}>Choose zip</button>
          <input ref={zipRef} type="file" accept=".zip" hidden onChange={(e) => setZip(e.target.files?.[0] ?? null)} />
          {zip && <span className="meta">{zip.name}</span>}
        </label>
        <label>
          Context docs (optional)
          <button type="button" onClick={() => docsRef.current?.click()}>Add docs</button>
          <input ref={docsRef} type="file" multiple hidden onChange={(e) => setDocs(Array.from(e.target.files ?? []))} />
          {docs.length > 0 && <span className="meta">{docs.length} file(s)</span>}
        </label>
        {error && <p className="banner error">{error}</p>}
        <button type="button" className="primary" disabled={loading} onClick={onSubmit}>
          {loading ? "Uploading…" : "Start ingestion"}
        </button>
      </section>
    </>
  );
}
