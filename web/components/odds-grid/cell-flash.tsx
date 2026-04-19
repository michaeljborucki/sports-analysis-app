"use client";
import { useEffect, useRef } from "react";

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
    if (last.current !== null && last.current !== value) {
      const el = ref.current;
      if (el) {
        el.animate(
          [
            { backgroundColor: "rgba(245,165,36,0.35)" },
            { backgroundColor: "rgba(245,165,36,0)" },
          ],
          { duration: 30_000, easing: "ease-out" }
        );
      }
    }
    last.current = value;
  }, [value]);
  return (
    <span ref={ref} className="inline-block px-1 rounded-sm">
      {children}
    </span>
  );
}
