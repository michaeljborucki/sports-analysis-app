"use client";
import clsx from "clsx";

import {
  EDGE_MODES,
  MODE_LABEL,
  MODE_LONG_LABEL,
  type EdgeMode,
} from "@/lib/edges";

/** Mode-pill accent by kind. */
const MODE_STYLES: Record<EdgeMode, { on: string; off: string }> = {
  arb: {
    on: "bg-price-up/15 text-price-up border-price-up/50",
    off: "text-text-2 border-border-subtle hover:text-price-up",
  },
  low_hold: {
    on: "bg-accent/15 text-accent border-accent/50",
    off: "text-text-2 border-border-subtle hover:text-accent",
  },
  ev: {
    on: "bg-violet-accent/15 text-violet-accent border-violet-accent/50",
    off: "text-text-2 border-border-subtle hover:text-violet-accent",
  },
  free_bet: {
    on: "bg-flash/15 text-flash border-flash/50",
    off: "text-text-2 border-border-subtle hover:text-flash",
  },
  profit_boost: {
    // Reuse the +EV violet — profit boost IS a +EV scan with a price
    // transform, so visually grouping them keeps the cognitive load down.
    on: "bg-violet-accent/15 text-violet-accent border-violet-accent/50",
    off: "text-text-2 border-border-subtle hover:text-violet-accent",
  },
};

/**
 * Single-select mode-chip group. Exactly one mode is active at any time;
 * clicking a different chip switches (radio-style). Clicking the already-
 * active chip is a no-op — never deselect to an empty state.
 */
export function ModeToggle({
  value,
  onChange,
}: {
  value: Set<EdgeMode>;
  onChange: (next: Set<EdgeMode>) => void;
}) {
  function select(mode: EdgeMode) {
    if (value.has(mode) && value.size === 1) return;
    onChange(new Set([mode]));
  }

  return (
    <div className="inline-flex items-center gap-1.5" role="radiogroup">
      {EDGE_MODES.map(mode => {
        const on = value.has(mode);
        const s = MODE_STYLES[mode];
        return (
          <button
            key={mode}
            type="button"
            onClick={() => select(mode)}
            title={
              on
                ? `${MODE_LONG_LABEL[mode]} — active`
                : `Switch to ${MODE_LONG_LABEL[mode]}`
            }
            role="radio"
            aria-checked={on}
            className={clsx(
              "inline-flex items-center gap-1.5 px-2.5 h-8 rounded-md border text-[11px] font-semibold uppercase tracking-wider transition-colors",
              on ? s.on : s.off,
            )}
          >
            {MODE_LABEL[mode]}
            <span
              className={clsx(
                "inline-block w-1.5 h-1.5 rounded-full",
                on ? "bg-current" : "bg-transparent border border-current",
              )}
              aria-hidden
            />
          </button>
        );
      })}
    </div>
  );
}
