"use client";
import useSWR from "swr";
import { useMemo } from "react";

import { apiPaths, type DashboardResponse, type EVResponse } from "@/lib/api";
import { RefreshButton } from "@/components/refresh-button";
import { FreshnessChip } from "@/components/freshness-chip";
import { BackendUnreachable, PageHeader } from "@/components/ui";
import { useVisibleBooks } from "@/lib/use-visible-books";

import { BestNowPanel } from "@/components/dashboard/best-now-panel";
import { SportRail } from "@/components/dashboard/sport-rail";
import { SystemStats } from "@/components/dashboard/system-stats";
import { StartingSoonCard } from "@/components/dashboard/starting-soon-card";

/**
 * Dashboard — the first screen on every app open.
 *
 *   Hero      "Best right now": top arbs (from /api/dashboard) merged with
 *             top +EV (from /api/ev). Real data only.
 *   Side      Starting soon (next 3h).
 *   Rail      Per-sport game counts, linking to odds.
 *   Footer    API quota, fetcher, cache age.
 */
export default function DashboardPage() {
  const { visible } = useVisibleBooks();
  const booksKey = useMemo(() => [...visible].sort(), [visible]);

  const { data, error, isLoading, isValidating, mutate } =
    useSWR<DashboardResponse>(apiPaths.dashboard(booksKey), {
      refreshInterval: 30_000,
    });

  // Top +EV isn't in the dashboard response, so /api/ev is fetched alongside
  // with the same books list and cadence.
  const { data: evData, mutate: evMutate, isValidating: evValidating } =
    useSWR<EVResponse>(
      apiPaths.ev(booksKey, { minEv: 1, maxLongshotOdds: 800 }),
      { refreshInterval: 30_000 },
    );

  const refreshAll = () => {
    mutate();
    evMutate();
  };

  return (
    <div>
      <PageHeader
        title="Dashboard"
        meta={<FreshnessChip />}
        actions={
          <RefreshButton
            onRefresh={refreshAll}
            isValidating={isValidating || evValidating}
          />
        }
      />
      <div className="flex flex-col gap-5">

      {error && <BackendUnreachable error={error} />}

      {isLoading && !data && (
        <div aria-label="Loading dashboard" className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="skeleton h-80 rounded-lg" />
          <div className="skeleton h-80 rounded-lg" />
        </div>
      )}

      {data && (
        <>
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <BestNowPanel arbs={data.top_arbs} evs={evData?.opportunities} />
            <StartingSoonCard games={data.upcoming_games} onRefresh={refreshAll} />
          </div>
          <SportRail sports={data.sports} />
          <SystemStats data={data} />
        </>
      )}
      </div>
    </div>
  );
}
