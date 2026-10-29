import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, RotateCcw, ShieldAlert } from "lucide-react";
import { api, patch, post } from "../api";
import {
  Badge,
  Button,
  Empty,
  ErrorState,
  Field,
  Loading,
  PageHeader,
  Panel,
  useAction,
} from "../components";

type Template = {
  id: number;
  category: string;
  raw_category: string;
  variant: string | null;
  body: string;
  active: boolean;
  version: number;
  stats: Record<string, number>;
  banned_words: string[];
};

export default function TemplatesPage() {
  const data = useQuery({
    queryKey: ["templates"],
    queryFn: () => api<Template[]>("/message-templates"),
  });
  const client = useQueryClient();
  const action = useAction();
  const [edits, setEdits] = useState<Record<number, string>>({});

  if (data.isPending) return <Loading />;
  if (data.isError)
    return <ErrorState error={data.error} retry={() => data.refetch()} />;

  const byCategory = data.data.reduce<Record<string, Template[]>>((acc, item) => {
    acc[item.category] = acc[item.category] || [];
    acc[item.category].push(item);
    return acc;
  }, {});

  async function save(item: Template) {
    await action.run(
      () =>
        patch(`/message-templates/${item.id}`, {
          body: edits[item.id] ?? item.body,
        }),
      "Template saved. It was validated before saving.",
    );
    setEdits((current) => {
      const next = { ...current };
      delete next[item.id];
      return next;
    });
    await data.refetch();
    client.invalidateQueries({ queryKey: ["templates"] });
  }

  async function reset() {
    if (
      !window.confirm(
        "Restore the reviewed default wording? Your edited template bodies will be replaced.",
      )
    )
      return;
    await action.run(
      () => post("/message-templates/reset"),
      "Default templates restored",
    );
    await data.refetch();
  }

  return (
    <>
      <PageHeader
        eyebrow="WORDING YOU CONTROL"
        title="Message templates"
        description="Short, plain, compliant drafts. Every template is validated in code: identity, address, opt-out line, no emoji, no links, no invented urgency."
        actions={
          <Button variant="secondary" busy={action.busy} onClick={reset}>
            <RotateCcw size={14} /> Restore defaults
          </Button>
        }
      />
      {Object.entries(byCategory).map(([category, items]) => (
        <Panel key={category} title={category.replaceAll("_", " ")}>
          <div className="stack">
            {items.map((item) => {
              const blocked = item.banned_words.length > 0;
              return (
                <div key={item.id} className="stack">
                  <div className="row wrap">
                    <Badge tone="neutral">variant {item.variant || "default"}</Badge>
                    <Badge tone="neutral">v{item.version}</Badge>
                    <Badge tone={item.active ? "green" : "neutral"}>
                      {item.active ? "active" : "inactive"}
                    </Badge>
                    {blocked && (
                      <Badge tone="red">
                        <ShieldAlert size={12} /> validator: {item.banned_words.join(", ")}
                      </Badge>
                    )}
                  </div>
                  <Field label="Template body">
                    <textarea
                      rows={6}
                      value={edits[item.id] ?? item.body}
                      onChange={(e) =>
                        setEdits((current) => ({
                          ...current,
                          [item.id]: e.target.value,
                        }))
                      }
                    />
                  </Field>
                  <div className="row wrap">
                    <Button
                      variant="secondary"
                      busy={action.busy}
                      disabled={edits[item.id] === undefined}
                      onClick={() => save(item)}
                    >
                      <Check size={15} /> Save template
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </Panel>
      ))}
      {Object.keys(byCategory).length === 0 && (
        <Empty
          title="No templates"
          description="Restore the reviewed defaults to begin."
        />
      )}
      <p className="muted" style={{ fontSize: 12 }}>
        Templates only ever produce drafts for review. No send, dialer or
        automatic outreach exists anywhere in this app.
      </p>
    </>
  );
}
