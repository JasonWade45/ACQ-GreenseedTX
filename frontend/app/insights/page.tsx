"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge, ErrorBox, PageHeader, Spinner, useAsync } from "@/components/UI";
import { AiStatus, BatchProgress, apiGet, apiPost } from "@/lib/api";

export default function InsightsPage() {
  const status = useAsync<AiStatus>(() => apiGet<AiStatus>("/api/ai/status"));
  const [batch, setBatch] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<BatchProgress | null>(null);

  async function runBatch() {
    setError(null);
    setBatch(null);
    try {
      const start = await apiPost<BatchProgress>("/api/ai/analyze-batch?limit=200&background=true");
      setProgress(start);
      setRunning(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    if (!running) return;
    const id = setInterval(async () => {
      try {
        const p = await apiGet<BatchProgress>("/api/ai/analyze-progress");
        setProgress(p);
        if (!p.running) {
          setRunning(false);
          setBatch(
            p.error
              ? `Batch stopped: ${p.error}`
              : `Processed ${p.done} lead(s): ${p.groq} analysed on Groq, ${p.rules} on rules, ${p.skipped} already up to date. ` +
                  "Run again to continue through the list (up to 200 per run).",
          );
          status.reload();
        }
      } catch {
        /* transient poll failure — the next tick retries */
      }
    }, 2500);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const engine = status.data?.engine ?? "rules";
  const ready = Boolean(status.data?.available);
  const readyLabel =
    engine === "groq" ? "Groq cloud AI ready" : engine === "ollama" ? "Local AI ready" : "Rules engine only";
  const engineBadge =
    engine === "groq"
      ? "bg-brand-100 text-brand-800"
      : engine === "ollama"
        ? "bg-sky-100 text-sky-800"
        : "bg-amber-100 text-amber-800";
  const pct =
    progress && progress.total > 0 ? Math.min(100, Math.round((progress.done / progress.total) * 100)) : 2;

  return (
    <>
      <PageHeader
        title="AI insights"
        subtitle="Batch analysis organises notes, activities and property data into structured per-lead insights. Advisory only — always review before acting."
        actions={
          <button
            className="btn-primary"
            disabled={running || !ready}
            onClick={runBatch}
            title={ready ? "Analyse up to 200 leads per run" : "No model engine available"}
          >
            {running ? (
              <span className="flex items-center gap-2">
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-brand-200 border-t-white" />
                Analyzing…
              </span>
            ) : (
              "Analyze / upgrade leads"
            )}
          </button>
        }
      />

      {status.loading && <Spinner />}
      {status.error && <ErrorBox message={status.error} onRetry={status.reload} />}

      {status.data && (
        <div
          className={`mb-4 rounded-lg border p-4 transition ${
            ready ? "border-brand-200 bg-brand-50/60" : "border-amber-200 bg-amber-50"
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-ink-900">{readyLabel}</span>
            <Badge className={engineBadge}>engine: {engine}</Badge>
            {status.data.model_in_use && <Badge className="bg-ink-100 text-ink-700">{status.data.model_in_use}</Badge>}
            {ready && <span className="pulse-dot inline-block h-2 w-2 rounded-full bg-brand-500" aria-hidden="true" />}
          </div>
          <p className="mt-1.5 text-sm text-ink-700">{status.data.message}</p>
          <p className="mt-1 text-xs text-ink-500">{status.data.disclaimer}</p>
          {!ready && (
            <pre className="mt-2 overflow-x-auto rounded bg-ink-950 p-3 text-[11px] text-ink-200">
{`# Option A (fast, cloud): add to backend/.env then restart
GROQ_API_KEY=...        # https://console.groq.com/keys
# Option B (local): install https://ollama.com then:
ollama pull ${status.data.configured_model}`}
            </pre>
          )}
        </div>
      )}

      {running && progress && (
        <div className="anim-in mb-4 rounded-xl border border-brand-200 bg-white p-4 shadow-[0_1px_2px_rgba(16,24,40,0.05)]">
          <div className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 font-semibold text-ink-900">
              <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
              Analyzing leads in the background…
            </span>
            <span className="tabular-nums text-ink-600">
              {progress.done} / {progress.total || "?"}
            </span>
          </div>
          <div className="mt-2.5 h-2.5 overflow-hidden rounded-full bg-ink-100">
            <div
              className="h-full rounded-full bg-gradient-to-r from-brand-400 to-brand-600 transition-[width] duration-700 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-xs">
            <Badge className="bg-brand-100 text-brand-800">Groq: {progress.groq}</Badge>
            <Badge className="bg-ink-100 text-ink-700">Rules: {progress.rules}</Badge>
            <Badge className="bg-ink-100 text-ink-700">Skipped: {progress.skipped}</Badge>
            <span className="text-ink-400">You can leave this page — the run continues on the server.</span>
          </div>
        </div>
      )}

      {batch && (
        <div className="anim-in mb-4 rounded-lg border border-brand-200 bg-brand-50/60 p-3 text-sm text-ink-700">
          {batch}
        </div>
      )}
      {error && <ErrorBox message={error} />}

      <section className="card p-4">
        <h2 className="mb-2 text-sm font-semibold text-ink-800">How analysis works</h2>
        <ul className="list-disc space-y-1 pl-5 text-sm text-ink-600">
          <li>Each lead is analyzed from its stored activities, notes, appointments and property record only.</li>
          <li>Facts, inferences and unknowns are reported separately; evidence references are shown where available.</li>
          <li>
            Re-analysis runs when the underlying context changed, and upgrades older rule-based insights to the live
            model.
          </li>
          <li>Each run processes up to 200 leads — run it again to continue through the full list.</li>
          <li>
            Message drafts are never sent. Open a lead profile to generate, edit and copy a draft for your approved
            outreach workflow.
          </li>
          <li>Leads flagged Do Not Contact never receive marketing drafts.</li>
        </ul>
      </section>

      <section className="card mt-4 p-4">
        <h2 className="mb-2 text-sm font-semibold text-ink-800">Review insights by lead</h2>
        <p className="text-sm text-ink-600">
          Analysis results appear on each lead profile under <span className="font-medium">AI analysis</span>.{" "}
          <Link className="underline" href="/leads">
            Browse leads
          </Link>{" "}
          to open one.
        </p>
      </section>
    </>
  );
}
