"use client";
import clsx from "clsx";

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
    <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
      {tabs.map(t => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={clsx(
            "px-3 py-1 text-xs tracking-wide uppercase transition-colors rounded-sm",
            value === t.key
              ? "bg-bg-2 text-text-1"
              : "text-text-2 hover:text-text-1"
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
