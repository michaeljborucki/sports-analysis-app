"use client";

import { StatTile } from "@/components/ui";

interface Window {
  count: number;
  wagered: number;
  net: number;
  roi_pct: number;
}

export interface Rollups {
  window_30d: Window;
  window_90d: Window;
  lifetime: Window;
}

const fmtPct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const fmtUsd = (v: number) =>
  v.toLocaleString("en-US", { style: "currency", currency: "USD" });
const fmtSignedUsd = (v: number) => `${v > 0 ? "+" : ""}${fmtUsd(v)}`;

const tone = (v: number) => (v > 0 ? "gain" : v < 0 ? "loss" : undefined);

function WindowTile({ label, w }: { label: string; w: Window }) {
  return (
    <StatTile
      label={`${label} ROI`}
      value={fmtPct(w.roi_pct)}
      tone={w.count > 0 ? tone(w.roi_pct) : undefined}
      sub={
        <>
          <span className="tabular">{w.count}</span> {w.count === 1 ? "bet" : "bets"}, net{" "}
          <span className="tabular">{fmtSignedUsd(w.net)}</span>
        </>
      }
    />
  );
}

export function RollupTiles({ data }: { data: Rollups | undefined }) {
  if (!data) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-[86px] rounded-lg border border-border-subtle bg-bg-1 animate-pulse"
          />
        ))}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <WindowTile label="30 day" w={data.window_30d} />
      <WindowTile label="90 day" w={data.window_90d} />
      <WindowTile label="Lifetime" w={data.lifetime} />
      <StatTile
        label="Lifetime net"
        value={fmtSignedUsd(data.lifetime.net)}
        tone={tone(data.lifetime.net)}
        sub={
          <>
            <span className="tabular">{fmtUsd(data.lifetime.wagered)}</span> wagered
          </>
        }
      />
    </div>
  );
}
