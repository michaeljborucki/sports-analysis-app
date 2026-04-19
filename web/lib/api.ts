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

const BASE =
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
  lowHold: (books: string[], maxHoldPct = 2.5) => {
    const qs = new URLSearchParams();
    if (books.length) qs.set("books", books.join(","));
    qs.set("max_hold_pct", String(maxHoldPct));
    return `/api/low-hold?${qs.toString()}`;
  },
  freeBets: (books: string[], minFreeOdds = 100) => {
    const qs = new URLSearchParams();
    if (books.length) qs.set("books", books.join(","));
    qs.set("min_free_odds", String(minFreeOdds));
    return `/api/free-bets?${qs.toString()}`;
  },
  dashboard: "/api/dashboard",
} as const;

export type ArbResponse = components["schemas"]["ArbResponse"];
export type ArbOpportunity = components["schemas"]["ArbOpportunity"];
export type ArbSide = components["schemas"]["ArbSide"];
export type LowHoldResponse = components["schemas"]["LowHoldResponse"];
export type LowHoldOpportunity = components["schemas"]["LowHoldOpportunity"];
export type FreeBetResponse = components["schemas"]["FreeBetResponse"];
export type FreeBetOpportunity = components["schemas"]["FreeBetOpportunity"];
export type FreeBetLeg = components["schemas"]["FreeBetLeg"];
export type DashboardResponse = components["schemas"]["DashboardResponse"];
export type SportSummary = components["schemas"]["SportSummary"];

export function refreshEventUrl(eventId: string): string {
  return `/api/refresh/${encodeURIComponent(eventId)}`;
}
