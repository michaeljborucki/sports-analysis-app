"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";

import { RefreshButton } from "@/components/refresh-button";
import { SystemsWorkbench } from "@/components/systems/systems-workbench";
import { ErrorBanner, PageHeader, Segmented } from "@/components/ui";
import { apiPaths } from "@/lib/api";
import { useIsMounted } from "@/lib/use-is-mounted";
import { parseTimeframe, type SystemsResponse, type SystemsTimeframe } from "@/lib/systems";

const TIMEFRAMES: { value: SystemsTimeframe; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "tomorrow", label: "Tomorrow" },
  { value: "upcoming", label: "Upcoming" },
];

export default function SystemsPage() {
  return (
    <Suspense fallback={<SystemsPageLoading />}>
      <SystemsPageInner />
    </Suspense>
  );
}

function SystemsPageInner() {
  const router = useRouter();
  const mounted = useIsMounted();
  const searchParams = useSearchParams();
  const timeframe = parseTimeframe(searchParams.get("timeframe"));
  const { data, error, isLoading, isValidating, mutate } = useSWR<SystemsResponse>(
    apiPaths.systems(timeframe),
    { refreshInterval: 60_000 },
  );

  const description = data ? (
    <>
      Slate for <span className="tabular">{data.requested_date}</span> in {data.timezone}
      {mounted && (
        <>
          , evaluated at{" "}
          <span className="tabular">
            {new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date(data.evaluated_at))}
          </span>
        </>
      )}
    </>
  ) : (
    `Evaluating ${timeframe === "upcoming" ? "all upcoming" : timeframe === "tomorrow" ? "tomorrow’s" : "today’s"} cached MLB, college football and NFL slate`
  );

  return (
    <div className="flex min-w-0 flex-col">
      <PageHeader
        title="Systems"
        description={description}
        inline={
          <Segmented<SystemsTimeframe>
            ariaLabel="Systems timeframe"
            value={timeframe}
            onChange={v => router.push(`/systems?timeframe=${v}`)}
            options={TIMEFRAMES}
          />
        }
        actions={<RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />}
      />

      {error && (
        <ErrorBanner
          tone="loss"
          title="The systems API is unavailable. Check the FastAPI server logs."
          details={String(error)}
          className="mb-5"
        />
      )}
      {isLoading && !data && <SystemsLoading />}
      {data && <SystemsWorkbench data={data} timeframe={timeframe} />}
    </div>
  );
}

function SystemsPageLoading() {
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <div className="skeleton h-16 rounded-lg" />
      <SystemsLoading />
    </div>
  );
}

function SystemsLoading() {
  return (
    <div aria-label="Loading systems" className="grid gap-4">
      <div className="skeleton h-20 rounded-lg" />
      <div className="skeleton h-48 rounded-lg" />
      <div className="skeleton h-72 rounded-lg" />
    </div>
  );
}
