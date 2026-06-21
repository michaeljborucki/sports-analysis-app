"use client";

interface Group {
  source_book?: string;
  sport_key?: string;
  market_key?: string;
  count: number;
  wagered: number;
  net: number;
  roi_pct: number;
}

interface Rollups {
  by_book: Group[];
  by_sport: Group[];
  by_market: Group[];
}

const fmtPct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;

function Table({
  title,
  rows,
  keyCol,
}: {
  title: string;
  rows: Group[];
  keyCol: "source_book" | "sport_key" | "market_key";
}) {
  return (
    <div className="rounded border border-border-subtle bg-bg-1 p-3">
      <div className="text-[10px] uppercase tracking-wider text-text-3 mb-2">
        {title}
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-text-3">
            <th className="text-left font-normal">Group</th>
            <th className="text-right font-normal">Bets</th>
            <th className="text-right font-normal">ROI</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={3} className="py-2 text-text-3">
                No data
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr key={r[keyCol] ?? "—"} className="border-t border-border-subtle">
                <td className="py-1">{r[keyCol] ?? "—"}</td>
                <td className="py-1 text-right tabular">{r.count}</td>
                <td className="py-1 text-right tabular">{fmtPct(r.roi_pct)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function Breakdowns({ data }: { data: Rollups | undefined }) {
  if (!data) return null;
  return (
    <div className="grid md:grid-cols-3 gap-3">
      <Table title="BY BOOK" rows={data.by_book} keyCol="source_book" />
      <Table title="BY SPORT" rows={data.by_sport} keyCol="sport_key" />
      <Table title="BY MARKET" rows={data.by_market} keyCol="market_key" />
    </div>
  );
}
