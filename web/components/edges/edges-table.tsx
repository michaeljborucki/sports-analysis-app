"use client";
import { Fragment } from "react";
import clsx from "clsx";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  ChevronDownIcon,
  ChevronRightIcon,
} from "lucide-react";

import { BookLogo } from "@/components/book-logo";
import { AnimatedPrice } from "@/components/animated-price";
import { formatAmerican } from "@/lib/format";
import {
  MODE_LABEL,
  type EdgeMode,
  type EdgeOpportunity,
  type SortDir,
  type SortKey,
  commenceLabel,
  edgeColor,
  formatEdgePct,
  formatOutcomeLabel,
  marketLabel,
  sideLabel,
} from "@/lib/edges";
import { SPORTS, type SportKey } from "@/lib/sports";
import { useEdgesPrefs } from "@/lib/use-edges-prefs";
import { kellyStake, roundStake } from "@/lib/stake-calc";

import { Workbench } from "./workbench";
import { EdgeSparkline } from "./edge-sparkline";

const MODE_CHIP_STYLE: Record<EdgeMode, string> = {
  arb: "bg-price-up/15 text-price-up",
  low_hold: "bg-accent/15 text-accent",
  ev: "bg-violet-accent/15 text-violet-accent",
  free_bet: "bg-flash/15 text-flash",
  profit_boost: "bg-violet-accent/15 text-violet-accent",
};

// Row paddings follow the global density toggle. Inline-styled so the
// vars resolve against <html data-density>. The edges table has many
// columns stacking leg chips vertically, so we use the density vars
// directly without the 0.66× compression used in the odds matrix.
const CELL_PAD_STYLE: React.CSSProperties = {
  paddingInline: "var(--row-pad-x)",
  paddingBlock: "var(--row-pad-y)",
};
// Expand-caret cell is narrow: keep horizontal padding tight, inherit Y.
const CARET_PAD_STYLE: React.CSSProperties = {
  paddingInline: 4,
  paddingBlock: "var(--row-pad-y)",
};

function sportShortLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label.slice(0, 3).toUpperCase();
  return key.slice(0, 3).toUpperCase();
}

/**
 * Pick the left-bar accent colour for a row hover based on edge magnitude.
 * Positive edges pull from the price-up ramp; LH / tiny edges get a
 * neutral accent shade so the bar reads as "here" not "profitable."
 */
function hoverBarShadow(op: EdgeOpportunity): string {
  // Free bets always positive; arb always positive; EV can be near-zero
  // after rounding. LH uses -hold, near-zero magnitudes → neutral accent.
  const pct = op.edge_pct;
  if (op.mode === "low_hold") {
    return "inset 2px 0 0 var(--accent-60)";
  }
  if (pct >= 2) return "inset 2px 0 0 var(--price-up-75)";
  if (pct >= 0.5) return "inset 2px 0 0 var(--price-up-50)";
  if (pct > 0) return "inset 2px 0 0 var(--price-up-25)";
  // Negative-edge rows shouldn't normally be shown, but if they slip
  // through, mark them red.
  return "inset 2px 0 0 var(--price-down-25)";
}

interface HeaderProps {
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
}

function HeaderCell({
  label,
  colKey,
  widthClass,
  align = "left",
  sortKey,
  sortDir,
  onSort,
}: {
  label: string;
  colKey?: SortKey;
  widthClass?: string;
  align?: "left" | "right";
} & HeaderProps) {
  const active = colKey === sortKey;
  const clickable = colKey != null;
  const ArrowIcon = !active ? null : sortDir === "asc" ? ArrowUpIcon : ArrowDownIcon;
  return (
    <th
      className={clsx(
        "font-medium uppercase tracking-wide text-[11px]",
        align === "right" ? "text-right" : "text-left",
        widthClass,
        clickable && "cursor-pointer select-none hover:text-text-1",
      )}
      style={CELL_PAD_STYLE}
      onClick={clickable ? () => onSort(colKey!) : undefined}
    >
      <span className={clsx("inline-flex items-center gap-1", active && "text-text-1")}>
        {label}
        {ArrowIcon && <ArrowIcon size={10} className="text-text-3" />}
      </span>
    </th>
  );
}

