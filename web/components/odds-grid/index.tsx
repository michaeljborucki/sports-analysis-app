"use client";
import { useMemo, useState, Fragment } from "react";
import clsx from "clsx";

import type { Game, Market, MarketOutcome } from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { BOOK_ORDER } from "@/lib/books";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { medianAmerican, pickBest } from "@/lib/consensus";
import { MarketTabs, type MarketKey } from "./market-tabs";
import { BestCell } from "./best-cell";
import { CellFlash } from "./cell-flash";
import { BookLogo } from "../book-logo";
import { BookFilter } from "../book-filter";

function findMarket(game: Game, key: MarketKey): Market | undefined {
  return game.markets?.find(m => m.market_key === key);
}

function priceAtBook(outcome: MarketOutcome | undefined, bookKey: string) {
  return outcome?.prices.find(p => p.bookmaker_key === bookKey);
}

/**
 * Two outcomes per game — [top row, bottom row]. Order:
 *   h2h:     away team, home team   (reading order of "AWAY @ HOME")
 *   spreads: away team, home team   (same)
 *   totals:  Over,       Under
 *
 * If a market has multiple (outcome_name, point) tuples (e.g. different books
 * offering different main lines), we pick the most-priced one per side — i.e.
 * the consensus main line.
 */
function orderedOutcomes(
  market: Market | undefined,
  game: Game,
  key: MarketKey
): [MarketOutcome | undefined, MarketOutcome | undefined] {
  if (!market) return [undefined, undefined];
  const best = (candidates: MarketOutcome[]): MarketOutcome | undefined => {
    if (candidates.length === 0) return undefined;
    return candidates.reduce((a, b) =>
      a.prices.length >= b.prices.length ? a : b
    );
  };
  if (key === "totals") {
    return [
      best(market.outcomes.filter(o => o.outcome_name === "Over")),
      best(market.outcomes.filter(o => o.outcome_name === "Under")),
    ];
  }
  return [
    best(market.outcomes.filter(o => o.outcome_name === game.away_team)),
    best(market.outcomes.filter(o => o.outcome_name === game.home_team)),
  ];
}

function sideLabel(
  outcome: MarketOutcome | undefined,
  game: Game,
  key: MarketKey
): string {
  if (!outcome) return "—";
  if (key === "h2h") {
    return outcome.outcome_name === game.home_team
      ? abbrev(game.home_team)
      : abbrev(game.away_team);
  }
  if (key === "spreads") {
    const team =
      outcome.outcome_name === game.home_team
        ? abbrev(game.home_team)
        : abbrev(game.away_team);
    const p = outcome.best_price?.point ?? outcome.prices[0]?.point ?? null;
    if (p == null) return team;
    const sign = p > 0 ? "+" : "";
    return `${team} ${sign}${p}`;
  }
  if (key === "totals") {
    const letter = outcome.outcome_name === "Over" ? "O" : "U";
    const p = outcome.best_price?.point ?? outcome.prices[0]?.point ?? null;
    return p == null ? letter : `${letter} ${p}`;
  }
  return outcome.outcome_name;
}

