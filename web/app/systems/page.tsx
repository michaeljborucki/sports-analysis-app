/* Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V4
 * genre: modern-minimal · macrostructure: Workbench · tone: technical/utilitarian
 * theme: existing betting-site dark tokens · enrichment: none
 */
"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import clsx from "clsx";

import { RefreshButton } from "@/components/refresh-button";
import { SystemsWorkbench } from "@/components/systems/systems-workbench";
import { apiPaths } from "@/lib/api";
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
  const searchParams = useSearchParams();
  const timeframe = parseTimeframe(searchParams.get("timeframe"));
  const { data, error, isLoading, isValidating, mutate } = useSWR<SystemsResponse>(
    apiPaths.systems(timeframe),
    { refreshInterval: 60_000 },
  );

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <header className="flex min-w-0 items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex min-w-0 items-baseline gap-3">
            <h1 className="text-[28px] leading-[34px] font-semibold tracking-tight text-text-1">Systems</h1>
            <span className="hidden text-xs text-text-3 sm:inline">forward-looking system signals</span>
          </div>
          <p className="mt-1 text-xs text-text-2">
            {data ? `${data.requested_date} · ${data.timezone} · evaluated ${new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" }).format(new Date(data.evaluated_at))}` : `Evaluating ${timeframe === "upcoming" ? "all upcoming" : timeframe === "tomorrow" ? "tomorrow’s" : "today’s"} cached MLB, college football, and NFL slate`}
          </p>
        </div>
        <RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />
      </header>

      <div className="flex w-fit rounded-md border border-border-subtle bg-bg-1 p-1" role="group" aria-label="Systems timeframe">
        {TIMEFRAMES.map(option => (
          <Link
            key={option.value}
            href={`/systems?timeframe=${option.value}`}
            aria-current={timeframe === option.value ? "page" : undefined}
            className={clsx(
              "inline-flex min-h-8 items-center rounded px-3 text-xs font-medium transition-colors",
              timeframe === option.value
                ? "bg-accent text-bg-0"
                : "text-text-2 hover:bg-bg-2 hover:text-text-1",
            )}
          >
            {option.label}
          </Link>
        ))}
      </div>

      {error && (
        <div role="alert" className="rounded-md border border-price-down/40 bg-price-down/10 px-4 py-3 text-sm text-price-down">Systems API is unavailable. Check the FastAPI server logs.</div>
      )}
      {isLoading && !data && <SystemsLoading />}
      {data && <SystemsWorkbench data={data} timeframe={timeframe} />}
    </div>
  );
}

function SystemsPageLoading() {
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <div className="h-16 animate-pulse rounded-md bg-bg-1" />
      <SystemsLoading />
    </div>
  );
}

function SystemsLoading() {
  return (
    <div aria-label="Loading systems" className="grid gap-4">
      <div className="h-20 animate-pulse rounded-md border border-border-subtle bg-bg-1" />
      <div className="h-48 animate-pulse rounded-md border border-border-subtle bg-bg-1" />
      <div className="h-72 animate-pulse rounded-md border border-border-subtle bg-bg-1" />
    </div>
  );
}
