"use client";
import clsx from "clsx";

export interface SegmentedOption<T extends string> {
  value: T;
  label: React.ReactNode;
  /** Optional count shown in mono after the label. */
  count?: number | string | null;
  title?: string;
  disabled?: boolean;
}

/**
 * The one segmented control (spec §4). Active segment = text-1 on bg-2 —
 * the "current location" treatment, never a hue.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = "md",
  ariaLabel,
  className,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (v: T) => void;
  size?: "sm" | "md";
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={clsx(
        "inline-flex items-center gap-0.5 rounded-lg bg-bg-1 p-[3px] border border-border-subtle",
        className,
      )}
    >
      {options.map(o => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={o.title}
            disabled={o.disabled}
            onClick={() => onChange(o.value)}
            className={clsx(
              "inline-flex items-baseline gap-1.5 rounded-md font-medium transition-colors whitespace-nowrap",
              size === "sm" ? "h-7 px-2.5 text-[length:var(--fs-12)] items-center" : "h-8 px-3 text-[length:var(--fs-13)] items-center",
              active ? "bg-bg-2 text-text-1 shadow-[0_1px_0_rgb(0_0_0/0.25)]" : "text-text-2 hover:text-text-1",
              o.disabled && "opacity-40 cursor-not-allowed",
            )}
          >
            {o.label}
            {o.count != null && o.count !== "" && (
              <span className={clsx("tabular text-[length:var(--fs-11)]", active ? "text-edge" : "text-text-3")}>
                {o.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
