"use client";
import useSWR from "swr";
import { apiPaths, type OddsResponse } from "@/lib/api";
import { intervals } from "@/lib/swr";
import { OddsGrid } from "@/components/odds-grid";
import { StaleIndicator } from "@/components/stale-indicator";
import { StaleBanner } from "@/components/stale-banner";
import { OddsGridSkeleton } from "@/components/skeletons";

export default function OddsMlbPage() {
  const { data, error, isLoading } = useSWR<OddsResponse>(apiPaths.odds, {
    refreshInterval: intervals.odds,
  });

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">MLB Odds</h1>
          <span className="text-xs text-text-3 tabular">
            {new Date().toLocaleDateString([], { month: "short", day: "numeric" })}
          </span>
        </div>
        <div>
          {data && <StaleIndicator staleSeconds={data.stale_seconds ?? 0} />}
        </div>
      </header>

      {data && <StaleBanner staleSeconds={data.stale_seconds ?? 0} />}

      {error && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && <OddsGridSkeleton />}
      {data && <OddsGrid games={data.games ?? []} />}
    </div>
  );
}
