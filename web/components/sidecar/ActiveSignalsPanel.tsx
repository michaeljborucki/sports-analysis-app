"use client";
import { useMemo } from "react";
import useSWR from "swr";
import clsx from "clsx";
import { Activity, AlertCircle } from "lucide-react";

import { fetchJson } from "@/lib/api";

/**
 * ActiveSignalsPanel — armed signals the sidecar is actively watching
 * for delta-driven re-fires. Each card surfaces the predicate the
 * delta-tick uses to decide whether to top up:
 *
 *   delta-to-fire = (target_now - total_placed)
 *
 * where target_now = kelly_pct × bankroll_at_arm (the bankroll snapshot
 * the signal was armed against). Green ≥ $30 (FLOOR) means the next
 * delta-tick will fire another placement; gray means below threshold,
 * waiting on the next price/EV refresh.
 *
 * Sorted by largest delta first.
 */

const FLOOR = 30;

interface ActiveSignal {
  ev_row_id: string;
  kelly_fraction: string;
  bankroll_at_arm: number;
  total_placed: number;
  first_armed_at: number;
  last_checked_at: number | null;
  last_delta_at: number | null;
  last_target: number | null;
  /** Optional pretty label the server may include for cleaner UI. */
  label?: string | null;
}

interface ActiveSignalsResponse {
  signals: ActiveSignal[];
}

function fmtUsd(n: number | null | undefined): string {
  if (n == null) return "—";
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
}

function fmtTimeAgo(epoch: number | null | undefined): string {
  if (!epoch) return "—";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/**
 * Parse an ev_row_id into a friendlier label. The id schema is
 * documented in the EV scanner as a `|`-delimited tuple, typically
 *   "<event_id>|<market_kind>|<outcome>"
 * Falls back to the raw id if the shape doesn't match.
 */
function prettyLabel(s: ActiveSignal): string {
  if (s.label) return s.label;
  const parts = s.ev_row_id.split("|");
  if (parts.length >= 3) {
    const market = parts[1];
    const outcome = parts.slice(2).join(" ").replace(/_/g, " ");
    return `${outcome} · ${market}`;
  }
  return s.ev_row_id;
}

export function ActiveSignalsPanel() {
  const { data, isLoading, error } = useSWR<ActiveSignalsResponse>(
    "/api/sidecar/active-signals",
    fetchJson,
    { refreshInterval: 10_000 },
  );

  const cards = useMemo(() => {
    if (!data?.signals) return [];
    const decorated = data.signals.map((s) => {
      const target = s.last_target ?? 0;
      const delta = Math.max(0, target - s.total_placed);
      return { s, target, delta };
    });
    decorated.sort((a, b) => b.delta - a.delta);
    return decorated;
  }, [data]);

  return (
    <section className="flex flex-col gap-2">
      <header className="flex items-center justify-between gap-2 px-0.5">
        <h2 className="text-[10px] uppercase tracking-wider text-text-3 flex items-center gap-1.5">
          <Activity size={11} aria-hidden />
          Active signals
          <span className="text-text-2 tabular">({cards.length})</span>
        </h2>
        <span className="text-[10px] tabular text-text-3">
          delta ≥ ${FLOOR} → re-fire
        </span>
      </header>

      {isLoading && !data && (
        <div className="text-text-3 text-[11px] italic px-1 py-3">
          Loading active signals…
        </div>
      )}
      {error && (
        <div className="text-price-down text-xs flex items-center gap-1.5 px-1 py-3">
          <AlertCircle size={12} aria-hidden />
          /api/sidecar/active-signals unreachable (Phase F endpoint pending?)
        </div>
      )}
      {!isLoading && !error && cards.length === 0 && (
        <div className="text-text-3 text-[11px] italic px-1 py-3">
          No armed signals. Confirm a placement to arm one.
        </div>
      )}

      {cards.length > 0 && (
        <div className="flex flex-col gap-2">
          {cards.map(({ s, target, delta }) => (
            <ActiveSignalCard
              key={s.ev_row_id}
              signal={s}
              target={target}
              delta={delta}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ActiveSignalCard({
  signal,
  target,
  delta,
}: {
  signal: ActiveSignal;
  target: number;
  delta: number;
}) {
  const willFire = delta >= FLOOR;
  return (
    <div
      className={clsx(
        "border rounded-md bg-bg-1 px-3 py-2 flex flex-col gap-1.5",
        willFire ? "border-price-up/40" : "border-border-subtle",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-text-1 text-[12px] font-medium truncate">
            {prettyLabel(signal)}
          </div>
          <div className="text-text-3 text-[10px] tabular truncate" title={signal.ev_row_id}>
            {signal.ev_row_id}
          </div>
        </div>
        <span
          className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[9px] font-semibold tracking-wider uppercase text-accent bg-accent/15 shrink-0"
          title={`Kelly fraction at arm time: ${signal.kelly_fraction}`}
        >
          {signal.kelly_fraction}
        </span>
      </div>

      <div className="grid grid-cols-4 gap-2">
        <Stat label="Bankroll" value={fmtUsd(signal.bankroll_at_arm)} />
        <Stat label="Placed" value={fmtUsd(signal.total_placed)} size="lg" />
        <Stat label="Last target" value={fmtUsd(target)} />
        <Stat
          label="Δ to fire"
          value={fmtUsd(delta)}
          tone={willFire ? "go" : "wait"}
          size="lg"
        />
      </div>

      <div className="flex items-center justify-between text-[10px] tabular text-text-3">
        <span>armed {fmtTimeAgo(signal.first_armed_at)}</span>
        <span>
          last checked {fmtTimeAgo(signal.last_checked_at)}
        </span>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
  size = "md",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "go" | "wait";
  size?: "md" | "lg";
}) {
  return (
    <div className="flex flex-col">
      <span className="text-[9px] uppercase tracking-wider text-text-3">
        {label}
      </span>
      <span
        className={clsx(
          "tabular font-semibold",
          size === "lg" ? "text-[15px]" : "text-[12px]",
          tone === "neutral" && "text-text-1",
          tone === "go" && "text-price-up",
          tone === "wait" && "text-text-3",
        )}
      >
        {value}
      </span>
    </div>
  );
}
