"use client";
import { useEffect, useRef } from "react";

// Resolved once per page: the neutral price-change wash (spec §1 — a white
// wash at 14%, never amber). Read from the token so the TSX holds no color
// literal; falls back to the var reference if computed styles aren't ready.
let flashWash: string | null = null;
function resolveFlashWash(): string {
  if (flashWash) return flashWash;
  const v =
    typeof window !== "undefined"
      ? getComputedStyle(document.documentElement).getPropertyValue("--flash-wash").trim()
      : "";
  flashWash = v || "var(--flash-wash)";
  return flashWash;
}

/**
 * Flashes a neutral wash on value change, decaying over ~4.5s. Skips the
 * initial mount (no flash when a cell first appears, only when its value
 * actually changes from one number to another).
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
      // No `fill` — the final keyframe is transparent, which already matches
      // the element's resting background, so the animation can be discarded
      // the instant it finishes (nothing to hold forward). The ease-out curve
      // approximates the previous exponential decay.
      anim.current = ref.current.animate(
        [
          { backgroundColor: resolveFlashWash() },
          { backgroundColor: "transparent" },
        ],
        { duration: 4500, easing: "cubic-bezier(0.15, 0.7, 0.3, 1)" }
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
    <span ref={ref} className="inline-block px-1.5 py-0.5 rounded-sm -mx-0.5">
      {children}
    </span>
  );
}
