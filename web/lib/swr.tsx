"use client";
import { SWRConfig, type SWRConfiguration } from "swr";
import { fetchJson } from "./api";
import type { ReactNode } from "react";
import { useLiveUpdates } from "./use-live-updates";

const base: SWRConfiguration = {
  fetcher: fetchJson,
  // SSE push (see useLiveUpdates) is the single source of freshness.
  // Refocus revalidation would re-fire EVERY mounted hook on every tab
  // switch — a duplicate trigger that costs an avalanche of fetches with
  // no benefit. Keep it off.
  revalidateOnFocus: false,
  keepPreviousData: true,
  dedupingInterval: 5_000,
};

/**
 * Inner component that subscribes to the backend SSE stream. Must live
 * INSIDE `<SWRConfig>` so `useSWRConfig()` can access the same SWR
 * cache the rest of the app reads from.
 */
function LiveUpdatesBridge() {
  useLiveUpdates();
  return null;
}

export function SwrProvider({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={base}>
      <LiveUpdatesBridge />
      {children}
    </SWRConfig>
  );
}

export const intervals = {
  odds: 15_000,
  picks: 60_000,
  health: 30_000,
} as const;
