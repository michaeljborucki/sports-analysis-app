"use client";
import { useMemo, useState } from "react";
import { TrendingUp } from "lucide-react";

/**
 * Hero dashboard module — 24-hour edge-volume stacked bar chart.
 *
 * ## Synthetic data disclaimer
 * There is no backend endpoint yet that returns per-hour opportunity counts
 * bucketed by scanner mode. Until that lands, the chart uses a deterministic
 * synthetic generator seeded by the current UTC hour so the numbers stay
 * stable across the 30s dashboard SWR cycle (otherwise every refresh would
 * shuffle the bars — noisy and dishonest-feeling).
 *
 * Seed strategy: `seed = floor(Date.now() / 3_600_000) + hashString(mode)`.
 * The LCG below (`mulberry32`) is fast, deterministic, and has acceptable
 * distribution for display purposes. When a real time-series endpoint ships,
 * swap `buildSeries()` for a fetch + keep the render logic.
 *
 * ## Geometry
 * SVG, hand-rolled, no charting library. 24 bars × 4 segments each.
 * Width is responsive (viewBox 0 0 480 160, `preserveAspectRatio="none"`
 * on the x-axis via `viewBox` scaling). Height is fixed at 180px by the
 * parent container — the SVG fills it via `width="100%" height="100%"`.
 *
 * Hover tooltip is a conditional <div> positioned over the hovered bar.
 */

type Mode = "arb" | "low_hold" | "ev" | "free_bet";

const MODES: readonly Mode[] = ["arb", "low_hold", "ev", "free_bet"] as const;

const MODE_META: Record<Mode, { label: string; color: string; long: string }> = {
  // Re-use the ModeToggle palette:
  //   arb      → price-up (green)
  //   low_hold → accent (cyan)
  //   ev       → violet-accent
  //   free_bet → flash (amber)
  arb: { label: "ARB", color: "var(--color-price-up)", long: "Arbitrage" },
  low_hold: { label: "LH", color: "var(--color-accent)", long: "Low Hold" },
  ev: { label: "EV", color: "var(--color-violet-accent)", long: "+EV" },
  free_bet: { label: "FB", color: "var(--color-flash)", long: "Free Bet" },
};

function hashString(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

/** Deterministic 32-bit PRNG — https://stackoverflow.com/a/47593316. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Bar {
  /** 0..23, hour offset where 0 = 24h ago and 23 = current hour. */
  hour: number;
  counts: Record<Mode, number>;
  total: number;
}

function buildSeries(seedHour: number): { bars: Bar[]; totalsByMode: Record<Mode, number>; grandTotal: number } {
  const bars: Bar[] = [];
  const totalsByMode: Record<Mode, number> = {
    arb: 0,
    low_hold: 0,
    ev: 0,
    free_bet: 0,
  };

  for (let h = 0; h < 24; h++) {
    // Seed ties hour-in-chart + absolute hour-of-day so the pattern is stable
    // across a 30s SWR refresh but shifts when the real wall-clock hour rolls.
    const counts = {} as Record<Mode, number>;
    let total = 0;
    for (const mode of MODES) {
      const seed = seedHour + h + hashString(mode);
      const rand = mulberry32(seed);
      // Most hours have 0-3 of each mode; a handful spike to 4-6. The 0.72
      // cutoff + squaring biases toward low counts with occasional spikes
      // — looks realistic rather than uniformly busy.
      const raw = rand();
      const v = raw < 0.72 ? Math.floor(raw * 4) : Math.floor(raw * raw * 8 + 2);
      counts[mode] = v;
      total += v;
      totalsByMode[mode] += v;
    }
    bars.push({ hour: h, counts, total });
  }

  return {
    bars,
    totalsByMode,
    grandTotal: bars.reduce((s, b) => s + b.total, 0),
  };
}

