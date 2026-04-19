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
  dashboard: "/api/dashboard",
} as const;

export type ArbResponse = components["schemas"]["ArbResponse"];
export type ArbOpportunity = components["schemas"]["ArbOpportunity"];
export type ArbSide = components["schemas"]["ArbSide"];
export type DashboardResponse = components["schemas"]["DashboardResponse"];
export type SportSummary = components["schemas"]["SportSummary"];

export function refreshEventUrl(eventId: string): string {
  return `/api/refresh/${encodeURIComponent(eventId)}`;
}
