"use client";

interface Window {
  count: number;
  wagered: number;
  net: number;
  roi_pct: number;
}

interface Rollups {
  window_30d: Window;
  window_90d: Window;
  lifetime: Window;
}

const fmtPct = (v: number) =>
  `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const fmtUsd = (v: number) =>
  v.toLocaleString("en-US", { style: "currency", currency: "USD" });

export function RollupTiles({ data }: { data: Rollups | undefined }) {
  if (!data) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-24 rounded bg-bg-1 animate-pulse" />
        ))}
      </div>
    );
  }
  const tile = (label: string, w: Window) => (
    <div className="rounded border border-border-subtle bg-bg-1 p-3">
      <div className="text-[10px] uppercase tracking-wider text-text-3">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular">
        ROI {fmtPct(w.roi_pct)}
      </div>
      <div className="text-xs text-text-2">
        {w.count} bets · {fmtUsd(w.wagered)}
      </div>
    </div>
  );
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {tile("30 DAY", data.window_30d)}
      {tile("90 DAY", data.window_90d)}
      {tile("LIFETIME", data.lifetime)}
      <div className="rounded border border-border-subtle bg-bg-1 p-3">
        <div className="text-[10px] uppercase tracking-wider text-text-3">
          NET LIFETIME
        </div>
        <div className="mt-1 text-lg font-semibold tabular">
          {fmtUsd(data.lifetime.net)}
        </div>
      </div>
    </div>
  );
}
