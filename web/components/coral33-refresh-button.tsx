"use client";
import { useState } from "react";
import clsx from "clsx";

import { apiPaths } from "@/lib/api";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Status =
  | { kind: "idle" }
  | { kind: "refreshing" }
  | { kind: "done"; summary: string }
  | { kind: "error"; message: string };

/**
 * Triggers an immediate coral33 refresh cycle across every configured sport.
 * Main runs first for each sport; alt and prop follow in random order per
 * cycle. Sports run in parallel. Returns row counts per sport when done.
 */
export function Coral33RefreshButton() {
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  async function onClick() {
    setStatus({ kind: "refreshing" });
    try {
      const res = await fetch(`${API_BASE}${apiPaths.coral33Refresh}`, {
        method: "POST",
        cache: "no-store",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as {
        status: string;
        sports_refreshed: string[];
        duration_s: number;
        last_cycle_rows: Record<string, number>;
        errors: string[];
      };
      const total = Object.values(data.last_cycle_rows).reduce(
        (a, b) => a + b,
        0
      );
      const summary = `${total} rows · ${data.duration_s.toFixed(1)}s`;
      setStatus({ kind: "done", summary });
      setTimeout(() => setStatus({ kind: "idle" }), 6000);
    } catch (e) {
      setStatus({
        kind: "error",
        message: e instanceof Error ? e.message : String(e),
      });
      setTimeout(() => setStatus({ kind: "idle" }), 6000);
    }
  }

  const busy = status.kind === "refreshing";

  return (
    <div className="inline-flex items-center gap-2">
      <button
        onClick={onClick}
        disabled={busy}
        className={clsx(
          "h-8 px-3 rounded-md text-xs font-medium transition-colors inline-flex items-center gap-2",
          "border",
          busy
            ? "bg-bg-1 border-border-subtle text-text-3 cursor-wait"
            : "bg-bg-1 border-border-subtle text-text-2 hover:text-text-1"
        )}
        title="Kick off a coral33 refresh cycle immediately (main → alt/prop). ~5–10s."
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={busy ? "animate-spin" : ""}
          aria-hidden
        >
          <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
          <path d="M21 3v5h-5" />
          <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
          <path d="M8 16H3v5" />
        </svg>
        <span>
          {busy ? "Refreshing coral33…" : "Refresh coral33"}
        </span>
      </button>
      {status.kind === "done" && (
        <span className="text-[11px] text-accent tabular">{status.summary}</span>
      )}
      {status.kind === "error" && (
        <span className="text-[11px] text-price-down tabular">
          error · {status.message}
        </span>
      )}
    </div>
  );
}
