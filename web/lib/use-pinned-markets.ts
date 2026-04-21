"use client";
import { useCallback, useEffect, useState } from "react";
import type { SportKey } from "./sports";

/**
 * Per-sport pin state for the Props matrix. The tab bar shows pinned markets
 * as first-class tabs and hides the rest behind a "More" popover. Pin state
 * is pure user preference and is NOT filtered by Settings — a market that
 * the user pinned and later disabled stays in the pin list (so re-enabling
 * restores it), it's just filtered out at render time.
 *
 * Seeded on first visit per sport with sensible defaults so the UI is
 * usable immediately.
 */

const STORAGE_PREFIX = "props_pinned_markets_";

/**
 * First-visit defaults. These are the "make NBA usable with 4 tabs"
 * starting set — power users customize from there. Empty array = fall back
 * to everything-unpinned (user sees only "More (N)").
 */
const DEFAULT_PINS: Record<SportKey, string[]> = {
  nba: [
    "player_points",
    "player_rebounds",
    "player_assists",
    "player_threes",
  ],
  mlb: [
    "pitcher_strikeouts",
    "batter_hits",
    "batter_total_bases",
    "batter_runs_scored",
  ],
  nhl: [
    "player_points",
    "player_goals",
    "player_assists",
    "player_shots_on_goal",
  ],
  // NCAA baseball shares key-shape with MLB; same defaults are a reasonable
  // guess, but if the fetcher never yields matching keys the intersection
  // in the matrix silently produces an empty pin set (everything in More).
  baseball_ncaa: [
    "pitcher_strikeouts",
    "batter_hits",
    "batter_total_bases",
    "batter_runs_scored",
  ],
  // Tennis has no player-prop tier — nothing to pin.
  tennis: [],
};

function storageKey(sport: SportKey): string {
  return `${STORAGE_PREFIX}${sport}`;
}

export function usePinnedMarkets(sport: SportKey) {
  // Start with defaults so SSR / first render is deterministic; sync from
  // localStorage on mount (mirrors the useVisibleBooks pattern).
  const [pins, setPins] = useState<string[]>(() => DEFAULT_PINS[sport] ?? []);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(false);
    try {
      const raw = window.localStorage.getItem(storageKey(sport));
      if (raw === null) {
        // First visit for this sport — seed defaults into storage so future
        // reads are a simple read-what-you-wrote path.
        const seeded = DEFAULT_PINS[sport] ?? [];
        window.localStorage.setItem(storageKey(sport), JSON.stringify(seeded));
        setPins(seeded);
      } else {
        const parsed = JSON.parse(raw) as unknown;
        if (Array.isArray(parsed) && parsed.every(v => typeof v === "string")) {
          setPins(parsed as string[]);
        }
      }
    } catch {
      // Corrupt storage → fall back to defaults for this session without
      // overwriting (the user may fix it themselves).
      setPins(DEFAULT_PINS[sport] ?? []);
    }
    setHydrated(true);
  }, [sport]);

  const persist = useCallback(
    (next: string[]) => {
      setPins(next);
      try {
        window.localStorage.setItem(storageKey(sport), JSON.stringify(next));
      } catch {}
    },
    [sport]
  );

  const toggle = useCallback(
    (marketKey: string) => {
      // Pin order matters — we render pins in the order they were added so
      // a user's "my favorites first" list stays stable.
      const idx = pins.indexOf(marketKey);
      if (idx === -1) persist([...pins, marketKey]);
      else persist(pins.filter(k => k !== marketKey));
    },
    [pins, persist]
  );

  const isPinned = useCallback(
    (marketKey: string) => pins.includes(marketKey),
    [pins]
  );

  return { pins, toggle, isPinned, hydrated };
}
