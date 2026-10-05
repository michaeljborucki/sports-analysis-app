"use client";
import clsx from "clsx";
import { RefreshCw } from "lucide-react";

/**
 * Manual refresh for SWR-backed pages: re-reads the backend cache (never
 * triggers a paid fetch). Wire to `mutate` from useSWR.
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
      title="Re-read the cache"
      className={clsx(
        "inline-flex items-center gap-2 h-8 px-3 rounded-md text-[length:var(--fs-13)] font-medium",
        "border border-border-subtle bg-bg-1 text-text-2 hover:text-text-1 hover:bg-bg-2",
        "transition-colors disabled:cursor-wait disabled:opacity-70",
      )}
    >
      <RefreshCw size={13} aria-hidden className={clsx(isValidating && "animate-spin")} />
      Refresh
    </button>
  );
}