export function EdgeVolumeChart() {
  // Current UTC hour — the one number that legitimately should "refresh" the
  // underlying data. Stable within a calendar hour.
  const seedHour = useMemo(() => Math.floor(Date.now() / 3_600_000), []);
  const { bars, totalsByMode, grandTotal } = useMemo(
    () => buildSeries(seedHour),
    [seedHour],
  );

  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // SVG geometry — 24 bars + gaps. We compute in viewBox space and let the
  // parent container dictate actual render size. VB width = 480, height = 160.
  const VB_W = 480;
  const VB_H = 160;
  const BAR_GAP = 2;
  const PAD_L = 4;
  const PAD_R = 4;
  const PAD_T = 8;
  const PAD_B = 18; // leaves room for hour labels on the bottom
  const innerW = VB_W - PAD_L - PAD_R;
  const innerH = VB_H - PAD_T - PAD_B;
  const barW = (innerW - BAR_GAP * 23) / 24;

  const maxTotal = Math.max(1, ...bars.map(b => b.total));

  // x-axis hour labels: show 00, 06, 12, 18, now
  const nowHour = new Date().getHours();
  const axisHours = [0, 6, 12, 18];

  return (
    <div className="relative h-full flex flex-col">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <TrendingUp size={14} className="text-text-3 translate-y-[1px]" aria-hidden />
          <span className="text-[11px] uppercase tracking-wider text-text-3">
            Today&apos;s edge volume
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px] uppercase tracking-wider text-text-3">
          {MODES.map(m => (
            <span key={m} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block w-2 h-2 rounded-sm"
                style={{ background: MODE_META[m].color }}
                aria-hidden
              />
              {MODE_META[m].label}
              <span className="text-text-2 tabular">{totalsByMode[m]}</span>
            </span>
          ))}
        </div>
      </div>

      {/* Big count */}
      <div className="mt-2 flex items-baseline gap-2">
        <span className="tabular text-[28px] leading-[30px] font-semibold text-text-1">
          {grandTotal}
        </span>
        <span className="text-[11px] text-text-3">
          edges detected · last 24h
        </span>
      </div>

      {/* Chart */}
      <div className="relative flex-1 min-h-[140px] mt-3">
        <svg
          viewBox={`0 0 ${VB_W} ${VB_H}`}
          preserveAspectRatio="none"
          className="w-full h-full block"
          role="img"
          aria-label={`24-hour edge volume chart — ${grandTotal} edges across 4 scanner modes`}
        >
          {/* Faint horizontal grid line at chart top (reads as "ceiling") */}
          <line
            x1={PAD_L}
            x2={VB_W - PAD_R}
            y1={PAD_T}
            y2={PAD_T}
            stroke="var(--color-border-subtle)"
            strokeDasharray="2 3"
            strokeWidth={0.5}
            opacity={0.6}
          />

          {bars.map((bar, i) => {
            const x = PAD_L + i * (barW + BAR_GAP);
            const totalH = (bar.total / maxTotal) * innerH;
            let yCursor = PAD_T + innerH - totalH;
            const isHover = hoverIdx === i;
            return (
              <g key={i}>
                {/* Hover hit area — full-height transparent rect so thin
                    bars are still easy to hit. */}
                <rect
                  x={x - BAR_GAP / 2}
                  y={PAD_T}
                  width={barW + BAR_GAP}
                  height={innerH}
                  fill="transparent"
                  onMouseEnter={() => setHoverIdx(i)}
                  onMouseLeave={() => setHoverIdx(null)}
                />
                {MODES.map(mode => {
                  const c = bar.counts[mode];
                  if (c === 0) return null;
                  const segH = (c / maxTotal) * innerH;
                  const y = yCursor;
                  yCursor += segH;
                  return (
                    <rect
                      key={mode}
                      x={x}
                      y={y}
                      width={barW}
                      height={Math.max(0.5, segH)}
                      fill={MODE_META[mode].color}
                      opacity={isHover ? 1 : 0.85}
                      rx={0.5}
                    />
                  );
                })}
                {/* Hover outline */}
                {isHover && (
                  <rect
                    x={x - 0.5}
                    y={PAD_T + innerH - totalH - 0.5}
                    width={barW + 1}
                    height={totalH + 1}
                    fill="none"
                    stroke="var(--color-text-1)"
                    strokeWidth={0.5}
                    opacity={0.6}
                  />
                )}
              </g>
            );
          })}

          {/* x-axis hour ticks */}
          {axisHours.map(hr => {
            const i = hr;
            const x = PAD_L + i * (barW + BAR_GAP) + barW / 2;
            return (
              <text
                key={hr}
                x={x}
                y={VB_H - 4}
                fill="var(--color-text-3)"
                fontSize={8}
                fontFamily="var(--font-mono)"
                textAnchor="middle"
              >
                {String(hr).padStart(2, "0")}
              </text>
            );
          })}
          <text
            x={PAD_L + 23 * (barW + BAR_GAP) + barW / 2}
            y={VB_H - 4}
            fill="var(--color-text-2)"
            fontSize={8}
            fontFamily="var(--font-mono)"
            textAnchor="middle"
          >
            now
          </text>
        </svg>

        {/* Tooltip — positioned absolutely over the hovered bar. */}
        {hoverIdx != null && bars[hoverIdx] && (
          <div
            className="pointer-events-none absolute z-10 rounded-md border border-border-subtle bg-bg-2 px-2.5 py-2 text-[10px] shadow-lg"
            style={{
              left: `calc(${((hoverIdx + 0.5) / 24) * 100}% - 62px)`,
              top: 4,
              minWidth: 124,
            }}
          >
            <div className="text-text-3 uppercase tracking-wider mb-1">
              {hoverIdx === 23
                ? "Current hour"
                : `${24 - hoverIdx}h ago`}
              {" · "}
              <span className="tabular text-text-2">
                {bars[hoverIdx].total} total
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              {MODES.map(m => (
                <div key={m} className="flex items-center justify-between gap-3">
                  <span className="inline-flex items-center gap-1.5 text-text-2">
                    <span
                      className="inline-block w-1.5 h-1.5 rounded-sm"
                      style={{ background: MODE_META[m].color }}
                      aria-hidden
                    />
                    {MODE_META[m].long}
                  </span>
                  <span className="tabular text-text-1">
                    {bars[hoverIdx].counts[m]}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Synthetic-data stub disclaimer — tiny, whispered. Backend TODO
          signal so the user knows the bars aren't yet authoritative. */}
      <div className="mt-2 text-[10px] text-text-3 tracking-wide">
        Synthetic sample · seeded by current hour
        <span className="text-text-3/60"> (backend time-series TODO)</span>
      </div>

      {/* Compact hour-label marker for "now" already rendered in SVG. */}
      <div className="sr-only">Current UTC hour: {nowHour}</div>
    </div>
  );
}
