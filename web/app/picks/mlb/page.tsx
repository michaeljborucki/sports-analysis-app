"use client";
import useSWR from "swr";
import { apiPaths, type PicksResponse } from "@/lib/api";
import { intervals } from "@/lib/swr";
import { PicksTable } from "@/components/picks-table";

export default function PicksMlbPage() {
  const { data, error, isLoading } = useSWR<PicksResponse>(apiPaths.picks, {
    refreshInterval: intervals.picks,
  });

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold">MLB Picks</h1>
          {data?.bet_card_date && (
            <span className="text-xs text-text-3 tabular">
              Bet card: {data.bet_card_date}
            </span>
          )}
          {data?.status === "no_picks_today" && (
            <span className="text-xs text-flash">No picks today</span>
          )}
        </div>
        <div className="text-xs text-text-3">
          Agent: <span className="text-text-1">baseball-agents</span>
        </div>
      </header>

      {error && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && (
        <div className="text-text-2 text-sm">Loading picks…</div>
      )}
      {data && <PicksTable picks={data.picks ?? []} />}
    </div>
  );
}
