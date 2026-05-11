"use client";
import { useMemo, type ReactNode } from "react";
import clsx from "clsx";

import type { MarketOutcome, BookPrice } from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { BookLogo } from "./book-logo";
import { AnimatedPrice } from "./animated-price";


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

// Shared inline styles for cells that should respect the global density
// mode. Wave 1 owns the vars themselves; we consume them here so rows
// shrink/grow in lockstep with the Settings density toggle.
const CELL_PAD_STYLE: React.CSSProperties = {
  paddingInline: "var(--row-pad-x)",
  paddingBlock: "var(--row-pad-y)",
};
// Header cells get the same paddings so column widths don't jump when the
// user switches density mode.
const HEADER_PAD_STYLE: React.CSSProperties = {
  paddingInline: "var(--row-pad-x)",
  paddingBlock: "var(--row-pad-y)",
};
// Price cells still need their per-book min-width control, which we keep
// as a class on the <td>. Only the paddings migrate to vars.
const PRICE_PAD_STYLE: React.CSSProperties = {
  paddingInline: "calc(var(--row-pad-x) * 0.66)",
  paddingBlock: "var(--row-pad-y)",
};


function bestAmerican(prices: BookPrice[]): number | null {
  if (prices.length === 0) return null;
  return Math.max(
    ...prices.map(p =>
      p.price_american > 0
        ? p.price_american / 100.0
        : 100.0 / -p.price_american
    ).map((r, i) => ({ r, v: prices[i].price_american }))
     .sort((a, b) => b.r - a.r)
     .map(x => x.v)
  );
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
 * tinted `text-price-up`. Missing entries render as em-dash.
 *
 * Sticky first column and sticky header row, so horizontal scrolling with
 * 20+ books stays oriented.
 *
 * Row chrome (Wave 2):
 *   - Row paddings flex with `html[data-density]` via the --row-pad-* vars.
 *   - Hover lifts the row with a subtle bg tint plus a 2px left accent
 *     indicator. The indicator is rendered via `box-shadow: inset 2px 0 0`
 *     so it doesn't shift the row layout.
 *   - `prefers-reduced-motion` strips the transition timing.
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
  // Precompute best-price-per-row-per-side for tinting. Cheap: N × 2.
  const bestBySide = useMemo(() => {
    const out: Record<string, { over: number | null; under: number | null }> = {};
    for (const r of rows) {
      out[r.key] = {
        over: r.over ? bestAmerican(r.over.prices) : null,
        under: r.under ? bestAmerican(r.under.prices) : null,
      };
    }
    return out;
  }, [rows]);

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
        <div className="text-center text-text-3 py-16 text-sm">
          {content}
        </div>
      );
    }
    return <div className="py-10">{content}</div>;
  }

  return (
    <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
      <div className="overflow-x-auto">
        <table className="text-xs border-collapse">
          <thead className="bg-bg-1 text-text-2">
            <tr>
              <th
                className="sticky left-0 z-20 bg-bg-1 text-left font-medium uppercase tracking-wide text-[11px] min-w-[180px] border-r border-border-subtle"
                style={HEADER_PAD_STYLE}
              >
                {rowLabelHeader}
              </th>
              {sideMode !== "over" && sideMode !== "under" && (
                <th
                  className="sticky left-[180px] z-20 bg-bg-1 text-center font-medium uppercase tracking-wide text-[11px] w-[32px] border-r border-border-subtle"
                  style={HEADER_PAD_STYLE}
                >
                  {/* Side column header (O/U) */}
                </th>
              )}
              {books.map(book => (
                <th
                  key={book}
                  className="font-medium uppercase tracking-wide text-[11px] min-w-[80px]"
                  style={HEADER_PAD_STYLE}
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
                best={bestBySide[row.key]}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}


function MatrixRowView({
  row,
  books,
  sideMode,
  sideLabels,
  best,
}: {
  row: MatrixRow;
  books: string[];
  sideMode: "both" | "over" | "under";
  sideLabels: SideLabels;
  best: { over: number | null; under: number | null };
}) {
  const sides: ("Over" | "Under")[] =
    sideMode === "over" ? ["Over"]
    : sideMode === "under" ? ["Under"]
    : ["Over", "Under"];

  return (
    <>
      {sides.map((side, idx) => {
        const outcome = side === "Over" ? row.over : row.under;
        const sideBest = side === "Over" ? best.over : best.under;
        const isFirst = idx === 0;
        const labelBgClass = row.isMain ? "bg-accent/5" : "bg-bg-0";
        const rowBgClass = row.isMain ? "bg-accent/5" : "";
        return (
          <tr
            key={`${row.key}-${side}`}
            className={clsx(
              "group/matrixrow border-t border-border-subtle",
              "motion-safe:transition-colors motion-safe:duration-150",
              "hover:bg-bg-1/60",
              isFirst ? "border-t-2 border-border-subtle" : "",
              rowBgClass,
            )}
          >
            {isFirst && (
              <td
                rowSpan={sides.length}
                className={clsx(
                  "sticky left-0 z-10 align-middle border-r border-border-subtle whitespace-nowrap",
                  "motion-safe:transition-shadow motion-safe:duration-150",
                  "group-hover/matrixrow:[box-shadow:inset_2px_0_0_var(--accent-60)]",
                  labelBgClass,
                )}
                style={CELL_PAD_STYLE}
              >
                <div className="flex items-center gap-1.5">
                  {row.isMain && (
                    <span
                      className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider bg-accent/15 text-accent"
                      title="Main line (posted by books as the mainline)"
                    >
                      MAIN
                    </span>
                  )}
                  <div>
                    <div className={clsx(
                      "text-xs",
                      row.isMain ? "text-text-1 font-medium" : "text-text-1"
                    )}>
                      {row.label}
                    </div>
                    {row.sublabel && (
                      <div className="text-text-3 text-[10px] tabular">
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
                  "sticky left-[180px] z-10 text-center text-[10px] uppercase tracking-wider text-text-3 border-r border-border-subtle",
                  labelBgClass,
                )}
                style={CELL_PAD_STYLE}
              >
                {side === "Over" ? sideLabels.over : sideLabels.under}
              </td>
            )}
            {books.map(book => {
              const price = priceForBook(outcome, book);
              const isBest = price != null && price === sideBest;
              return (
                <td
                  key={book}
                  className={clsx(
                    "text-center tabular",
                    isBest ? "text-price-up font-semibold" : "text-text-2",
                  )}
                  style={PRICE_PAD_STYLE}
                >
                  {price != null ? (
                    <AnimatedPrice value={price}>
                      {formatAmerican(price)}
                    </AnimatedPrice>
                  ) : (
                    <span className="text-text-3">—</span>
                  )}
                </td>
              );
            })}
          </tr>
        );
      })}
    </>
  );
}
