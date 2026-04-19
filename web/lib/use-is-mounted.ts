"use client";
import { useEffect, useState } from "react";

/**
 * Returns `false` on the server / first client render, `true` after mount.
 *
 * Use this to gate rendering of values that differ between server and client
 * (e.g. `new Date().toLocaleDateString(...)` or `toLocaleTimeString(...)`,
 * which render with the server's TZ/locale during SSR but the browser's on
 * hydration — causing a hydration mismatch).
 *
 * Pattern:
 *   const mounted = useIsMounted();
 *   return <span>{mounted ? new Date().toLocaleDateString() : null}</span>;
 */
export function useIsMounted(): boolean {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted;
}
