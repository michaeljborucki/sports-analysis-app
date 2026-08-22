import { Fragment, memo, useMemo } from "react";
import clsx from "clsx";
import { ChevronRight } from "lucide-react";

import type { Game, Market, MarketOutcome } from "@/lib/api";
import { bookInfo } from "@/lib/books";
import { pickBest, findAllBest } from "@/lib/consensus";
import { formatAmerican } from "@/lib/format";
import type { DisplayKind, MarketGroup, Sport } from "@/lib/sports";
import { renderTeam } from "@/lib/sports";
import { matchesLiveFilter } from "../live-status-filter";
import { BookLogo } from "../book-logo";
import { BestCell } from "./best-cell";
import { CellFlash } from "./cell-flash";
import { GameTime } from "./game-time";

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
): (MarketOutcome | undefined)[] {
  // Returns rows in render order. Length is variable:
  //   - total markets: [Over, Under] — 2 rows
  //   - 2-way moneyline / spread: [away, home] — 2 rows
  //   - 3-way moneyline (soccer h2h): [away, draw, home] — 3 rows
  // Game label cell uses rowSpan={returnedArray.length} to span them.
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
  if (display === "yes_no") {
    // NRFI / DRP / props that resolve as Yes/No. Two rows, fixed order.
    return [
      best(market.outcomes.filter(o => o.outcome_name === "Yes")),
      best(market.outcomes.filter(o => o.outcome_name === "No")),
    ];
  }
  // For h2h-shaped markets, detect a Draw outcome and slot it between the
  // away and home rows. Soccer's h2h is the primary case (home/draw/away,
  // 3-way) but this also supports any future 3-way market that uses the
  // "Draw" outcome name convention.
  const drawOutcome = best(
    market.outcomes.filter(o => o.outcome_name === "Draw"),
  );
  const awayOutcome = best(
    market.outcomes.filter(o => o.outcome_name === game.away_team),
  );
  const homeOutcome = best(
    market.outcomes.filter(o => o.outcome_name === game.home_team),
  );
  if (drawOutcome) {
    return [awayOutcome, drawOutcome, homeOutcome];
  }
  return [awayOutcome, homeOutcome];
}

