"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { animate } from "motion";

/**
 * Flashes a cell background when its numeric value changes. The flash is a
 * neutral white wash (`--flash-wash`, spec §1) regardless of direction —
 * price moves are not colored. No flash on first render.
 *
 * Perf notes (matters at 100+ rows re-rendering on every SWR revalidation):
 *   - Tracks the previous value in a `useRef` — no setState, no re-render.
 *   - Bails on first mount, unchanged value, or non-finite values — the
 *     dominant case on most refetches.
 *   - Respects `prefers-reduced-motion`.
 *   - Uses Motion's `animate()` which mutates the DOM node directly — zero
 *     React overhead per frame.
 */
export function AnimatedPrice({
  value,
  className,
  children,
  /**
   * Kept for backward compatibility. The flash is direction-neutral now,
   * so this no longer changes anything.
   */
  invert: _invert = false,
}: {
  /** The scalar the cell represents; change triggers the flash. */
  value: number;
  className?: string;
  children: ReactNode;
  invert?: boolean;
}) {
  void _invert;
  const ref = useRef<HTMLSpanElement | null>(null);
  const prevRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const node = ref.current;
    const prev = prevRef.current;
    prevRef.current = value;

    if (prev === undefined) return;
    if (!node) return;
    if (!Number.isFinite(value) || !Number.isFinite(prev)) return;
    if (value === prev) return;

    if (
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ) {
      return;
    }

    // --flash-wash is rgb(var(--text-rgb) / 0.14); build it from the triple
    // so Motion gets plain rgba() keyframes it can interpolate.
    const triple =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--text-rgb")
        .trim()
        .replace(/\s+/g, ",") || "241,240,237";

    animate(
      node,
      {
        backgroundColor: [
          `rgba(${triple},0)`,
          `rgba(${triple},0.14)`,
          `rgba(${triple},0)`,
        ],
      },
      { duration: 0.4, ease: "easeOut" },
    );
  }, [value]);

  return (
    <span
      ref={ref}
      className={className}
      style={{ display: "inline-block", borderRadius: 3, padding: "0 2px" }}
    >
      {children}
    </span>
  );
}
