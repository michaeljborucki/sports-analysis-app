// Worked-example tests for the client-side splitter mirror.
// Mirrors server/tests/test_sidecar_splitter.py one-for-one so any
// algorithmic divergence between the Python and TS implementations
// surfaces as a failing test in both suites.
//
// Jest is not yet wired into this project (see Task G1 in the plan).
// The minimal ambient declarations below let `tsc --noEmit` accept this
// file without requiring @types/jest as a dev dependency; when jest is
// installed later, jest's own types will take over and these become
// inert dupes (same shapes, structural compatibility).

declare const test: (name: string, fn: () => void) => void;
declare const expect: (actual: unknown) => {
  toBe(expected: unknown): void;
  toEqual(expected: unknown): void;
};

import { planSplits, FLOOR, AccountSnapshot } from "../splitter";

const acct = (
  id: string,
  bal: number,
  cap = 100,
): AccountSnapshot => ({
  customer_id: id,
  available_balance: bal,
  max_parlay_stake: cap,
});

const pairs = (plan: ReturnType<typeof planSplits>) =>
  plan.assignments.map((a) => [a.account.customer_id, a.amount] as const);

// --- worked examples from the spec ---

test("target 300, A=250, B=1000 -> A:100 A:100 A:50 B:50", () => {
  const plan = planSplits(300, [acct("A", 250), acct("B", 1000)]);
  expect(plan.status).toBe("planned");
  expect(pairs(plan)).toEqual([
    ["A", 100],
    ["A", 100],
    ["A", 50],
    ["B", 50],
  ]);
});

test("target 300, A=500, B=1000 -> all on A (three 100s)", () => {
  const plan = planSplits(300, [acct("A", 500), acct("B", 1000)]);
  expect(plan.status).toBe("planned");
  expect(pairs(plan)).toEqual([
    ["A", 100],
    ["A", 100],
    ["A", 100],
  ]);
});

test("target 105, A=1000, B=1000 -> peelback A:75 B:30", () => {
  const plan = planSplits(105, [acct("A", 1000), acct("B", 1000)]);
  expect(plan.status).toBe("planned");
  expect(pairs(plan)).toEqual([
    ["A", 75],
    ["B", 30],
  ]);
});

test("target 260, A=250, B=1000 -> A:100 A:100 A:30 B:30", () => {
  const plan = planSplits(260, [acct("A", 250), acct("B", 1000)]);
  expect(plan.status).toBe("planned");
  expect(pairs(plan)).toEqual([
    ["A", 100],
    ["A", 100],
    ["A", 30],
    ["B", 30],
  ]);
});

test("target 130, STANLEY (cap=150, bal=300) lowest balance takes alone", () => {
  const stanley = acct("STANLEY", 300, 150);
  const other = acct("B", 1000);
  const plan = planSplits(130, [stanley, other]);
  expect(plan.status).toBe("planned");
  expect(pairs(plan)).toEqual([["STANLEY", 130]]);
});

test("target 230, STANLEY stacks twice (150 then 80) — balance covers second parlay", () => {
  const stanley = acct("STANLEY", 300, 150);
  const other = acct("B", 1000);
  const plan = planSplits(230, [stanley, other]);
  expect(plan.status).toBe("planned");
  expect(pairs(plan)).toEqual([
    ["STANLEY", 150],
    ["STANLEY", 80],
  ]);
});

// --- refusals ---

test("below_minimum: target 18 < FLOOR", () => {
  const plan = planSplits(18, [acct("A", 1000)]);
  expect(plan.status).toBe("below_minimum");
  expect(plan.assignments).toEqual([]);
});

test("no_eligible_account: nobody has FLOOR", () => {
  const plan = planSplits(50, [acct("A", 20), acct("B", 25)]);
  expect(plan.status).toBe("no_eligible_account");
});

test("partial_fill: only acct has 80, requested 200", () => {
  const plan = planSplits(200, [acct("ONLY", 80)]);
  expect(plan.status).toBe("partial_fill");
  expect(plan.filled).toBe(80);
  expect(plan.unfilled).toBe(120);
});

// Sanity: FLOOR is exported and is 30 (so callers can reference it).
test("FLOOR constant is 30", () => {
  expect(FLOOR).toBe(30);
});
