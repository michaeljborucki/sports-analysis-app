import type { components } from "@/types/api";

export type OddsResponse = components["schemas"]["OddsResponse"];
export type PicksResponse = components["schemas"]["PicksResponse"];
export type Game = components["schemas"]["Game"];
export type Pick = components["schemas"]["Pick"];
export type Market = components["schemas"]["Market"];
export type MarketOutcome = components["schemas"]["MarketOutcome"];
export type BookPrice = components["schemas"]["BookPrice"];
export type FetcherStatus = components["schemas"]["FetcherStatus"];
export type PickTier = components["schemas"]["PickTier"];

export const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const apiPaths = {
  health: "/api/health",
  sports: "/api/sports",
  odds: (sport: string) => `/api/odds/${sport}`,
  props: (sport: string) => `/api/props/${sport}`,
  picks: (sport: string) => `/api/picks/${sport}`,
  arbitrage: (books: string[]) =>
    `/api/arbitrage${books.length ? `?books=${books.join(",")}` : ""}`,
  lowHold: (books: string[], maxHoldPct = 1) => {
    const qs = new URLSearchParams();
    if (books.length) qs.set("books", books.join(","));
    qs.set("max_hold_pct", String(maxHoldPct));
    return `/api/low-hold?${qs.toString()}`;
  },
  freeBets: (
    books: string[],
    minFreeOdds = 100,
    freeBetBooks: string[] = [],
  ) => {
    const qs = new URLSearchParams();
    if (books.length) qs.set("books", books.join(","));
    // `free_bet_books` locks the free-bet leg to specific promo-eligible
    // books (e.g. coral33 = where the user has a free-bet credit). Hedge
    // leg is free to use any of `books`. Empty = no promo restriction.
    if (freeBetBooks.length) qs.set("free_bet_books", freeBetBooks.join(","));
    qs.set("min_free_odds", String(minFreeOdds));
    return `/api/free-bets?${qs.toString()}`;
  },
  ev: (
    books: string[],
    opts: {
      minEv?: number;
      maxLongshotOdds?: number;
      staleSeconds?: number;
      maxResults?: number;
      sort?: "desc" | "asc" | "bidir";
      wagerFilter?: "any" | "straight" | "parlay";
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (books.length) qs.set("books", books.join(","));
    qs.set("min_ev", String(opts.minEv ?? 1));
    if (opts.maxResults != null) qs.set("max_results", String(opts.maxResults));
    if (opts.sort) qs.set("sort", opts.sort);
    qs.set("max_longshot_odds", String(opts.maxLongshotOdds ?? 800));
    qs.set("stale_seconds", String(opts.staleSeconds ?? 300));
    if (opts.wagerFilter && opts.wagerFilter !== "any") {
      qs.set("wager_filter", opts.wagerFilter);
    }
    return `/api/ev?${qs.toString()}`;
  },
  profitBoost: (
    books: string[],
    opts: {
      boostPct?: number;
      boostBooks?: string[];
      minConversion?: number;
      minBoostOdds?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    qs.set("boost_pct", String(opts.boostPct ?? 30));
    if (books.length) qs.set("books", books.join(","));
    if (opts.boostBooks && opts.boostBooks.length) {
      qs.set("boost_books", opts.boostBooks.join(","));
    }
    qs.set("min_conversion", String(opts.minConversion ?? 0));
    if (opts.minBoostOdds != null) {
      qs.set("min_boost_odds", String(opts.minBoostOdds));
    }
    return `/api/profit_boost?${qs.toString()}`;
  },
  dashboard: (books: string[] = []) =>
    `/api/dashboard${books.length ? `?books=${books.join(",")}` : ""}`,
  settings: "/api/settings",
  coral33Refresh: "/api/coral33/refresh",
  coral33Status: "/api/coral33/status",
} as const;

export type ArbResponse = components["schemas"]["ArbResponse"];
export type ArbOpportunity = components["schemas"]["ArbOpportunity"];
export type ArbSide = components["schemas"]["ArbSide"];
export type LowHoldResponse = components["schemas"]["LowHoldResponse"];
export type LowHoldOpportunity = components["schemas"]["LowHoldOpportunity"];
export type FreeBetResponse = components["schemas"]["FreeBetResponse"];
export type FreeBetOpportunity = components["schemas"]["FreeBetOpportunity"];
export type FreeBetLeg = components["schemas"]["FreeBetLeg"];
export type EVResponse = components["schemas"]["EVResponse"];
export type EVOpportunity = components["schemas"]["EVOpportunity"];

// Profit-boost types are not yet in the generated openapi schema (run the
// schema regen task to pick them up). Defined inline as a structural mirror
// of the backend `ProfitBoostOpportunity` model.
//
// Conversion-style scanner: applies the boost to one leg and hedges the
// other at a different book — same shape as free_bet (two priced legs +
// per-$100 hedge ratio + conversion %), with the boost replacing the
// "free bet" treatment of leg A.
export interface ProfitBoostBoostLeg {
  outcome_name: string;
  book: string;
  point: number | null;
  original_price_american: number;
  boosted_price_american: number;
}

export interface ProfitBoostHedgeLeg {
  outcome_name: string;
  book: string;
  point: number | null;
  price_american: number;
}

export interface ProfitBoostOpportunity {
  sport_key: string;
  event_id: string;
  home_team: string;
  away_team: string;
  commence_time: string;
  market_kind: string;
  point: number | null;
  /** Guaranteed profit as % of total stake (boost stake + hedge stake). */
  conversion_pct: number;
  /** Implied-prob hold of the boosted pair. Negative = profitable pair. */
  hold_pct: number;
  /** Boost percentage applied (e.g., 30.0). */
  boost_pct: number;
  /** Hedge stake per $100 placed on the boosted leg. */
  hedge_stake_per_100_boost: number;
  boost_leg: ProfitBoostBoostLeg;
  hedge_leg: ProfitBoostHedgeLeg;
}

export interface ProfitBoostResponse {
  opportunities: ProfitBoostOpportunity[];
  scanned_at: string;
  boost_pct: number;
  min_conversion_pct: number;
}
export type DashboardResponse = components["schemas"]["DashboardResponse"];
export type SportSummary = components["schemas"]["SportSummary"];
export type SettingsResponse = components["schemas"]["SettingsResponse"];
export type SportOption = components["schemas"]["SportOption"];
export type TierOption = components["schemas"]["TierOption"];
export type MarketOption = components["schemas"]["MarketOption"];
export type SettingsPayload = components["schemas"]["SettingsPayload"];

export function refreshEventUrl(eventId: string): string {
  return `/api/refresh/${encodeURIComponent(eventId)}`;
}
