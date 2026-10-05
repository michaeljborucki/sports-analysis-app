"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Panel } from "@/components/ui";
import { CLV_CHART_HEIGHT_CLASS } from "./chart-size";

interface Bet {
  accepted_at: string;
  clv_pct: number | null;
}

const AXIS_TICK = {
  fontSize: 11,
  fill: "var(--color-text-3)",
  fontFamily: "var(--font-mono)",
};

const fmtPct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;

export function CLVChart({ bets }: { bets: Bet[] | undefined }) {
  if (!bets) {
    return (
      <div
        className={`${CLV_CHART_HEIGHT_CLASS} rounded-lg border border-border-subtle bg-bg-1 animate-pulse`}
      />
    );
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
    .map(([day, s]) => ({ day, clv: s.sum / s.count, n: s.count }));

  // Split the fill at zero: positive CLV (beat the close) reads as gain,
  // negative as loss. The gradient offset is where y=0 sits in the
  // plotted range.
  const values = series.map(p => p.clv);
  const max = Math.max(0, ...values);
  const min = Math.min(0, ...values);
  const zeroOffset = max - min === 0 ? 0.5 : max / (max - min);
  const sampleSize = series.reduce((acc, p) => acc + p.n, 0);

  return (
    <Panel
      className={`${CLV_CHART_HEIGHT_CLASS} flex flex-col`}
      title={
        <>
          Closing-line value{" "}
          <span className="font-normal text-text-3">daily average</span>
        </>
      }
      actions={
        sampleSize > 0 ? (
          <span className="text-[length:var(--fs-12)] text-text-3">
            <span className="tabular">{sampleSize}</span> bets with a closing line
          </span>
        ) : null
      }
      bodyClassName="flex-1 min-h-0 px-2 pt-3 pb-1"
    >
      {series.length === 0 ? (
        <div className="h-full flex items-center justify-center text-[length:var(--fs-13)] text-text-3">
          No CLV data yet. Closing lines populate after games settle.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 4, right: 12, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="clv-stroke" x1="0" y1="0" x2="0" y2="1">
                <stop offset={zeroOffset} stopColor="var(--color-gain)" />
                <stop offset={zeroOffset} stopColor="var(--color-loss)" />
              </linearGradient>
              <linearGradient id="clv-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset={0} stopColor="var(--color-gain)" stopOpacity={0.22} />
                <stop offset={zeroOffset} stopColor="var(--color-gain)" stopOpacity={0.04} />
                <stop offset={zeroOffset} stopColor="var(--color-loss)" stopOpacity={0.04} />
                <stop offset={1} stopColor="var(--color-loss)" stopOpacity={0.22} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="2 3"
              stroke="var(--color-border-subtle)"
              vertical={false}
            />
            <XAxis
              dataKey="day"
              tick={AXIS_TICK}
              tickFormatter={(d: string) => d.slice(5)}
              axisLine={false}
              tickLine={false}
              minTickGap={24}
            />
            <YAxis
              tick={AXIS_TICK}
              tickFormatter={(v: number) => `${v}%`}
              axisLine={false}
              tickLine={false}
              width={44}
            />
            <ReferenceLine y={0} stroke="var(--color-text-3)" strokeWidth={1} />
            <Tooltip
              cursor={{ stroke: "var(--color-text-3)", strokeDasharray: "2 2" }}
              contentStyle={{
                background: "var(--color-bg-1)",
                border: "1px solid var(--color-border-subtle)",
                borderRadius: 6,
                fontSize: 12,
              }}
              labelStyle={{ color: "var(--color-text-3)", fontFamily: "var(--font-mono)" }}
              itemStyle={{ color: "var(--color-text-1)", fontFamily: "var(--font-mono)" }}
              // Recharts 3 types the formatter value as ValueType | undefined
              // (a tooltip payload entry can be a string, an array, or absent),
              // so narrow rather than asserting number.
              formatter={(v) => [typeof v === "number" ? fmtPct(v) : "—", "CLV"]}
            />
            <Area
              type="monotone"
              dataKey="clv"
              stroke="url(#clv-stroke)"
              strokeWidth={1.75}
              fill="url(#clv-fill)"
              dot={
                series.length === 1
                  ? { r: 3, fill: series[0].clv >= 0 ? "var(--color-gain)" : "var(--color-loss)", strokeWidth: 0 }
                  : false
              }
              activeDot={{ r: 3, fill: "var(--color-text-1)", stroke: "var(--color-bg-1)" }}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </Panel>
  );
}
