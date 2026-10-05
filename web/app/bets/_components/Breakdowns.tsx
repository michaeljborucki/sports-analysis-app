"use client";

import clsx from "clsx";

import { Panel } from "@/components/ui";
import { bookName, marketName, sportName } from "./labels";

interface Group {
  source_book?: string;
  sport_key?: string;
  market_key?: string;
  count: number;
  wagered: number;
  net: number;
  roi_pct: number;
}

export interface Rollups {
  by_book: Group[];
  by_sport: Group[];
  by_market: Group[];
}

type KeyCol = "source_book" | "sport_key" | "market_key";

const fmtPct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const fmtUsd = (v: number) =>
  `${v > 0 ? "+" : v < 0 ? "-" : ""}${Math.abs(v).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  })}`;

const NAMERS: Record<KeyCol, (k: string | null | undefined) => string> = {
  source_book: bookName,
  sport_key: sportName,
  market_key: marketName,
};

const tone = (v: number) =>
  clsx(v > 0 && "text-gain", v < 0 && "text-loss", v === 0 && "text-text-2");

function Table({
  title,
  groupLabel,
  rows,
  keyCol,
}: {
  title: string;
  groupLabel: string;
  rows: Group[];
  keyCol: KeyCol;
}) {
  const name = NAMERS[keyCol];
  return (
    <Panel title={title} bodyClassName="overflow-x-auto">
      <table className="w-full">
        <thead className="dt-head">
          <tr>
            <th className="dt-th">{groupLabel}</th>
            <th className="dt-th text-right">Bets</th>
            <th className="dt-th text-right">Net</th>
            <th className="dt-th text-right">ROI</th>
          </tr>
        </thead>
        <tbody className="bg-bg-0">
          {rows.length === 0 ? (
            <tr>
              <td colSpan={4} className="dt-td text-text-3">
                No settled bets yet
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr key={r[keyCol] ?? "—"} className="dt-row last:border-b-0">
                <td className="dt-td text-text-1 truncate max-w-[160px]" title={r[keyCol] ?? undefined}>
                  {name(r[keyCol])}
                </td>
                <td className="dt-td text-right tabular text-text-2">{r.count}</td>
                <td className={clsx("dt-td text-right tabular", tone(r.net))}>{fmtUsd(r.net)}</td>
                <td className={clsx("dt-td text-right tabular font-medium", tone(r.roi_pct))}>
                  {fmtPct(r.roi_pct)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </Panel>
  );
}

export function Breakdowns({ data }: { data: Rollups | undefined }) {
  if (!data) return null;
  return (
    <div className="grid lg:grid-cols-3 gap-3 items-start">
      <Table title="By book" groupLabel="Book" rows={data.by_book} keyCol="source_book" />
      <Table title="By sport" groupLabel="Sport" rows={data.by_sport} keyCol="sport_key" />
      <Table title="By market" groupLabel="Market" rows={data.by_market} keyCol="market_key" />
    </div>
  );
}
