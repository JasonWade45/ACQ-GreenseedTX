import { useState } from "react";
import type { FormEvent } from "react";
import { Play, Plus, RefreshCw } from "lucide-react";
import {
  Badge,
  Button,
  ErrorState,
  Field,
  Loading,
  PageHeader,
  Panel,
  useAction,
  useData,
} from "../components";
import { dateTime, human, patch, post } from "../api";

type Rule = {
  id: number;
  name: string;
  description: string | null;
  rule_type: "stale_lead" | "hot_lead" | "dead_lead";
  config: Record<string, unknown>;
  enabled: boolean;
  last_run_at: string | null;
  last_run_result: string | null;
};

type Log = {
  id: number;
  rule_name: string;
  records_affected: number;
  result: string;
  error_message: string | null;
  started_at: string;
};

type StaleLead = {
  lead_id: number;
  full_name: string;
  stage_code: string;
  contact_status: string;
  assigned_manager: string | null;
  last_contact_at: string | null;
  days_since_contact: number;
  has_pending_followup: boolean;
};

type RunResult = { results: { rule_name: string; affected: number; state: string }[] };

export function AutomationPage() {
  const rules = useData<Rule[]>("automation-rules", "/automation/rules");
  const logs = useData<Log[]>("automation-logs", "/automation/logs?limit=30");
  const stale = useData<StaleLead[]>("automation-stale", "/automation/stale-leads?days=14");
  const action = useAction();
  const [name, setName] = useState("");
  const [ruleType, setRuleType] = useState<Rule["rule_type"]>("stale_lead");
  const [days, setDays] = useState("14");
  const [lastRun, setLastRun] = useState<RunResult | null>(null);

  if (rules.isPending || logs.isPending || stale.isPending) return <Loading />;
  if (rules.isError) return <ErrorState error={rules.error} retry={() => rules.refetch()} />;

  async function create(e: FormEvent) {
    e.preventDefault();
    const config =
      ruleType === "hot_lead"
        ? { action: "create_followup", followup_delay_days: 0 }
        : {
            days_since_contact: Number(days),
            action: "create_followup",
            followup_delay_days: 1,
          };
    const ok = await action.run(
      () =>
        post("/automation/rules", {
          name,
          rule_type: ruleType,
          config,
          enabled: true,
          description: `Created from the automation screen (${ruleType}).`,
        }),
      "Rule created",
    );
    if (ok) setName("");
  }

  async function runAll() {
    const result = await action.run(() => post<RunResult>("/automation/run"), "Automation finished");
    if (result) setLastRun(result);
  }

  return (
    <>
      <PageHeader
        eyebrow="LOCAL AUTOMATION"
        title="Automation"
        description="Rules create follow-ups, tags or a stage change. They never contact a seller, send a message or write to the CRM."
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => action.run(() => post("/automation/seed-defaults"), "Defaults added")}
              disabled={action.busy}
            >
              <RefreshCw size={16} />
              Add defaults
            </Button>
            <Button onClick={runAll} disabled={action.busy}>
              <Play size={16} />
              {action.busy ? "Running…" : "Run all rules"}
            </Button>
          </>
        }
      />

      {lastRun && (
        <Panel title="Last run">
          <ul>
            {lastRun.results.length === 0 && <li>No enabled rules ran.</li>}
            {lastRun.results.map((result) => (
              <li key={result.rule_name}>
                {result.rule_name}: {result.affected} affected ({result.state})
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <Panel title={`Rules (${rules.data.length})`} subtitle="Disabled rules are skipped entirely.">
        {rules.data.length === 0 ? (
          <p className="muted">No rules yet. Add the defaults or create one below.</p>
        ) : (
          <div className="stack">
            {rules.data.map((rule) => (
              <article key={rule.id} className="panel" style={{ padding: "1rem" }}>
                <div className="row" style={{ justifyContent: "space-between", gap: "1rem" }}>
                  <div>
                    <strong>{rule.name}</strong>
                    <div className="row" style={{ gap: "0.4rem", marginTop: "0.3rem" }}>
                      <Badge tone="neutral">{human(rule.rule_type)}</Badge>
                      <Badge tone={rule.enabled ? "green" : "red"}>
                        {rule.enabled ? "Enabled" : "Disabled"}
                      </Badge>
                    </div>
                  </div>
                  <Button
                    variant="secondary"
                    disabled={action.busy}
                    onClick={() =>
                      action.run(
                        () => patch(`/automation/rules/${rule.id}`, { enabled: !rule.enabled }),
                        rule.enabled ? "Rule disabled" : "Rule enabled",
                      )
                    }
                  >
                    {rule.enabled ? "Disable" : "Enable"}
                  </Button>
                </div>
                <p className="muted">{rule.description}</p>
                <p className="muted">
                  {rule.last_run_at
                    ? `Last run ${dateTime(rule.last_run_at)} — ${rule.last_run_result || "no result"}`
                    : "Never run."}
                </p>
              </article>
            ))}
          </div>
        )}
      </Panel>

      <Panel title="New rule" subtitle="Only the three local rule types are accepted.">
        <form className="form-stack" onSubmit={create}>
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
          </Field>
          <Field label="Rule type">
            <select value={ruleType} onChange={(e) => setRuleType(e.target.value as Rule["rule_type"])}>
              <option value="stale_lead">Stale lead — no contact for N days</option>
              <option value="hot_lead">Warm lead — last call was interested</option>
              <option value="dead_lead">Dead lead — no contact for N days</option>
            </select>
          </Field>
          {ruleType !== "hot_lead" && (
            <Field label="Days without contact">
              <input
                type="number"
                min={1}
                max={365}
                value={days}
                onChange={(e) => setDays(e.target.value)}
              />
            </Field>
          )}
          <Button type="submit" disabled={action.busy || !name.trim()}>
            <Plus size={16} />
            Create rule
          </Button>
        </form>
        {action.error && <p className="form-error">{action.error}</p>}
      </Panel>

      <Panel
        title={`Stale leads (${(stale.data ?? []).length})`}
        subtitle="No contact for 14+ days. A pending follow-up is shown, not duplicated."
      >
        {(stale.data ?? []).length === 0 ? (
          <p className="muted">No stale leads at the current threshold.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Lead</th>
                <th>Stage</th>
                <th>Days</th>
                <th>Owner</th>
                <th>Follow-up</th>
              </tr>
            </thead>
            <tbody>
              {(stale.data ?? []).slice(0, 50).map((lead) => (
                <tr key={lead.lead_id}>
                  <td>{lead.full_name}</td>
                  <td>{human(lead.stage_code)}</td>
                  <td>{lead.days_since_contact}</td>
                  <td>{lead.assigned_manager || "Unassigned"}</td>
                  <td>{lead.has_pending_followup ? "Pending" : "None"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Run log" subtitle="Every run records its counts and any failure.">
        <table>
          <thead>
            <tr>
              <th>Rule</th>
              <th>Result</th>
              <th>Affected</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {(logs.data ?? []).map((log) => (
              <tr key={log.id}>
                <td>{log.rule_name}</td>
                <td>{log.result}</td>
                <td>{log.records_affected}</td>
                <td>{dateTime(log.started_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(logs.data ?? []).length === 0 && <p className="muted">No runs yet.</p>}
      </Panel>
    </>
  );
}

