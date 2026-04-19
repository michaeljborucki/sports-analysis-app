"use client";
import clsx from "clsx";
import { bookInfo } from "@/lib/books";

/**
 * Branded sportsbook pill.
 *  - mode="header":  monochrome in column headers (subdued)
 *  - mode="full":    full brand color (for best-cell / filter)
 *  - mode="label":   inline under a best price (small, full color)
 */
export function BookLogo({
  bookKey,
  mode = "header",
  className,
}: {
  bookKey: string;
  mode?: "header" | "full" | "label";
  className?: string;
}) {
  const info = bookInfo(bookKey);

  if (mode === "header") {
    return (
      <span
        title={info.name}
        className={clsx(
          "inline-flex items-center justify-center h-5 min-w-[30px] px-1.5 rounded-sm",
          "text-[10px] font-bold tracking-wide uppercase",
          "bg-bg-2 text-text-2 border border-border-subtle",
          className
        )}
      >
        {info.label}
      </span>
    );
  }

  if (mode === "label") {
    return (
      <span
        title={info.name}
        className={clsx(
          "inline-flex items-center justify-center h-4 min-w-[26px] px-1 rounded-sm",
          "text-[9px] font-bold tracking-wide uppercase",
          className
        )}
        style={{ background: info.bg, color: info.fg }}
      >
        {info.label}
      </span>
    );
  }

  // full
  return (
    <span
      title={info.name}
      className={clsx(
        "inline-flex items-center justify-center h-5 min-w-[34px] px-1.5 rounded-sm",
        "text-[11px] font-bold tracking-wide uppercase",
        className
      )}
      style={{ background: info.bg, color: info.fg }}
    >
      {info.label}
    </span>
  );
}
