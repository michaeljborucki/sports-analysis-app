"use client";
import { use } from "react";
import { notFound } from "next/navigation";
import useSWR from "swr";
import { apiPaths, type OddsResponse } from "@/lib/api";
import { intervals } from "@/lib/swr";
import { isSportKey, getSport } from "@/lib/sports";
import { PropsMatrix } from "@/components/props-matrix";
import { StaleIndicator } from "@/components/stale-indicator";
import { StaleBanner } from "@/components/stale-banner";
import { RefreshButton } from "@/components/refresh-button";
import { OddsGridSkeleton } from "@/components/skeletons";
import { BackendUnreachable, PageHeader } from "@/components/ui";

export default function PropsPage({
  params,
}: {
  params: Promise<{ sport: string }>;
}) {
  const { sport } = use(params);
  if (!isSportKey(sport)) notFound();
  const sportMeta = getSport(sport);

  const { data, error, isLoading, isValidating, mutate } = useSWR<OddsResponse>(
    apiPaths.props(sport),
    { refreshInterval: intervals.odds }
  );

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        className="mb-0"
        title={`${sportMeta.label} props`}
        description="Player props, over and under, book by book."
        meta={data ? <StaleIndicator staleSeconds={data.stale_seconds ?? 0} /> : undefined}
        actions={<RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />}
      />

      {data && <StaleBanner staleSeconds={data.stale_seconds ?? 0} />}

      {error && <BackendUnreachable error={error} />}
      {isLoading && !data && <OddsGridSkeleton />}
      {data && <PropsMatrix sport={sport} games={data.games ?? []} />}
    </div>
  );
}
