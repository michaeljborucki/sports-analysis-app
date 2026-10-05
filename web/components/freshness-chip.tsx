"use client";
import useSWR from "swr";

import { apiPaths, type FetcherStatus } from "@/lib/api";
import { Freshness } from "@/components/ui";

/**
 * Price-cache freshness for scanner pages, from /api/health (shared SWR key,
 * so requests dedupe). Thin wrapper over the shared <Freshness>.
 */
export function FreshnessChip({
  staleAfterSeconds = 300,
  className,
}: {
  staleAfterSeconds?: number;
  className?: string;
}) {
  const { data } = useSWR<FetcherStatus>(apiPaths.health, {
    refreshInterval: 15_000,
  });
  const age = data?.last_fetch_at
    ? (Date.now() - new Date(data.last_fetch_at).getTime()) / 1000
    : null;
  return (
    <Freshness
      ageSeconds={age}
      staleAfter={staleAfterSeconds}
      what="Prices"
      className={className}
    />
  );
}
