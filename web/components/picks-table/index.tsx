"use client";
import { useState, Fragment } from "react";
import clsx from "clsx";

import type { Pick } from "@/lib/api";
import { formatAmerican, formatPct, formatUnits } from "@/lib/format";
import { TierBadge } from "./tier-badge";
import { ExpandedRow } from "./expanded-row";

export function PicksTable({ picks }: { picks: Pick[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (picks.length === 0) {
    return (
      <div className="text-center text-text-3 py-16 text-sm">
        The agent hasn&apos;t produced picks for today yet.
      </div>
    );
  }

  return (
    <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
      <table className="w-full text-xs">
        <thead className="bg-bg-1 text-text-2">
          <tr>
            <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px]">
              Tier
            </th>
            <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
              Game
            </th>
            <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
              Pick
            </th>
            <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
              Odds
            </th>
            <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
              Prob
            </th>
            <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
              Edge
            </th>
            <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
              Stake
            </th>
            <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px]">
              Agent · 30d
            </th>
          </tr>
        </thead>
        <tbody>
          {picks.map(p => {
            const open = expandedId === p.id;
            return (
              <Fragment key={p.id}>
                <tr
                  onClick={() => setExpandedId(open ? null : p.id)}
                  className={clsx(
                    "border-t border-border-subtle cursor-pointer transition-colors",
                    open ? "bg-bg-1" : "hover:bg-bg-1/40"
                  )}
                >
                  <td className="px-3 py-2">
                    <TierBadge tier={p.tier} />
                  </td>
                  <td className="px-2 py-2 text-text-1">{p.game_label}</td>
                  <td className="px-2 py-2 text-text-1">{p.market_label}</td>
                  <td className="px-2 py-2 text-right tabular">
                    {formatAmerican(p.odds_american)}
                  </td>
                  <td className="px-2 py-2 text-right tabular font-semibold">
                    {formatPct(p.probability_pct)}
                  </td>
                  <td className="px-2 py-2 text-right tabular font-semibold text-price-up">
                    {formatPct(p.edge_pct, true)}
                  </td>
                  <td className="px-2 py-2 text-right tabular text-accent font-semibold">
                    {formatUnits(p.stake_units)}
                  </td>
                  <td className="px-3 py-2 text-text-2">
                    <span className="text-text-1">{p.agent_key}</span>
                    {p.agent_record_30d && (
                      <span className="text-text-3"> · {p.agent_record_30d}</span>
                    )}
                  </td>
                </tr>
                {open && (
                  <tr className="bg-bg-1/30">
                    <td colSpan={8} className="px-3 py-0">
                      <ExpandedRow pick={p} />
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
