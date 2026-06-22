// Plan how a Kelly target gets allocated across the account pool.
//
// Multi-parlay-per-account walk; lowest balance first; stack max-cap parlays
// on each account until it can't fund another; take one partial; peel-back
// when the residual would drop below the per-parlay floor.
//
// Faithful port of server/sidecar/splitter.py. Property/worked-example tests
// in `__tests__/splitter.test.ts` mirror the Python suite.

export const FLOOR = 30; // dollars; no individual parlay smaller than this

export type SplitStatus =
  | "planned"
  | "below_minimum"
  | "no_eligible_account"
  | "partial_fill";

export interface AccountSnapshot {
  customer_id: string;
  label?: string;
  available_balance: number;
  max_parlay_stake: number;
}

export interface SplitAssignment {
  account: AccountSnapshot;
  amount: number;
}

export interface SplitPlan {
  assignments: SplitAssignment[];
  status: SplitStatus;
  target: number;
  filled: number;
  unfilled: number;
}

function makePlan(
  assignments: SplitAssignment[],
  status: SplitStatus,
  target: number,
): SplitPlan {
  const filled = assignments.reduce((sum, a) => sum + a.amount, 0);
  return {
    assignments,
    status,
    target,
    filled,
    unfilled: target - filled,
  };
}

export function planSplits(
  target: number,
  accounts: AccountSnapshot[],
): SplitPlan {
  if (target < FLOOR) {
    return makePlan([], "below_minimum", target);
  }

  const eligible = accounts
    .filter((a) => a.available_balance >= FLOOR)
    .slice()
    .sort((a, b) => a.available_balance - b.available_balance);

  if (eligible.length === 0) {
    return makePlan([], "no_eligible_account", target);
  }

  const assignments: SplitAssignment[] = [];
  let remaining = target;

  for (const account of eligible) {
    if (remaining === 0) break;

    // Python uses int(account.available_balance); mirror that truncation.
    let balance = Math.trunc(account.available_balance);
    const cap = account.max_parlay_stake;

    // Pack full-cap parlays on this account.
    while (balance >= cap && remaining >= cap) {
      assignments.push({ account, amount: cap });
      balance -= cap;
      remaining -= cap;
    }

    if (remaining === 0) break;

    // Try one partial parlay on this account.
    const partial = Math.min(balance, remaining, cap);
    if (partial < FLOOR) {
      continue;
    }
    const newRemaining = remaining - partial;
    if (newRemaining === 0 || newRemaining >= FLOOR) {
      assignments.push({ account, amount: partial });
      balance -= partial;
      remaining = newRemaining;
    } else {
      // Shrink this partial so residual lands on FLOOR exactly.
      const adjusted = partial - (FLOOR - newRemaining);
      if (adjusted >= FLOOR) {
        assignments.push({ account, amount: adjusted });
        balance -= adjusted;
        remaining = FLOOR;
      }
    }
  }

  // Final peel-back: reduce last assignment by (FLOOR - remaining) and
  // place a fresh FLOOR-sized bet on the next-cheapest non-same account.
  if (remaining > 0 && remaining < FLOOR && assignments.length > 0) {
    const last = assignments[assignments.length - 1];
    const deficit = FLOOR - remaining;
    if (last.amount - deficit >= FLOOR) {
      const alt = eligible.find(
        (a) =>
          a.customer_id !== last.account.customer_id &&
          a.available_balance >= FLOOR,
      );
      if (alt !== undefined) {
        last.amount -= deficit;
        assignments.push({ account: alt, amount: FLOOR });
        remaining = 0;
      }
    }
  }

  const status: SplitStatus = remaining === 0 ? "planned" : "partial_fill";
  return makePlan(assignments, status, target);
}
