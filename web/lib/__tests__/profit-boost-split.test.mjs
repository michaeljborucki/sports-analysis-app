import assert from "node:assert/strict";
import test from "node:test";

import { profitBoostSplit } from "../stake-calc.ts";

// +200 boosted 30% (→ +260) hedged at -250: exact hedge is $257.14 per $100.
const PER_100 = (100 * (1 + 2.6)) / (1 + 0.4);

test("unrounded hedge locks equal profit on both outcomes", () => {
  const s = profitBoostSplit(100, 200, 30, -250, PER_100, 1);
  assert.equal(s.hedge_stake, 257);
  assert.ok(Math.abs(s.profit_if_boost_wins - 3) < 1e-9);
  assert.ok(Math.abs(s.profit_if_hedge_wins - 2.8) < 1e-9);
  assert.equal(s.profit, s.profit_if_hedge_wins);
});

test("coarse rounding reports the worst-case outcome, not total × conversion", () => {
  const s = profitBoostSplit(100, 200, 30, -250, PER_100, 5);
  assert.equal(s.hedge_stake, 255);
  assert.equal(s.total, 355);
  assert.ok(Math.abs(s.profit_if_boost_wins - 5) < 1e-9);
  assert.ok(Math.abs(s.profit_if_hedge_wins - 2) < 1e-9);
  assert.ok(Math.abs(s.profit - 2) < 1e-9);
});

test("rounding can push one side negative and the guarantee goes negative", () => {
  // Thin pair, big rounding: $100 boost at +100 (→ +130) vs -120 hedge.
  const per100 = (100 * 2.3) / (1 + 100 / 120);
  const s = profitBoostSplit(100, 100, 30, -120, per100, 100);
  assert.equal(s.hedge_stake, 100);
  assert.ok(s.profit < 0);
});

test("free-bet profit is the worst case from the rounded hedge", async () => {
  const { freeBetConvert } = await import("../stake-calc.ts");
  // $100 free at +300 hedged at -200: exact hedge 300/1.5 = $200 → +$100 both ways.
  const exact = freeBetConvert(100, 300, -200, 200, 1);
  assert.equal(exact.hedge_stake, 200);
  assert.ok(Math.abs(exact.profit - 100) < 1e-9);
  // $100 free at +260 vs -150: exact 156 → rounds to 150 (free wins 110, hedge wins 100).
  const r = freeBetConvert(100, 260, -150, 260 / (1 + 100 / 150), 25);
  assert.equal(r.hedge_stake, 150);
  assert.ok(Math.abs(r.profit_if_free_wins - 110) < 1e-9);
  assert.ok(Math.abs(r.profit_if_hedge_wins - 100) < 1e-9);
  assert.ok(Math.abs(r.profit - 100) < 1e-9);
});
