"use client";
import { ErrorBanner, formatAgeShort } from "@/components/ui";

/**
 * Escalation for badly stale grids (> 5 min). Mild staleness is already
 * shown by the header's <Freshness>, so this only fires when the fetcher
 * looks stuck.
 */
export function StaleBanner({ staleSeconds }: { staleSeconds: number }) {
  if (staleSeconds <= 300) return null;
  return (
    <ErrorBanner
      title={
        <>
          Prices haven&apos;t updated in{" "}
          <span className="tabular">{formatAgeShort(staleSeconds)}</span>. The
          fetcher may be stuck or the data source is set to Latest.
        </>
      }
    />
  );
}
