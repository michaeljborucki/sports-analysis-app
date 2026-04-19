/**
 * Median American odds in implied-probability space. Mirror of
 * `server/odds/best_odds.py::median_american_odds`. Prices passed in are
 * already commission-adjusted effective prices (applied server-side).
 */

function americanToImpliedProb(odds: number): number {
  if (odds < 0) return -odds / (-odds + 100);
  return 100 / (odds + 100);
}

function probToAmerican(p: number): number {
  if (p <= 0 || p >= 1) return 0;
  if (p >= 0.5) return Math.round((-p / (1 - p)) * 100);
  return Math.round(((1 - p) / p) * 100);
}

function median(xs: number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const n = s.length;
  if (n === 0) return 0;
  if (n % 2 === 1) return s[(n - 1) / 2];
  return (s[n / 2 - 1] + s[n / 2]) / 2;
}

export function medianAmerican(prices: number[]): number | null {
  if (!prices.length) return null;
  return probToAmerican(median(prices.map(americanToImpliedProb)));
}

/** Higher = better payout. For comparison only. */
function payoutMultiplier(odds: number): number {
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / -odds;
}

export interface PricedAtBook {
  bookmaker_key: string;
  price_american: number;
  point?: number | null;
}

/** Highest payout across the supplied price list. Prices are already
 * effective (commission-adjusted server-side). */
export function pickBest<T extends PricedAtBook>(prices: T[]): T | null {
  if (!prices.length) return null;
  return prices.reduce((a, b) =>
    payoutMultiplier(a.price_american) >= payoutMultiplier(b.price_american) ? a : b
  );
}

/** Every price tied for best payout. */
export function findAllBest<T extends PricedAtBook>(prices: T[]): T[] {
  if (!prices.length) return [];
  let bestMult = -Infinity;
  const mults: number[] = [];
  for (const p of prices) {
    const m = payoutMultiplier(p.price_american);
    mults.push(m);
    if (m > bestMult) bestMult = m;
  }
  const EPS = 1e-9;
  return prices.filter((_, i) => Math.abs(mults[i] - bestMult) < EPS);
}
