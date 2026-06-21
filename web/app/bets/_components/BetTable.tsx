"use client";

import clsx from "clsx";

interface Bet {
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

const STATUS_TONE: Record<string, string> = {
  open: "text-text-2 bg-bg-2",
  win: "text-price-up bg-price-up/15",
  loss: "text-price-down bg-price-down/15",
  push: "text-text-2 bg-bg-2",
  void: "text-text-3 bg-bg-2",
  pending: "text-text-2 bg-bg-2",
};

export function BetTable({ bets }: { bets: Bet[] | undefined }) {
  if (!bets) {
    return <div className="h-48 rounded bg-bg-1 animate-pulse" />;
  }
  if (bets.length === 0) {
    return (
      <div className="rounded border border-border-subtle bg-bg-1 p-6 text-center text-text-3">
        No bets yet. Place some on Coral33, configure Kalshi/Polymarket sync in
        Settings, or import a CSV.
      </div>
    );
  }
  return (
    <div className="rounded border border-border-subtle overflow-auto">
      <table className="w-full text-xs">
        <thead className="bg-bg-1 text-text-3">
          <tr>
            <th className="text-left px-2 py-1.5">Date</th>
            <th className="text-left px-2 py-1.5">Book</th>
            <th className="text-left px-2 py-1.5">Sport</th>
            <th className="text-left px-2 py-1.5">Pick</th>
            <th className="text-right px-2 py-1.5">Odds</th>
            <th className="text-right px-2 py-1.5">Stake</th>
            <th className="text-right px-2 py-1.5">Result</th>
            <th className="text-right px-2 py-1.5">CLV</th>
          </tr>
        </thead>
        <tbody>
          {bets.map((b) => {
            const net =
              b.status === "win"
                ? (b.settled_amount ?? 0) - b.stake
                : b.status === "loss"
                  ? -b.stake
                  : 0;
            const tone = STATUS_TONE[b.status] ?? "text-text-3 bg-bg-2";
            return (
              <tr
                key={`${b.source_book}-${b.external_id}`}
                className="border-t border-border-subtle hover:bg-bg-1"
              >
                <td className="px-2 py-1">{fmtDate(b.accepted_at)}</td>
                <td className="px-2 py-1">{b.source_book}</td>
                <td className="px-2 py-1">{b.sport_key ?? "—"}</td>
                <td className="px-2 py-1 truncate max-w-[260px]">
                  {b.outcome_name ?? b.raw_description ?? "—"}
                </td>
                <td className="px-2 py-1 text-right tabular">
                  {fmtOdds(b.odds_american)}
                </td>
                <td className="px-2 py-1 text-right tabular">
                  {fmtUsd(b.stake)}
                </td>
                <td className="px-2 py-1 text-right whitespace-nowrap">
                  <span
                    className={clsx(
                      "inline-flex items-center px-1.5 rounded-sm text-[10px] font-semibold tracking-wider",
                      tone,
                    )}
                  >
                    {b.status.toUpperCase()}
                  </span>
                  {b.status !== "open" && b.status !== "pending" && (
                    <span
                      className={clsx(
                        "tabular ml-1.5",
                        net > 0 && "text-price-up",
                        net < 0 && "text-price-down",
                        net === 0 && "text-text-3",
                      )}
                    >
                      {net > 0 ? "+" : ""}
                      {fmtUsd(Math.abs(net))}
                    </span>
                  )}
                </td>
                <td className="px-2 py-1 text-right tabular">
                  {b.clv_pct == null ? "—" : `${b.clv_pct.toFixed(2)}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
