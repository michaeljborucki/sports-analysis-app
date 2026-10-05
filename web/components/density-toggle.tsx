"use client";

import { Segmented } from "@/components/ui";
import { DENSITY_CYCLE, useDensity, type Density } from "@/lib/use-density";

/**
 * Row-density selector. Writes localStorage + <html data-density> so the
 * CSS density vars cascade. The ⌘⇧D cycle hotkey is installed globally by
 * ShortcutOverlayMount, not here, so it isn't double-bound.
 */
const LABELS: Record<Density, string> = {
  compact: "Compact",
  comfortable: "Comfortable",
  spacious: "Spacious",
};

const HINTS: Record<Density, string> = {
  compact: "Tight rows, fit more on screen.",
  comfortable: "Default row rhythm.",
  spacious: "Larger rows, easier scanning.",
};

export function DensityToggle() {
  const { density, setDensity } = useDensity();

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
      <div className="min-w-0 flex-1">
        <div className="text-[length:var(--fs-14)] font-medium text-text-1">Row density</div>
        <div className="text-[length:var(--fs-12)] text-text-3">
          Row height across every table. Shortcut{" "}
          <kbd className="rounded border border-border-subtle bg-bg-2 px-1 font-sans text-[length:var(--fs-11)] text-text-2">
            ⌘ Shift D
          </kbd>
        </div>
      </div>
      <Segmented<Density>
        size="sm"
        ariaLabel="Row density"
        value={density}
        onChange={setDensity}
        options={DENSITY_CYCLE.map(mode => ({ value: mode, label: LABELS[mode], title: HINTS[mode] }))}
      />
    </div>
  );
}
