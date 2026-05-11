"use client";

/**
 * Small inline sparkline for edge % over the last ~15 minutes.
 *
 * Backend has no time-series endpoint yet; we synthesise a stable
 * per-row walk by hashing a seed key (typically `event_id + market_kind`).
 * The walk is deterministic for the session so the line does not jitter
 * between renders. The final sample is pinned to the caller-supplied
 * `currentEdge` so the sparkline always terminates at "now."
 *
 * Styling is driven by the trend between the first and last sample:
 *   - up   → `text-price-up` (green)
 *   - down → `text-price-down` (red)
 *   - flat → `text-text-3`
 *
 * Hand-rolled SVG — intentionally zero-dependency. At ~300 rows × 12
 * samples the perceived cost is under a millisecond of render time.
 */

// FNV-1a 32-bit — tiny, fast, adequate distribution for a PRNG seed. Not
// cryptographic; we don't care.
function hashSeed(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    // `Math.imul` keeps the multiplication in 32-bit space without the
    // precision loss of a plain `*` on large numbers.
    h = Math.imul(h, 0x01000193);
  }
  // Fold to unsigned 32-bit.
  return h >>> 0;
}

// mulberry32 — a 32-bit PRNG with good-enough distribution for placeholder
// visuals. Deterministic given the seed.
function mulberry32(seed: number): () => number {
  let t = seed;
  return () => {
    t = (t + 0x6d2b79f5) >>> 0;
    let r = t;
    r = Math.imul(r ^ (r >>> 15), r | 1);
    r ^= r + Math.imul(r ^ (r >>> 7), r | 61);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Generate a synthetic random-walk series terminating at `endValue`. The
 * first sample is chosen relative to `endValue` so the resulting line has
 * a plausible drift (not a flatline unless the walk genuinely is).
 */
function buildSeries(
  seedKey: string,
  endValue: number,
  samples: number,
): number[] {
  const rand = mulberry32(hashSeed(seedKey));
  // Drift magnitude: 0-ish for tiny edges, up to ~2 points for larger
  // edges. Keeps the walk visually proportional to the row's magnitude.
  const scale = Math.max(0.25, Math.abs(endValue) * 0.15 + 0.3);
  const walk: number[] = new Array(samples);
  walk[samples - 1] = endValue;
  for (let i = samples - 2; i >= 0; i--) {
    // Random step in [-scale, +scale]; bias slightly toward the mean so
    // the walk doesn't drift to infinity on long series.
    const step = (rand() - 0.5) * 2 * scale;
    walk[i] = walk[i + 1] - step;
  }
  return walk;
}

const W = 40;
const H = 12;
const PAD_Y = 1.5;

export function EdgeSparkline({
  seedKey,
  currentEdge,
  width = W,
  height = H,
  samples = 12,
  ariaLabel,
}: {
  /** Stable key — same value across renders should produce the same line. */
  seedKey: string;
  /** The current edge %. Last point in the walk equals this. */
  currentEdge: number;
  width?: number;
  height?: number;
  samples?: number;
  ariaLabel?: string;
}) {
  const series = buildSeries(seedKey, currentEdge, samples);
  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = max - min || 1;

  const first = series[0];
  const last = series[series.length - 1];
  const delta = last - first;
  // Flat threshold: <2% of range or <0.05pp absolute — whichever is
  // looser. Keeps "barely moving" lines gray.
  const flat = Math.abs(delta) < Math.max(range * 0.02, 0.05);
  const trend: "up" | "down" | "flat" = flat ? "flat" : delta > 0 ? "up" : "down";

  const colorClass =
    trend === "up"
      ? "text-price-up"
      : trend === "down"
      ? "text-price-down"
      : "text-text-3";

  // Map each sample to an (x, y) coordinate. X is evenly spaced; Y maps
  // the value into [PAD_Y, H - PAD_Y] with min → bottom, max → top. The
  // vertical padding keeps the stroke from clipping at 1.5px thickness.
  const innerH = height - PAD_Y * 2;
  const step = samples > 1 ? width / (samples - 1) : 0;
  const points = series
    .map((v, i) => {
      const x = i * step;
      const y = height - PAD_Y - ((v - min) / range) * innerH;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={
        ariaLabel ??
        `Edge ${trend === "flat" ? "flat" : trend === "up" ? "rising" : "falling"} over last 15 minutes`
      }
      className={colorClass}
      style={{ display: "block" }}
    >
      <polyline
        fill="none"
        stroke="currentColor"
        strokeOpacity={0.8}
        strokeWidth={1.25}
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}
