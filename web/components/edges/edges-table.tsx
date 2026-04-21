"use client";
import { Fragment } from "react";
import clsx from "clsx";

import { BookLogo } from "@/components/book-logo";
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
  marketLabel,
  sideLabel,
} from "@/lib/edges";
import { SPORTS, type SportKey } from "@/lib/sports";

import { Workbench } from "./workbench";

const MODE_CHIP_STYLE: Record<EdgeMode, string> = {
  arb: "bg-price-up/15 text-price-up",
  low_hold: "bg-accent/15 text-accent",
  ev: "bg-violet-accent/15 text-violet-accent",
  free_bet: "bg-flash/15 text-flash",
};

function sportShortLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label.slice(0, 3).toUpperCase();
  return key.slice(0, 3).toUpperCase();
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
  const arrow = !active ? "" : sortDir === "asc" ? "↑" : "↓";
  const clickable = colKey != null;
  return (
    <th
      className={clsx(
        "font-medium uppercase tracking-wide text-[11px] px-2 py-2",
        align === "right" ? "text-right" : "text-left",
        widthClass,
        clickable && "cursor-pointer select-none hover:text-text-1",
      )}
      onClick={clickable ? () => onSort(colKey!) : undefined}
    >
      <span className={clsx(active && "text-text-1")}>
        {label}
        {arrow && <span className="ml-1 text-text-3">{arrow}</span>}
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
            <th className="w-6 px-1 py-2" aria-label="Expand" />
            <HeaderCell label="Edge" colKey="edge" widthClass="w-[70px]" {...hdr} />
            <HeaderCell label="Mode" colKey="mode" widthClass="w-[54px]" {...hdr} />
            <HeaderCell label="Sport" colKey="sport" widthClass="w-[50px]" {...hdr} />
            <HeaderCell label="Event" colKey="event" {...hdr} />
            <HeaderCell label="Market" colKey="market" widthClass="w-[150px]" {...hdr} />
            <th className="font-medium uppercase tracking-wide text-[11px] text-left px-2 py-2">
              Side / Legs
            </th>
            <th className="font-medium uppercase tracking-wide text-[11px] text-right px-2 py-2 w-[90px]">
              Stake
            </th>
            <HeaderCell
              label="Starts"
              colKey="commence"
              widthClass="w-[70px]"
              align="right"
              {...hdr}
            />
            <th className="font-medium uppercase tracking-wide text-[11px] text-right px-2 py-2 w-[96px]">
              Flags
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(op => {
            const open = expanded.has(op.row_key);
            return (
              <Fragment key={op.row_key}>
                <tr
                  className={clsx(
                    "border-t border-border-subtle transition-colors",
                    open ? "bg-bg-1" : "hover:bg-bg-1/40",
                    op.stale && "opacity-70",
                  )}
                >
                  <td className="px-1 py-1.5 align-top">
                    <button
                      type="button"
                      onClick={() => onToggleExpand(op.row_key)}
                      aria-expanded={open}
                      aria-label={open ? "Collapse workbench" : "Expand workbench"}
                      className="w-5 h-5 inline-flex items-center justify-center text-text-3 hover:text-text-1 transition-colors"
                    >
                      <svg
                        width="10"
                        height="10"
                        viewBox="0 0 16 16"
                        fill="none"
                        aria-hidden
                        className={clsx(
                          "transition-transform",
                          open && "rotate-90",
                        )}
                      >
                        <path
                          d="M6 4l4 4-4 4"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                  </td>
                  <td className="px-2 py-1.5 align-top">
                    <span className={clsx("tabular font-semibold", edgeColor(op))}>
                      {formatEdgePct(op)}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 align-top">
                    <span
                      className={clsx(
                        "inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] font-semibold tracking-wider",
                        MODE_CHIP_STYLE[op.mode],
                      )}
                    >
                      {MODE_LABEL[op.mode]}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-text-2 text-[11px] uppercase tracking-wide align-top">
                    {sportShortLabel(op.sport_key)}
                  </td>
                  <td className="px-2 py-1.5 text-text-1 whitespace-nowrap align-top">
                    {op.away_team} @ {op.home_team}
                  </td>
                  <td className="px-2 py-1.5 text-text-2 align-top">
                    {marketLabel(op)}
                  </td>
                  <td className="px-2 py-1.5 align-top">
                    {op.mode === "arb" || op.mode === "low_hold" ? (
                      <div className="flex flex-col gap-0.5">
                        {op.legs.map((leg, i) => (
                          <div
                            key={i}
                            className="flex items-center gap-1.5 text-[11px]"
                          >
                            <BookLogo bookKey={leg.book} mode="label" />
                            <span className="text-text-2 truncate max-w-[120px]">
                              {leg.outcome_name}
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
                    ) : (
                      // free_bet
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center gap-1.5 text-[11px]">
                          <span className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-flash bg-flash/15">
                            FREE
                          </span>
                          <BookLogo bookKey={op.raw.free_leg.book} mode="label" />
                          <span className="text-text-2 truncate max-w-[120px]">
                            {op.raw.free_leg.outcome_name}
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
                            {op.raw.hedge_leg.outcome_name}
                          </span>
                          <span className="text-text-1 font-semibold tabular">
                            {formatAmerican(op.raw.hedge_leg.price_american)}
                          </span>
                        </div>
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-right align-top">
                    <StakeCell op={op} stake={stake} />
                  </td>
                  <td className="px-2 py-1.5 text-right text-text-3 tabular text-[11px] align-top">
                    {commenceLabel(op.commence_time)}
                  </td>
                  <td className="px-2 py-1.5 text-right align-top">
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
                    <td colSpan={10} className="p-0">
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
 * workbench (minus the bankroll/Kelly overrides — the row cell always
 * reflects the page-level stake input). Each mode gets a mode-aware
 * single-number summary.
 */
function StakeCell({ op, stake }: { op: EdgeOpportunity; stake: number }) {
  if (op.mode === "arb" || op.mode === "low_hold") {
    // Sum of arb split at page stake, snapped to $1.
    const total = stake;
    return <span className="text-text-1 tabular">${total.toLocaleString()}</span>;
  }
  if (op.mode === "ev") {
    const kellyDollars = (op.raw.kelly_quarter_pct / 100) * stake;
    return (
      <span className="text-text-1 tabular">
        ${kellyDollars.toFixed(0)}
      </span>
    );
  }
  // free_bet — hedge per $100 free * (stake/100)
  const hedge = (stake / 100) * op.raw.hedge_stake_per_100;
  return (
    <span className="text-text-1 tabular">
      ${hedge.toFixed(0)}
    </span>
  );
}
