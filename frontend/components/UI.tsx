"use client";

import { useEffect, useState } from "react";

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-ink-500">
      <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
      {label}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="card border-red-200 bg-red-50 p-4">
      <div className="text-sm font-semibold text-red-800">Something went wrong</div>
      <div className="mt-1 break-words text-sm text-red-700">{message}</div>
      {onRetry && (
        <button onClick={onRetry} className="btn mt-3">
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="card p-10 text-center">
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 ring-1 ring-brand-100">
        <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" aria-hidden="true">
          <path d="M12 21v-8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          <path d="M12 13C12 8.6 8.6 5.2 4.2 5.2c0 4.4 3.4 7.8 7.8 7.8z" fill="currentColor" />
          <path d="M12 13c0-3.8 2.9-6.7 6.7-6.7 0 3.8-2.9 6.7-6.7 6.7z" fill="currentColor" fillOpacity="0.55" />
        </svg>
      </div>
      <div className="text-base font-semibold text-ink-800">{title}</div>
      <p className="mx-auto mt-2 max-w-xl text-sm text-ink-500">{description}</p>
      {action && <div className="mt-4 flex justify-center gap-2">{action}</div>}
    </div>
  );
}

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fn()
      .then((result) => {
        if (alive) setData(result);
      })
      .catch((err: Error) => {
        if (alive) setError(err.message || String(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}

export function Badge({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`badge ${className}`}>{children}</span>;
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-center gap-3">
        <span className="h-8 w-1.5 shrink-0 rounded-full bg-gradient-to-b from-brand-400 to-brand-600" />
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink-950">{title}</h1>
          {subtitle && <p className="mt-0.5 text-sm text-ink-500">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CopyButton({ text, label = "Copy draft" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="btn"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
        } catch {
          const ta = document.createElement("textarea");
          ta.value = text;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          document.body.removeChild(ta);
        }
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      }}
    >
      {copied ? "Copied ✓" : label}
    </button>
  );
}
