/**
 * Stake math for the /edges workbench.
 *
 * All functions are pure — no React, no localStorage. The hook that
 * exposes bankroll / Kelly fraction / rounding lives in the workbench
 * component.
 */
import type { EdgeOpportunity } from "@/lib/edges";

export type RoundIncrement = 1 | 5 | 25 | 100;

/** Convert American odds to decimal. */
export function americanToDecimal(american: number): number {
  if (american > 0) return 1 + american / 100;
  return 1 + 100 / Math.abs(american);
}

/** Implied probability of an American price. */
export function americanToProb(american: number): number {
  const dec = americanToDecimal(american);
  return 1 / dec;
}

export function roundStake(amount: number, inc: RoundIncrement): number {
  if (inc <= 1) return Math.round(amount);
  return Math.round(amount / inc) * inc;
}

// ─────────────────────── Arbitrage / Low-Hold splits ────────────────

export interface ArbSplit {
  leg_stakes: number[];
  /** Net profit regardless of outcome. */
  profit: number;
  /** Total outlay across all legs. */
  total: number;
}

/**
 * Given a total bankroll commitment and the two legs' American prices,
 * compute the Kelly-agnostic split that produces equal profit whichever
 * leg wins. Works for any number of legs given implied-prob weights.
 */
export function arbSplit(
  totalStake: number,
  legs: Array<{ price_american: number }>,
  inc: RoundIncrement,
): ArbSplit {
  const probs = legs.map(l => americanToProb(l.price_american));
  const sumProb = probs.reduce((a, b) => a + b, 0);
  // Unrounded stakes proportional to implied probability — lowest odds
  // carries the biggest share.
  const raw = probs.map(p => (totalStake * p) / sumProb);
  const rounded = raw.map(s => roundStake(s, inc));
  const total = rounded.reduce((a, b) => a + b, 0);
  // Net profit per leg — same across legs when split is ideal, but
  // rounding introduces small drift. Report the minimum (worst-case).
  const perLegReturn = rounded.map(
    (s, i) => s * americanToDecimal(legs[i].price_american) - total,
  );
  const profit = perLegReturn.length ? Math.min(...perLegReturn) : 0;
  return { leg_stakes: rounded, profit, total };
}

// ─────────────────────── +EV Kelly ───────────────────────────────

export interface KellyResult {
  stake: number;
  expected_profit: number;
  expected_roi_pct: number;
}

/**
 * Fractional-Kelly stake for +EV bets.
 *
 * Uses the true Kelly formula: f = (p·b − q) / b, where b = decimal
 * odds − 1. `kelly_full_pct` is already computed server-side, but we
 * recompute here so the workbench can re-shade with live bankroll +
 * fraction sliders.
 */
export function kellyStake(
  bankroll: number,
  offeredAmerican: number,
  fairProb: number,
  fraction: number,
  inc: RoundIncrement,
): KellyResult {
  const dec = americanToDecimal(offeredAmerican);
  const b = dec - 1;
  const p = Math.max(0, Math.min(1, fairProb));
  const q = 1 - p;
  const fullF = (p * b - q) / b;
  const f = Math.max(0, fullF * fraction);
  const stake = roundStake(bankroll * f, inc);
  // EV per $1 stake at this offered price & fair prob.
  const evPerDollar = p * b - q;
  const expected_profit = stake * evPerDollar;
  const expected_roi_pct = stake > 0 ? (expected_profit / stake) * 100 : 0;
  return { stake, expected_profit, expected_roi_pct };
}

// ─────────────────────── Free-bet conversion ─────────────────────

export interface FreeBetResult {
  /**
   * Face value of the promo free bet (the "stake" the user configures
   * globally on the page). Not risked — if the free leg wins we collect
   * winnings only; if it loses, we forfeit the bet.
   */
  free_face: number;
  /** Rounded cash stake on the hedge leg (risked). */
  hedge_stake: number;
  profit_if_free_wins: number;
  profit_if_hedge_wins: number;
  /**
   * Worst-case net across both outcomes, computed from the ROUNDED hedge.
   * Equals the backend's `conversion_pct × face` only when the hedge
   * needs no rounding.
   */
  profit: number;
}

