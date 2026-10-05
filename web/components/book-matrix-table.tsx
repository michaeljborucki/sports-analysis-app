"use client";
import { memo, useMemo, type ReactNode } from "react";
import clsx from "clsx";

import type { MarketOutcome, BookPrice } from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { Chip } from "@/components/ui";
import { BookLogo } from "./book-logo";
import { AnimatedPrice } from "./animated-price";
import { bookHeaderTint } from "./odds-grid/grid-style";


export interface MatrixRow {
  /** Left-column label (e.g. "LeBron James") */
  label: string;
  /** Optional sub-label shown below (e.g. "Points 25.5") */
  sublabel?: string;
  /** Deduplication key (React key, row identity) */
  key: string;
  /** Over side outcome (or the sole outcome for 1-sided markets) */
  over?: MarketOutcome;
  /** Under side outcome */
  under?: MarketOutcome;
  /** Row carries a visual MAIN highlight (used by alt-lines for mainline). */
  isMain?: boolean;
}


export interface SideLabels {
  over: string;   // e.g. "O" (totals) / "A" (spreads, Away)
  under: string;  // e.g. "U" (totals) / "H" (spreads, Home)
}


const DEFAULT_SIDE_LABELS: SideLabels = { over: "O", under: "U" };

// Price cells keep a tighter inline padding than the .dt-td default so 20+
// book columns stay scannable; block padding still follows density.
const PRICE_PAD_STYLE: React.CSSProperties = {
  paddingInline: "calc(var(--row-pad-x) * 0.66)",
  paddingBlock: "var(--row-pad-y)",
};


/**
 * "Best" american odds = highest payout. For American odds, the higher
 * the signed number, the higher the payout ratio (across sign too:
 * positive odds always beat negative odds). So a single linear pass of
 * `Math.max` over the americans matches the prior chained
 * `.map().map().sort().map()` logic without the O(N log N) sort and
 * intermediate object allocation. At N props × M books per row this was
 * a measurable per-row cost.
 */
function bestAmerican(prices: BookPrice[]): number | null {
  if (prices.length === 0) return null;
  let best = prices[0].price_american;
  for (let i = 1; i < prices.length; i++) {
    const v = prices[i].price_american;
    if (v > best) best = v;
  }
  return best;
}


function priceForBook(outcome: MarketOutcome | undefined, book: string): number | null {
  if (!outcome) return null;
  const p = outcome.prices.find(x => x.bookmaker_key === book);
  return p ? p.price_american : null;
}


/**
 * Generic book-by-book matrix. Rows are user-defined (props: player+point;
 * alts: point variant). Columns are the visible-book set. Each cell shows
 * Over / Under prices for the row × book intersection. Best price per row is
 * `edge` text on an `--edge-10` wash. Missing entries render as em-dash.
 *
 * Sticky first column and sticky header row, so horizontal scrolling with
 * 20+ books stays oriented.
 *
 * Row chrome:
 *   - Cells use the density-aware .dt-th / .dt-td classes.
 *   - Hover lifts the row with a subtle bg tint plus a 2px left marker on
 *     the label cell (inset box-shadow, so no layout shift).
 *   - Sharp-book columns get a `--sharp-20` header tint.
 */