export function EdgesTable({
  rows,
  expanded,
  onToggleExpand,
  stake,
  sortKey,
  sortDir,
  onSort,
}: {
  rows: EdgeOpportunity[];
  expanded: Set<string>;
  onToggleExpand: (key: string) => void;
  stake: number;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (key: SortKey) => void;
}) {
  const hdr: HeaderProps = { sortKey, sortDir, onSort };
  return (
    <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
      <table className="w-full text-xs">
        <thead className="bg-bg-1 text-text-2">
          <tr>
            <th className="w-6" style={CARET_PAD_STYLE} aria-label="Expand" />
            <HeaderCell label="Edge" colKey="edge" widthClass="w-[70px]" {...hdr} />
            <HeaderCell label="Mode" colKey="mode" widthClass="w-[54px]" {...hdr} />
            <th
              className="font-medium uppercase tracking-wide text-[11px] text-right w-[60px]"
              style={CELL_PAD_STYLE}
            >
              Trend
            </th>
            <HeaderCell label="Sport" colKey="sport" widthClass="w-[50px]" {...hdr} />
            <HeaderCell label="Event" colKey="event" {...hdr} />
            <HeaderCell label="Market" colKey="market" widthClass="w-[150px]" {...hdr} />
            <th
              className="font-medium uppercase tracking-wide text-[11px] text-left"
              style={CELL_PAD_STYLE}
            >
              Side / Legs
            </th>
            <th
              className="font-medium uppercase tracking-wide text-[11px] text-right w-[90px]"
              style={CELL_PAD_STYLE}
            >
              Stake
            </th>
            <HeaderCell
              label="Starts"
              colKey="commence"
              widthClass="w-[70px]"
              align="right"
              {...hdr}
            />
            <th
              className="font-medium uppercase tracking-wide text-[11px] text-right w-[96px]"
              style={CELL_PAD_STYLE}
            >
              Flags
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(op => {
            const open = expanded.has(op.row_key);
            // Deterministic seed — same row across renders produces the
            // same sparkline.
            const sparkSeed = `${op.event_id}|${op.market_kind}|${op.point ?? ""}|${op.mode}`;
            return (
              <Fragment key={op.row_key}>
                <tr
                  className={clsx(
                    "group/edgerow border-t border-border-subtle",
                    "motion-safe:transition-colors motion-safe:duration-150",
                    open ? "bg-bg-1" : "hover:bg-bg-1/60",
                    op.stale && "opacity-70",
                  )}
                  style={
                    open
                      ? undefined
                      : ({
                          // Per-row hover-bar colour — the caret cell
                          // below reads this var inside its
                          // `group-hover/edgerow:[box-shadow:var(--row-hover-bar)]`
                          // rule. Each row picks its own ramp shade based
                          // on edge magnitude without needing a class-per-bucket.
                          ["--row-hover-bar" as string]: hoverBarShadow(op),
                        } as React.CSSProperties)
                  }
                >
                  <td
                    className={clsx(
                      "align-top",
                      "motion-safe:transition-shadow motion-safe:duration-150",
                      !open &&
                        "group-hover/edgerow:[box-shadow:var(--row-hover-bar)]",
                    )}
                    style={CARET_PAD_STYLE}
                  >
                    <button
                      type="button"
                      onClick={() => onToggleExpand(op.row_key)}
                      aria-expanded={open}
                      aria-label={open ? "Collapse workbench" : "Expand workbench"}
                      className="w-5 h-5 inline-flex items-center justify-center text-text-3 hover:text-text-1 transition-colors"
                    >
                      {open ? (
                        <ChevronDownIcon size={12} />
                      ) : (
                        <ChevronRightIcon size={12} />
                      )}
                    </button>
                  </td>
                  <td className="align-top" style={CELL_PAD_STYLE}>
                    <AnimatedPrice
                      value={op.edge_pct}
                      className={clsx("tabular font-semibold", edgeColor(op))}
                      invert={op.mode === "low_hold"}
                    >
                      {formatEdgePct(op)}
                    </AnimatedPrice>
                  </td>
                  <td className="align-top" style={CELL_PAD_STYLE}>
                    <span
                      className={clsx(
                        "inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] font-semibold tracking-wider",
                        MODE_CHIP_STYLE[op.mode],
                      )}
                    >
                      {MODE_LABEL[op.mode]}
                    </span>
                  </td>
                  <td className="align-top text-right" style={CELL_PAD_STYLE}>
                    <span
                      className="inline-block"
                      title="Synthetic edge % over the last 15 minutes (placeholder data until the backend time-series lands)."
                    >
                      <EdgeSparkline
                        seedKey={sparkSeed}
                        currentEdge={op.edge_pct}
                      />
                    </span>
                  </td>
                  <td
                    className="text-text-2 text-[11px] uppercase tracking-wide align-top"
                    style={CELL_PAD_STYLE}
                  >
                    {sportShortLabel(op.sport_key)}
                  </td>
                  <td
                    className="text-text-1 whitespace-nowrap align-top"
                    style={CELL_PAD_STYLE}
                  >
                    {op.away_team} @ {op.home_team}
                  </td>
                  <td className="text-text-2 align-top" style={CELL_PAD_STYLE}>
                    {marketLabel(op)}
                  </td>
                  <td className="align-top" style={CELL_PAD_STYLE}>
                    {op.mode === "arb" || op.mode === "low_hold" ? (
                      <div className="flex flex-col gap-0.5">
                        {op.legs.map((leg, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-1.5 text-[11px]"
                          >
                            <BookLogo bookKey={leg.book} mode="label" />
                            <span className="text-text-2 truncate max-w-[120px]">
                              {formatOutcomeLabel(leg.outcome_name, op.market_kind, leg.point)}
                            </span>
                            <span className="text-price-up font-semibold tabular">
                              {formatAmerican(leg.price_american)}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : op.mode === "ev" ? (
                      <div className="flex items-center gap-2 text-[11px]">
                        <BookLogo bookKey={op.raw.book} mode="label" />
                        <span className="text-text-2 truncate max-w-[140px]">
                          {sideLabel(op)}
                        </span>
                        <span className="text-price-up font-semibold tabular">
                          {formatAmerican(op.raw.offered_price_american)}
                        </span>
                        <span
                          className={clsx(
                            "inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider",
                            op.anchor === "pinnacle"
                              ? "text-accent bg-accent/10"
                              : "text-text-3 bg-bg-2",
                          )}
                          title={
                            op.anchor === "pinnacle"
                              ? "Pinnacle no-vig"
                              : `Consensus of ${op.raw.anchor_book_count} books`
                          }
                        >
                          {op.anchor === "pinnacle" ? "PIN" : "CON"}
                        </span>
                        <span className="text-text-1 tabular">
                          {formatAmerican(op.raw.fair_price_american)}
                        </span>
                      </div>
                    ) : op.mode === "profit_boost" ? (
                      // Two-leg conversion: BOOST leg (with original →
                      // boosted price delta) + HEDGE leg.
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-1.5 text-[11px]">
                          <span
                            className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-violet-accent bg-violet-accent/15"
                            title={`Profit boost ${op.raw.boost_pct}% applied to winnings`}
                          >
                            BOOST {op.raw.boost_pct}%
                          </span>
                          <BookLogo bookKey={op.raw.boost_leg.book} mode="label" />
                          <span className="text-text-2 truncate max-w-[120px]">
                            {formatOutcomeLabel(op.raw.boost_leg.outcome_name, op.market_kind, op.raw.boost_leg.point)}
                          </span>
                          <span className="text-text-3 tabular text-[10px]">
                            {formatAmerican(op.raw.boost_leg.original_price_american)} →
                          </span>
                          <span className="text-price-up font-semibold tabular">
                            {formatAmerican(op.raw.boost_leg.boosted_price_american)}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 text-[11px]">
                          <span className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-text-3 bg-bg-2">
                            HEDGE
                          </span>
                          <BookLogo bookKey={op.raw.hedge_leg.book} mode="label" />
                          <span className="text-text-2 truncate max-w-[120px]">
                            {formatOutcomeLabel(op.raw.hedge_leg.outcome_name, op.market_kind, op.raw.hedge_leg.point)}
                          </span>
                          <span className="text-text-1 font-semibold tabular">
                            {formatAmerican(op.raw.hedge_leg.price_american)}
                          </span>
                          <span
                            className="text-text-3 tabular text-[10px] ml-1"
                            title={`Boosted-pair hold ${op.raw.hold_pct >= 0 ? "+" : ""}${op.raw.hold_pct.toFixed(2)}% — negative = locked profit`}
                          >
                            hold {op.raw.hold_pct >= 0 ? "+" : ""}{op.raw.hold_pct.toFixed(2)}%
                          </span>
                        </div>
                      </div>
                    ) : op.mode === "free_bet" ? (
                      // free_bet
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-1.5 text-[11px]">
                          <span className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-flash bg-flash/15">
                            FREE
                          </span>
                          <BookLogo bookKey={op.raw.free_leg.book} mode="label" />
                          <span className="text-text-2 truncate max-w-[120px]">
                            {formatOutcomeLabel(op.raw.free_leg.outcome_name, op.market_kind, op.raw.free_leg.point)}
                          </span>
                          <span className="text-price-up font-semibold tabular">
                            {formatAmerican(op.raw.free_leg.price_american)}
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 text-[11px]">
                          <span className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-text-3 bg-bg-2">
                            HEDGE
                          </span>
                          <BookLogo bookKey={op.raw.hedge_leg.book} mode="label" />
                          <span className="text-text-2 truncate max-w-[120px]">
                            {formatOutcomeLabel(op.raw.hedge_leg.outcome_name, op.market_kind, op.raw.hedge_leg.point)}
                          </span>
                          <span className="text-text-1 font-semibold tabular">
                            {formatAmerican(op.raw.hedge_leg.price_american)}
                          </span>
                        </div>
                      </div>
                    ) : null}
                  </td>
                  <td className="text-right align-top" style={CELL_PAD_STYLE}>
                    <StakeCell op={op} stake={stake} />
                  </td>
                  <td
                    className="text-right text-text-3 tabular text-[11px] align-top"
                    style={CELL_PAD_STYLE}
                  >
                    {commenceLabel(op.commence_time)}
                  </td>
                  <td className="text-right align-top" style={CELL_PAD_STYLE}>
                    <div className="inline-flex gap-1">
                      {op.also_in_arb && op.mode !== "arb" && (
                        <span
                          className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-price-up bg-price-up/20"
                          title="Also present as an arbitrage pair."
                        >
                          ARB
                        </span>
                      )}
                      {op.suspicious && (
                        <span
                          className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-price-down bg-price-down/10"
                          title="EV > 15% — likely stale or mispriced."
                        >
                          SUS
                        </span>
                      )}
                      {op.stale && (
                        <span
                          className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-text-3 bg-bg-2"
                          title={`Row age ${op.row_age_s}s.`}
                        >
                          STALE
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
                {open && (
                  <tr className="border-t border-border-subtle">
                    <td colSpan={11} className="p-0">
                      <Workbench op={op} stake={stake} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Compact per-row stake preview. Uses the same math module as the
 * workbench, sharing bankroll / Kelly fraction / rounding via the
 * useEdgesPrefs store so row stakes update live when the user edits
 * the workbench.
 *
 * - arb / low_hold: page-level stake input is the total outlay across legs.
 * - ev:             Kelly stake = bankroll × kelly_fraction × Kelly_full.
 * - free_bet:       page-level stake input is the free-bet face value;
 *                   shown amount is the cash hedge.
 */
function StakeCell({ op, stake }: { op: EdgeOpportunity; stake: number }) {
  const prefs = useEdgesPrefs();
  if (op.mode === "arb" || op.mode === "low_hold") {
    return (
      <span className="text-text-1 tabular">
        ${stake.toLocaleString()}
      </span>
    );
  }
  if (op.mode === "ev") {
    const k = kellyStake(
      prefs.bankroll,
      op.raw.offered_price_american,
      op.raw.fair_probability,
      prefs.kellyFrac,
      prefs.rounding,
    );
    return (
      <span className="text-text-1 tabular">
        ${k.stake.toLocaleString()}
      </span>
    );
  }
  if (op.mode === "profit_boost") {
    // Profit boost: `stake` is the BOOSTED-LEG stake (cash). Hedge is
    // sized to lock equal profit. Show total stake (boost + hedge).
    const hedge = roundStake(
      (stake / 100) * op.raw.hedge_stake_per_100_boost,
      prefs.rounding,
    );
    return (
      <span className="text-text-1 tabular">
        ${(stake + hedge).toLocaleString()}
      </span>
    );
  }
  if (op.mode !== "free_bet") {
    return <span className="text-text-3 tabular">—</span>;
  }
  // free_bet — hedge per $100 free * (stake/100), snapped to user rounding.
  const hedge = roundStake(
    (stake / 100) * op.raw.hedge_stake_per_100,
    prefs.rounding,
  );
  return (
    <span className="text-text-1 tabular">
      ${hedge.toLocaleString()}
    </span>
  );
}
