import { useState, type FormEvent } from "react";
import { login, register } from "./api";
import type { AuthUser } from "./authStorage";
import { saveSession } from "./authStorage";

type Mode = "login" | "register";

type Props = {
  onAuthed: (user: AuthUser) => void;
};

export function AuthPage({ onAuthed }: Props) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = mode === "login" ? await login(email, password) : await register(email, password);
      saveSession(result.access_token, result.user);
      onAuthed(result.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page auth-page">
      <header>
        <p className="eyebrow">AI Code Reviewer</p>
        <h1>{mode === "login" ? "Sign in" : "Create account"}</h1>
        <p className="lede">
          {mode === "login"
            ? "Sign in to upload code and run reviews."
            : "Register with an email and a password of at least 8 characters."}
        </p>
      </header>

      <section className="panel auth-panel">
        <form className="auth-form" onSubmit={onSubmit}>
          <label>
            Email
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={mode === "register" ? 8 : 1}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error && (
            <p className="banner error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" className="primary" disabled={loading}>
            {loading ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <p className="hint switch">
          {mode === "login" ? "No account yet?" : "Already registered?"}{" "}
          <button
            type="button"
            className="text"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
            }}
          >
            {mode === "login" ? "Create one" : "Sign in"}
          </button>
        </p>
      </section>
    </div>
  );
}
