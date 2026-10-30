import { useState } from "react";
import type { FormEvent } from "react";
import { Play, Plus, Trash2 } from "lucide-react";
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
import { del, post } from "../api";

type Rule = {
  id: number;
  name: string;
  priority: number;
  enabled: boolean;
  is_fallback: boolean;
  state: string | null;
  city: string | null;
  target_assignee: string;
  notes: string | null;
};

type ApplyResult = { considered: number; assigned: number; unmatched: number };

export function AssignmentPage() {
  const rules = useData<Rule[]>("assignment-rules", "/assignment/rules");
  const action = useAction();
  const [name, setName] = useState("");
  const [state, setState] = useState("");
  const [city, setCity] = useState("");
  const [assignee, setAssignee] = useState("");
  const [priority, setPriority] = useState("100");
  const [fallback, setFallback] = useState(false);
  const [onlyUnassigned, setOnlyUnassigned] = useState(true);
  const [result, setResult] = useState<ApplyResult | null>(null);

  if (rules.isPending) return <Loading />;
  if (rules.isError) return <ErrorState error={rules.error} retry={() => rules.refetch()} />;

  async function create(e: FormEvent) {
    e.preventDefault();
    const ok = await action.run(
      () =>
        post("/assignment/rules", {
          name,
          priority: Number(priority),
          enabled: true,
          is_fallback: fallback,
          state: fallback ? null : state ? state.toUpperCase() : null,
          city: fallback ? null : city || null,
          target_assignee: assignee,
        }),
      "Assignment rule created",
    );
    if (ok) {
      setName("");
      setState("");
      setCity("");
      setAssignee("");
      setFallback(false);
    }
  }

  async function apply() {
    const applied = await action.run(
      () => post<ApplyResult>("/assignment/apply", { only_unassigned: onlyUnassigned }),
      "Assignment applied",
    );
    if (applied) setResult(applied);
  }

  return (
    <>
      <PageHeader
        eyebrow="DESK ASSIGNMENT"
        title="Assignments"
        description="State and city rules fill the lead's owner. They never change a stage, a restriction or contact permission."
        actions={
          <Button onClick={apply} disabled={action.busy}>
            <Play size={16} />
            {action.busy ? "Applying…" : "Apply rules"}
          </Button>
        }
      />

      <Panel title="Run options">
        <label className="row" style={{ gap: "0.5rem" }}>
          <input
            type="checkbox"
            checked={onlyUnassigned}
            onChange={(e) => setOnlyUnassigned(e.target.checked)}
          />
          Only fill leads with no owner (never overwrite a manual assignment)
        </label>
        {result && (
          <p className="panel-footnote">
            Considered {result.considered}; assigned {result.assigned}; no matching rule{" "}
            {result.unmatched}.
          </p>
        )}
      </Panel>

      <Panel title={`Rules (${rules.data.length})`} subtitle="Lowest priority number wins; the fallback is last.">
        {rules.data.length === 0 ? (
          <p className="muted">No assignment rules yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Match</th>
                <th>Owner</th>
                <th>Priority</th>
                <th>State</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rules.data.map((rule) => (
                <tr key={rule.id}>
                  <td>{rule.name}</td>
                  <td>
                    {rule.is_fallback ? "Fallback" : [rule.state, rule.city].filter(Boolean).join(" / ")}
                  </td>
                  <td>{rule.target_assignee}</td>
                  <td>{rule.priority}</td>
                  <td>
                    <Badge tone={rule.enabled ? "green" : "red"}>
                      {rule.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </td>
                  <td>
                    <Button
                      variant="ghost"
                      aria-label={`Delete ${rule.name}`}
                      disabled={action.busy}
                      onClick={() =>
                        action.run(() => del(`/assignment/rules/${rule.id}`), "Rule deleted")
                      }
                    >
                      <Trash2 size={15} />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="New rule" subtitle="A rule needs a state, a city, or the fallback flag.">
        <form className="form-stack" onSubmit={create}>
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
          </Field>
          <Field label="State (2 letters)">
            <input
              value={state}
              onChange={(e) => setState(e.target.value.toUpperCase())}
              maxLength={2}
              placeholder="TX"
              disabled={fallback}
            />
          </Field>
          <Field label="City (optional)">
            <input
              value={city}
              onChange={(e) => setCity(e.target.value)}
              maxLength={120}
              placeholder="Austin"
              disabled={fallback}
            />
          </Field>
          <Field label="Owner">
            <input value={assignee} onChange={(e) => setAssignee(e.target.value)} required maxLength={120} />
          </Field>
          <Field label="Priority" hint="Lower numbers run first.">
            <input
              type="number"
              min={0}
              max={1000}
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
            />
          </Field>
          <label className="row" style={{ gap: "0.5rem" }}>
            <input type="checkbox" checked={fallback} onChange={(e) => setFallback(e.target.checked)} />
            Use as the fallback when no state/city rule matches
          </label>
          <Button type="submit" disabled={action.busy || !name.trim() || !assignee.trim()}>
            <Plus size={16} />
            Create rule
          </Button>
        </form>
        {action.error && <p className="form-error">{action.error}</p>}
      </Panel>
    </>
  );
}
