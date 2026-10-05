import clsx from "clsx";

/**
 * Edge magnitude cell: a soft amber bar behind the mono number. Bar width is
 * value / max, clamped. Stale rows drop the bar and color in `stale`.
 */
export function EdgeBar({
  value,
  max,
  children,
  stale = false,
  className,
}: {
  value: number;
  max: number;
  children: React.ReactNode;
  stale?: boolean;
  className?: string;
}) {
  const pct = max > 0 ? Math.max(4, Math.min(100, (Math.abs(value) / max) * 100)) : 0;
  return (
    <span className={clsx("relative flex h-6 min-w-[88px] items-center", className)}>
      {!stale && value > 0 && (
        <span
          aria-hidden
          className="absolute inset-y-0 left-0 rounded-[3px] bg-[var(--edge-25)]"
          style={{ width: `${pct}%` }}
        />
      )}
      <span
        className={clsx(
          "tabular relative pl-2 font-semibold",
          stale ? "text-stale" : value > 0 ? "text-edge" : "text-text-2",
        )}
      >
        {children}
      </span>
    </span>
  );
}