export function freeBetConvert(
  faceValue: number,
  freeAmerican: number,
  hedgeAmerican: number,
  hedgeStakePer100: number,
  inc: RoundIncrement,
): FreeBetResult {
  const hedge_stake = roundStake((faceValue / 100) * hedgeStakePer100, inc);
  // Free bet returns winnings only; the hedge stake is lost when it wins.
  const profit_if_free_wins =
    faceValue * (americanToDecimal(freeAmerican) - 1) - hedge_stake;
  const profit_if_hedge_wins =
    hedge_stake * (americanToDecimal(hedgeAmerican) - 1);
  return {
    free_face: faceValue,
    hedge_stake,
    profit_if_free_wins,
    profit_if_hedge_wins,
    profit: Math.min(profit_if_free_wins, profit_if_hedge_wins),
  };
}

// ─────────────────────── Profit-boost conversion ─────────────────

function fmtSigned(n: number): string {
  return `${n < 0 ? "-" : "+"}$${Math.abs(n).toFixed(2)}`;
}

export interface ProfitBoostSplit {
  boost_stake: number;
  /** Rounded cash stake on the hedge leg. */
  hedge_stake: number;
  total: number;
  profit_if_boost_wins: number;
  profit_if_hedge_wins: number;
  /** Worst-case net across both outcomes, computed from the ROUNDED stakes. */
  profit: number;
}

/**
 * Boosted leg + rounded hedge, with profit evaluated per outcome from the
 * stakes actually placed. Rounding the hedge breaks the equal-profit
 * balance, so the guaranteed figure is the minimum of the two outcomes —
 * not `total × conversion_pct`, which assumes an unrounded hedge.
 *
 * The boosted payout is rebuilt from the ORIGINAL price × (1 + boost%),
 * matching the server, rather than from the rounded boosted American.
 */
export function profitBoostSplit(
  boostStake: number,
  originalBoostAmerican: number,
  boostPct: number,
  hedgeAmerican: number,
  hedgeStakePer100: number,
  inc: RoundIncrement,
): ProfitBoostSplit {
  const boostedWin =
    (americanToDecimal(originalBoostAmerican) - 1) * (1 + boostPct / 100);
  const hedgeWin = americanToDecimal(hedgeAmerican) - 1;
  const hedge_stake = roundStake((boostStake / 100) * hedgeStakePer100, inc);
  const profit_if_boost_wins = boostStake * boostedWin - hedge_stake;
  const profit_if_hedge_wins = hedge_stake * hedgeWin - boostStake;
  return {
    boost_stake: boostStake,
    hedge_stake,
    total: boostStake + hedge_stake,
    profit_if_boost_wins,
    profit_if_hedge_wins,
    profit: Math.min(profit_if_boost_wins, profit_if_hedge_wins),
  };
}

// ─────────────────────── Per-row stake (matches table) ──────────

/**
 * Return the same raw $ amount that `StakeCell` renders for this row.
 * Used by the Edges page's `minStake` filter so that "≥ $X" matches what
 * the user sees in the column.
 *
 * Mode contract — must stay in lockstep with `StakeCell` in
 * `components/edges/edges-table.tsx`:
 *   arb / low_hold → same `stake` for every row (the global "Stake" input)
 *   ev             → Kelly stake from bankroll × fair-prob × Kelly fraction
 *   free_bet       → hedge stake = round((stake / 100) × hedge_per_100)
 */
export function computeRowStakeDollars(
  op: EdgeOpportunity,
  cfg: {
    bankroll: number;
    kellyFrac: number;
    rounding: RoundIncrement;
    /** "Stake" / "Free face" global input from the page filter row. */
    stake: number;
  },
): number {
  if (op.mode === "arb" || op.mode === "low_hold") return cfg.stake;
  if (op.mode === "ev") {
    return kellyStake(
      cfg.bankroll,
      op.raw.offered_price_american,
      op.raw.fair_probability,
      cfg.kellyFrac,
      cfg.rounding,
    ).stake;
  }
  if (op.mode === "profit_boost") {
    // Total stake = boost stake + hedge stake. The "stake" input the user
    // configures is the BOOSTED-LEG cash stake; hedge is sized to lock
    // equal profit.
    const hedge = roundStake(
      (cfg.stake / 100) * op.raw.hedge_stake_per_100_boost,
      cfg.rounding,
    );
    return cfg.stake + hedge;
  }
  // free_bet
  return roundStake((cfg.stake / 100) * op.raw.hedge_stake_per_100, cfg.rounding);
}

// ─────────────────────── Mode-aware facade ───────────────────────