function sideLabel(
  outcome: MarketOutcome | undefined,
  game: Game,
  display: DisplayKind,
  sport: Sport
): string {
  if (!outcome) return "—";
  if (display === "moneyline") {
    if (outcome.outcome_name === "Draw") return "Draw";
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
  if (display === "yes_no") {
    return outcome.outcome_name; // "Yes" or "No"
  }
  return outcome.outcome_name;
}

export interface OddsGamesTableProps {
  games: Game[];
  sport: Sport;
  activeGroup: MarketGroup;
  activeKey: string;
  books: string[];
  visible: Set<string>;
  sheetEventId: string | null;
  onToggleSheet: (eventId: string | null) => void;
}

interface LeagueSectionProps extends OddsGamesTableProps {
  title: string;
}

export function LeagueSection({
  title,
  games,
  ...tableProps
}: LeagueSectionProps) {
  return (
    <section aria-label={title}>
      <details open className="group">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-1 py-1 text-sm text-text-1 [&::-webkit-details-marker]:hidden">
          <ChevronRight
            aria-hidden
            size={14}
            className="text-text-3 transition-transform group-open:rotate-90"
          />
          <span className="font-semibold">{title}</span>
          <span className="text-xs tabular text-text-3">
            {games.length} {games.length === 1 ? "match" : "matches"}
          </span>
        </summary>
        <div className="mt-1">
          <OddsGamesTable games={games} {...tableProps} />
        </div>
      </details>
    </section>
  );
}

export function OddsGamesTable({
  games,
  sport,
  activeGroup,
  activeKey,
  books,
  visible,
  sheetEventId,
  onToggleSheet,
}: OddsGamesTableProps) {
  return (
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
            const outcomes = orderedOutcomes(m, g, activeGroup.display);
            const isOpen = sheetEventId === g.event_id;
            const rowCount = outcomes.length;
            return (
              <Fragment key={g.event_id}>
                {outcomes.map((out, idx) => (
                  <OutcomeRow
                    key={`${g.event_id}-${idx}`}
                    game={g}
                    outcome={out}
                    idx={idx}
                    rowCount={rowCount}
                    isOpen={isOpen}
                    sport={sport}
                    display={activeGroup.display}
                    books={books}
                    visible={visible}
                    onToggleSheet={onToggleSheet}
                  />
                ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One outcome row in the odds grid. Extracted + memoised so the inner work
 * (filtering visible prices, computing tied-best, finding the lead book
 * among ties) runs in a useMemo keyed on stable inputs and re-renders
 * skip when neither this row's outcome nor the book columns/visible set
 * have changed.
 *
 * Caveats:
 *   - SWR returns fresh `outcome` object refs on every poll even when the
 *     underlying data is identical (no compare option configured). So
 *     memo equality fails on every tick — but it still saves work when
 *     OddsGrid re-renders for sheet open/close, market-tab swaps, or live
 *     filter changes that don't touch this game's outcomes.
 *   - `visible` is a `Set` (stable identity from `useVisibleBooks`); not
 *     mutated in place so referential equality holds across renders that
 *     don't change the set.
 */
const OutcomeRow = memo(function OutcomeRow({
  game,
  outcome,
  idx,
  rowCount,
  isOpen,
  sport,
  display,
  books,
  visible,
  onToggleSheet,
}: {
  game: Game;
  outcome: MarketOutcome | undefined;
  idx: number;
  rowCount: number;
  isOpen: boolean;
  sport: Sport;
  display: DisplayKind;
  books: string[];
  visible: Set<string>;
  onToggleSheet: (eventId: string | null) => void;
}) {
  const isFirst = idx === 0;

  // Compute best / tied / consensus once per (outcome, visible) tuple
  // rather than per render. `pickBest` / `findAllBest` are O(prices) each
  // — at ~30 books × 2-3 sides per game this adds up across the grid.
  const { best, tiedKeys, consensus } = useMemo(() => {
    const allPrices = outcome?.prices ?? [];
    const visiblePrices = allPrices.filter(p =>
      visible.has(p.bookmaker_key),
    );
    const tiedBest = findAllBest(visiblePrices);
    const tiedKeysSet = new Set(tiedBest.map(p => p.bookmaker_key));
    // When multiple books tie for best price, prefer the one with the
    // lowest priority value (sharper / more recognised brand) so the
    // Best cell shows a stable logo across renders.
    const bestRow =
      tiedBest.length > 0
        ? tiedBest.reduce((a, b) =>
            bookInfo(a.bookmaker_key).priority <=
            bookInfo(b.bookmaker_key).priority
              ? a
              : b,
          )
        : pickBest(visiblePrices);
    return {
      best: bestRow,
      tiedKeys: tiedKeysSet,
      consensus: outcome?.consensus_price_american ?? null,
    };
  }, [outcome, visible]);

  return (
    <tr
      className={clsx(
        isFirst && "border-t border-border-subtle",
        "hover:bg-bg-1/40",
      )}
    >
      {isFirst && (
        <td
          rowSpan={rowCount}
          onClick={() => onToggleSheet(isOpen ? null : game.event_id)}
          className={clsx(
            "px-3 py-1.5 align-middle whitespace-nowrap",
            "border-r border-border-subtle/60 cursor-pointer",
            isOpen && "bg-bg-1/50",
          )}
        >
          <div className="flex items-center gap-2">
            <ChevronRight
              aria-hidden
              size={10}
              className={clsx(
                "text-text-3 transition-transform",
                isOpen ? "rotate-90" : "rotate-0",
              )}
            />
            <div className="flex flex-col gap-0.5">
              <span className="text-text-1 font-medium">
                {renderTeam(game.away_team, sport)} @{" "}
                {renderTeam(game.home_team, sport)}
              </span>
              <span className="text-text-3 text-[11px] flex items-center gap-1.5">
                {matchesLiveFilter(game.commence_time, "live") ? (
                  <>
                    <span className="live-dot" aria-hidden />
                    <span className="text-price-down font-semibold uppercase tracking-wide">
                      live
                    </span>
                  </>
                ) : (
                  <GameTime commenceTime={game.commence_time} />
                )}
              </span>
            </div>
          </div>
        </td>
      )}
      <td
        className={clsx(
          "px-2 py-1.5 whitespace-nowrap text-text-1",
          !isFirst && "text-text-2",
        )}
      >
        {sideLabel(outcome, game, display, sport)}
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
        const p = priceAtBook(outcome, b);
        return (
          <BookPriceCell
            key={b}
            price={p ? p.price_american : null}
            isBest={p ? tiedKeys.has(p.bookmaker_key) : false}
          />
        );
      })}
    </tr>
  );
});

/**
 * One book × outcome cell. Memoised on primitive props so an SWR tick
 * that returns the same price for this book skips the CellFlash effect
 * comparison and the clsx work. The flash animation itself is keyed by
 * `value` change inside CellFlash, so memoisation does NOT suppress
 * legitimate flashes.
 */
const BookPriceCell = memo(function BookPriceCell({
  price,
  isBest,
}: {
  price: number | null;
  isBest: boolean;
}) {
  if (price == null) {
    return (
      <td className="text-right px-2 py-1.5 text-text-3 tabular">—</td>
    );
  }
  return (
    <td
      className={clsx(
        "text-right px-2 py-1.5 tabular transition-colors",
        isBest
          ? "text-price-up font-semibold bg-price-up/[0.06] border-l border-price-up/25"
          : "text-text-1",
      )}
    >
      <CellFlash value={price}>{formatAmerican(price)}</CellFlash>
    </td>
  );
});
