"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { animate } from "motion";

/**
 * Flashes a cell background when its numeric value changes. Green on
 * up-ticks, red on down-ticks, neutral skip on first render.
 *
 * Perf notes (matters at 100+ rows re-rendering on every SWR revalidation):
 *   - Tracks the previous value in a `useRef` — no setState, no re-render.
 *   - Bails in three cases: (1) first mount (prev is undefined), (2) value
 *     unchanged, (3) either value non-finite. This is the dominant case
 *     on most refetches — SWR hands back the same payload — so we avoid
 *     ever touching `animate()` for the majority of cells.
 *   - Respects `prefers-reduced-motion`: the effect still runs, but
 *     `animate()` is skipped.
 *   - Uses Motion One's `animate()` (imported from `motion`) rather than
 *     Framer's React motion components so there is zero React overhead
 *     per frame — it mutates the DOM node directly.
 *
 * The component is intentionally an inline <span> so it can drop into any
 * table cell without layout shift.
 */
export function AnimatedPrice({
  value,
  className,
  children,
  /**
   * Optional override: normally an increase is green and a decrease is
   * red. For cells where "higher" is worse (e.g. hold %), pass
   * `invert=true` to swap colors.
   */
  invert = false,
}: {
  /** The scalar the cell represents; change triggers the flash. */
  value: number;
  className?: string;
  children: ReactNode;
  invert?: boolean;
}) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const prevRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const node = ref.current;
    const prev = prevRef.current;
    prevRef.current = value;

    // First render: no flash. Just record the starting value.
    if (prev === undefined) return;
    if (!node) return;
    if (!Number.isFinite(value) || !Number.isFinite(prev)) return;
    if (value === prev) return;

    // Respect reduced-motion. We still updated prevRef above so the next
    // real change is detected correctly.
    if (
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ) {
      return;
    }

    const up = invert ? value < prev : value > prev;
    // Use the Wave 1 RGB triple tokens so the flash colour matches the
    // table's magnitude ramp. Computed from CSS custom properties so a
    // future theme swap follows along.
    const styles = getComputedStyle(document.documentElement);
    const rgb = up
      ? styles.getPropertyValue("--price-up-rgb").trim() || "44 180 89"
      : styles.getPropertyValue("--price-down-rgb").trim() || "229 72 77";

    // Background flash: 0 → 0.3 → 0 over 400ms. Motion One mutates the
    // inline style property directly — no React re-renders, no layout.
    animate(
      node,
      {
        backgroundColor: [
          "rgba(0,0,0,0)",
          `rgba(${rgb.replace(/\s+/g, ",")}, 0.3)`,
          "rgba(0,0,0,0)",
        ],
      },
      { duration: 0.4, ease: "easeOut" },
    );
  }, [value, invert]);

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
