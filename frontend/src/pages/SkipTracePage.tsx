import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownToLine, Check, FileUp, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { api, download, post } from "../api";
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
  Timestamp,
  useAction,
} from "../components";

type Summary = {
  needs_skip_trace: number;
  columns: string[];
  accepts: string[];
};

type PreviewRow = {
  id: number;
  row_number: number;
  state: string;
  lead: { lead_id: number; name: string | null } | null;
  incoming: {
    owner_name: string | null;
    phones: string[];
    email: string | null;
    address: string | null;
  };
  errors: string[];
};

type Preview = {
  batch_id: number;
  state: string;
  counts: { rows: number; matched: number; rejected: number };
  rows: PreviewRow[];
};

export default function SkipTracePage() {
  const summary = useQuery({
    queryKey: ["skip-trace-summary"],
    queryFn: () => api<Summary>("/skip-trace/summary"),
  });
  const action = useAction();
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [phrase, setPhrase] = useState("");
  const [applied, setApplied] = useState<{
    applied: number;
    kept_crm_phone: number;
  } | null>(null);

  async function upload(file: File | undefined) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setApplied(null);
    const result = await action.run(
      () => api<Preview>("/skip-trace/upload", { method: "POST", body: form }),
      "Skip-trace file matched against local leads. Nothing was written.",
    );
    if (result) {
      setPreview(result);
      setPhrase("");
    }
  }

  async function apply() {
    if (!preview) return;
    const result = await action.run(
      () =>
        post<{ applied: number; kept_crm_phone: number }>(
          `/skip-trace/${preview.batch_id}/apply`,
          { confirmation: phrase },
        ),
      "Skip-trace results applied locally",
    );
    if (result) {
      setApplied(result);
      setPreview(null);
      await summary.refetch();
    }
  }

  if (summary.isPending) return <Loading />;
  if (summary.isError)
    return (
      <ErrorState error={summary.error} retry={() => summary.refetch()} />
    );

  return (
    <>
      <PageHeader
        eyebrow="ADDRESS IN. CONTACT OUT."
        title="Skip-trace loop"
        description="Export only the addresses that still need a contact, run them through your provider, then import the results for review. The app never calls a provider itself."
        actions={
          <Button
            variant="secondary"
            busy={action.busy}
            onClick={() =>
              action.run(
                () =>
                  download("/skip-trace/export", "skip-trace-export.csv"),
                "Skip-trace export downloaded",
              )
            }
          >
            <ArrowDownToLine size={15} /> Export addresses
          </Button>
        }
      />
      <Panel title="What the file contains">
        <div className="settings-facts">
          <div>
            <span>Leads waiting</span>
            <strong>{summary.data.needs_skip_trace}</strong>
          </div>
          <div>
            <span>Export columns</span>
            <strong>{summary.data.columns.join(", ")}</strong>
          </div>
          <div>
            <span>Result columns accepted</span>
            <strong>{summary.data.accepts.join(", ")}</strong>
          </div>
        </div>
        <p className="muted">
          Only address fields and the local lead key leave this app, and only
          when you click export. No lead key is invented for a row that failed
          validation on import.
        </p>
        {summary.data.needs_skip_trace === 0 && (
          <Empty
            title="No lead is waiting on a skip trace"
            description="Every address-only lead already has a verified contact."
          />
        )}
      </Panel>

      <Panel
        title="Import provider results"
        subtitle="Every row is matched by lead key or normalized address before a single field changes."
      >
        <input
          ref={input}
          type="file"
          accept=".csv"
          aria-label="Skip-trace results file"
          className="sr-only"
          onChange={(e) => {
            void upload(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <Button busy={action.busy} onClick={() => input.current?.click()}>
          <FileUp size={15} /> Choose results CSV
        </Button>
        {action.error && <Notice tone="warning">{action.error}</Notice>}
      </Panel>

      {preview && (
        <Panel
          title={`Review batch #${preview.batch_id}`}
          subtitle="Unmatched rows and invalid phone numbers are rejected, never guessed."
        >
          <div className="row wrap">
            <Badge tone="green">{preview.counts.matched} matched</Badge>
            <Badge tone={preview.counts.rejected ? "amber" : "neutral"}>
              {preview.counts.rejected} rejected
            </Badge>
            <Badge tone="neutral">{preview.counts.rows} rows</Badge>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Lead</th>
                  <th>Incoming contact</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.row_number}</td>
                    <td>
                      {row.lead ? (
                        <Link to={`/leads/${row.lead.lead_id}`}>
                          {row.lead.name || `Lead #${row.lead.lead_id}`}
                        </Link>
                      ) : (
                        <span className="muted">unmatched</span>
                      )}
                    </td>
                    <td>
                      <small>
                        {[
                          row.incoming.owner_name,
                          (row.incoming.phones || []).join(", "),
                          row.incoming.email,
                        ]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </small>
                    </td>
                    <td>
                      {row.state === "ready" ? (
                        <Badge tone="green">ready</Badge>
                      ) : (
                        <>
                          <Badge tone="amber">rejected</Badge>
                          <small> {row.errors.join("; ")}</small>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Field
            label="Type IMPORT LOCAL to apply"
            hint="Matched owner names, phones and emails are written locally. A CRM-synced phone number is never replaced."
          >
            <input value={phrase} onChange={(e) => setPhrase(e.target.value)} />
          </Field>
          <Button
            busy={action.busy}
            disabled={phrase !== "IMPORT LOCAL" || preview.counts.matched === 0}
            onClick={apply}
          >
            <Check size={15} /> Apply matched results
          </Button>
        </Panel>
      )}

      {applied && (
        <Notice tone="info">
          <ShieldAlert size={14} /> {applied.applied} lead(s) updated,{" "}
          {applied.kept_crm_phone} CRM-synced phone number(s) kept. Nothing was
          written to the CRM.
        </Notice>
      )}
      <p className="muted" style={{ fontSize: 12 }}>
        <Timestamp value={new Date().toISOString()} /> Local session · no
        provider credentials are stored by this app.
      </p>
    </>
  );
}
