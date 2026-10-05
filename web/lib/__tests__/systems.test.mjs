import assert from "node:assert/strict";
import test from "node:test";

import { conflictingWagers, groupEvaluations, parseTimeframe, statusLabel } from "../systems.ts";
import { apiPaths } from "../api.ts";

const pick = (selection, overrides = {}) => ({
  sport: "ncaaf", event_id: "nebraska", home_team: "Nebraska Cornhuskers",
  away_team: "Akron Zips", bet_type: "total", selection, ...overrides,
});

test("flags both sides of a total even when their quoted lines differ", () => {
  const over = pick("Over 48.5");
  const under = pick("Under 49.5");
  const spread = pick("Nebraska Cornhuskers -20.5", { bet_type: "spread" });
  assert.deepEqual([...conflictingWagers([over, under, spread])], [over, under]);
});

test("agreement, other games, other sports, and unknown selections are not conflicts", () => {
  const wagers = [pick("Over 48.5"), pick("Over 49.5"),
    pick("Under 48.5", { event_id: "other" }),
    pick("Under 48.5", { sport: "nfl" }), pick("Unknown")];
  assert.equal(conflictingWagers(wagers).size, 0);
});

test("flags opposing teams within spreads and moneylines, without mixing markets", () => {
  for (const bet_type of ["spread", "moneyline"]) {
    const home = pick(`Nebraska Cornhuskers${bet_type === "spread" ? " -20.5" : ""}`, { bet_type });
    const away = pick(`Akron Zips${bet_type === "spread" ? " +20.5" : ""}`, { bet_type });
    assert.deepEqual([...conflictingWagers([home, away])], [home, away]);
  }
  assert.equal(conflictingWagers([
    pick("Nebraska Cornhuskers -20.5", { bet_type: "spread" }),
    pick("Akron Zips", { bet_type: "moneyline" }),
  ]).size, 0);
  assert.equal(conflictingWagers([]).size, 0);
});

test("groups the 25 primary system evaluations by display sport", () => {
  const grouped = groupEvaluations([
    { system_id: "a", sport: "mlb" },
    { system_id: "b", sport: "ncaaf" },
    { system_id: "c", sport: "nfl" },
  ]);
  assert.deepEqual(Object.keys(grouped), ["MLB", "College football", "NFL"]);
  assert.equal(grouped.MLB[0].system_id, "a");
});

test("uses explicit operator-facing labels for every evaluation status", () => {
  assert.equal(statusLabel("qualified"), "Qualified");
  assert.equal(statusLabel("no_match", "today"), "No match today");
  assert.equal(statusLabel("no_match", "tomorrow"), "No match tomorrow");
  assert.equal(statusLabel("no_match", "upcoming"), "No upcoming match");
  assert.equal(statusLabel("no_slate", "today"), "No games today");
  assert.equal(statusLabel("no_slate", "upcoming"), "No upcoming games");
  assert.equal(statusLabel("unable_to_evaluate"), "Unable to evaluate");
  assert.equal(statusLabel("disabled"), "Disabled");
});

test("builds systems API queries and safely parses bookmarked timeframes", () => {
  assert.equal(apiPaths.systems("today"), "/api/systems?timeframe=today");
  assert.equal(apiPaths.systems("upcoming"), "/api/systems?timeframe=upcoming");
  assert.equal(parseTimeframe("tomorrow"), "tomorrow");
  assert.equal(parseTimeframe("garbage"), "today");
});
