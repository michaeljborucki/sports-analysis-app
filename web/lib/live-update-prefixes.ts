const ODDS_DERIVED_PREFIXES = [
  "/api/ev",
  "/api/arbitrage",
  "/api/low-hold",
  "/api/free-bets",
  "/api/profit_boost",
  "/api/odds",
  "/api/props",
  "/api/dashboard",
] as const;

const TYPE_TO_PREFIXES: Record<string, readonly string[]> = {
  tick: ODDS_DERIVED_PREFIXES,
  odds_changed: ODDS_DERIVED_PREFIXES,
  direct_books_changed: ODDS_DERIVED_PREFIXES,
  heartbeat: [],
};

export const LIVE_UPDATE_EVENT_TYPES = [
  "tick",
  "odds_changed",
  "direct_books_changed",
] as const;

/** Empty means intentionally ignored; null means compatibility fallback. */
export function prefixesForLiveEvent(type: string): readonly string[] | null {
  return TYPE_TO_PREFIXES[type] ?? null;
}
