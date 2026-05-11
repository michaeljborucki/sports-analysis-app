"use client";
import { Target } from "lucide-react";
import clsx from "clsx";

import type { Pick } from "@/lib/api";
import { formatAmerican, formatPct, formatUnits } from "@/lib/format";
import { SPORTS, type SportKey } from "@/lib/sports";
import { EmptyState } from "@/components/empty-state";

/**
 * Compact cross-sport top-picks table for the dashboard.
 *
 * Shows up to 8 rows. Keeps the table shape of the prior TopPicksCard but
 * compresses padding (11px body) and drops the header styling to a thinner
 * uppercase meta strip. Hooks into the global density vars so the density
 * toggle affects dashboard rows too.
 */
export function TopPicksCard({
  picks,
  onRefresh,
}: {
  picks: Pick[];
  onRefresh: () => void;
}) {
  const visible = picks.slice(0, 8);
  return (
    <div className="rounded-md border border-border-subtle bg-bg-1 overflow-hidden flex flex-col">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-subtle">
        <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wider text-text-2">
          <Target size={13} className="text-text-3" aria-hidden />
          Top picks by edge
        </div>
        <span className="text-[11px] text-text-3">cross-sport</span>
      </div>
      {visible.length === 0 ? (
        <div className="p-4">
          <EmptyState
            icon={<Target size={28} />}
            title="No picks from any agent today"
            body="Agents publish picks once their daily cards close. If today's slate has already started, try tomorrow's card."
            action={{
              label: "Refresh",
              onClick: onRefresh,
              variant: "ghost",
            }}
          />
        </div>
      ) : (
        <table className="w-full text-[11px]">
          <thead className="text-text-3">
            <tr className="border-b border-border-subtle">
              <Th className="w-[50px] pl-4">Sport</Th>
              <Th>Game</Th>
              <Th>Pick</Th>
              <Th align="right" className="w-[55px]">Odds</Th>
              <Th align="right" className="w-[60px]">Edge</Th>
              <Th align="right" className="w-[55px] pr-4">Stake</Th>
            </tr>
          </thead>
          <tbody>
            {visible.map(p => (
              <tr
                key={p.id}
                className="border-b border-border-subtle/60 last:border-b-0 hover:bg-bg-2/50 transition-colors"
              >
                <Td className="pl-4">
                  <span className="inline-flex items-center px-1.5 h-5 rounded-sm bg-bg-2 text-[10px] tracking-wider uppercase text-text-2">
                    {sportLabel(p.sport_key ?? "mlb")}
                  </span>
                </Td>
                <Td className="text-text-1 truncate max-w-[220px]">
                  {p.game_label}
                </Td>
                <Td className="text-text-2 truncate max-w-[180px]">
                  {p.market_label}
                </Td>
                <Td align="right" className="tabular text-text-1">
                  {formatAmerican(p.odds_american)}
                </Td>
                <Td align="right" className="tabular font-semibold text-price-up">
                  {formatPct(p.edge_pct, true)}
                </Td>
                <Td align="right" className="tabular font-semibold text-accent pr-4">
                  {formatUnits(p.stake_units)}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Th({
  children,
  align = "left",
  className,
}: {
  children: React.ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <th
      className={clsx(
        "font-medium uppercase tracking-wider text-[10px]",
        align === "right" ? "text-right" : "text-left",
        className,
      )}
      style={{
        paddingTop: 6,
        paddingBottom: 6,
        paddingLeft: align === "left" ? "var(--row-pad-x)" : undefined,
        paddingRight: align === "right" ? "var(--row-pad-x)" : undefined,
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = "left",
  className,
}: {
  children: React.ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  return (
    <td
      className={clsx(align === "right" ? "text-right" : "text-left", className)}
      style={{
        paddingTop: "var(--row-pad-y)",
        paddingBottom: "var(--row-pad-y)",
        paddingLeft: align === "left" ? "var(--row-pad-x)" : undefined,
        paddingRight: align === "right" ? "var(--row-pad-x)" : undefined,
      }}
    >
      {children}
    </td>
  );
}

function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}
