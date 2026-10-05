"use client";
import { Segmented, type SegmentedOption } from "@/components/ui";
import { EDGE_MODES, type EdgeMode } from "@/lib/edges";

/** Full, sentence-case mode names for the page header (spec §5). */
export const MODE_NAME: Record<EdgeMode, string> = {
  arb: "Arbitrage",
  low_hold: "Low hold",
  ev: "Positive EV",
  free_bet: "Free bet",
  profit_boost: "Profit boost",
};

/**
 * Single-select mode switch. Exactly one mode is active at any time;
 * clicking the already-active segment is a no-op — never deselect to empty.
 * `counts` shows a number on the segments the page has data for.
 */
export function ModeToggle({
  value,
  onChange,
  counts,
}: {
  value: Set<EdgeMode>;
  onChange: (next: Set<EdgeMode>) => void;
  counts?: Partial<Record<EdgeMode, number | null>>;
}) {
  const active = [...value][0] ?? "arb";
  const options: SegmentedOption<EdgeMode>[] = EDGE_MODES.map(mode => ({
    value: mode,
    label: MODE_NAME[mode],
    count: counts?.[mode] ?? null,
    title: mode === active ? `${MODE_NAME[mode]} is showing` : `Switch to ${MODE_NAME[mode]}`,
  }));
  return (
    <Segmented
      ariaLabel="Edge type"
      options={options}
      value={active}
      onChange={mode => {
        if (value.has(mode) && value.size === 1) return;
        onChange(new Set([mode]));
      }}
    />
  );
}
