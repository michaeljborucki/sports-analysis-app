"use client";
import { Segmented } from "@/components/ui";
import { sentenceCaseLabel } from "./grid-style";

/**
 * Market switcher for the odds grid — the shared `Segmented` control with
 * sentence-case labels. Scrolls horizontally (no wrap) when a sport has many
 * period markets (NBA quarters, NFL halves).
 */
export function MarketTabs<T extends string>({
  value,
  onChange,
  tabs,
}: {
  value: T;
  onChange: (k: T) => void;
  tabs: { key: T; label: string }[];
}) {
  return (
    <div className="max-w-full overflow-x-auto no-scrollbar">
      <Segmented
        ariaLabel="Market"
        value={value}
        onChange={onChange}
        options={tabs.map(t => ({ value: t.key, label: sentenceCaseLabel(t.label) }))}
      />
    </div>
  );
}
