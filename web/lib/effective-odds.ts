import { bookInfo } from "./books";

/**
 * Payout multiplier on a $1 bet — what the bettor wins on a win.
 *   +105 → 1.05     (bet $1, win $1.05)
 *   -110 → 0.909    (bet $1, win $0.909)
 */
function payoutMultiplier(american: number): number {
  return american > 0 ? american / 100 : 100 / -american;
}

/** Convert payout multiplier back to American odds, rounded to integer. */
function multiplierToAmerican(m: number): number {
  if (m >= 1) return Math.round(m * 100);
  if (m <= 0) return 0;
  return -Math.round(100 / m);
}

/**
 * Apply a commission-on-winnings to an American price. Used for exchanges
 * that charge a percentage of net profit at settlement.
 *   +105 with 2% commission → +103 effective  (1.05 × 0.98 = 1.029)
 *   -110 with 2% commission → -112 effective  (0.909 × 0.98 = 0.891)
 *
 * For books with no commission, returns the listed price unchanged.
 */
export function effectiveAmerican(
  listedAmerican: number,
  commission: number = 0
): number {
  if (!commission || commission <= 0) return listedAmerican;
  const m = payoutMultiplier(listedAmerican) * (1 - commission);
  return multiplierToAmerican(m);
}

/** Shortcut: resolve commission from the book registry and apply. */
export function effectiveForBook(
  listedAmerican: number,
  bookmakerKey: string
): number {
  const info = bookInfo(bookmakerKey);
  return effectiveAmerican(listedAmerican, info.commission ?? 0);
}
