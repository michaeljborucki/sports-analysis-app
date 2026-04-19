"use client";
import { useMemo, useState } from "react";
import clsx from "clsx";

import type { Game, Market, MarketOutcome } from "@/lib/api";
import { formatAmerican, formatBookAbbrev } from "@/lib/format";
import { MarketTabs, type MarketKey } from "./market-tabs";
import { BestCell } from "./best-cell";
import { CellFlash } from "./cell-flash";

const BOOK_ORDER = [
  "draftkings",
  "fanduel",
  "betmgm",
  "caesars",
  "williamhill_us",
  "fanatics",
  "hardrockbet",
  "espnbet",
  "pointsbetus",
  "betrivers",
  "unibet_us",
  "twinspires",
  "superbook",
  "lowvig",
  "betonlineag",
  "bovada",
  "betus",
  "mybookieag",
];

function findMarket(game: Game, key: MarketKey): Market | undefined {
  return game.markets?.find(m => m.market_key === key);
}

function priceAtBook(outcome: MarketOutcome | undefined, bookKey: string) {
  return outcome?.prices.find(p => p.bookmaker_key === bookKey);
}

function primaryOutcome(
  market: Market | undefined,
  game: Game
): MarketOutcome | undefined {
  if (!market) return undefined;
  if (market.market_key === "h2h" || market.market_key === "spreads") {
    return (
      market.outcomes.find(o => o.outcome_name === game.home_team) ??
      market.outcomes[0]
    );
  }
  if (market.market_key === "totals") {
    return market.outcomes.find(o => o.outcome_name === "Over") ?? market.outcomes[0];
  }
  return market.outcomes[0];
}

export function OddsGrid({ games }: { games: Game[] }) {
  const [market, setMarket] = useState<MarketKey>("h2h");

  const books = useMemo(() => {
    const present = new Set<string>();
    for (const g of games)
      for (const m of g.markets ?? [])
        for (const o of m.outcomes) for (const p of o.prices) present.add(p.bookmaker_key);
    const ordered = BOOK_ORDER.filter(b => present.has(b));
    const extras = [...present].filter(b => !BOOK_ORDER.includes(b)).sort();
    return [...ordered, ...extras].slice(0, 10); // cap visible columns
  }, [games]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-4">
        <MarketTabs value={market} onChange={setMarket} />
        <div className="text-xs text-text-3 tabular">{games.length} games</div>
      </div>

      <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
        <table className="w-full text-xs">
          <thead className="bg-bg-1 text-text-2">
            <tr>
              <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px]">
                Game
              </th>
              <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Best
              </th>
              {books.map(b => (
                <th
                  key={b}
                  className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]"
                >
                  {formatBookAbbrev(b)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {games.length === 0 && (
              <tr>
                <td
                  colSpan={2 + books.length}
                  className="text-center py-12 text-text-3"
                >
                  No MLB odds cached yet. Waiting for fetcher…
                </td>
              </tr>
            )}
            {games.map(g => {
              const m = findMarket(g, market);
              const out = primaryOutcome(m, g);
              const best = out?.best_price;
              return (
                <tr
                  key={g.event_id}
                  className="border-t border-border-subtle hover:bg-bg-1/40"
                >
                  <td className="px-3 py-2 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <span className="text-text-1 font-medium">
                        {abbrev(g.away_team)} @ {abbrev(g.home_team)}
                      </span>
                      {g.is_live ? (
                        <span className="inline-flex items-center gap-1.5 text-price-down text-[10px] font-semibold uppercase tracking-wide">
                          <span className="live-dot" aria-hidden />
                          live
                        </span>
                      ) : (
                        <span className="text-text-3 text-[11px] tabular">
                          ·{" "}
                          {new Date(g.commence_time).toLocaleTimeString([], {
                            hour: "numeric",
                            minute: "2-digit",
                          })}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="text-right px-2 py-2 tabular">
                    {best ? (
                      <BestCell
                        price={best.price_american}
                        book={best.bookmaker_key}
                      />
                    ) : (
                      <span className="text-text-3">—</span>
                    )}
                  </td>
                  {books.map(b => {
                    const p = priceAtBook(out, b);
                    if (!p)
                      return (
                        <td
                          key={b}
                          className="text-right px-2 py-2 text-text-3 tabular"
                        >
                          —
                        </td>
                      );
                    const isBest =
                      best &&
                      p.bookmaker_key === best.bookmaker_key &&
                      p.price_american === best.price_american;
                    return (
                      <td
                        key={b}
                        className={clsx(
                          "text-right px-2 py-2 tabular transition-colors",
                          isBest
                            ? "text-price-up font-semibold bg-price-up/[0.06] border-l border-price-up/25"
                            : "text-text-1"
                        )}
                      >
                        <CellFlash value={p.price_american}>
                          {formatAmerican(p.price_american)}
                        </CellFlash>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function abbrev(team: string): string {
  const map: Record<string, string> = {
    "Arizona Diamondbacks": "ARI",
    "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",
    "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",
    "Houston Astros": "HOU",
    "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",
    "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN",
    "New York Mets": "NYM",
    "New York Yankees": "NYY",
    "Oakland Athletics": "OAK",
    "Athletics": "OAK",
    "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD",
    "Seattle Mariners": "SEA",
    "San Francisco Giants": "SF",
    "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
  };
  return (
    map[team] ??
    team
      .split(" ")
      .map(w => w[0])
      .join("")
      .slice(0, 3)
      .toUpperCase()
  );
}
