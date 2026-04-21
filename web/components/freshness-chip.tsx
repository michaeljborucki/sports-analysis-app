"use client";
import useSWR from "swr";
import clsx from "clsx";

import { apiPaths, type FetcherStatus } from "@/lib/api";
import { useIsMounted } from "@/lib/use-is-mounted";

/**
 * Compact "updated N min ago" chip for scanner pages.
 *
 * Reads cache age from /api/health (shared SWR key with FetcherToggle, so the
 * request dedupes). Tints warning when the cache is past `staleAfterSeconds`
 * — a scanner-side signal that 0-opps results may just mean the cache is old.
 */
export function FreshnessChip({
  staleAfterSeconds = 300,
  className,
}: {
  staleAfterSeconds?: number;
  className?: string;
}) {
  const mounted = useIsMounted();
  const { data } = useSWR<FetcherStatus>(apiPaths.health, {
    refreshInterval: 15_000,
  });

  // Render nothing server-side so the cache-age text doesn't hydrate-mismatch
  // (Date.now() differs between SSR and client).
  if (!mounted || !data?.last_fetch_at) {
    return null;
  }

  const fetchedAt = new Date(data.last_fetch_at);
  const ageMs = Date.now() - fetchedAt.getTime();
  const ageSec = Math.max(0, Math.floor(ageMs / 1000));
  const stale = ageSec > staleAfterSeconds;

  const label = formatAge(ageSec);
  const title = stale
    ? `Cache is ${label} old — scanner data may be empty. Toggle the fetcher or refresh coral33 to pull fresh prices.`
    : `Cache last refreshed ${label} ago.`;

  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1.5 px-2 h-7 rounded-md border text-[10px] uppercase tracking-wider tabular",
        stale
          ? "border-flash/50 text-flash bg-flash/10"
          : "border-border-subtle text-text-3 bg-bg-1",
        className,
      )}
    >
      <span
        className={clsx(
          "inline-block w-1.5 h-1.5 rounded-full",
          stale ? "bg-flash" : "bg-price-up",
        )}
      />
      {stale ? "Stale" : "Fresh"} · {label}
    </span>
  );
}

function formatAge(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${Math.round(sec / 3600)}h`;
}
