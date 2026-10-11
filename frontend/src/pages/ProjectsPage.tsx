import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { deleteProject, fetchProjects } from "../api";
import type { Project } from "../types";

export function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  useEffect(() => {
    fetchProjects()
      .then(setProjects)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load projects."));
  }, []);

  async function onDelete(project: Project) {
    if (!window.confirm(`Delete “${project.name}”? This removes its files, chunks, and reviews.`)) {
      return;
    }
    setDeletingId(project.id);
    setError(null);
    try {
      await deleteProject(project.id);
      setProjects((prev) => prev.filter((item) => item.id !== project.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete project.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <>
      <div className="row-between">
        <h1>Projects</h1>
        <Link className="button-link primary" to="/projects/new">New project</Link>
      </div>
      <p className="lede">Upload a repo zip, ingest chunks into pgvector, then review files with retrieval.</p>
      {error && <p className="banner error">{error}</p>}
      <section className="panel">
        {projects.length === 0 ? (
          <p className="hint">No projects yet. Create one to start Phase 2.</p>
        ) : (
          <ul className="file-list">
            {projects.map((project) => (
              <li key={project.id}>
                <div>
                  <Link to={`/projects/${project.id}`}><strong>{project.name}</strong></Link>
                  <span className="meta">
                    {project.status} · {project.file_count} files · {project.chunk_count} chunks
                  </span>
                </div>
                <button
                  type="button"
                  className="text"
                  disabled={deletingId === project.id}
                  onClick={() => onDelete(project)}
                >
                  {deletingId === project.id ? "Deleting…" : "Delete"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
