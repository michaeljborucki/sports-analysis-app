"use client";
import { use } from "react";
import { notFound } from "next/navigation";
import useSWR from "swr";
import { useIsMounted } from "@/lib/use-is-mounted";
import { apiPaths, type OddsResponse } from "@/lib/api";
import { intervals } from "@/lib/swr";
import { isSportKey, getSport } from "@/lib/sports";
import { OddsGrid } from "@/components/odds-grid";
import { StaleIndicator } from "@/components/stale-indicator";
import { StaleBanner } from "@/components/stale-banner";
import { OddsGridSkeleton } from "@/components/skeletons";
import { RefreshButton } from "@/components/refresh-button";

export default function OddsPage({
  params,
}: {
  params: Promise<{ sport: string }>;
}) {
  const { sport } = use(params);
  if (!isSportKey(sport)) notFound();
  const sportMeta = getSport(sport);

  const { data, error, isLoading, isValidating, mutate } = useSWR<OddsResponse>(
    apiPaths.odds(sport),
    { refreshInterval: intervals.odds }
  );
  const mounted = useIsMounted();

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">
            {sportMeta.label} Odds
          </h1>
          <span className="text-xs text-text-3 tabular">
            {mounted
              ? new Date().toLocaleDateString([], {
                  month: "short",
                  day: "numeric",
                })
              : null}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {data && <StaleIndicator staleSeconds={data.stale_seconds ?? 0} />}
          <RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />
        </div>
      </header>

      {data && <StaleBanner staleSeconds={data.stale_seconds ?? 0} />}

      {error && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && <OddsGridSkeleton />}
      {data && <OddsGrid games={data.games ?? []} sport={sportMeta} />}
    </div>
  );
}
