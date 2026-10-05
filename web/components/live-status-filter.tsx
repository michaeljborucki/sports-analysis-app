"use client";
import { Segmented } from "@/components/ui";

export type LiveStatus = "all" | "pre" | "live";

const OPTIONS: { key: LiveStatus; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pre", label: "Upcoming" },
  { key: "live", label: "Live" },
];

/**
 * 3-way filter: All / Upcoming / Live.
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
    <Segmented<LiveStatus>
      size="sm"
      ariaLabel="Game status"
      value={value}
      onChange={onChange}
      options={OPTIONS.map(o => ({
        value: o.key,
        label:
          o.key === "live" ? (
            <span className="inline-flex items-center gap-1.5">
              <span
                aria-hidden
                className={value === "live" ? "live-dot" : "inline-block h-1.5 w-1.5 rounded-full bg-text-3"}
              />
              Live
            </span>
          ) : (
            o.label
          ),
      }))}
    />
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
