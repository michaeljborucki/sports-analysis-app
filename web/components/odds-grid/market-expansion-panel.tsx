"use client";
import { useState } from "react";
import clsx from "clsx";
import useSWRMutation from "swr/mutation";

import type { Game, Market, MarketOutcome } from "@/lib/api";
import { refreshEventUrl } from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { findAllBest } from "@/lib/consensus";
import type { Sport, MarketGroup, DisplayKind } from "@/lib/sports";
import { BookLogo } from "../book-logo";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

async function postRefresh(url: string) {
  const res = await fetch(`${API_BASE}${url}`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

function findMarket(game: Game, key: string): Market | undefined {
  return game.markets?.find(m => m.market_key === key);
}

/**
 * Combine a market's main outcomes with its alternate-line outcomes into one
 * unified list. The caller then sorts + renders rows.
 */
function allOutcomes(
  game: Game,
  mainKey: string,
  altKey?: string
): MarketOutcome[] {
  const main = findMarket(game, mainKey)?.outcomes ?? [];
  const alt = altKey ? findMarket(game, altKey)?.outcomes ?? [] : [];
  return [...main, ...alt];
}

/**
 * Format the line part of the row label.
 *   "spread" — e.g., "+1.5"  (sign included)
 *   "total"  — e.g., "7.5"   (plain; Over/Under comes from outcome_name)
 *   "moneyline" — "" (no point)
 */
function formatLine(point: number | null, display: DisplayKind): string {
  if (display === "moneyline" || point == null) return "";
  if (display === "spread") return point > 0 ? `+${point}` : `${point}`;
  return `${point}`;
}

function rowLabel(
  outcome: MarketOutcome,
  game: Game,
  display: DisplayKind
): string {
  const point =
    outcome.best_price?.point ?? outcome.prices[0]?.point ?? null;
  if (display === "moneyline") return outcome.outcome_name;
  if (display === "spread") {
    // "New York Yankees +1.5" — keep full name in the expansion for clarity
    return `${outcome.outcome_name} ${formatLine(point, display)}`.trim();
  }
  // total
  return `${outcome.outcome_name} ${formatLine(point, display)}`.trim();
}

interface LineRow {
  outcome: MarketOutcome;
  point: number | null;
  isMain: boolean;
}

function buildRows(
  game: Game,
  group: MarketGroup
): LineRow[] {
  const mainOutcomes = findMarket(game, group.mainKey)?.outcomes ?? [];
  const mainPoints = new Set(
    mainOutcomes.map(o => o.best_price?.point ?? o.prices[0]?.point ?? null)
  );
  const combined = allOutcomes(game, group.mainKey, group.altKey);
  const rows: LineRow[] = combined.map(o => {
    const point = o.best_price?.point ?? o.prices[0]?.point ?? null;
    return { outcome: o, point, isMain: mainPoints.has(point) };
  });
  // Sort: by outcome_name first (so sides cluster), then by point ascending
  rows.sort((a, b) => {
    const an = a.outcome.outcome_name ?? "";
    const bn = b.outcome.outcome_name ?? "";
    if (an !== bn) return an.localeCompare(bn);
    const ap = a.point ?? 0;
    const bp = b.point ?? 0;
    return ap - bp;
  });
  return rows;
}

function LineRowDisplay({
  row,
  game,
  group,
  visible,
}: {
  row: LineRow;
  game: Game;
  group: MarketGroup;
  visible: Set<string>;
}) {
  const visiblePrices = row.outcome.prices.filter(p =>
    visible.has(p.bookmaker_key)
  );
  const tied = findAllBest(visiblePrices);
  const best = tied[0];
  return (
    <tr
      className={clsx(
        "border-t border-border-subtle/40",
        row.isMain ? "bg-bg-1/60" : "hover:bg-bg-1/30"
      )}
    >
      <td className="px-2 py-1.5 whitespace-nowrap">
        <span className="inline-flex items-center gap-2">
          {row.isMain && (
            <span
              className="inline-flex items-center px-1 py-px rounded-sm text-[9px] font-semibold uppercase tracking-wide bg-accent/15 text-accent"
              title="Main line"
            >
              Main
            </span>
          )}
          <span className={clsx("tabular", row.isMain ? "text-text-1" : "text-text-2")}>
            {rowLabel(row.outcome, game, group.display)}
          </span>
        </span>
      </td>
      <td className="px-2 py-1.5 text-right tabular">
        {best ? (
          <span className="inline-flex items-baseline gap-1">
            <span className="text-price-up font-semibold">
              {formatAmerican(best.price_american)}
            </span>
            <BookLogo bookKey={best.bookmaker_key} mode="label" />
          </span>
        ) : (
          <span className="text-text-3">—</span>
        )}
      </td>
      <td className="px-2 py-1.5 text-right text-text-3 tabular">
        {row.outcome.consensus_price_american != null
          ? formatAmerican(row.outcome.consensus_price_american)
          : "—"}
      </td>
      <td className="px-2 py-1.5 text-text-3 text-[10px] tabular">
        {row.outcome.prices.length}b
      </td>
    </tr>
  );
}

export function MarketExpansionPanel({
  game,
  sport,
  visible,
}: {
  game: Game;
  sport: Sport;
  visible: Set<string>;
}) {
  // Only show tabs for market groups with at least one outcome in this game
  const availableGroups = sport.marketGroups.filter(g => {
    const main = findMarket(game, g.mainKey);
    const alt = g.altKey ? findMarket(game, g.altKey) : undefined;
    return (main?.outcomes.length ?? 0) > 0 || (alt?.outcomes.length ?? 0) > 0;
  });
  const [activeKey, setActiveKey] = useState<string>(
    availableGroups[0]?.mainKey ?? sport.marketGroups[0].mainKey
  );
  const activeGroup =
    availableGroups.find(g => g.mainKey === activeKey) ?? availableGroups[0];

  const [status, setStatus] = useState<string | null>(null);
  const { trigger, isMutating } = useSWRMutation(
    refreshEventUrl(game.event_id),
    (url: string) => postRefresh(url)
  );
  async function handleRefresh() {
    try {
      const r = await trigger();
      setStatus(
        r.status === "debounced"
          ? `Debounced — retry in ${r.retry_after_seconds}s`
          : `Refreshed: ${(r.polled ?? []).join(", ") || "—"}`
      );
      setTimeout(() => setStatus(null), 4000);
    } catch {
      setStatus("Refresh failed");
      setTimeout(() => setStatus(null), 3000);
    }
  }

  if (!activeGroup) {
    return (
      <div className="p-4 bg-bg-1/40 text-xs text-text-3">
        No alt lines cached for this game.
      </div>
    );
  }
  const rows = buildRows(game, activeGroup);

  return (
    <div className="p-4 bg-bg-1/40 border-l-2 border-accent/60 flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
          {availableGroups.map(g => (
            <button
              key={g.mainKey}
              onClick={() => setActiveKey(g.mainKey)}
              className={clsx(
                "px-3 py-1 text-xs tracking-wide uppercase transition-colors rounded-sm",
                activeKey === g.mainKey
                  ? "bg-bg-2 text-text-1"
                  : "text-text-2 hover:text-text-1"
              )}
            >
              {g.label}
            </button>
          ))}
        </div>

        <button
          onClick={handleRefresh}
          disabled={isMutating}
          className={clsx(
            "ml-auto inline-flex items-center gap-1.5 h-7 px-2 rounded-sm text-[10px] font-medium",
            "border border-border-subtle bg-bg-1 text-text-2 hover:text-text-1",
            isMutating && "opacity-60 cursor-wait"
          )}
        >
          <svg
            width="10"
            height="10"
            viewBox="0 0 16 16"
            fill="none"
            className={clsx(isMutating && "animate-spin")}
          >
            <path
              d="M3 8a5 5 0 0 1 8.5-3.5l1-1M13 8a5 5 0 0 1-8.5 3.5l-1 1M11.5 4.5v-3h3M4.5 11.5v3h-3"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Refresh this game
        </button>
        {status && <span className="text-[10px] text-accent">{status}</span>}
      </div>

      <div className="border border-border-subtle rounded-md overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-bg-1 text-text-2">
            <tr>
              <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                {activeGroup.label} — Side / Line
              </th>
              <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                Best
              </th>
              <th className="text-right px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                Consensus
              </th>
              <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                Depth
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={4}
                  className="text-center text-text-3 py-4 text-[11px]"
                >
                  No lines cached in this market yet.
                </td>
              </tr>
            ) : (
              rows.map((r, i) => (
                <LineRowDisplay
                  key={`${r.outcome.outcome_name}-${r.point}-${i}`}
                  row={r}
                  game={game}
                  group={activeGroup}
                  visible={visible}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
