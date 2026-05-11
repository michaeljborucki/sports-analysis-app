"use client";
import clsx from "clsx";
import { RefreshCw } from "lucide-react";

/**
 * Manual refresh trigger for SWR-backed pages.
 *
 * Wire it up with the `mutate` function from `useSWR`:
 *   const { mutate, isValidating } = useSWR(...);
 *   <RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />
 *
 * Always cache-only — re-reads whatever the backend has cached without
 * triggering a live API pull. Background fetchers (Odds API, coral33)
 * keep the cache fresh on their own polling cadence.
 */
export function RefreshButton({
  onRefresh,
  isValidating,
}: {
  onRefresh: () => void;
  isValidating: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onRefresh}
      disabled={isValidating}
      aria-label="Refresh"
      title="Re-read the cache"
      className={clsx(
        "inline-flex items-center gap-2 h-8 px-3 rounded-md text-xs font-medium",
        "bg-bg-1 border border-border-subtle text-text-2 hover:text-text-1",
        "transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-70"
      )}
    >
      <RefreshCw
        size={12}
        aria-hidden
        className={clsx(
          "transition-transform",
          isValidating && "animate-spin"
        )}
      />
      <span>Refresh</span>
    </button>
  );
}
