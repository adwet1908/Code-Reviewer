import { useEffect, useState } from "react";
import {
  createUserModel,
  deleteUserModel,
  fetchModels,
  fetchUserModels,
  updateDefaultModel,
  updateUserModel,
} from "../api";
import type { ModelOption, UserModel } from "../types";

const emptyForm = {
  label: "",
  provider: "gemini" as "gemini" | "openai" | "anthropic",
  model_id: "",
  api_key: "",
  base_url: "",
};

export function SettingsPage() {
  const [catalog, setCatalog] = useState<ModelOption[]>([]);
  const [defaultModel, setDefaultModel] = useState("");
  const [rows, setRows] = useState<UserModel[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function reload() {
    const [modelsResponse, custom] = await Promise.all([fetchModels(), fetchUserModels()]);
    setCatalog(modelsResponse.models);
    setDefaultModel(modelsResponse.default);
    setRows(custom);
  }

  useEffect(() => {
    reload().catch((err) => setError(err instanceof Error ? err.message : "Could not load settings."));
  }, []);

  async function saveDefault() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await updateDefaultModel(defaultModel);
      setNotice("Default model saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save default model.");
    } finally {
      setSaving(false);
    }
  }

  async function saveCustom() {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const payload = {
        label: form.label.trim(),
        provider: form.provider,
        model_id: form.model_id.trim(),
        api_key: form.api_key.trim(),
        base_url: form.provider === "openai" ? form.base_url.trim() || null : null,
      };
      if (editingId === null) {
        if (!payload.api_key) {
          setError("API key is required for a new model.");
          return;
        }
        await createUserModel(payload);
        setNotice("Custom model added. It now appears in review and chat dropdowns.");
      } else {
        await updateUserModel(editingId, payload.api_key ? payload : { ...payload, api_key: undefined });
        setNotice("Custom model updated.");
      }
      setForm(emptyForm);
      setEditingId(null);
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the model.");
    } finally {
      setSaving(false);
    }
  }

  function startEdit(row: UserModel) {
    setEditingId(row.id);
    setForm({
      label: row.label,
      provider: row.provider,
      model_id: row.model_id,
      api_key: "",
      base_url: row.base_url ?? "",
    });
    setNotice(`Editing “${row.label}”. Leave the API key blank to keep the stored key.`);
  }

  async function remove(row: UserModel) {
    if (!window.confirm(`Remove “${row.label}”?`)) return;
    setError(null);
    try {
      await deleteUserModel(row.id);
      if (editingId === row.id) {
        setEditingId(null);
        setForm(emptyForm);
      }
      await reload();
      setNotice("Custom model removed.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the model.");
    }
  }

  const builtins = catalog.filter((item) => item.source !== "custom");

  return (
    <>
      <h1>Settings</h1>
      <p className="lede">
        Built-in Gemini models use <code>GEMINI_API_KEY</code> from the server. Add your own models
        and keys here; those keys are stored encrypted and never shown again.
      </p>
      {error && <p className="banner error">{error}</p>}
      {notice && <p className="banner success">{notice}</p>}

      <section className="panel">
        <h2>Default model</h2>
        <label className="model-picker">
          <span>Used when a page does not pick another model</span>
          <select value={defaultModel} onChange={(e) => setDefaultModel(e.target.value)}>
            {catalog.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label} ({item.provider})
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="primary" disabled={saving || !defaultModel} onClick={saveDefault}>
          Save default
        </button>
      </section>

      <section className="panel">
        <h2>Built-in Gemini models</h2>
        <ul className="settings-list">
          {builtins.map((item) => (
            <li key={item.id}>
              <strong>{item.label}</strong>
              <span className="meta">{item.id}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <h2>Your models</h2>
        {rows.length === 0 ? (
          <p className="hint">No custom models yet.</p>
        ) : (
          <ul className="settings-list">
            {rows.map((row) => (
              <li key={row.id}>
                <div>
                  <strong>{row.label}</strong>
                  <span className="meta">
                    {row.provider} · {row.model_id} · key …{row.api_key_hint}
                    {row.base_url ? ` · ${row.base_url}` : ""}
                  </span>
                </div>
                <div className="settings-row-actions">
                  <button type="button" onClick={() => startEdit(row)}>Edit</button>
                  <button type="button" className="text" onClick={() => remove(row)}>Remove</button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <h3>{editingId === null ? "Add a model" : "Edit model"}</h3>
        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault();
            saveCustom();
          }}
        >
          <label>
            Display name
            <input
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              placeholder="My GPT-4o"
              required
            />
          </label>
          <label>
            Provider
            <select
              value={form.provider}
              onChange={(e) => setForm({ ...form, provider: e.target.value as typeof form.provider })}
            >
              <option value="gemini">Gemini</option>
              <option value="openai">OpenAI-compatible</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </label>
          <label>
            Model id
            <input
              value={form.model_id}
              onChange={(e) => setForm({ ...form, model_id: e.target.value })}
              placeholder={
                form.provider === "gemini"
                  ? "gemini-3.7-flash"
                  : form.provider === "anthropic"
                    ? "claude-sonnet-4-5"
                    : "gpt-4o"
              }
              required
            />
          </label>
          <label>
            API key {editingId !== null ? "(leave blank to keep current)" : ""}
            <input
              type="password"
              value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              placeholder="sk-…"
              autoComplete="off"
              required={editingId === null}
            />
          </label>
          {form.provider === "openai" && (
            <label>
              Base URL (optional)
              <input
                value={form.base_url}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                placeholder="https://api.openai.com/v1"
              />
            </label>
          )}
          <div className="settings-row-actions">
            <button type="submit" className="primary" disabled={saving}>
              {editingId === null ? "Add model" : "Save changes"}
            </button>
            {editingId !== null && (
              <button
                type="button"
                onClick={() => {
                  setEditingId(null);
                  setForm(emptyForm);
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      </section>
    </>
  );
}
