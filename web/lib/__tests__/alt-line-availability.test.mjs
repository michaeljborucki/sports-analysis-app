import assert from "node:assert/strict";
import test from "node:test";

import { canExpandAltLines, validAltLineSelection } from "../alt-line-availability.ts";

const soccerSpread = { mainKey: "spreads", altKey: "alternate_spreads", display: "spread" };

test("soccer spread expands only when that event has alternate spreads", () => {
  const withoutAlternates = { markets: [{ market_key: "spreads" }] };
  const withAlternates = { markets: [{ market_key: "spreads" }, { market_key: "alternate_spreads" }] };

  assert.equal(canExpandAltLines(withoutAlternates, "soccer", soccerSpread), false);
  assert.equal(canExpandAltLines(withAlternates, "soccer", soccerSpread), true);
});

test("other sports and soccer market groups preserve existing expansion behavior", () => {
  const game = { markets: [{ market_key: "spreads" }] };
  assert.equal(canExpandAltLines(game, "nba", soccerSpread), true);
  assert.equal(canExpandAltLines(game, "soccer", { mainKey: "h2h", display: "moneyline" }), true);
});

test("an open soccer spread selection closes when alternate coverage disappears", () => {
  const selected = "event-1";
  assert.equal(validAltLineSelection([
    { event_id: selected, markets: [{ market_key: "spreads" }, { market_key: "alternate_spreads" }] },
  ], selected, "soccer", soccerSpread), selected);
  assert.equal(validAltLineSelection([
    { event_id: selected, markets: [{ market_key: "spreads" }] },
  ], selected, "soccer", soccerSpread), null);
});
