import { Link, Outlet } from "react-router-dom";
import type { AuthUser } from "./authStorage";

type Props = {
  user: AuthUser;
  onLogout: () => void;
};

export function Layout({ user, onLogout }: Props) {
  return (
    <div className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">AI Code Reviewer</p>
          <nav className="nav">
            <Link to="/projects">Projects (RAG)</Link>
            <Link to="/quick">Quick review</Link>
            <Link to="/settings">Settings</Link>
          </nav>
        </div>
        <div className="account">
          <span className="meta">{user.email}</span>
          <button type="button" className="text" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>
      <Outlet />
    </div>
  );
}
