"use client";
import useSWR from "swr";
import { useIsMounted } from "@/lib/use-is-mounted";
import { apiPaths, type OddsResponse } from "@/lib/api";
import { intervals } from "@/lib/swr";
import { PropsTable } from "@/components/props-table";
import { StaleIndicator } from "@/components/stale-indicator";
import { RefreshButton } from "@/components/refresh-button";
import { OddsGridSkeleton } from "@/components/skeletons";

export default function PropsMlbPage() {
  const { data, error, isLoading, isValidating, mutate } = useSWR<OddsResponse>(
    apiPaths.props,
    { refreshInterval: intervals.odds }
  );
  const mounted = useIsMounted();

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">MLB Player Props</h1>
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

      {error && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && <OddsGridSkeleton />}
      {data && <PropsTable games={data.games ?? []} />}
    </div>
  );
}
