import assert from "node:assert/strict";
import test from "node:test";

import { prefixesForLiveEvent } from "../live-update-prefixes.ts";


test("typed odds changes target only odds-derived SWR keys", () => {
  for (const type of ["tick", "odds_changed", "direct_books_changed"]) {
    const prefixes = prefixesForLiveEvent(type);
    assert.ok(prefixes.includes("/api/odds"));
    assert.ok(prefixes.includes("/api/props"));
    assert.ok(prefixes.includes("/api/low-hold"));
    assert.equal(prefixes.includes("/api/coral33/accounts"), false);
    assert.equal(prefixes.includes("/api/settings"), false);
  }
});


test("heartbeat is ignored and unknown events request compatibility fallback", () => {
  assert.deepEqual(prefixesForLiveEvent("heartbeat"), []);
  assert.equal(prefixesForLiveEvent("future_event"), null);
});
