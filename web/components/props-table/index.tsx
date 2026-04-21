"use client";
import { useMemo, useState } from "react";
import clsx from "clsx";

import type { Game, Market, MarketOutcome } from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { findAllBest } from "@/lib/consensus";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { BookLogo } from "../book-logo";

const PROP_CATEGORIES: {
  key: string;
  label: string;
  markets: { key: string; label: string }[];
}[] = [
  {
    key: "pitcher",
    label: "Pitcher",
    markets: [
      { key: "pitcher_strikeouts", label: "Strikeouts" },
      { key: "pitcher_outs", label: "Outs" },
      { key: "pitcher_hits_allowed", label: "Hits Allowed" },
      { key: "pitcher_earned_runs", label: "Earned Runs" },
      { key: "pitcher_walks", label: "Walks" },
    ],
  },
  {
    key: "batter",
    label: "Batter",
    markets: [
      { key: "batter_hits", label: "Hits" },
      { key: "batter_total_bases", label: "Total Bases" },
      { key: "batter_home_runs", label: "Home Runs" },
      { key: "batter_rbis", label: "RBIs" },
      { key: "batter_runs_scored", label: "Runs" },
      { key: "batter_hits_runs_rbis", label: "Hits + Runs + RBIs" },
      { key: "batter_singles", label: "Singles" },
      { key: "batter_doubles", label: "Doubles" },
      { key: "batter_stolen_bases", label: "Stolen Bases" },
    ],
  },
];

/**
 * A prop outcome is encoded as "Player Name Over" or "Player Name Under" in
 * outcome_name. Split off the trailing Over/Under to recover the player.
 */
function splitOutcomeName(raw: string): { player: string; side: "Over" | "Under" | "?" } {
  const trimmed = raw.trim();
  if (trimmed.endsWith(" Over")) return { player: trimmed.slice(0, -5), side: "Over" };
  if (trimmed.endsWith(" Under")) return { player: trimmed.slice(0, -6), side: "Under" };
  return { player: trimmed, side: "?" };
}

interface PropRow {
  player: string;
  point: number | null;
  over?: MarketOutcome;
  under?: MarketOutcome;
}

function buildPropRows(market: Market | undefined): PropRow[] {
  if (!market) return [];
  const groups = new Map<string, PropRow>();
  for (const o of market.outcomes) {
    const { player, side } = splitOutcomeName(o.outcome_name);
    const point = o.best_price?.point ?? o.prices[0]?.point ?? null;
    const key = `${player}|${point}`;
    const existing = groups.get(key) ?? { player, point };
    if (side === "Over") existing.over = o;
    else if (side === "Under") existing.under = o;
    groups.set(key, existing);
  }
  const rows = [...groups.values()];
  rows.sort((a, b) => a.player.localeCompare(b.player));
  return rows;
}

function SideCell({
  outcome,
  visible,
}: {
  outcome?: MarketOutcome;
  visible: Set<string>;
}) {
  if (!outcome) return <span className="text-text-3">—</span>;
  // Only score books the user has visible globally — mirrors the odds grid's
  // behavior. Consensus across ALL books is still informative, so we keep that
  // unfiltered (matches the established convention on the odds grid).
  const visiblePrices = outcome.prices.filter(p => visible.has(p.bookmaker_key));
  const tied = findAllBest(visiblePrices);
  const best = tied[0];
  const consensus = outcome.consensus_price_american;
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
      {consensus != null && (
        <span className="text-text-3 text-[10px] tabular">
          con {formatAmerican(consensus)}
        </span>
      )}
      <span className="text-text-3 text-[10px] tabular">
        {visiblePrices.length}b
      </span>
    </span>
  );
}

export function PropsTable({ games }: { games: Game[] }) {
  const { visible } = useVisibleBooks();
  const availableMarkets = useMemo(() => {
    const keys = new Set<string>();
    for (const g of games)
      for (const m of g.markets ?? []) keys.add(m.market_key);
    return keys;
  }, [games]);

  const [activeMarket, setActiveMarket] = useState<string>(() => {
    // Default to the first market that actually has data
    for (const cat of PROP_CATEGORIES)
      for (const m of cat.markets) if (availableMarkets.has(m.key)) return m.key;
    return "pitcher_strikeouts";
  });

  if (games.length === 0) {
    return (
      <div className="text-center text-text-3 py-16 text-sm">
        No prop odds cached. Props only populate within ~3 hours of game start
        — turn the fetcher on closer to first pitch.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        {PROP_CATEGORIES.map(cat => (
          <div key={cat.key} className="flex items-center gap-1">
            <span className="text-[10px] uppercase tracking-wider text-text-3 mr-1">
              {cat.label}
            </span>
            {cat.markets.map(m => {
              const has = availableMarkets.has(m.key);
              const active = activeMarket === m.key;
              return (
                <button
                  key={m.key}
                  disabled={!has}
                  onClick={() => setActiveMarket(m.key)}
                  className={clsx(
                    "h-7 px-2.5 rounded-sm text-[11px] font-medium transition-colors",
                    active
                      ? "bg-accent/20 text-accent border border-accent/40"
                      : has
                      ? "bg-bg-1 text-text-2 border border-border-subtle hover:text-text-1"
                      : "bg-bg-1 text-text-3/60 border border-border-subtle opacity-40 cursor-not-allowed"
                  )}
                >
                  {m.label}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-4">
        {games.map(g => {
          const market = g.markets?.find(m => m.market_key === activeMarket);
          const rows = buildPropRows(market);
          return (
            <div
              key={g.event_id}
              className="border border-border-subtle rounded-md overflow-hidden bg-bg-0"
            >
              <div className="bg-bg-1 px-3 py-2 border-b border-border-subtle flex items-center gap-3">
                <span className="text-text-1 font-semibold text-sm">
                  {g.away_team} @ {g.home_team}
                </span>
                <span className="text-text-3 text-[11px] tabular ml-auto">
                  {rows.length} {rows.length === 1 ? "player" : "players"}
                </span>
              </div>
              {rows.length === 0 ? (
                <div className="text-center text-text-3 py-6 text-xs">
                  No props cached for this game in this market.
                </div>
              ) : (
                <table className="w-full text-xs">
                  <thead className="bg-bg-1/50 text-text-2">
                    <tr>
                      <th className="text-left px-3 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                        Player
                      </th>
                      <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                        Line
                      </th>
                      <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                        Over
                      </th>
                      <th className="text-left px-2 py-1.5 font-medium uppercase tracking-wide text-[10px]">
                        Under
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr
                        key={`${r.player}-${r.point}-${i}`}
                        className="border-t border-border-subtle hover:bg-bg-1/40"
                      >
                        <td className="px-3 py-1.5 text-text-1 whitespace-nowrap">
                          {r.player}
                        </td>
                        <td className="px-2 py-1.5 text-text-2 tabular">
                          {r.point != null ? r.point : "—"}
                        </td>
                        <td className="px-2 py-1.5">
                          <SideCell outcome={r.over} visible={visible} />
                        </td>
                        <td className="px-2 py-1.5">
                          <SideCell outcome={r.under} visible={visible} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
