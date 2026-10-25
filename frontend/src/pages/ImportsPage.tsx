import { WorkspaceBridge } from "../unified";
import { useRef, useState } from "react";
import type { DragEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowDownToLine,
  ArrowLeft,
  Check,
  CheckCircle2,
  ChevronRight,
  Database,
  FileSpreadsheet,
  FileUp,
  LockKeyhole,
  Play,
  ShieldCheck,
  Upload,
} from "lucide-react";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Loading,
  Modal,
  Notice,
  PageHeader,
  Pagination,
  Panel,
  useAction,
  useData,
  useWorkspace,
} from "../components";
import { api, dateTime, download, human, post } from "../api";
import type { BatchRow, ImportBatch, MappingTemplate } from "../types";

export default function ImportsPage() {
  const [params, setParams] = useSearchParams();
  const batchId = params.get("batch");
  const batches = useData<ImportBatch[]>("imports", "/imports");
  const action = useAction();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  async function upload(file: File | undefined) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const b = await action.run(
      () => api<ImportBatch>("/imports/upload", { method: "POST", body: form }),
      "File inspected locally",
    );
    if (b) {
      setParams({ batch: String(b.id) });
      if (b.repeated_file)
        action.setError(
          "This exact file was already uploaded. Its existing batch is reopened; completed rows will not be duplicated.",
        );
    }
  }
  function dropped(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    void upload(e.dataTransfer.files[0]);
  }
  return (
    <>
      <PageHeader
        eyebrow="BRING YOUR HISTORY FORWARD"
        title="Legacy import center"
        description="Clean, review and organize historical seller leads. Nothing is submitted to REsimpli automatically."
        actions={
          <Button
            variant="secondary"
            onClick={() =>
              action.run(() =>
                download(
                  "/examples/sample-seller-leads.xlsx",
                  "sample-seller-leads.xlsx",
                ),
              )
            }
          >
            <ArrowDownToLine size={16} />
            Sample workbook
          </Button>
        }
      />
      {batchId ? (
        <>
          <button className="back-link" onClick={() => setParams({})}>
            <ArrowLeft size={14} />
            Import history & upload
          </button>
          <BatchView key={batchId} id={Number(batchId)} />
        </>
      ) : (
        <>
          <WorkspaceBridge />
          <div className="import-top-grid">
            <div
              className={`upload-zone ${drag ? "drag-over" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={dropped}
            >
              <div className="upload-symbol">
                <FileUp size={32} />
              </div>
              <h2>Give old leads a fresh start.</h2>
              <p>
                Drag a CSV or Excel workbook here, or choose a file.
                <br />
                Multiple sheets. Thousands of records. One careful review.
              </p>
              <input
                ref={input}
                type="file"
                accept=".csv,.xlsx"
                aria-label="Upload lead file"
                className="sr-only"
                onChange={(e) => {
                  void upload(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
              <Button busy={action.busy} onClick={() => input.current?.click()}>
                <Upload size={16} />
                Choose CSV or XLSX
              </Button>
              <span className="upload-spec">
                CSV / XLSX · 25 MB default limit · up to 50,000 rows
              </span>
            </div>
            <Panel
              title="A safe path into your pipeline"
              subtitle="Review is a step, not a suggestion."
            >
              <ol className="import-steps">
                {[
                  [
                    "Upload & inspect",
                    "All sheets, headers and record counts.",
                  ],
                  ["Map & normalize", "Your columns, consistent local fields."],
                  [
                    "Review & resolve",
                    "Invalid data and potential duplicates.",
                  ],
                  [
                    "Approve local import",
                    "Explicit approval. Audited. Resumable.",
                  ],
                ].map(([title, desc], i) => (
                  <li key={title}>
                    <span>{i + 1}</span>
                    <div>
                      <strong>{title}</strong>
                      <p>{desc}</p>
                    </div>
                  </li>
                ))}
              </ol>
              <div className="safe-import-note">
                <LockKeyhole size={16} />
                <span>
                  No external writes. Export a reviewed CSV for your company’s
                  approved REsimpli import.
                </span>
              </div>
            </Panel>
          </div>
          {action.error && <Notice tone="warning">{action.error}</Notice>}
          <div className="import-sample-bar">
            <FileSpreadsheet size={20} />
            <span>
              Want to test the workflow first? Sample files contain{" "}
              <strong>fictional sellers only.</strong>
            </span>
            <button
              className="text-link"
              onClick={() =>
                action.run(() =>
                  download(
                    "/examples/sample-seller-leads.csv",
                    "sample-seller-leads.csv",
                  ),
                )
              }
            >
              Download sample CSV <ArrowDownToLine size={14} />
            </button>
          </div>
          <Panel
            title="Import history"
            subtitle="Each file has a checksum and a resumable batch ledger."
            action={
              <Badge tone="neutral">{batches.data?.length || 0} batches</Badge>
            }
          >
            {batches.isPending ? (
              <Loading />
            ) : batches.isError ? (
              <ErrorState error={batches.error} />
            ) : !batches.data.length ? (
              <Empty
                title="No imports yet"
                description="Upload a seller lead file to inspect its sheets, map the fields and review normalized records."
              />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>FILE / BATCH</th>
                      <th>RECORDS</th>
                      <th>STATE</th>
                      <th>IMPORTED / REJECTED</th>
                      <th>CREATED</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {batches.data.map((b) => (
                      <tr key={b.id}>
                        <td>
                          <button
                            className="file-cell"
                            onClick={() => setParams({ batch: String(b.id) })}
                          >
                            <FileSpreadsheet size={22} />
                            <span>
                              <strong>{b.filename}</strong>
                              <small>
                                Batch #{b.id} · {Object.keys(b.sheets).length}{" "}
                                sheet(s)
                              </small>
                            </span>
                          </button>
                        </td>
                        <td>{b.row_count.toLocaleString()}</td>
                        <td>
                          <Badge
                            tone={
                              b.state === "completed"
                                ? "green"
                                : b.state === "partial"
                                  ? "amber"
                                  : "blue"
                            }
                          >
                            {human(b.state)}
                          </Badge>
                        </td>
                        <td>
                          {b.counts.imported || 0} imported ·{" "}
                          {b.counts.invalid || 0} invalid ·{" "}
                          {b.counts.failed || 0} failed
                        </td>
                        <td>{dateTime(b.created_at)}</td>
                        <td>
                          <button
                            className="icon-button"
                            aria-label={`Open batch ${b.id}`}
                            onClick={() => setParams({ batch: String(b.id) })}
                          >
                            <ChevronRight size={17} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
    </>
  );
}
function BatchView({ id }: { id: number }) {
  const [page, setPage] = useState(1);
  const data = useData<ImportBatch>(
    "import-batch",
    `/imports/${id}?page=${page}&page_size=50`,
  );
  if (data.isPending) return <Loading />;
  if (data.isError)
    return <ErrorState error={data.error} retry={() => data.refetch()} />;
  return <BatchWorkspace batch={data.data} page={page} setPage={setPage} />;
}
function BatchWorkspace({
  batch: b,
  page,
  setPage,
}: {
  batch: ImportBatch;
  page: number;
  setPage: (p: number) => void;
}) {
  const { meta } = useWorkspace();
  const action = useAction();
  const templates = useData<MappingTemplate[]>(
    "mapping-templates",
    "/imports/templates",
  );
  const sheetNames = Object.keys(b.sheets);
  const [sheets, setSheets] = useState<string[]>(
    b.mapping_config.sheets || sheetNames,
  );
  const [mapping, setMapping] = useState<Record<string, string>>(
    b.mapping_config.mapping || b.sheets[sheetNames[0]].suggested_mapping,
  );
  const [dateOrder, setDateOrder] = useState(
    b.mapping_config.date_order || "reject",
  );
  const [templateName, setTemplateName] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [resolutions, setResolutions] = useState<Record<string, string>>({});
  const [approve, setApprove] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [fillMissing, setFillMissing] = useState(false);
  const [mappingOpen, setMappingOpen] = useState(b.state === "uploaded");
  const [rowDetail, setRowDetail] = useState<BatchRow | null>(null);
  const headers = [...new Set(sheets.flatMap((s) => b.sheets[s].headers))];
  const rows = b.rows || [];
  const readied = b.state !== "uploaded";
  async function preview() {
    const result = await action.run(
      () =>
        post(`/imports/${b.id}/preview`, {
          sheets,
          mapping,
          date_order: dateOrder,
          template_name: templateName || null,
        }),
      "Normalization and duplicate review ready",
    );
    if (result) {
      setMappingOpen(false);
      setPage(1);
      setSelected([]);
    }
  }
  async function commit() {
    const result = await action.run(
      () =>
        post(`/imports/${b.id}/approve`, {
          row_ids: selected,
          resolutions,
          confirmation,
          destination: "local",
          fill_missing: fillMissing,
        }),
      "Local import finished — review the batch report",
    );
    if (result) {
      setApprove(false);
      setConfirmation("");
      setSelected([]);
    }
  }
  return (
    <>
      <div className="batch-title">
        <div className="row">
          <span className="file-batch-icon">
            <FileSpreadsheet size={23} />
          </span>
          <div>
            <h2>{b.filename}</h2>
            <p>
              Batch #{b.id} · {b.row_count.toLocaleString()} source records ·{" "}
              {sheetNames.length} sheet(s)
            </p>
          </div>
        </div>
        <Badge tone={b.state === "completed" ? "green" : "blue"}>
          {human(b.state)}
        </Badge>
      </div>
      <div className="stepper">
        {[
          "File inspected",
          "Column mapping",
          "Preview & review",
          "Approved local import",
        ].map((s, i) => (
          <div
            key={s}
            className={
              i === 0 || (readied && i < 3) || b.state === "completed"
                ? "complete"
                : ""
            }
          >
            <span>
              {i === 0 || (readied && i < 3) || b.state === "completed" ? (
                <Check size={13} />
              ) : (
                i + 1
              )}
            </span>
            {s}
            {i < 3 && <ChevronRight size={14} />}
          </div>
        ))}
      </div>
      {b.errors.map((e, i) => (
        <Notice tone="warning" key={i}>
          {e}
        </Notice>
      ))}
      <Panel
        title="Column mapping & sheets"
        subtitle="Original source values are always retained."
        action={
          <Button variant="ghost" onClick={() => setMappingOpen(!mappingOpen)}>
            {mappingOpen ? "Collapse mapping" : "Review / adjust mapping"}
          </Button>
        }
      >
        {mappingOpen ? (
          <div className="mapping-workspace">
            <div className="sheet-options">
              <div className="mini-label">SELECT SHEETS</div>
              {sheetNames.map((name) => (
                <label key={name} className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={sheets.includes(name)}
                    onChange={(e) =>
                      setSheets((s) =>
                        e.target.checked
                          ? [...s, name]
                          : s.filter((x) => x !== name),
                      )
                    }
                  />
                  <strong>{name}</strong>
                  <Badge>{b.sheets[name].record_count} rows</Badge>
                </label>
              ))}
            </div>
            <div className="mapping-settings">
              <Field label="Date interpretation">
                <select
                  value={dateOrder}
                  onChange={(e) => setDateOrder(e.target.value)}
                >
                  <option value="reject">Reject ambiguous dates</option>
                  <option value="MDY">MM/DD/YYYY (US)</option>
                  <option value="DMY">DD/MM/YYYY</option>
                </select>
              </Field>
              <Field label="Load mapping template">
                <select
                  value=""
                  onChange={(e) => {
                    const t = templates.data?.find(
                      (t) => t.id === Number(e.target.value),
                    );
                    if (t) {
                      setMapping(t.mapping);
                      setDateOrder(t.date_order);
                    }
                  }}
                >
                  <option value="">Choose saved template</option>
                  {templates.data?.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Save mapping as (optional)">
                <input
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  placeholder="e.g. Legacy spreadsheet"
                />
              </Field>
            </div>
            <Notice>
              Required locally: a first/full name and at least a phone, email,
              property address or external ID. Dates without years and invalid
              fields are rejected. Sheets with different header names can be
              processed in separate passes; completed rows stay locked.
            </Notice>
            <div className="table-wrap mapping-table">
              <table>
                <thead>
                  <tr>
                    <th>SOURCE COLUMN</th>
                    <th>SAMPLE VALUE</th>
                    <th>STANDARDIZED FIELD</th>
                  </tr>
                </thead>
                <tbody>
                  {headers.map((h) => (
                    <tr key={h}>
                      <td>
                        <strong>{h}</strong>
                      </td>
                      <td className="sample-value">
                        {String(
                          rows.find((r) => r.original[h] != null)?.original[
                            h
                          ] ?? "—",
                        ).slice(0, 120)}
                      </td>
                      <td>
                        <select
                          aria-label={`Map ${h}`}
                          value={mapping[h] || ""}
                          onChange={(e) =>
                            setMapping((m) => {
                              const next = { ...m };
                              if (e.target.value) next[h] = e.target.value;
                              else delete next[h];
                              return next;
                            })
                          }
                        >
                          <option value="">Do not map</option>
                          {Object.entries(meta.import_fields).map(
                            ([field, label]) => (
                              <option key={field} value={field}>
                                {label}
                              </option>
                            ),
                          )}
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mapping-actions">
              <span className="muted">
                No dates, values or contact outcomes are invented.
              </span>
              <Button
                busy={action.busy}
                disabled={!sheets.length}
                onClick={preview}
              >
                <Play size={15} />
                Normalize & preview
              </Button>
            </div>
          </div>
        ) : (
          <div className="mapping-collapsed">
            <CheckCircle2 size={17} />
            <span>
              {Object.keys(b.mapping_config.mapping || {}).length} mapped fields
              · {b.mapping_config.sheets?.join(", ") || sheets.join(", ")} ·
              Date mode: {b.mapping_config.date_order || "reject"}
            </span>
          </div>
        )}
      </Panel>
      {readied && (
        <>
          <div className="import-counts">
            {[
              ["new", "New records", "green"],
              ["duplicates", "Duplicate candidates", "purple"],
              ["warnings", "Rows with warnings", "amber"],
              ["invalid", "Invalid / rejected", "red"],
              ["imported", "Imported locally", "teal"],
              ["linked", "Linked records", "purple"],
              ["enriched", "Missing fields filled", "green"],
              ["failed", "Failed — retryable", "red"],
            ].map(([key, label, tone]) => (
              <div key={key}>
                <span>{label}</span>
                <strong className={`text-${tone}`}>
                  {(b.counts[key] || 0).toLocaleString()}
                </strong>
              </div>
            ))}
          </div>
          <Panel
            title="Review normalized records"
            subtitle="Ambiguous matches need an explicit resolution. No uncertain records are automatically merged."
            action={
              <div className="row">
                <Button
                  variant="ghost"
                  onClick={async () => {
                    const result = await action.run(() =>
                      api<{ row_ids: number[] }>(
                        `/imports/${b.id}/eligible-ids`,
                      ),
                    );
                    if (result) setSelected(result.row_ids);
                  }}
                >
                  Select all new records
                </Button>
                <Badge tone="teal">{selected.length} selected</Badge>
              </div>
            }
          >
            <div className="table-wrap import-preview">
              <table>
                <thead>
                  <tr>
                    <th />
                    <th>SOURCE ROW</th>
                    <th>NORMALIZED SELLER</th>
                    <th>PROPERTY / CONTACT</th>
                    <th>VALIDATION</th>
                    <th>DUPLICATE REVIEW</th>
                    <th>OUTCOME</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr
                      key={r.id}
                      className={
                        r.state === "invalid"
                          ? "invalid-row"
                          : selected.includes(r.id)
                            ? "selected-row"
                            : ""
                      }
                    >
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Select import row ${r.row_number}`}
                          disabled={
                            !["ready", "failed"].includes(r.state) ||
                            r.errors.length > 0
                          }
                          checked={selected.includes(r.id)}
                          onChange={(e) =>
                            setSelected((s) =>
                              e.target.checked
                                ? [...s, r.id]
                                : s.filter((id) => id !== r.id),
                            )
                          }
                        />
                      </td>
                      <td>
                        <button
                          className="text-link"
                          onClick={() => setRowDetail(r)}
                        >
                          {r.sheet} #{r.row_number}
                        </button>
                        <small>Record #{r.id}</small>
                      </td>
                      <td>
                        <strong>
                          {String(
                            r.normalized.full_name ||
                              "Owner unknown · property-only",
                          )}
                        </strong>
                        <small>
                          {String(
                            r.normalized.source_status || "Status not supplied",
                          )}
                        </small>
                      </td>
                      <td>
                        {String(
                          r.normalized.street_address || "Address missing",
                        )}
                        <small>
                          {String(
                            r.normalized.primary_phone ||
                              r.normalized.email ||
                              "Contact missing",
                          )}
                        </small>
                      </td>
                      <td>
                        {r.errors.length ? (
                          <>
                            <Badge tone="red">{r.errors.length} error(s)</Badge>
                            <small className="text-red">{r.errors[0]}</small>
                          </>
                        ) : (
                          <Badge tone="green">Valid</Badge>
                        )}
                        {r.warnings.length > 0 && (
                          <small>{r.warnings.length} warning(s)</small>
                        )}
                        {r.error && (
                          <small className="text-red">{r.error}</small>
                        )}
                      </td>
                      <td>
                        <Badge
                          tone={
                            r.duplicate_kind === "new_record"
                              ? "green"
                              : "amber"
                          }
                        >
                          {human(r.duplicate_kind)}
                        </Badge>
                        {r.candidates.map((c, i) => (
                          <small key={i}>
                            {c.lead_id ? (
                              <Link to={`/leads/${c.lead_id}`}>
                                {c.full_name} · Lead #{c.lead_id}
                              </Link>
                            ) : (
                              `${c.full_name} · source row ID ${c.row_id}`
                            )}
                          </small>
                        ))}
                        {r.duplicate_kind !== "new_record" &&
                          ["ready", "failed"].includes(r.state) && (
                            <select
                              aria-label={`Resolve duplicate row ${r.row_number}`}
                              value={
                                resolutions[String(r.id)] || r.resolution || ""
                              }
                              onChange={(e) =>
                                setResolutions((s) => ({
                                  ...s,
                                  [String(r.id)]: e.target.value,
                                }))
                              }
                            >
                              <option value="">
                                Choose explicit resolution
                              </option>
                              <option value="skip">
                                Approve skipping this row
                              </option>
                              <option value="link">
                                Link to one resolved local lead
                              </option>
                              {r.duplicate_kind !==
                                "existing_resimpli_record" && (
                                <option value="separate">
                                  Approve a separate local seller
                                </option>
                              )}
                            </select>
                          )}
                      </td>
                      <td>
                        <Badge
                          tone={
                            ["imported", "linked"].includes(r.state)
                              ? "green"
                              : r.state === "failed"
                                ? "red"
                                : "neutral"
                          }
                        >
                          {human(r.state)}
                        </Badge>
                        {r.lead_id && (
                          <small>
                            <Link to={`/leads/${r.lead_id}`}>
                              Lead #{r.lead_id}
                            </Link>
                          </small>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination
              page={page}
              pageSize={50}
              total={b.total_rows || b.row_count}
              onChange={setPage}
            />
            <div className="import-approval-bar">
              <div>
                <Database size={20} />
                <span>
                  <strong>{selected.length} selected records</strong>
                  <small>
                    Writes only to this local database. Never to REsimpli.
                  </small>
                </span>
              </div>
              <Button
                disabled={!selected.length}
                busy={action.busy}
                onClick={() => setApprove(true)}
              >
                <ShieldCheck size={16} />
                Review & approve local import
              </Button>
            </div>
          </Panel>
          <div className="import-export-grid">
            <Panel
              title="Reports & rejected records"
              subtitle="Every row has an outcome, a source reference and a resumable state."
            >
              <div className="row wrap">
                <Button
                  variant="secondary"
                  onClick={() =>
                    action.run(() =>
                      download(
                        `/imports/${b.id}/export?kind=report`,
                        `import-${b.id}-report.csv`,
                      ),
                    )
                  }
                >
                  <ArrowDownToLine size={15} />
                  Batch report
                </Button>
                <Button
                  variant="secondary"
                  onClick={() =>
                    action.run(() =>
                      download(
                        `/imports/${b.id}/export?kind=rejected`,
                        `import-${b.id}-rejected.csv`,
                      ),
                    )
                  }
                >
                  <ArrowDownToLine size={15} />
                  Rejected / failed rows
                </Button>
              </div>
              <p className="panel-description">
                To retry, select failed records after resolving the reported
                issue. Previously committed rows are never re-created.
              </p>
            </Panel>
            <Panel
              title="REsimpli CSV handoff"
              subtitle="A mapping-ready file, not an automatic CRM import."
            >
              <Button
                variant="secondary"
                onClick={() =>
                  action.run(() =>
                    download(
                      `/imports/${b.id}/export?kind=resimpli`,
                      `import-${b.id}-resimpli.csv`,
                    ),
                  )
                }
              >
                <FileSpreadsheet size={16} />
                Export reviewed records
              </Button>
              <p className="panel-description">
                Only approved imported/linked rows are included. Confirm the
                account’s seller-lead import path and disable downstream
                communication automations. List Stacking is not the same as
                Active Leads.
              </p>
            </Panel>
          </div>
        </>
      )}
      {action.error && <Notice tone="warning">{action.error}</Notice>}
      {approve && (
        <Modal
          title="Approve this local import"
          subtitle={`${selected.length} selected records · batch #${b.id}`}
          onClose={() => setApprove(false)}
        >
          <form
            className="form-stack"
            onSubmit={(e) => {
              e.preventDefault();
              void commit();
            }}
          >
            <Notice>
              No records will be submitted to REsimpli. Existing CRM records
              will not be edited. Ambiguous candidates require your resolution
              before execution.
            </Notice>
            <label className="check-label">
              <input
                type="checkbox"
                checked={fillMissing}
                onChange={(e) => setFillMissing(e.target.checked)}
              />
              For explicitly linked duplicates only: fill empty local fields.
              Never overwrite known values, infer contact or update REsimpli.
            </label>
            <Field label="Type IMPORT LOCAL to confirm">
              <input
                autoFocus
                required
                pattern="IMPORT LOCAL"
                value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)}
                placeholder="IMPORT LOCAL"
              />
            </Field>
            {action.error && <Notice tone="danger">{action.error}</Notice>}
            <div className="modal-actions">
              <Button
                variant="secondary"
                type="button"
                onClick={() => setApprove(false)}
              >
                Cancel
              </Button>
              <Button busy={action.busy} type="submit">
                <Check size={16} />
                Approve local writes
              </Button>
            </div>
          </form>
        </Modal>
      )}
      {rowDetail && (
        <Modal
          title={`Source row ${rowDetail.row_number} · ${rowDetail.sheet}`}
          subtitle="Original values are preserved alongside normalized fields."
          onClose={() => setRowDetail(null)}
        >
          <div className="form-stack">
            {rowDetail.errors.length > 0 && (
              <Notice tone="danger">{rowDetail.errors.join(" · ")}</Notice>
            )}
            {rowDetail.warnings.length > 0 && (
              <Notice tone="warning">{rowDetail.warnings.join(" · ")}</Notice>
            )}
            <h3>Normalized values</h3>
            <pre className="json-preview">
              {JSON.stringify(rowDetail.normalized, null, 2)}
            </pre>
            <h3>Original source values</h3>
            <pre className="json-preview">
              {JSON.stringify(rowDetail.original, null, 2)}
            </pre>
          </div>
        </Modal>
      )}
    </>
  );
}
