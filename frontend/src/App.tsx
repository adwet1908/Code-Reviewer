import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { fetchMe } from "./api";
import { AuthPage } from "./AuthPage";
import type { AuthUser } from "./authStorage";
import { clearSession, getStoredUser, getToken } from "./authStorage";
import { Layout } from "./Layout";
import { NewProjectPage } from "./pages/NewProjectPage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { QuickReviewPage } from "./pages/QuickReviewPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(() => getStoredUser());
  const [authChecking, setAuthChecking] = useState(() => Boolean(getToken()));

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setAuthChecking(false);
      return;
    }
    let cancelled = false;
    fetchMe()
      .then((me) => { if (!cancelled) setUser(me); })
      .catch(() => { if (!cancelled) { clearSession(); setUser(null); } })
      .finally(() => { if (!cancelled) setAuthChecking(false); });
    return () => { cancelled = true; };
  }, []);

  if (authChecking) return <div className="page"><p className="hint">Checking session…</p></div>;
  if (!user) return <AuthPage onAuthed={setUser} />;

  const logout = () => { clearSession(); setUser(null); };

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout user={user} onLogout={logout} />}>
          <Route path="/" element={<Navigate to="/projects" replace />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/new" element={<NewProjectPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="/quick" element={<QuickReviewPage onLogout={logout} />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