export interface WorkbenchConfig {
  bankroll: number;
  kelly_fraction: number;
  rounding: RoundIncrement;
  /** Free-bet face value (overrides bankroll for FB conversion math). */
  stake: number;
}

export interface WorkbenchMath {
  /** Pretty headline number — the "per row" stake the user pays. */
  primary_stake_label: string;
  /** Expected/guaranteed profit for this row at current config. */
  profit_label: string;
  /** Per-leg breakdown, order matches `op.legs`. */
  legs: Array<{ stake_label: string }>;
}

export function computeWorkbenchMath(
  op: EdgeOpportunity,
  cfg: WorkbenchConfig,
): WorkbenchMath {
  if (op.mode === "arb" || op.mode === "low_hold") {
    const split = arbSplit(
      cfg.stake,
      op.legs.map(l => ({ price_american: l.price_american })),
      cfg.rounding,
    );
    return {
      primary_stake_label: `$${split.total.toLocaleString()}`,
      profit_label:
        op.mode === "arb"
          ? `+$${split.profit.toFixed(2)} guaranteed`
          : `$${split.profit.toFixed(2)} (hedged, tiny edge)`,
      legs: op.legs.map((_, i) => ({
        stake_label: `$${split.leg_stakes[i].toLocaleString()}`,
      })),
    };
  }
  if (op.mode === "ev") {
    const fairProb = op.raw.fair_probability;
    const k = kellyStake(
      cfg.bankroll,
      op.raw.offered_price_american,
      fairProb,
      cfg.kelly_fraction,
      cfg.rounding,
    );
    return {
      primary_stake_label: `$${k.stake.toLocaleString()}`,
      profit_label: `+$${k.expected_profit.toFixed(2)} expected (${k.expected_roi_pct.toFixed(1)}% ROI)`,
      legs: op.legs.map(leg => ({
        stake_label:
          leg.role === "offered"
            ? `$${k.stake.toLocaleString()}`
            : "(fair)",
      })),
    };
  }
  if (op.mode === "profit_boost") {
    // The user configures `cfg.stake` as the boost-leg cash stake. Hedge
    // sizes to lock equal profit, then gets rounded — so report the
    // worst-case outcome from the stakes actually placed.
    const split = profitBoostSplit(
      cfg.stake,
      op.raw.boost_leg.original_price_american,
      op.raw.boost_pct,
      op.raw.hedge_leg.price_american,
      op.raw.hedge_stake_per_100_boost,
      cfg.rounding,
    );
    const skew =
      Math.abs(split.profit_if_boost_wins - split.profit_if_hedge_wins) >= 0.01
        ? ` · boost wins ${fmtSigned(split.profit_if_boost_wins)} / hedge wins ${fmtSigned(split.profit_if_hedge_wins)}`
        : "";
    return {
      primary_stake_label: `$${split.total.toLocaleString()}`,
      profit_label: `${fmtSigned(split.profit)} guaranteed (${op.raw.conversion_pct.toFixed(2)}% conversion @ ${op.raw.boost_pct}% boost)${skew}`,
      legs: op.legs.map(leg => ({
        stake_label:
          leg.role === "offered"
            ? `$${cfg.stake.toLocaleString()} boost`
            : `$${split.hedge_stake.toLocaleString()} hedge`,
      })),
    };
  }
  // free_bet
  const fb = freeBetConvert(
    cfg.stake,
    op.raw.free_leg.price_american,
    op.raw.hedge_leg.price_american,
    op.raw.hedge_stake_per_100,
    cfg.rounding,
  );
  const fbSkew =
    Math.abs(fb.profit_if_free_wins - fb.profit_if_hedge_wins) >= 0.01
      ? ` · free wins ${fmtSigned(fb.profit_if_free_wins)} / hedge wins ${fmtSigned(fb.profit_if_hedge_wins)}`
      : "";
  return {
    primary_stake_label: `$${fb.free_face.toLocaleString()} free`,
    profit_label: `${fmtSigned(fb.profit)} guaranteed (${op.raw.conversion_pct.toFixed(2)}% conversion)${fbSkew}`,
    legs: op.legs.map(leg => ({
      stake_label:
        leg.role === "offered"
          ? `$${fb.free_face.toLocaleString()} free`
          : `$${fb.hedge_stake.toLocaleString()} cash`,
    })),
  };
}
