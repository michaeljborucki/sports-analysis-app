import assert from "node:assert/strict";
import test from "node:test";

import { groupSoccerGames } from "../soccer-leagues.ts";
import { SPORTS } from "../sports.ts";

test("groups soccer games by league while prioritizing live leagues and sorting each league by kickoff", () => {
  const groups = groupSoccerGames([
    {
      event_id: "epl-late",
      league_key: "soccer_epl",
      league_title: "EPL",
      is_live: true,
      commence_time: "2026-08-21T18:00:00Z",
    },
    {
      event_id: "mls-early",
      league_key: "soccer_mls",
      league_title: "MLS",
      is_live: false,
      commence_time: "2026-08-21T12:00:00Z",
    },
    {
      event_id: "other",
      is_live: false,
      commence_time: "2026-08-21T10:00:00Z",
    },
    {
      event_id: "epl-early",
      league_key: "soccer_epl",
      league_title: "EPL",
      is_live: false,
      commence_time: "2026-08-21T16:00:00Z",
    },
  ]);

  assert.deepEqual(groups.map((group) => group.title), ["EPL", "MLS", "Other Soccer"]);
  assert.deepEqual(groups[0].games.map((game) => game.event_id), ["epl-early", "epl-late"]);
  assert.equal(groups[0].hasLive, true);
  assert.equal(groups[0].earliestKickoff, "2026-08-21T16:00:00Z");
});

test("orders otherwise-equal leagues by key", () => {
  const groups = groupSoccerGames([
    {
      event_id: "league-z-game",
      league_key: "league-z",
      league_title: "Same League",
      is_live: false,
      commence_time: "2026-08-21T12:00:00Z",
    },
    {
      event_id: "league-a-game",
      league_key: "league-a",
      league_title: "Same League",
      is_live: false,
      commence_time: "2026-08-21T12:00:00Z",
    },
  ]);

  assert.deepEqual(groups.map((group) => group.key), ["league-a", "league-z"]);
});

test("orders equal-kickoff games deterministically by event id across permutations", () => {
  const games = [
    { event_id: "z-game", league_key: "soccer_epl", league_title: "EPL", is_live: false, commence_time: "2026-08-21T12:00:00Z" },
    { event_id: "a-game", league_key: "soccer_epl", league_title: "EPL", is_live: false, commence_time: "2026-08-21T12:00:00Z" },
  ];

  for (const input of [games, [...games].reverse()]) {
    assert.deepEqual(
      groupSoccerGames(input).flatMap((group) => group.games.map((game) => game.event_id)),
      ["a-game", "z-game"],
    );
  }
});

test("exposes alternate soccer spreads for market selection", () => {
  const spread = SPORTS.soccer.marketGroups.find((market) => market.label === "Spread");

  assert.equal(spread?.altKey, "alternate_spreads");
});
