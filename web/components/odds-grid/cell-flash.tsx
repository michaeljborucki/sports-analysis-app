"use client";
import { useEffect, useRef } from "react";

/**
 * Flashes a yellow backdrop on value change, decaying exponentially over ~4.5s.
 * Skips the initial mount (no flash when a cell first appears, only when its
 * value actually changes from one number to another).
 */
export function CellFlash({
  value,
  children,
}: {
  value: number;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const last = useRef<number | null>(null);
  // Hold the in-flight flash so we can cancel it before starting the next one.
  // Without this, LIVE mode (a price tick ~every second) stacks a fresh 4.5s
  // animation on every change while the previous ones are never released —
  // and with `fill: forwards` those finished animations stay retained rather
  // than GC'd. Over hours × hundreds of cells that leaks tens of thousands of
  // Animation objects and eventually OOMs the tab.
  const anim = useRef<Animation | null>(null);

  useEffect(() => {
    if (last.current !== null && last.current !== value && ref.current) {
      anim.current?.cancel();
      // No `fill` — the final keyframe is fully transparent, which already
      // matches the element's resting background, so the animation can be
      // discarded the instant it finishes (nothing to hold forward).
      anim.current = ref.current.animate(
        [
          { backgroundColor: "rgba(245,165,36,0.45)", offset: 0 },
          { backgroundColor: "rgba(245,165,36,0.30)", offset: 0.12 },
          { backgroundColor: "rgba(245,165,36,0.14)", offset: 0.35 },
          { backgroundColor: "rgba(245,165,36,0.05)", offset: 0.65 },
          { backgroundColor: "rgba(245,165,36,0.00)", offset: 1 },
        ],
        { duration: 4500, easing: "linear" }
      );
    }
    last.current = value;
  }, [value]);

  // Cancel any in-flight flash when the cell unmounts (grid re-renders swap
  // cells constantly as games/markets change) so nothing dangles.
  useEffect(() => {
    return () => anim.current?.cancel();
  }, []);

  return (
    <span
      ref={ref}
      className="inline-block px-1.5 py-0.5 rounded-sm -mx-0.5"
    >
      {children}
    </span>
  );
}
