/**
 * Median American odds in implied-probability space.
 * Client mirror of `server/odds/best_odds.py::median_american_odds`.
 *
 * Used for the "Consensus" column, which is computed from the user's currently
 * visible books (not a fixed server value), so toggling the book filter
 * re-centers the consensus.
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

import { effectiveForBook } from "./effective-odds";

/** Higher = better payout. For comparison only, not a real EV figure. */
function payoutMultiplier(odds: number): number {
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / -odds;
}

export interface PricedAtBook {
  bookmaker_key: string;
  price_american: number;
  point?: number | null;
}

/**
 * Highest effective payout across the supplied price list. Each book's listed
 * price is adjusted by its commission (if any) before comparison, so a +105 at
 * Prophet Exchange (2% commission → effective +103) loses to a listed +104 at
 * a commission-free book.
 */
export function pickBest<T extends PricedAtBook>(prices: T[]): T | null {
  if (!prices.length) return null;
  return prices.reduce((a, b) => {
    const ma = payoutMultiplier(effectiveForBook(a.price_american, a.bookmaker_key));
    const mb = payoutMultiplier(effectiveForBook(b.price_american, b.bookmaker_key));
    return ma >= mb ? a : b;
  });
}
