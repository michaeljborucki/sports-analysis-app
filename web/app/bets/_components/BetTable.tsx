"use client";

import clsx from "clsx";

import { Chip, type ChipTone } from "@/components/ui";
import { bookName, sportName } from "./labels";

export interface Bet {
  source_book: string;
  external_id: string;
  accepted_at: string;
  settled_at: string | null;
  status: string;
  wager_type: string;
  total_picks: number;
  sport_key: string | null;
  market_key: string | null;
  outcome_name: string | null;
  odds_american: number | null;
  stake: number;
  to_win: number | null;
  settled_amount: number | null;
  is_free_play: boolean;
  raw_description: string | null;
  clv_pct: number | null;
}

const fmtDate = (s: string) => s.slice(5, 10);
const fmtOdds = (n: number | null) =>
  n == null ? "—" : n > 0 ? `+${n}` : `${n}`;
const fmtUsd = (n: number | null | undefined) =>
  n == null
    ? "—"
    : n.toLocaleString("en-US", { style: "currency", currency: "USD" });

const STATUS: Record<string, { label: string; tone: ChipTone }> = {
  open: { label: "Open", tone: "neutral" },
  pending: { label: "Pending", tone: "neutral" },
  win: { label: "Win", tone: "gain" },
  loss: { label: "Loss", tone: "loss" },
  push: { label: "Push", tone: "neutral" },
  void: { label: "Void", tone: "neutral" },
};

export function BetTable({
  bets,
  filtered = false,
}: {
  bets: Bet[] | undefined;
  filtered?: boolean;
}) {
  if (!bets) {
    return (
      <div className="h-48 rounded-lg border border-border-subtle bg-bg-1 animate-pulse" />
    );
  }
  if (bets.length === 0) {
    return (
      <div className="rounded-lg border border-border-subtle bg-bg-1 px-6 py-8 text-center text-[length:var(--fs-13)] text-text-3">
        {filtered
          ? "No bets match these filters."
          : "No bets yet. Place some on Coral33, configure Kalshi or Polymarket sync in Settings, or import a CSV."}
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-border-subtle bg-bg-1 overflow-x-auto">
      <table className="w-full">
        <thead className="dt-head">
          <tr>
            <th className="dt-th">Date</th>
            <th className="dt-th">Book</th>
            <th className="dt-th">Sport</th>
            <th className="dt-th">Pick</th>
            <th className="dt-th text-right">Odds</th>
            <th className="dt-th text-right">Stake</th>
            <th className="dt-th text-right">Result</th>
            <th className="dt-th text-right" title="Closing-line value: how your price compared to the closing line">
              CLV
            </th>
          </tr>
        </thead>
        <tbody className="bg-bg-0">
          {bets.map((b) => {
            const net =
              b.status === "win"
                ? (b.settled_amount ?? 0) - b.stake
                : b.status === "loss"
                  ? -b.stake
                  : 0;
            const status = STATUS[b.status] ?? { label: b.status, tone: "neutral" as const };
            const pick = b.outcome_name ?? b.raw_description ?? "—";
            const settled = b.status !== "open" && b.status !== "pending";
            return (
              <tr key={`${b.source_book}-${b.external_id}`} className="dt-row">
                <td className="dt-td tabular text-text-2 whitespace-nowrap">
                  {fmtDate(b.accepted_at)}
                </td>
                <td className="dt-td text-text-1 whitespace-nowrap">{bookName(b.source_book)}</td>
                <td className="dt-td text-text-2 whitespace-nowrap">{sportName(b.sport_key)}</td>
                <td className="dt-td text-text-1 max-w-[320px]">
                  <span className="flex items-center gap-1.5 min-w-0">
                    <span className="truncate" title={pick}>{pick}</span>
                    {b.total_picks > 1 && (
                      <Chip title={`${b.total_picks}-leg ${b.wager_type}`}>
                        <span className="tabular">{b.total_picks}</span> legs
                      </Chip>
                    )}
                    {b.is_free_play && <Chip>Free play</Chip>}
                  </span>
                </td>
                <td className="dt-td text-right tabular text-text-1">
                  {fmtOdds(b.odds_american)}
                </td>
                <td className="dt-td text-right tabular text-text-2">
                  {fmtUsd(b.stake)}
                </td>
                <td className="dt-td text-right whitespace-nowrap">
                  <span className="inline-flex items-center justify-end gap-2">
                    {settled && (
                      <span
                        className={clsx(
                          "tabular",
                          net > 0 && "text-gain",
                          net < 0 && "text-loss",
                          net === 0 && "text-text-3",
                        )}
                      >
                        {net > 0 ? "+" : net < 0 ? "-" : ""}
                        {fmtUsd(Math.abs(net))}
                      </span>
                    )}
                    <Chip tone={status.tone}>{status.label}</Chip>
                  </span>
                </td>
                <td
                  className={clsx(
                    "dt-td text-right tabular",
                    b.clv_pct == null && "text-text-3",
                    b.clv_pct != null && b.clv_pct > 0 && "text-gain",
                    b.clv_pct != null && b.clv_pct < 0 && "text-loss",
                    b.clv_pct === 0 && "text-text-2",
                  )}
                >
                  {b.clv_pct == null
                    ? "—"
                    : `${b.clv_pct > 0 ? "+" : ""}${b.clv_pct.toFixed(2)}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
