"use client";
import { useState } from "react";
import clsx from "clsx";
import { AlertTriangle, ChevronDown } from "lucide-react";

/**
 * One-line problem statement with optional collapsible details (spec §4).
 * Raw upstream errors belong in `details`, never in the headline.
 */
export function ErrorBanner({
  title,
  details,
  tone = "stale",
  action,
  className,
}: {
  title: React.ReactNode;
  details?: React.ReactNode;
  tone?: "stale" | "loss";
  action?: React.ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div
      role="alert"
      className={clsx(
        "rounded-lg border px-4 py-2.5 text-[length:var(--fs-13)]",
        tone === "stale" ? "border-[var(--stale-25)] bg-[var(--stale-10)]" : "border-[var(--loss-25)] bg-[var(--loss-10)]",
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <AlertTriangle size={14} aria-hidden className={tone === "stale" ? "text-stale" : "text-loss"} />
        <span className="text-text-1">{title}</span>
        <div className="ml-auto flex items-center gap-3">
          {action}
          {details && (
            <button
              type="button"
              onClick={() => setOpen(v => !v)}
              aria-expanded={open}
              className="inline-flex items-center gap-1 text-text-2 hover:text-text-1"
            >
              Details
              <ChevronDown size={12} aria-hidden className={clsx("transition-transform", open && "rotate-180")} />
            </button>
          )}
        </div>
      </div>
      {open && details && (
        <div className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all font-mono text-[length:var(--fs-11)] text-text-3">
          {details}
        </div>
      )}
    </div>
  );
}

/** Standard copy for when the FastAPI backend can't be reached. */
export function BackendUnreachable({ error }: { error?: unknown }) {
  return (
    <ErrorBanner
      tone="loss"
      title="Can't reach the API on :8000. Start the backend, then refresh."
      details={error ? String(error) : undefined}
    />
  );
}
