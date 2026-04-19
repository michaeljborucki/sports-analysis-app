"use client";
import { useEffect, useMemo, useState, Fragment } from "react";
import clsx from "clsx";

import type { Game, Market, MarketOutcome } from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { BOOK_ORDER } from "@/lib/books";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { pickBest, findAllBest } from "@/lib/consensus";
import { bookInfo } from "@/lib/books";
import type { Sport, MarketGroup, DisplayKind } from "@/lib/sports";
import { renderTeam } from "@/lib/sports";
import { MarketTabs } from "./market-tabs";
import { BestCell } from "./best-cell";
import { CellFlash } from "./cell-flash";
import { GameTime } from "./game-time";
import { BookLogo } from "../book-logo";
import { BookFilter } from "../book-filter";
import { MarketExpansionPanel } from "./market-expansion-panel";

function findMarket(game: Game, key: string): Market | undefined {
  return game.markets?.find(m => m.market_key === key);
}

function priceAtBook(outcome: MarketOutcome | undefined, bookKey: string) {
  return outcome?.prices.find(p => p.bookmaker_key === bookKey);
}

/**
 * Pick the two outcomes to show in the main grid row for this game + market
 * group. For h2h/spreads markets: [away team, home team]. For totals: [Over, Under].
 * Picks the most-priced outcome per side when multiple (point, name) tuples exist.
 */
function orderedOutcomes(
  market: Market | undefined,
  game: Game,
  display: DisplayKind
): [MarketOutcome | undefined, MarketOutcome | undefined] {
  if (!market) return [undefined, undefined];
  const best = (candidates: MarketOutcome[]): MarketOutcome | undefined => {
    if (candidates.length === 0) return undefined;
    return candidates.reduce((a, b) =>
      a.prices.length >= b.prices.length ? a : b
    );
  };
  if (display === "total") {
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
  display: DisplayKind,
  sport: Sport
): string {
  if (!outcome) return "—";
  if (display === "moneyline") {
    return outcome.outcome_name === game.home_team
      ? renderTeam(game.home_team, sport)
      : renderTeam(game.away_team, sport);
  }
  if (display === "spread") {
    const team =
      outcome.outcome_name === game.home_team
        ? renderTeam(game.home_team, sport)
        : renderTeam(game.away_team, sport);
    const p = outcome.best_price?.point ?? outcome.prices[0]?.point ?? null;
    if (p == null) return team;
    const sign = p > 0 ? "+" : "";
    return `${team} ${sign}${p}`;
  }
  if (display === "total") {
    const letter = outcome.outcome_name === "Over" ? "O" : "U";
    const p = outcome.best_price?.point ?? outcome.prices[0]?.point ?? null;
    return p == null ? letter : `${letter} ${p}`;
  }
  return outcome.outcome_name;
}

export function OddsGrid({
  games,
  sport,
}: {
  games: Game[];
  sport: Sport;
}) {
  // Which market_groups actually have any data in this dataset
  const availableGroups = useMemo(() => {
    const present = new Set<string>();
    for (const g of games)
      for (const m of g.markets ?? []) present.add(m.market_key);
    return sport.marketGroups.filter(mg => present.has(mg.mainKey));
  }, [games, sport]);

  const fallbackGroup: MarketGroup =
    availableGroups[0] ?? sport.marketGroups[0];
  const [activeKey, setActiveKey] = useState<string>(fallbackGroup.mainKey);

  // If the sport changes (user switches via nav), clamp the selected market
  useEffect(() => {
    if (!sport.marketGroups.some(mg => mg.mainKey === activeKey)) {
      setActiveKey(sport.marketGroups[0].mainKey);
    }
  }, [sport, activeKey]);

  const activeGroup: MarketGroup =
    sport.marketGroups.find(mg => mg.mainKey === activeKey) ??
    sport.marketGroups[0];

  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);
  const { visible, toggle, setAll } = useVisibleBooks();

  // Books present in this dataset, ordered by registry priority.
  const availableBooks = useMemo(() => {
    const present = new Set<string>();
    for (const g of games)
      for (const m of g.markets ?? [])
        for (const o of m.outcomes) for (const p of o.prices) present.add(p.bookmaker_key);
    const ordered = BOOK_ORDER.filter(b => present.has(b));
    const extras = [...present].filter(b => !BOOK_ORDER.includes(b)).sort();
    return [...ordered, ...extras];
  }, [games]);

  const books = useMemo(
    () => availableBooks.filter(b => visible.has(b)),
    [availableBooks, visible]
  );

  const tabs = availableGroups.map(g => ({ key: g.mainKey, label: g.label }));

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-4 justify-between">
        <div className="flex items-center gap-4 flex-wrap">
          {tabs.length > 0 && (
            <MarketTabs
              value={activeKey}
              onChange={setActiveKey}
              tabs={tabs}
            />
          )}
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
                  No {sport.label} odds cached yet. Turn the fetcher on or wait
                  for the first tick.
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
              const m = findMarket(g, activeKey);
              const [topOutcome, bottomOutcome] = orderedOutcomes(
                m,
                g,
                activeGroup.display
              );
              const isExpanded = expandedEventId === g.event_id;
              return (
                <Fragment key={g.event_id}>
                  {[topOutcome, bottomOutcome].map((out, idx) => {
                    const isFirst = idx === 0;
                    const allPrices = out?.prices ?? [];
                    // Best follows the filter; consensus is server-computed.
                    const visiblePrices = allPrices.filter(p =>
                      visible.has(p.bookmaker_key)
                    );
                    const tiedBest = findAllBest(visiblePrices);
                    const tiedKeys = new Set(
                      tiedBest.map(p => p.bookmaker_key)
                    );
                    const best =
                      tiedBest.length > 0
                        ? tiedBest.reduce((a, b) =>
                            bookInfo(a.bookmaker_key).priority <=
                            bookInfo(b.bookmaker_key).priority
                              ? a
                              : b
                          )
                        : pickBest(visiblePrices);
                    const consensus = out?.consensus_price_american ?? null;
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
                            onClick={() =>
                              setExpandedEventId(
                                isExpanded ? null : g.event_id
                              )
                            }
                            className={clsx(
                              "px-3 py-1.5 align-middle whitespace-nowrap",
                              "border-r border-border-subtle/60 cursor-pointer",
                              isExpanded && "bg-bg-1/50"
                            )}
                          >
                            <div className="flex items-center gap-2">
                              <span
                                aria-hidden
                                className={clsx(
                                  "text-text-3 text-[10px] transition-transform",
                                  isExpanded ? "rotate-90" : "rotate-0"
                                )}
                              >
                                ▶
                              </span>
                              <div className="flex flex-col gap-0.5">
                                <span className="text-text-1 font-medium">
                                  {renderTeam(g.away_team, sport)} @{" "}
                                  {renderTeam(g.home_team, sport)}
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
                                    <GameTime commenceTime={g.commence_time} />
                                  )}
                                </span>
                              </div>
                            </div>
                          </td>
                        )}
                        <td
                          className={clsx(
                            "px-2 py-1.5 whitespace-nowrap text-text-1",
                            idx === 1 && "text-text-2"
                          )}
                        >
                          {sideLabel(out, g, activeGroup.display, sport)}
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
                          {consensus != null
                            ? formatAmerican(consensus)
                            : "—"}
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
                          const isBest = tiedKeys.has(p.bookmaker_key);
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
                  {isExpanded && (
                    <tr>
                      <td
                        colSpan={4 + books.length}
                        className="p-0 border-t border-border-subtle"
                      >
                        <MarketExpansionPanel
                          game={g}
                          sport={sport}
                          visible={visible}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
