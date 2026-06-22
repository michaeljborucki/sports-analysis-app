"use client";
import useSWR from "swr";
import clsx from "clsx";
import { AlertCircle, Wallet } from "lucide-react";

import { fetchJson } from "@/lib/api";

/**
 * AccountPoolGrid — 7-up grid of Coral33 account cards used by the sidecar
 * dashboard. Reads /api/coral33/accounts (the same rollup the /accounts
 * page uses) and sorts ascending by available balance so the splitter's
 * "lowest balance first" mental model is mirrored visually.
 *
 * Each card surfaces:
 *   - customer_id + label (player_name when present)
 *   - current_balance + available_balance + pending_wager_balance
 *   - max_parlay_stake (defaults to 100 until A1 wires it through the API)
 *   - today's bet count (open_count from the wager summary)
 *   - proxy-status dot — gray placeholder. Real "last 3 placements failed"
 *     wiring lives downstream; the slot is here so the visual vocabulary
 *     locks in now.
 */

interface AccountSnapshotApi {
  customer_id: string;
  label: string;
  player_name: string | null;
  current_balance: number;
  available_balance: number;
  pending_wager_balance: number;
  free_play_balance: number;
  /** Phase-A field — server returns this once A1/A2 ship the proxy +
      max_parlay_stake plumbing. Until then card falls back to 100. */
  max_parlay_stake?: number;
  /** Optional — same Phase-A field. Falls back to "gray" until wired. */
  proxy_url?: string | null;
  wagers: {
    open_count: number;
    open_amount_risked: number;
    parlay_count: number;
    straight_count: number;
  };
  error: string | null;
}

interface AccountsRollupApi {
  snapshots: AccountSnapshotApi[];
  account_count: number;
}

function fmtUsd(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
}

export function AccountPoolGrid() {
  const { data, isLoading, error } = useSWR<AccountsRollupApi>(
    "/api/coral33/accounts",
    fetchJson,
    { refreshInterval: 30_000 },
  );

  if (isLoading && !data) {
    return (
      <div className="text-text-3 text-[11px] italic px-1 py-3">
        Loading account pool…
      </div>
    );
  }
  if (error) {
    return (
      <div className="text-price-down text-xs flex items-center gap-1.5 px-1 py-3">
        <AlertCircle size={12} aria-hidden />
        Failed to load /api/coral33/accounts
      </div>
    );
  }
  if (!data || data.snapshots.length === 0) {
    return (
      <div className="text-text-3 text-[11px] italic px-1 py-3">
        No accounts configured.
      </div>
    );
  }

  // Sort ascending by available balance — splitter drains lowest first,
  // and the card list should read top-to-bottom in that same order.
  const sorted = [...data.snapshots].sort(
    (a, b) => a.available_balance - b.available_balance,
  );

  return (
    <section className="flex flex-col gap-2">
      <header className="flex items-center justify-between gap-2 px-0.5">
        <h2 className="text-[10px] uppercase tracking-wider text-text-3 flex items-center gap-1.5">
          <Wallet size={11} aria-hidden />
          Account pool ({sorted.length})
        </h2>
        <span className="text-[10px] tabular text-text-3">
          drain order →
        </span>
      </header>
      <div className="grid grid-cols-1 gap-1.5">
        {sorted.map((s) => (
          <AccountCard key={s.customer_id} snap={s} />
        ))}
      </div>
    </section>
  );
}

function AccountCard({ snap }: { snap: AccountSnapshotApi }) {
  const cap = snap.max_parlay_stake ?? 100;
  const display = snap.player_name || snap.label || snap.customer_id;
  const isLow = snap.available_balance < 30; // FLOOR
  return (
    <div
      className={clsx(
        "border rounded-md bg-bg-1 px-2.5 py-2 flex flex-col gap-1",
        snap.error
          ? "border-price-down/40"
          : isLow
            ? "border-flash/40"
            : "border-border-subtle",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <ProxyStatusDot />
          <span className="text-text-1 text-[12px] font-medium truncate">
            {display}
          </span>
        </div>
        <span className="text-text-3 text-[10px] tabular shrink-0">
          {snap.customer_id}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 mt-0.5">
        <Stat label="Available" value={fmtUsd(snap.available_balance)} tone={isLow ? "warn" : "primary"} />
        <Stat label="Balance" value={fmtUsd(snap.current_balance)} />
        <Stat label="Pending" value={fmtUsd(snap.pending_wager_balance)} />
      </div>

      <div className="flex items-center justify-between gap-2 mt-0.5">
        <span
          className="inline-flex items-center px-1 py-0.5 rounded-sm bg-bg-2 text-text-2 text-[10px] tabular"
          title="Maximum stake per parlay this account is configured for"
        >
          cap ${cap}
        </span>
        <span
          className="text-text-3 text-[10px] tabular"
          title="Open bets currently riding on this account"
        >
          {snap.wagers.open_count} open
          {snap.wagers.parlay_count > 0 && (
            <span className="text-accent ml-1">· {snap.wagers.parlay_count}P</span>
          )}
        </span>
      </div>

      {snap.error && (
        <div className="text-price-down text-[10px] mt-0.5 flex items-center gap-1">
          <AlertCircle size={10} aria-hidden />
          <span className="truncate" title={snap.error}>
            {snap.error}
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * Proxy-status dot. Defers the "last 3 placements failed → red" logic
 * planned in the sidecar audit work; renders a neutral gray dot today so
 * the visual vocabulary is in place when the predicate lands.
 */
function ProxyStatusDot() {
  return (
    <span
      title="Proxy status (placeholder — last-3-fail predicate pending)"
      className="inline-block w-1.5 h-1.5 rounded-full bg-text-3 shrink-0"
      aria-hidden
    />
  );
}

function Stat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "primary" | "warn";
}) {
  return (
    <div className="flex flex-col">
      <span className="text-[9px] uppercase tracking-wider text-text-3">
        {label}
      </span>
      <span
        className={clsx(
          "tabular text-[12px] font-semibold",
          tone === "primary" && "text-text-1",
          tone === "warn" && "text-flash",
          tone === "neutral" && "text-text-2",
        )}
      >
        {value}
      </span>
    </div>
  );
}
