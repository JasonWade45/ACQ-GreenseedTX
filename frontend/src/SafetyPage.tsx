import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  Plus,
  Trash2,
  CheckCircle2,
} from "lucide-react";
import { api, post, patch, del, download } from "./api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Loading,
  Notice,
  PageHeader,
  Panel,
  useWorkspace,
} from "./components";

type Template = { id: number; category: string; variant: string; body: string; active: boolean; stats: { sent?: number; replies?: number; positive?: number } };
type Suppression = { id: number; phone: string; phone_normalized: string; reason: string; source: string; notes?: string; created_at: string };
type AuditRow = { id: number; lead_id?: number; action: string; actor: string; details: any; created_at: string };
type Task = { id: number; lead_id?: number; title: string; description?: string; priority: number; due_at?: string; status: string; source: string; created_at: string };
type Backup = { name: string; size_bytes: number; created_at: string; reason: string };
type Compliance = { settings: any; secret_backend: string };

export function SafetyPage() {
  const { toast } = useWorkspace();
  const [tab, setTab] = useState<"suppression" | "audit" | "tasks" | "compliance" | "backups" | "templates" | "updates">("suppression");
  return (
    <>
      <PageHeader eyebrow="SAFETY & COMPLIANCE" title="Safety controls" description="Suppression, audit log, tasks, compliance settings, backups and templates." />
      <div className="tabs" style={{ marginBottom: 16 }}>
        {(["suppression", "audit", "tasks", "compliance", "backups", "templates", "updates"] as const).map((k) => (
          <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>
            {k.charAt(0).toUpperCase() + k.slice(1)}
          </button>
        ))}
      </div>
      {tab === "suppression" && <SuppressionPanel toast={toast} />}
      {tab === "audit" && <AuditPanel />}
      {tab === "tasks" && <TasksPanel toast={toast} />}
      {tab === "compliance" && <CompliancePanel toast={toast} />}
      {tab === "backups" && <BackupsPanel toast={toast} />}
      {tab === "templates" && <TemplatesPanel />}
      {tab === "updates" && <UpdatesPanel />}
    </>
  );
}

