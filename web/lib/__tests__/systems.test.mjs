import assert from "node:assert/strict";
import test from "node:test";

import { groupEvaluations, parseTimeframe, statusLabel } from "../systems.ts";
import { apiPaths } from "../api.ts";

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
