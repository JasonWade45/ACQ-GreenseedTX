import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { NavLink, Link, Route, Routes, useLocation } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  CalendarDays,
  ChartNoAxesCombined,
  CheckCheck,
  ChevronsUpDown,
  ClipboardList,
  CloudDownload,
  House,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  Menu,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Upload,
  Users,
  X,
} from "lucide-react";
import { api, post, sessionKey } from "./api";
import { Button, ErrorState, Loading, WorkspaceContext } from "./components";
import type { Meta, SyncState } from "./types";
import SearchPalette from "./SearchPalette";
import Dashboard from "./pages/Dashboard";
import Leads from "./pages/Leads";
import LeadDetail from "./pages/LeadDetail";
import QueuePage from "./pages/QueuePage";
import ImportsPage from "./pages/ImportsPage";
import {
  AppointmentsPage,
  ReportsPage,
  InsightsPage,
  SyncPage,
  SettingsPage,
} from "./pages/OperationsPages";

const navigation = [
  { label: "Dashboard", path: "/", icon: LayoutDashboard },
  { label: "Seller Leads", path: "/leads", icon: Users },
  { label: "Daily Follow-ups", path: "/followups", icon: ClipboardList },
  { label: "Appointments", path: "/appointments", icon: CalendarDays },
  { label: "Import Center", path: "/imports", icon: Upload },
  { label: "Reports", path: "/reports", icon: ChartNoAxesCombined },
  { label: "AI Insights", path: "/insights", icon: Sparkles },
  { label: "Sync Status", path: "/sync", icon: CloudDownload },
  { label: "Settings", path: "/settings", icon: Settings2 },
];
export default function App() {
  const [signedIn, setSignedIn] = useState(
    !!sessionStorage.getItem(sessionKey),
  );
  const client = useQueryClient();
  const auth = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => api<{ required: boolean }>("/auth/status"),
    retry: 1,
  });
  useEffect(() => {
    const expire = () => {
      sessionStorage.removeItem(sessionKey);
      setSignedIn(false);
      client.clear();
    };
    window.addEventListener("session-expired", expire);
    return () => window.removeEventListener("session-expired", expire);
  }, [client]);
  if (auth.isPending) return <Loading />;
  if (auth.isError)
    return <ErrorState error={auth.error} retry={() => auth.refetch()} />;
  if (auth.data.required && !signedIn)
    return (
      <Login
        onSuccess={() => {
          setSignedIn(true);
          client.clear();
        }}
      />
    );
  return (
    <Workspace
      onLogout={
        auth.data.required
          ? () => {
              sessionStorage.removeItem(sessionKey);
              setSignedIn(false);
              client.clear();
            }
          : undefined
      }
    />
  );
}
function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const d = await post<{ token: string }>("/auth/login", { password });
      sessionStorage.setItem(sessionKey, d.token);
      onSuccess();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <div className="login-brand">
        <div className="brand-icon">
          <House size={26} />
        </div>
        <span>
          ACQUISITIONS <b>ASSISTANT</b>
        </span>
      </div>
      <form className="login-card" onSubmit={submit}>
        <div className="login-icon">
          <LockKeyhole size={25} />
        </div>
        <div className="eyebrow">PRIVATE WORKSPACE</div>
        <h1>Welcome back.</h1>
        <p>
          Your seller pipeline. Your next move.
          <br />
          Sign in to your locally hosted workspace.
        </p>
        <label className="field">
          <span>Workspace password</span>
          <input
            type="password"
            autoComplete="current-password"
            autoFocus
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <Button busy={busy} type="submit">
          Open workspace <ArrowUpRight size={17} />
        </Button>
        <div className="login-safety">
          <ShieldCheck size={16} />
          Private by design. Human decisions, always.
        </div>
      </form>
      <span className="login-footer">
        No automatic calls. No messages. Just clarity.
      </span>
    </div>
  );
}
function Workspace({ onLogout }: { onLogout?: () => void }) {
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: () => api<Meta>("/meta"),
  });
  const sync = useQuery({
    queryKey: ["sync"],
    queryFn: () => api<SyncState>("/sync"),
    refetchInterval: (q) => (q.state.data?.health === "running" ? 2000 : 30000),
  });
  const [toasts, setToasts] = useState<
    { id: number; text: string; tone: string }[]
  >([]);
  const [mobile, setMobile] = useState(false);
  const [narrow, setNarrow] = useState(() => window.innerWidth <= 800);
  const [commandOpen, setCommandOpen] = useState(false);
  const location = useLocation();
  const toast = (text: string, tone = "success") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-2), { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  };
  useEffect(() => {
    const keyboard = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setMobile(false);
        setCommandOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, []);
  useEffect(() => {
    setMobile(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);
  useEffect(() => {
    const resize = () => {
      const value = window.innerWidth <= 800;
      setNarrow(value);
      if (!value) setMobile(false);
    };
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => {
    if (!mobile || !narrow) return;
    const previous = document.activeElement as HTMLElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const sidebar = document.querySelector<HTMLElement>(".sidebar");
    sidebar?.querySelector<HTMLElement>("nav a")?.focus();
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobile(false);
      }
      if (event.key === "Tab") {
        const items = Array.from(
          sidebar?.querySelectorAll<HTMLElement>(
            "a[href],button:not(:disabled)",
          ) || [],
        ).filter((item) => item.getClientRects().length);
        if (!items.length) return;
        const first = items[0],
          last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        }
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", keyboard);
    return () => {
      document.removeEventListener("keydown", keyboard);
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [mobile, narrow]);
  if (meta.isPending) return <Loading />;
  if (meta.isError)
    return <ErrorState error={meta.error} retry={() => meta.refetch()} />;
  const current = navigation.find((n) =>
    n.path === "/"
      ? location.pathname === "/"
      : location.pathname.startsWith(n.path),
  );
  return (
    <WorkspaceContext.Provider value={{ meta: meta.data, toast }}>
      <a href="#main-content" className="skip-link">
        Skip to workspace content
      </a>
      {commandOpen && <SearchPalette onClose={() => setCommandOpen(false)} />}
      <div className="app-shell">
        {mobile && (
          <button
            className="sidebar-scrim"
            aria-label="Close menu"
            onClick={() => setMobile(false)}
          />
        )}
        <aside
          className={`sidebar ${mobile ? "sidebar-open" : ""}`}
          inert={narrow && !mobile}
          aria-hidden={narrow && !mobile ? true : undefined}
          role={mobile && narrow ? "dialog" : undefined}
          aria-modal={mobile && narrow ? true : undefined}
          aria-label={mobile && narrow ? "Workspace navigation" : undefined}
        >
          <button
            className="drawer-close icon-button"
            aria-label="Close navigation menu"
            onClick={() => setMobile(false)}
          >
            <X size={19} />
          </button>
          <Link className="brand" to="/">
            <span className="brand-icon">
              <House size={23} />
            </span>
            <span>
              ACQUISITIONS
              <br />
              <b>
                ASSISTANT <span>AI</span>
              </b>
            </span>
          </Link>
          <div className="workspace-switch">
            <div className="workspace-mark">W</div>
            <div>
              <strong>Acquisitions workspace</strong>
              <span>Private · Unified 1.2</span>
            </div>
            <ChevronsUpDown size={14} />
          </div>
          <div className="nav-caption">WORKSPACE</div>
          <nav aria-label="Main navigation">
            {navigation.map(({ label, path, icon: Icon }, i) => (
              <NavLink
                key={path}
                to={path}
                end={path === "/"}
                className={({ isActive }) =>
                  `nav-item ${isActive ? "active" : ""} ${i === 7 ? "nav-divider" : ""}`
                }
              >
                <Icon size={18} />
                <span>{label}</span>
                {label === "AI Insights" && <span className="nav-ai">AI</span>}
                {label === "Sync Status" && (
                  <i
                    className={`status-dot ${sync.data?.health === "success" ? "green" : sync.data?.health === "failed" ? "red" : "gray"}`}
                  />
                )}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="safety-card">
              <ShieldCheck size={19} />
              <strong>Your judgment. Always.</strong>
              <p>
                Local clarity. Reviewed AI.
                <br />
                Never automated outreach.
              </p>
              <Link to="/settings">
                View safety controls <ArrowUpRight size={12} />
              </Link>
            </div>
            <Link to="/settings" className="sidebar-user">
              <div className="avatar">AM</div>
              <div>
                <strong>Acquisitions Manager</strong>
                <span>Local workspace</span>
              </div>
              <Settings2 size={15} />
            </Link>
            {onLogout && (
              <button className="logout" onClick={onLogout}>
                <LogOut size={13} />
                Lock workspace
              </button>
            )}
          </div>
        </aside>
        <div className="main-shell">
          <header className="topbar">
            <div className="row">
              <button
                className="icon-button mobile-menu"
                aria-label="Open menu"
                onClick={() => setMobile(true)}
              >
                <Menu size={21} />
              </button>
              <span className="breadcrumb">
                Workspace <span>/</span>{" "}
                <strong>
                  {location.pathname.startsWith("/leads/")
                    ? "Lead profile"
                    : current?.label || "Workspace"}
                </strong>
              </span>
            </div>
            <button
              className="global-search command-trigger"
              aria-label="Open workspace search (Ctrl K)"
              onClick={() => setCommandOpen(true)}
            >
              <Search size={17} />
              <span>Search seller, property, phone…</span>
              <kbd>Ctrl K</kbd>
            </button>
            <div className="topbar-right">
              <span className="local-label">
                <i className="status-dot green" />
                Local-first workspace
              </span>
              <Link
                to="/settings"
                className="shield-label"
                aria-label="Safety settings"
              >
                <ShieldCheck size={18} />
              </Link>
              <Link to="/settings" className="avatar small">
                AM
              </Link>
            </div>
          </header>
          {meta.data.mode === "fixture" && (
            <div className="fixture-banner">
              <Activity size={14} />
              <strong>Synthetic integration mode</strong>
              <span>
                CRM sync uses fictional fixtures. No real REsimpli account is
                connected.
              </span>
              <Link to="/sync">
                View details <ArrowUpRight size={12} />
              </Link>
            </div>
          )}
          <main
            id="main-content"
            className="page-enter"
            key={location.pathname}
          >
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/leads" element={<Leads />} />
              <Route path="/leads/:id" element={<LeadDetail />} />
              <Route path="/followups" element={<QueuePage />} />
              <Route path="/appointments" element={<AppointmentsPage />} />
              <Route path="/imports" element={<ImportsPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/insights" element={<InsightsPage />} />
              <Route path="/sync" element={<SyncPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route
                path="*"
                element={
                  <div className="empty-state">
                    <h1>Page not found</h1>
                    <Link to="/">Back to dashboard</Link>
                  </div>
                }
              />
            </Routes>
          </main>
          <footer className="app-footer">
            <span>
              <ShieldCheck size={13} />
              Local storage. Cloud only with your approval.
            </span>
            <span>
              Analysis → Review → Human decision{" "}
              <span className="footer-dot">·</span> Draft-only by design
            </span>
          </footer>
        </div>
        <div className="toast-container" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className={`toast toast-${t.tone}`}>
              {t.tone === "success" ? (
                <CheckCheck size={18} />
              ) : (
                <X size={18} />
              )}
              <span>{t.text}</span>
              <button
                className="icon-button"
                aria-label="Dismiss notification"
                onClick={() =>
                  setToasts((ts) => ts.filter((x) => x.id !== t.id))
                }
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>
    </WorkspaceContext.Provider>
  );
}
