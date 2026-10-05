"use client";
import clsx from "clsx";

import { useIsMounted } from "@/lib/use-is-mounted";

export function formatAgeShort(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86_400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86_400)}d`;
}

/**
 * The one freshness indicator (spec §4). Neutral when fresh, `stale` rose
 * when older than `staleAfter` seconds. `what` names the data ("Prices",
 * "Accounts") so the age is never ambiguous.
 */
export function Freshness({
  ageSeconds,
  staleAfter = 120,
  what = "Prices",
  className,
}: {
  ageSeconds: number | null | undefined;
  staleAfter?: number;
  what?: string;
  className?: string;
}) {
  const mounted = useIsMounted();
  if (!mounted || ageSeconds == null || Number.isNaN(ageSeconds)) return null;
  const age = Math.max(0, Math.floor(ageSeconds));
  const stale = age > staleAfter;
  return (
    <span
      title={stale ? `${what} are ${formatAgeShort(age)} old. Results may be out of date.` : `${what} updated ${formatAgeShort(age)} ago`}
      className={clsx(
        "inline-flex items-center gap-1.5 text-[length:var(--fs-12)] whitespace-nowrap",
        stale ? "text-stale" : "text-text-3",
        className,
      )}
    >
      <span aria-hidden className={clsx("inline-block h-1.5 w-1.5 rounded-full", stale ? "bg-stale" : "bg-text-3")} />
      {stale ? (
        <>{what} <span className="tabular">{formatAgeShort(age)}</span> old</>
      ) : (
        <>Updated <span className="tabular">{formatAgeShort(age)}</span> ago</>
      )}
    </span>
  );
}
