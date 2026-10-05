"use client";
import { use } from "react";
import { notFound } from "next/navigation";
import useSWR from "swr";
import { apiPaths, type OddsResponse } from "@/lib/api";
import { intervals } from "@/lib/swr";
import { isSportKey, getSport } from "@/lib/sports";
import { OddsGrid } from "@/components/odds-grid";
import { StaleIndicator } from "@/components/stale-indicator";
import { StaleBanner } from "@/components/stale-banner";
import { OddsGridSkeleton } from "@/components/skeletons";
import { RefreshButton } from "@/components/refresh-button";
import { BackendUnreachable, PageHeader } from "@/components/ui";

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

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        className="mb-0"
        title={`${sportMeta.label} odds`}
        description="Best price per side across your visible books. Click a game for alt lines."
        meta={data ? <StaleIndicator staleSeconds={data.stale_seconds ?? 0} /> : undefined}
        actions={<RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />}
      />

      {data && <StaleBanner staleSeconds={data.stale_seconds ?? 0} />}

      {error && <BackendUnreachable error={error} />}
      {isLoading && !data && <OddsGridSkeleton />}
      {data && <OddsGrid games={data.games ?? []} sport={sportMeta} />}
    </div>
  );
}
