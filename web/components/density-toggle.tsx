"use client";

import clsx from "clsx";

import { DENSITY_CYCLE, useDensity, type Density } from "@/lib/use-density";

/**
 * Three-chip density selector. Writes to localStorage + the <html>
 * data-density attribute so the CSS density vars cascade. Also installs
 * the global Cmd/Ctrl+Shift+D cycle hotkey for the duration it is
 * mounted (Settings page is the canonical mount point).
 */
const LABELS: Record<Density, string> = {
  compact: "Compact",
  comfortable: "Comfortable",
  spacious: "Spacious",
};

const HINTS: Record<Density, string> = {
  compact: "Tight rows — fit more on screen.",
  comfortable: "Default row rhythm.",
  spacious: "Larger rows — easier scanning.",
};

export function DensityToggle() {
  const { density, setDensity } = useDensity({ installHotkey: true });

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex flex-col">
          <span className="text-xs font-semibold text-text-1">Row density</span>
          <span className="text-[11px] text-text-3">
            Toggle row height across every table. Shortcut:{" "}
            <kbd className="tabular text-[10px] px-1 rounded-sm bg-bg-2 border border-border-subtle">
              ⌘/Ctrl + Shift + D
            </kbd>
          </span>
        </div>
      </div>
      <div
        role="radiogroup"
        aria-label="Row density"
        className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5 self-start"
      >
        {DENSITY_CYCLE.map(mode => {
          const active = mode === density;
          return (
            <button
              key={mode}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => setDensity(mode)}
              title={HINTS[mode]}
              className={clsx(
                "px-3 py-1 text-[11px] tabular rounded-sm transition-colors",
                active
                  ? "bg-bg-2 text-text-1"
                  : "text-text-2 hover:text-text-1",
              )}
            >
              {LABELS[mode]}
            </button>
          );
        })}
      </div>
    </div>
  );
}
