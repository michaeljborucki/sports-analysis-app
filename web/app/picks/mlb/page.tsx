"use client";
import useSWR from "swr";
import { apiPaths, type PicksResponse } from "@/lib/api";
import { intervals } from "@/lib/swr";
import { PicksTable } from "@/components/picks-table";
import { PicksTableSkeleton } from "@/components/skeletons";
import { RefreshButton } from "@/components/refresh-button";

export default function PicksMlbPage() {
  const { data, error, isLoading, isValidating, mutate } = useSWR<PicksResponse>(
    apiPaths.picks,
    { refreshInterval: intervals.picks }
  );

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">MLB Picks</h1>
          {data?.bet_card_date && (
            <span className="text-xs text-text-3 tabular">
              Bet card: {data.bet_card_date}
            </span>
          )}
          {data?.status === "no_picks_today" && (
            <span className="text-xs text-flash">No picks today</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <div className="text-xs text-text-3">
            Agent: <span className="text-text-1">baseball-agents</span>
          </div>
          <RefreshButton
            onRefresh={() => mutate()}
            isValidating={isValidating}
          />
        </div>
      </header>

      {error && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && <PicksTableSkeleton />}
      {data && <PicksTable picks={data.picks ?? []} />}
    </div>
  );
}
