"use client";
import clsx from "clsx";

export type LiveStatus = "all" | "pre" | "live";

const OPTIONS: { key: LiveStatus; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pre", label: "Pre" },
  { key: "live", label: "Live" },
];

/**
 * Small 3-way segmented control: All / Pre-match / Live.
 *
 * Filters results by a `commence_time` field:
 *   pre  → commence_time > now
 *   live → commence_time <= now
 *   all  → no filter
 */
export function LiveStatusFilter({
  value,
  onChange,
}: {
  value: LiveStatus;
  onChange: (v: LiveStatus) => void;
}) {
  return (
    <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
      {OPTIONS.map(o => (
        <button
          key={o.key}
          onClick={() => onChange(o.key)}
          className={clsx(
            "px-3 py-1 text-xs tracking-wide uppercase transition-colors rounded-sm inline-flex items-center gap-1.5",
            value === o.key
              ? "bg-bg-2 text-text-1"
              : "text-text-2 hover:text-text-1"
          )}
        >
          {o.key === "live" && (
            <span
              aria-hidden
              className={clsx(
                "inline-block w-1.5 h-1.5 rounded-full",
                value === "live" ? "bg-price-down live-dot" : "bg-text-3"
              )}
            />
          )}
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function matchesLiveFilter(
  commenceTime: string,
  filter: LiveStatus,
  nowMs: number = Date.now()
): boolean {
  if (filter === "all") return true;
  const ts = new Date(commenceTime).getTime();
  const isLive = ts <= nowMs;
  return filter === "live" ? isLive : !isLive;
}
