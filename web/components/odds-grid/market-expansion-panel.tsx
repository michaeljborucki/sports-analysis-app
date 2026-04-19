"use client";
import { useState } from "react";
import clsx from "clsx";
import useSWRMutation from "swr/mutation";

import type { Game, Market, MarketOutcome, BookPrice } from "@/lib/api";
import { refreshEventUrl } from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { findAllBest } from "@/lib/consensus";
import type { Sport, MarketGroup } from "@/lib/sports";
import { renderTeam } from "@/lib/sports";
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

function pointOf(o: MarketOutcome): number | null {
  return o.best_price?.point ?? o.prices[0]?.point ?? null;
}

interface PairedRow {
  /** Signed line from the home team's / Over's perspective. */
  point: number | null;
  /** Over (for totals) or Away (for spreads/moneyline). */
  left?: MarketOutcome;
  /** Under (for totals) or Home (for spreads/moneyline). */
  right?: MarketOutcome;
  /** True when this line is the "main" line (from mainKey market). */
  isMain: boolean;
}

/**
 * Pair up outcomes into rows for side-by-side display:
 *   totals  → {point, Over, Under}
 *   spreads → {home-side-point, Away, Home}  (paired by |point|)
 *   moneyline → {null, Away, Home}  (a single row)
 */
function buildPairedRows(game: Game, group: MarketGroup): PairedRow[] {
  const main = findMarket(game, group.mainKey);
  const alt = group.altKey ? findMarket(game, group.altKey) : undefined;
  const mainOutcomes = main?.outcomes ?? [];
  const all = [...mainOutcomes, ...(alt?.outcomes ?? [])];
  if (all.length === 0) return [];

  if (group.display === "total") {
    // Points where the main line exists — used for "isMain" flagging
    const mainPoints = new Set<number>();
    for (const o of mainOutcomes) {
      const p = pointOf(o);
      if (p != null) mainPoints.add(p);
    }
    const byPoint = new Map<number, { over?: MarketOutcome; under?: MarketOutcome }>();
    for (const o of all) {
      const p = pointOf(o);
      if (p == null) continue;
      const bucket = byPoint.get(p) ?? {};
      if (o.outcome_name === "Over") bucket.over = o;
      else if (o.outcome_name === "Under") bucket.under = o;
      byPoint.set(p, bucket);
    }
    return [...byPoint.entries()]
      .sort(([a], [b]) => a - b)
      .map(([point, { over, under }]) => ({
        point,
        left: over,
        right: under,
        isMain: mainPoints.has(point),
      }));
  }

  if (group.display === "spread") {
    // Pair home- and away-sided outcomes by absolute point. Each pair has a
    // `home` point (signed) that drives the display ordering.
    const mainAbs = new Set<number>();
    for (const o of mainOutcomes) {
      const p = pointOf(o);
      if (p != null) mainAbs.add(Math.abs(p));
    }
    const byAbs = new Map<
      number,
      { away?: MarketOutcome; home?: MarketOutcome; homePoint?: number }
    >();
    for (const o of all) {
      const p = pointOf(o);
      if (p == null) continue;
      const bucket = byAbs.get(Math.abs(p)) ?? {};
      if (o.outcome_name === game.home_team) {
        bucket.home = o;
        bucket.homePoint = p;
      } else if (o.outcome_name === game.away_team) {
        bucket.away = o;
        bucket.homePoint = bucket.homePoint ?? -p;
      }
      byAbs.set(Math.abs(p), bucket);
    }
    return [...byAbs.entries()]
      .sort(([, a], [, b]) => (a.homePoint ?? 0) - (b.homePoint ?? 0))
      .map(([absPoint, { away, home, homePoint }]) => ({
        point: homePoint ?? absPoint,
        left: away,
        right: home,
        isMain: mainAbs.has(absPoint),
      }));
  }

  // moneyline — no alts, one pair
  const away = all.find(o => o.outcome_name === game.away_team);
  const home = all.find(o => o.outcome_name === game.home_team);
  return [{ point: null, left: away, right: home, isMain: true }];
}

function formatLine(point: number | null, display: MarketGroup["display"]): string {
  if (display === "moneyline" || point == null) return "—";
  if (display === "spread") return point > 0 ? `+${point}` : `${point}`;
  return `${point}`;
}

function PriceCell({
  outcome,
  visible,
}: {
  outcome?: MarketOutcome;
  visible: Set<string>;
}) {
  if (!outcome) return <span className="text-text-3">—</span>;
  const visiblePrices = outcome.prices.filter(p => visible.has(p.bookmaker_key));
  const tied = findAllBest(visiblePrices);
  const best: BookPrice | undefined = tied[0];
  return (
    <span className="inline-flex items-baseline gap-2">
      {best ? (
        <span className="inline-flex items-baseline gap-1">
          <span className="text-price-up font-semibold tabular">
            {formatAmerican(best.price_american)}
          </span>
          <BookLogo bookKey={best.bookmaker_key} mode="label" />
        </span>
      ) : (
        <span className="text-text-3">—</span>
      )}
      {outcome.consensus_price_american != null && (
        <span className="text-text-3 text-[10px] tabular">
          con {formatAmerican(outcome.consensus_price_american)}
        </span>
      )}
      <span className="text-text-3 text-[10px] tabular">
        {outcome.prices.length}b
      </span>
    </span>
  );
}

export function MarketExpansionPanel({
  game,
  sport,
  group,
  visible,
}: {
  game: Game;
  sport: Sport;
  /** The market tab currently selected in the main grid — the expansion mirrors it. */
  group: MarketGroup;
  visible: Set<string>;
}) {
  const rows = buildPairedRows(game, group);

  // Column headers depend on the market display type
  let leftHeader: string;
  let rightHeader: string;
  if (group.display === "total") {
    leftHeader = "Over";
    rightHeader = "Under";
  } else {
    leftHeader = renderTeam(game.away_team, sport);
    rightHeader = renderTeam(game.home_team, sport);
  }

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

  return (
    <div className="p-4 bg-bg-1/40 border-l-2 border-accent/60 flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-[11px] uppercase tracking-wider text-text-2">
          {group.label} — main + alt lines
        </span>
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
              <th className="text-left px-3 py-1.5 font-medium uppercase tracking-wide text-[10px] w-[90px]">
                Line
              </th>
              <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                {leftHeader}
              </th>
              <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                {rightHeader}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={3}
                  className="text-center text-text-3 py-4 text-[11px]"
                >
                  No lines cached in this market yet.
                </td>
              </tr>
            ) : (
              rows.map((r, i) => (
                <tr
                  key={`${r.point ?? "ml"}-${i}`}
                  className={clsx(
                    "border-t border-border-subtle/40",
                    r.isMain ? "bg-bg-1/60" : "hover:bg-bg-1/30"
                  )}
                >
                  <td className="px-3 py-1.5 tabular whitespace-nowrap">
                    <span className="inline-flex items-center gap-2">
                      {r.isMain && (
                        <span
                          className="inline-flex items-center px-1 py-px rounded-sm text-[9px] font-semibold uppercase tracking-wide bg-accent/15 text-accent"
                          title="Main line"
                        >
                          Main
                        </span>
                      )}
                      <span
                        className={clsx(
                          r.isMain ? "text-text-1" : "text-text-2"
                        )}
                      >
                        {formatLine(r.point, group.display)}
                      </span>
                    </span>
                  </td>
                  <td className="px-2 py-1.5">
                    <PriceCell outcome={r.left} visible={visible} />
                  </td>
                  <td className="px-2 py-1.5">
                    <PriceCell outcome={r.right} visible={visible} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
