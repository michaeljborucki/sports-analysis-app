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

  useEffect(() => {
    if (last.current !== null && last.current !== value && ref.current) {
      ref.current.animate(
        [
          { backgroundColor: "rgba(245,165,36,0.45)", offset: 0 },
          { backgroundColor: "rgba(245,165,36,0.30)", offset: 0.12 },
          { backgroundColor: "rgba(245,165,36,0.14)", offset: 0.35 },
          { backgroundColor: "rgba(245,165,36,0.05)", offset: 0.65 },
          { backgroundColor: "rgba(245,165,36,0.00)", offset: 1 },
        ],
        { duration: 4500, easing: "linear", fill: "forwards" }
      );
    }
    last.current = value;
  }, [value]);

  return (
    <span
      ref={ref}
      className="inline-block px-1.5 py-0.5 rounded-sm -mx-0.5"
    >
      {children}
    </span>
  );
}
