"use client";
import useSWR from "swr";
import clsx from "clsx";
import { AlertCircle, Check, Wallet } from "lucide-react";

import { fetchJson } from "@/lib/api";

/**
 * AccountPickerGrid — selectable variant of AccountPoolGrid for the
 * account-first /sidecar flow.
 *
 * Difference vs AccountPoolGrid: each card is a button. Clicking commits
 * the customer_id to the parent (page.tsx). The bet feed below the
 * picker only renders once a selection exists, so the workflow reads
 * top-down: pick account → see bets → click PLACE on a row.
 *
 * The pinned customer_id flows into POST /api/sidecar/place, where the
 * splitter constrains the plan to that one account and stacks multi-
 * parlays on it up to the Kelly target.
 */

interface AccountSnapshotApi {
  customer_id: string;
  label: string;
  player_name: string | null;
  current_balance: number;
  available_balance: number;
  pending_wager_balance: number;
  free_play_balance: number;
  max_parlay_stake?: number;
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

export interface SelectedAccount {
  customer_id: string;
  label: string;
  available_balance: number;
  max_parlay_stake: number;
}

function fmtUsd(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  })}`;
}

export function AccountPickerGrid({
  selected,
  onSelect,
}: {
  selected: SelectedAccount | null;
  onSelect: (account: SelectedAccount | null) => void;
}) {
  // Hit the sidecar-scoped endpoint (not /api/coral33/accounts) so the
  // picker mirrors the splitter's eligibility — accounts without a
  // residential proxy (e.g. VR12509) are excluded from both.
  const { data, isLoading, error } = useSWR<AccountsRollupApi>(
    "/api/sidecar/accounts",
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

  // Sort by available_balance descending — bias the first click toward
  // the account with the most room. Drain-order semantics are gone here;
  // a pinned plan stays on one account by construction.
  const sorted = [...data.snapshots].sort(
    (a, b) => b.available_balance - a.available_balance,
  );

  return (
    <section className="flex flex-col gap-2">
      <header className="flex items-center justify-between gap-2 px-0.5">
        <h2 className="text-[10px] uppercase tracking-wider text-text-3 flex items-center gap-1.5">
          <Wallet size={11} aria-hidden />
          Pick account ({sorted.length})
        </h2>
        <span className="text-[10px] tabular text-text-3">
          {selected
            ? `→ ${selected.label || selected.customer_id}`
            : "click a card to begin"}
        </span>
      </header>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-1.5">
        {sorted.map((s) => (
          <PickerCard
            key={s.customer_id}
            snap={s}
            isSelected={selected?.customer_id === s.customer_id}
            onClick={() => {
              if (selected?.customer_id === s.customer_id) {
                onSelect(null); // toggle off
                return;
              }
              onSelect({
                customer_id: s.customer_id,
                label: s.player_name || s.label || s.customer_id,
                available_balance: s.available_balance,
                max_parlay_stake: s.max_parlay_stake ?? 100,
              });
            }}
          />
        ))}
      </div>
    </section>
  );
}

function PickerCard({
  snap,
  isSelected,
  onClick,
}: {
  snap: AccountSnapshotApi;
  isSelected: boolean;
  onClick: () => void;
}) {
  const cap = snap.max_parlay_stake ?? 100;
  const display = snap.player_name || snap.label || snap.customer_id;
  const isLow = snap.available_balance < 30; // FLOOR
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!!snap.error || isLow}
      className={clsx(
        "text-left border rounded-md px-2.5 py-2 flex flex-col gap-1 transition-colors",
        "focus-visible:outline focus-visible:outline-1 focus-visible:outline-violet-accent",
        snap.error
          ? "border-price-down/40 bg-bg-1 cursor-not-allowed opacity-60"
          : isLow
            ? "border-flash/40 bg-bg-1 cursor-not-allowed opacity-60"
            : isSelected
              ? "border-violet-accent bg-violet-accent/10 ring-1 ring-violet-accent"
              : "border-border-subtle bg-bg-1 hover:border-violet-accent/60 hover:bg-bg-2",
      )}
      title={
        snap.error
          ? snap.error
          : isLow
            ? "Available balance below $30 floor"
            : `Pin placements to ${display}`
      }
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          {isSelected && (
            <Check size={11} className="text-violet-accent shrink-0" aria-hidden />
          )}
          <span className="text-text-1 text-[12px] font-medium truncate">
            {display}
          </span>
        </div>
        <span className="text-text-3 text-[10px] tabular shrink-0">
          {snap.customer_id}
        </span>
      </div>

      <div className="flex flex-col gap-0.5">
        <span className="text-[9px] uppercase tracking-wider text-text-3">
          Available
        </span>
        <span
          className={clsx(
            "tabular text-[14px] font-semibold",
            isLow ? "text-flash" : isSelected ? "text-violet-accent" : "text-text-1",
          )}
        >
          {fmtUsd(snap.available_balance)}
        </span>
      </div>

      <div className="flex items-center justify-between gap-2 mt-0.5">
        <span
          className="inline-flex items-center px-1 py-0.5 rounded-sm bg-bg-2 text-text-2 text-[10px] tabular"
          title="Maximum stake per parlay"
        >
          cap ${cap}
        </span>
        <span
          className="text-text-3 text-[10px] tabular"
          title="Open bets riding"
        >
          {snap.wagers.open_count} open
        </span>
      </div>

      {snap.error && (
        <div className="text-price-down text-[10px] mt-0.5 flex items-center gap-1">
          <AlertCircle size={10} aria-hidden />
          <span className="truncate">{snap.error}</span>
        </div>
      )}
    </button>
  );
}