export function BookMatrixTable({
  rows,
  books,
  sideMode = "both",
  sideLabels = DEFAULT_SIDE_LABELS,
  rowLabelHeader = "Outcome",
  emptyMessage = "No data in this market yet.",
}: {
  rows: MatrixRow[];
  books: string[];
  /** "both" shows Over and Under stacked. "over"/"under" shows only one. */
  sideMode?: "both" | "over" | "under";
  /** Labels for the O / U marker column (default "O" / "U"; spreads use "A"/"H"). */
  sideLabels?: SideLabels;
  rowLabelHeader?: string;
  /**
   * Accepts a plain string (legacy callers, e.g. alt-lines-matrix) or a
   * ReactNode so callers can drop in a teaching `<EmptyState>`. Strings are
   * rendered in the original dim-centered style for backward compatibility.
   */
  emptyMessage?: string | ReactNode;
}) {
  // best-by-side is computed inside MatrixRowView (memoised) so a single
  // row's `over`/`under` change doesn't invalidate the whole map.
  if (rows.length === 0 || books.length === 0) {
    // Callers may pass either a raw string (legacy) or a ReactNode such as
    // `<EmptyState …>`. Strings get the original dim-centered treatment so
    // existing callers like alt-lines-matrix don't regress visually.
    const content =
      books.length === 0
        ? "No books visible — add some in Settings."
        : emptyMessage;
    if (typeof content === "string") {
      return (
        <div className="py-16 text-center text-[length:var(--fs-13)] text-text-3">
          {content}
        </div>
      );
    }
    return <div className="py-10">{content}</div>;
  }

  return (
    <div className="rounded-lg border border-border-subtle bg-bg-0 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="border-collapse">
          <thead className="dt-head">
            <tr>
              <th className="dt-th sticky left-0 z-20 min-w-[180px] bg-bg-1 border-r border-border-subtle">
                {rowLabelHeader}
              </th>
              {sideMode !== "over" && sideMode !== "under" && (
                <th
                  className="dt-th sticky left-[180px] z-20 w-[32px] bg-bg-1 text-center border-r border-border-subtle"
                  aria-label="Side"
                />
              )}
              {books.map(book => (
                <th
                  key={book}
                  className={clsx("dt-th min-w-[80px] text-center", bookHeaderTint(book))}
                >
                  <BookLogo bookKey={book} mode="label" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <MatrixRowView
                key={row.key}
                row={row}
                books={books}
                sideMode={sideMode}
                sideLabels={sideLabels}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


/**
 * One MatrixRow (Over + Under stack, or single side). Memoised so that
 * an SWR tick which only touches another row's prices doesn't ripple
 * through every row of the matrix. `best` is computed inside via
 * useMemo so the parent doesn't have to hand us a fresh object each
 * render (which would defeat the memo).
 *
 * `sideLabels` defaults to a module-level constant in callers, so its
 * reference is stable across renders. If a caller starts passing an
 * inline `{ over: …, under: … }` literal each render the memo will
 * thrash — lift it to a module constant or useMemo if that happens.
 */
const MatrixRowView = memo(function MatrixRowView({
  row,
  books,
  sideMode,
  sideLabels,
}: {
  row: MatrixRow;
  books: string[];
  sideMode: "both" | "over" | "under";
  sideLabels: SideLabels;
}) {
  // Best per side — only recomputed when the row's outcome refs change.
  // Two scalars come out so the BookCell can take a primitive `isBest`
  // prop and skip re-render when the row's specific price didn't move.
  const { bestOver, bestUnder } = useMemo(
    () => ({
      bestOver: row.over ? bestAmerican(row.over.prices) : null,
      bestUnder: row.under ? bestAmerican(row.under.prices) : null,
    }),
    [row.over, row.under],
  );

  const sides: ("Over" | "Under")[] =
    sideMode === "over" ? ["Over"]
    : sideMode === "under" ? ["Under"]
    : ["Over", "Under"];

  return (
    <>
      {sides.map((side, idx) => {
        const outcome = side === "Over" ? row.over : row.under;
        const sideBest = side === "Over" ? bestOver : bestUnder;
        const isFirst = idx === 0;
        // Sticky cells must be opaque; the main line sits one step raised.
        const labelBgClass = row.isMain ? "bg-bg-2" : "bg-bg-1";
        return (
          <tr
            key={`${row.key}-${side}`}
            className={clsx(
              "group/matrixrow",
              "motion-safe:transition-colors motion-safe:duration-150",
              "hover:bg-[rgb(var(--text-rgb)/0.03)]",
              isFirst && "border-t border-border-subtle",
              row.isMain && "bg-bg-1",
            )}
          >
            {isFirst && (
              <td
                rowSpan={sides.length}
                className={clsx(
                  "dt-td sticky left-0 z-10 border-r border-border-subtle whitespace-nowrap",
                  "motion-safe:transition-shadow motion-safe:duration-150",
                  "group-hover/matrixrow:[box-shadow:inset_2px_0_0_var(--color-text-3)]",
                  labelBgClass,
                )}
              >
                <div className="flex items-center gap-2">
                  {row.isMain && (
                    <Chip title="Main line (posted by books as the mainline)">Main</Chip>
                  )}
                  <div>
                    <div className={clsx("text-text-1", row.isMain && "font-medium")}>
                      {row.label}
                    </div>
                    {row.sublabel && (
                      <div className="text-[length:var(--fs-11)] leading-[var(--lh-11)] text-text-3">
                        {row.sublabel}
                      </div>
                    )}
                  </div>
                </div>
              </td>
            )}
            {sideMode === "both" && (
              <td
                className={clsx(
                  "dt-td sticky left-[180px] z-10 text-center text-[length:var(--fs-11)] text-text-3 border-r border-border-subtle",
                  labelBgClass,
                )}
              >
                {side === "Over" ? sideLabels.over : sideLabels.under}
              </td>
            )}
            {books.map(book => {
              const price = priceForBook(outcome, book);
              return (
                <MatrixCell
                  key={book}
                  price={price}
                  isBest={price != null && price === sideBest}
                />
              );
            })}
          </tr>
        );
      })}
    </>
  );
});

/**
 * One price cell — memoised on primitive (price, isBest) so unchanged
 * cells skip re-render when SWR returns a fresh row payload that only
 * touched a sibling cell. AnimatedPrice's flash animation is keyed on
 * `value` change inside its own useEffect, so the flash still fires
 * the first time a price actually moves.
 */
const MatrixCell = memo(function MatrixCell({
  price,
  isBest,
}: {
  price: number | null;
  isBest: boolean;
}) {
  return (
    <td
      className={clsx(
        "dt-td tabular text-center",
        isBest ? "bg-[var(--edge-10)] font-semibold text-edge" : "text-text-1",
      )}
      style={PRICE_PAD_STYLE}
    >
      {price != null ? (
        <AnimatedPrice value={price}>{formatAmerican(price)}</AnimatedPrice>
      ) : (
        <span className="text-text-3">—</span>
      )}
    </td>
  );
});
