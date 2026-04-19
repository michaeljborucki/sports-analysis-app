"use client";
import clsx from "clsx";

export function StaleIndicator({ staleSeconds }: { staleSeconds: number }) {
  const stale = staleSeconds > 90;
  const label =
    staleSeconds < 5
      ? "live"
      : staleSeconds < 60
      ? `${staleSeconds}s old`
      : `${Math.floor(staleSeconds / 60)}m ${staleSeconds % 60}s old`;
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 text-xs tabular",
        stale ? "text-flash" : "text-text-2"
      )}
    >
      <span
        className={clsx(
          "inline-block w-1.5 h-1.5 rounded-full",
          stale ? "bg-flash" : "bg-price-up"
        )}
      />
      Updated {label}
    </span>
  );
}
