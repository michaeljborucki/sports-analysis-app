"use client";
import clsx from "clsx";
import type { ArbOpportunity } from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { BookLogo } from "./book-logo";
import { SPORTS, type SportKey } from "@/lib/sports";

function marketLabel(op: ArbOpportunity): string {
  if (op.market_kind === "h2h") return "Moneyline";
  if (op.market_kind === "totals") {
    return op.point != null ? `Total ${op.point}` : "Total";
  }
  if (op.market_kind === "spreads") {
    return op.point != null ? `Spread ±${op.point}` : "Spread";
  }
  return op.market_kind;
}

function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}

function commenceLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffH = (d.getTime() - now.getTime()) / 3_600_000;
  if (diffH < 0) return "LIVE";
  if (diffH < 1) return `${Math.round(diffH * 60)}m`;
  if (diffH < 24) return `${Math.round(diffH)}h`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function roiColor(pct: number): string {
  if (pct >= 2) return "text-price-up";
  if (pct >= 1) return "text-accent";
  if (pct >= 0.5) return "text-flash";
  return "text-text-2";
}

export function ArbitrageTable({ opportunities }: { opportunities: ArbOpportunity[] }) {
  if (opportunities.length === 0) {
    return (
      <div className="text-center text-text-3 py-16 text-sm">
        No arbitrage opportunities across your selected books. Widen the book
        filter (Books menu) — sharp books like Pinnacle, Novig, and Betfair
        exchanges drive most arbs.
      </div>
    );
  }
  return (
    <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
      <table className="w-full text-xs">
        <thead className="bg-bg-1 text-text-2">
          <tr>
            <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px] w-[70px]">
              ROI
            </th>
            <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[60px]">
              Sport
            </th>
            <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
              Event
            </th>
            <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
              Market
            </th>
            <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
              Side A
            </th>
            <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
              Side B
            </th>
            <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[60px]">
              Starts
            </th>
          </tr>
        </thead>
        <tbody>
          {opportunities.map((op, i) => {
            const a = op.sides[0];
            const b = op.sides[1];
            return (
              <tr
                key={`${op.event_id}-${op.market_kind}-${op.point ?? "na"}-${i}`}
                className="border-t border-border-subtle hover:bg-bg-1/40"
              >
                <td className="px-3 py-2">
                  <span
                    className={clsx(
                      "tabular font-semibold",
                      roiColor(op.roi_pct)
                    )}
                  >
                    +{op.roi_pct.toFixed(2)}%
                  </span>
                </td>
                <td className="px-2 py-2 text-text-2 text-[11px] uppercase tracking-wide">
                  {sportLabel(op.sport_key)}
                </td>
                <td className="px-2 py-2 text-text-1 whitespace-nowrap">
                  {op.away_team} @ {op.home_team}
                </td>
                <td className="px-2 py-2 text-text-2">{marketLabel(op)}</td>
                <td className="px-2 py-2">
                  <div className="flex items-center gap-2">
                    <BookLogo bookKey={a.book} mode="label" />
                    <span className="text-text-2 text-[11px] tabular">
                      {a.outcome_name}
                    </span>
                    <span className="text-price-up font-semibold tabular">
                      {formatAmerican(a.price_american)}
                    </span>
                    <span className="text-text-3 text-[10px] tabular">
                      stake {a.stake_pct.toFixed(1)}%
                    </span>
                  </div>
                </td>
                <td className="px-2 py-2">
                  <div className="flex items-center gap-2">
                    <BookLogo bookKey={b.book} mode="label" />
                    <span className="text-text-2 text-[11px] tabular">
                      {b.outcome_name}
                    </span>
                    <span className="text-price-up font-semibold tabular">
                      {formatAmerican(b.price_american)}
                    </span>
                    <span className="text-text-3 text-[10px] tabular">
                      stake {b.stake_pct.toFixed(1)}%
                    </span>
                  </div>
                </td>
                <td className="px-2 py-2 text-right text-text-3 tabular text-[11px]">
                  {commenceLabel(op.commence_time)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