function SuppressionPanel({ toast }: { toast: any }) {
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ["suppression"], queryFn: () => api<Suppression[]>("/suppression") });
  const [phone, setPhone] = useState("");
  const [reason, setReason] = useState("manual");
  const [busy, setBusy] = useState(false);
  async function add() {
    setBusy(true);
    try {
      await post("/suppression", { phone, reason, source: "manual" });
      toast("Suppressed");
      setPhone("");
      qc.invalidateQueries({ queryKey: ["suppression"] });
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }
  async function remove(p: string) {
    try {
      await del(`/suppression/${encodeURIComponent(p)}`);
      toast("Removed");
      qc.invalidateQueries({ queryKey: ["suppression"] });
    } catch (e: any) {
      toast(e.message, "error");
    }
  }
  if (data.isPending) return <Loading />;
  if (data.isError) return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const rows = data.data || [];
  return (
    <Panel title="Suppressed numbers" subtitle={`${rows.length}`}>
      <div className="form-row" style={{ marginBottom: 12 }}>
        <Field label="Phone"><input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+1..." /></Field>
        <Field label="Reason">
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
            {["manual", "stop", "wrong_number", "not_interested", "remove_me", "litigator"].map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </Field>
        <Button busy={busy} onClick={add}><Plus size={14} /> Add</Button>
      </div>
      {rows.length === 0 ? <Empty title="No suppressed numbers" description="Add a number above." /> : (
        <table className="data-table">
          <thead><tr><th>Phone</th><th>Reason</th><th>Source</th><th>Created</th><th></th></tr></thead>
          <tbody>
            {rows.map((r: any) => (
              <tr key={r.id}>
                <td>{r.phone}</td><td><Badge>{r.reason}</Badge></td><td>{r.source}</td><td>{r.created_at}</td>
                <td><Button variant="ghost" onClick={() => remove(r.phone)}><Trash2 size={14} /></Button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function AuditPanel() {
  const [action, setAction] = useState("");
  const data = useQuery({ queryKey: ["audit", action], queryFn: () => api<AuditRow[]>(`/audit?limit=200${action ? "&action=" + encodeURIComponent(action) : ""}`) });
  if (data.isPending) return <Loading />;
  if (data.isError) return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const rows = data.data || [];
  return (
    <Panel title="Audit log" subtitle={`${rows.length} entries`}>
      <div style={{ marginBottom: 12 }}>
        <input placeholder="filter by action" value={action} onChange={(e) => setAction(e.target.value)} style={{ width: 260 }} />
      </div>
      {rows.length === 0 ? <Empty title="No audit entries" description="Audit events appear here." /> : (
        <table className="data-table">
          <thead><tr><th>When</th><th>Action</th><th>Actor</th><th>Lead</th><th>Details</th></tr></thead>
          <tbody>
            {rows.map((r: any) => (
              <tr key={r.id}>
                <td>{r.created_at}</td><td>{r.action}</td><td>{r.actor}</td><td>{r.lead_id ?? "—"}</td>
                <td><code style={{ fontSize: 11 }}>{JSON.stringify(r.details || {})}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function TasksPanel({ toast }: { toast: any }) {
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ["tasks"], queryFn: () => api<Task[]>("/tasks?limit=200") });
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  async function add() {
    setBusy(true);
    try {
      await post("/tasks", { title, source: "manual" });
      toast("Task added");
      setTitle("");
      qc.invalidateQueries({ queryKey: ["tasks"] });
    } catch (e: any) { toast(e.message, "error"); }
    finally { setBusy(false); }
  }
  async function done(id: number) {
    try { await patch(`/tasks/${id}`, { status: "done" }); qc.invalidateQueries({ queryKey: ["tasks"] }); }
    catch (e: any) { toast(e.message, "error"); }
  }
  if (data.isPending) return <Loading />;
  if (data.isError) return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const rows = data.data || [];
  return (
    <Panel title="Tasks" subtitle={`${rows.length}`}>
      <div className="form-row" style={{ marginBottom: 12 }}>
        <Field label="New task"><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Call back seller..." /></Field>
        <Button busy={busy} onClick={add}><Plus size={14} /> Add</Button>
      </div>
      {rows.length === 0 ? <Empty title="No tasks" description="Add a task above." /> : (
        <ul className="task-list">
          {rows.map((t: any) => (
            <li key={t.id} className={t.status === "done" ? "done" : ""}>
              <button className="task-check" onClick={() => done(t.id)} disabled={t.status === "done"}><CheckCircle2 size={16} /></button>
              <div>
                <strong>{t.title}</strong>
                {t.description && <p>{t.description}</p>}
                <span className="task-meta">{t.source} · priority {t.priority}{t.due_at ? ` · due ${t.due_at}` : ""}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function CompliancePanel({ toast }: { toast: any }) {
  const data = useQuery({ queryKey: ["compliance"], queryFn: () => api<Compliance>("/compliance") });
  const [cfg, setCfg] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  if (data.isPending) return <Loading />;
  if (data.isError) return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const s = cfg || data.data?.settings || {};
  async function save() {
    setSaving(true);
    try { await patch("/compliance", s); toast("Compliance settings saved"); }
    catch (e: any) { toast(e.message, "error"); }
    finally { setSaving(false); }
  }
  return (
    <Panel title="Compliance settings" subtitle={`secret backend: ${data.data?.secret_backend}`}>
      <Notice>Verify current TCPA and Texas rules yourself. Defaults: send 09:00–20:00, Mon–Sat, recipient local time.</Notice>
      <div className="form-grid" style={{ marginTop: 12 }}>
        <Field label="Licensed counties (comma-separated)">
          <input value={(s.licensed_counties || []).join(", ")} onChange={(e) => setCfg({ ...s, licensed_counties: e.target.value.split(",").map((x: string) => x.trim()).filter(Boolean) })} />
        </Field>
        <Field label="Quiet start (HH:MM)"><input value={s.quiet_start || "09:00"} onChange={(e) => setCfg({ ...s, quiet_start: e.target.value })} /></Field>
        <Field label="Quiet end (HH:MM)"><input value={s.quiet_end || "20:00"} onChange={(e) => setCfg({ ...s, quiet_end: e.target.value })} /></Field>
        <Field label="Daily cap"><input type="number" value={s.daily_cap ?? 50} onChange={(e) => setCfg({ ...s, daily_cap: Number(e.target.value) })} /></Field>
        <Field label="Hourly cap"><input type="number" value={s.hourly_cap ?? 15} onChange={(e) => setCfg({ ...s, hourly_cap: Number(e.target.value) })} /></Field>
        <Field label="Warm-up days"><input type="number" value={s.warmup_days ?? 14} onChange={(e) => setCfg({ ...s, warmup_days: Number(e.target.value) })} /></Field>
      </div>
      <div style={{ marginTop: 12 }}><Button busy={saving} onClick={save}>Save compliance settings</Button></div>
    </Panel>
  );
}

function BackupsPanel({ toast }: { toast: any }) {
  const qc = useQueryClient();
  const data = useQuery({ queryKey: ["backups"], queryFn: () => api<{ backups: Backup[]; folder: string; second_folder?: string }>("/backups") });
  const [busy, setBusy] = useState(false);
  async function create() {
    setBusy(true);
    try { const r = await post<Backup>("/backups", {}); toast(`Backup created: ${r.name}`); qc.invalidateQueries({ queryKey: ["backups"] }); }
    catch (e: any) { toast(e.message, "error"); }
    finally { setBusy(false); }
  }
  async function exportAll() {
    setBusy(true);
    try { await download("/export/all", "acq-export.zip"); toast("Export downloaded"); }
    catch (e: any) { toast(e.message, "error"); }
    finally { setBusy(false); }
  }
  async function restore(name: string) {
    try { await post("/backups/restore", { name }); toast("Restored. Restart the app to use the restored database."); }
    catch (e: any) { toast(e.message, "error"); }
  }
  async function remove(name: string) {
    try { await del(`/backups/${encodeURIComponent(name)}?confirm=DELETE+BACKUP`); toast("Deleted"); qc.invalidateQueries({ queryKey: ["backups"] }); }
    catch (e: any) { toast(e.message, "error"); }
  }
  if (data.isPending) return <Loading />;
  if (data.isError) return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const d = data.data!;
  return (
    <Panel title="Backups" subtitle={d.folder}>
      <div className="form-row" style={{ marginBottom: 12, gap: 8 }}>
        <Button busy={busy} onClick={create}>Back up now</Button>
        <Button variant="secondary" busy={busy} onClick={exportAll}><Download size={14} /> Export everything (ZIP)</Button>
      </div>
      <p style={{ fontSize: 12, opacity: 0.7 }}>Second backup folder: {d.second_folder || "not set"}</p>
      {(d.backups || []).length === 0 ? <Empty title="No backups yet" description="Create one above." /> : (
        <table className="data-table">
          <thead><tr><th>Name</th><th>Reason</th><th>Size</th><th>Created</th><th></th></tr></thead>
          <tbody>
            {d.backups.map((b: any) => (
              <tr key={b.name}>
                <td>{b.name}</td><td>{b.reason}</td><td>{Math.round(b.size_bytes / 1024)} KB</td><td>{b.created_at}</td>
                <td style={{ display: "flex", gap: 6 }}>
                  <a className="btn btn-ghost btn-sm" href={`/api/backups/${encodeURIComponent(b.name)}`}>Download</a>
                  <Button variant="ghost" onClick={() => restore(b.name)}>Restore</Button>
                  <Button variant="ghost" onClick={() => remove(b.name)}><Trash2 size={14} /></Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function TemplatesPanel() {
  const data = useQuery({ queryKey: ["templates"], queryFn: () => api<Template[]>("/message-templates") });
  if (data.isPending) return <Loading />;
  if (data.isError) return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const rows = data.data || [];
  const byCat: Record<string, Template[]> = {};
  rows.forEach((t: any) => { (byCat[t.category] = byCat[t.category] || []).push(t); });
  return (
    <Panel title="Message templates" subtitle={`${rows.length} variants`}>
      <p style={{ fontSize: 12, opacity: 0.7, marginBottom: 12 }}>Seeded on first run. The engine picks the most specific matching category per lead. All drafts require approval.</p>
      {Object.keys(byCat).map((cat) => (
        <div key={cat} style={{ marginBottom: 16 }}>
          <h4 style={{ margin: "8px 0" }}>{cat}</h4>
          {byCat[cat].map((t: any) => (
            <div key={t.id} style={{ marginBottom: 8, padding: 10, border: "1px solid #ddd", borderRadius: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <Badge>Variant {t.variant}</Badge>
                <span style={{ fontSize: 11, opacity: 0.6 }}>sent {t.stats?.sent ?? 0} · replies {t.stats?.replies ?? 0}</span>
              </div>
              <pre style={{ whiteSpace: "pre-wrap", fontSize: 13, margin: 0 }}>{t.body}</pre>
            </div>
          ))}
        </div>
      ))}
    </Panel>
  );
}

function UpdatesPanel() {
  const data = useQuery({ queryKey: ["updates"], queryFn: () => api<any>("/updates/check") });
  if (data.isPending) return <Loading />;
  if (data.isError) return <ErrorState error={data.error} retry={() => data.refetch()} />;
  const d = data.data;
  return (
    <Panel title="Updates" subtitle={`current: ${d?.current}`}>
      {d?.available ? <Notice tone="info">New version available: {d.latest?.tag_name} — {d.latest?.name}</Notice> : <Notice>You are on the latest version ({d?.current}).</Notice>}
      {d?.latest?.body && <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, marginTop: 12 }}>{d.latest.body}</pre>}
      {d?.latest?.assets?.length ? (
        <div style={{ marginTop: 12 }}>
          {d.latest.assets.map((a: any) => (
            <a key={a.name} className="btn btn-secondary" href={a.browser_download_url} style={{ marginRight: 8 }}>
              <Download size={14} /> {a.name}
            </a>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}
