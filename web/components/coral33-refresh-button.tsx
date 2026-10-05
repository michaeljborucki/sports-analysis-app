"use client";
import { useState } from "react";
import clsx from "clsx";
import { RefreshCw } from "lucide-react";

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
      const summary = `${total.toLocaleString()} rows in ${data.duration_s.toFixed(1)}s`;
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
    <div className="inline-flex items-center gap-3">
      {status.kind === "done" && (
        <span role="status" className="text-[length:var(--fs-12)] text-text-2">
          {status.summary}
        </span>
      )}
      {status.kind === "error" && (
        <span role="status" className="text-[length:var(--fs-12)] text-loss">
          Refresh failed: {status.message}
        </span>
      )}
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className={clsx(
          "inline-flex h-8 items-center gap-2 rounded-md border border-border-subtle bg-bg-1 px-3",
          "text-[length:var(--fs-13)] font-medium transition-colors",
          busy ? "cursor-wait text-text-3" : "text-text-2 hover:bg-bg-2 hover:text-text-1",
        )}
        title="Kick off a Coral33 refresh cycle immediately (main, then alternates and props). Takes about 5 to 10 seconds."
      >
        <RefreshCw size={13} aria-hidden className={clsx(busy && "animate-spin")} />
        {busy ? "Refreshing Coral33…" : "Refresh Coral33"}
      </button>
    </div>
  );
}