export function OddsGrid({ games }: { games: Game[] }) {
  const [market, setMarket] = useState<MarketKey>("h2h");
  const { visible, toggle, setAll } = useVisibleBooks();

  // All books present in the current dataset, ordered by registry priority.
  const availableBooks = useMemo(() => {
    const present = new Set<string>();
    for (const g of games)
      for (const m of g.markets ?? [])
        for (const o of m.outcomes) for (const p of o.prices) present.add(p.bookmaker_key);
    const ordered = BOOK_ORDER.filter(b => present.has(b));
    const extras = [...present].filter(b => !BOOK_ORDER.includes(b)).sort();
    return [...ordered, ...extras];
  }, [games]);

  // Only the subset the user has toggled on.
  const books = useMemo(
    () => availableBooks.filter(b => visible.has(b)),
    [availableBooks, visible]
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-4 justify-between">
        <div className="flex items-center gap-4">
          <MarketTabs value={market} onChange={setMarket} />
          <div className="text-xs text-text-3 tabular">{games.length} games</div>
        </div>
        <BookFilter
          availableBooks={availableBooks}
          visible={visible}
          onToggle={toggle}
          onSetAll={setAll}
        />
      </div>

      <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
        <table className="w-full text-xs">
          <thead className="bg-bg-1 text-text-2">
            <tr>
              <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px]">
                Game
              </th>
              <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Side
              </th>
              <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Best
              </th>
              <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                Consensus
              </th>
              {books.map(b => (
                <th key={b} className="text-right px-2 py-2">
                  <div className="flex justify-end">
                    <BookLogo bookKey={b} mode="header" />
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {games.length === 0 && (
              <tr>
                <td
                  colSpan={4 + books.length}
                  className="text-center py-12 text-text-3"
                >
                  No MLB odds cached yet. Waiting for fetcher…
                </td>
              </tr>
            )}
            {games.length > 0 && books.length === 0 && (
              <tr>
                <td colSpan={4} className="text-center py-12 text-text-3">
                  No books selected. Click the Books button above to pick which
                  sportsbooks to show.
                </td>
              </tr>
            )}
            {games.map(g => {
              const m = findMarket(g, market);
              const [topOutcome, bottomOutcome] = orderedOutcomes(m, g, market);
              return (
                <Fragment key={g.event_id}>
                  {[topOutcome, bottomOutcome].map((out, idx) => {
                    const isFirst = idx === 0;
                    const allPrices = out?.prices ?? [];
                    // Best follows the filter — it's the best price among books
                    // you'd actually bet at. Consensus is market-level, always
                    // computed across every available book.
                    const visiblePrices = allPrices.filter(p =>
                      visible.has(p.bookmaker_key)
                    );
                    const best = pickBest(visiblePrices);
                    const consensus = medianAmerican(
                      allPrices.map(p => p.price_american)
                    );
                    return (
                      <tr
                        key={`${g.event_id}-${idx}`}
                        className={clsx(
                          isFirst && "border-t border-border-subtle",
                          "hover:bg-bg-1/40"
                        )}
                      >
                        {isFirst && (
                          <td
                            rowSpan={2}
                            className="px-3 py-1.5 align-middle whitespace-nowrap border-r border-border-subtle/60"
                          >
                            <div className="flex flex-col gap-0.5">
                              <span className="text-text-1 font-medium">
                                {abbrev(g.away_team)} @ {abbrev(g.home_team)}
                              </span>
                              <span className="text-text-3 text-[11px] flex items-center gap-1.5">
                                {g.is_live ? (
                                  <>
                                    <span className="live-dot" aria-hidden />
                                    <span className="text-price-down font-semibold uppercase tracking-wide">
                                      live
                                    </span>
                                  </>
                                ) : (
                                  <span className="tabular">
                                    {new Date(g.commence_time).toLocaleTimeString(
                                      [],
                                      { hour: "numeric", minute: "2-digit" }
                                    )}
                                  </span>
                                )}
                              </span>
                            </div>
                          </td>
                        )}
                        <td
                          className={clsx(
                            "px-2 py-1.5 whitespace-nowrap text-text-1",
                            idx === 1 && "text-text-2"
                          )}
                        >
                          {sideLabel(out, g, market)}
                        </td>
                        <td className="text-right px-2 py-1.5 tabular">
                          {best ? (
                            <BestCell
                              price={best.price_american}
                              book={best.bookmaker_key}
                            />
                          ) : (
                            <span className="text-text-3">—</span>
                          )}
                        </td>
                        <td className="text-right px-2 py-1.5 tabular text-text-2 border-r border-border-subtle/60">
                          {consensus != null ? formatAmerican(consensus) : "—"}
                        </td>
                        {books.map(b => {
                          const p = priceAtBook(out, b);
                          if (!p)
                            return (
                              <td
                                key={b}
                                className="text-right px-2 py-1.5 text-text-3 tabular"
                              >
                                —
                              </td>
                            );
                          const isBest =
                            !!best &&
                            p.bookmaker_key === best.bookmaker_key &&
                            p.price_american === best.price_american;
                          return (
                            <td
                              key={b}
                              className={clsx(
                                "text-right px-2 py-1.5 tabular transition-colors",
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
                </Fragment>
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
