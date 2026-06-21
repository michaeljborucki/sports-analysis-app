"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface Bet {
  accepted_at: string;
  clv_pct: number | null;
}

export function CLVChart({ bets }: { bets: Bet[] | undefined }) {
  if (!bets) {
    return <div className="h-48 rounded bg-bg-1 animate-pulse" />;
  }
  const byDay = new Map<string, { sum: number; count: number }>();
  for (const b of bets) {
    if (b.clv_pct == null) continue;
    const day = b.accepted_at.slice(0, 10);
    const cur = byDay.get(day) ?? { sum: 0, count: 0 };
    cur.sum += b.clv_pct;
    cur.count += 1;
    byDay.set(day, cur);
  }
  const series = [...byDay.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([day, s]) => ({ day, clv: s.sum / s.count }));

  return (
    <div className="h-48 rounded border border-border-subtle bg-bg-1 p-3">
      <div className="text-[10px] uppercase tracking-wider text-text-3 mb-2">
        CLV % over time
      </div>
      {series.length === 0 ? (
        <div className="h-[80%] flex items-center justify-center text-xs text-text-3">
          No CLV data yet — closing lines populate after games settle.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height="85%">
          <LineChart data={series}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
            <XAxis dataKey="day" tick={{ fontSize: 10 }} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip
              contentStyle={{
                background: "var(--bg-1)",
                border: "1px solid var(--border-subtle)",
              }}
              formatter={(v: number) => `${v.toFixed(2)}%`}
            />
            <Line type="monotone" dataKey="clv" stroke="var(--accent)" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
