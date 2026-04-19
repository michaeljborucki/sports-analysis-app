"use client";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import { isSportKey, type SportKey } from "./sports";

const STORAGE_KEY = "last_sport_v1";

/**
 * Resolves the current sport. Priority:
 *   1. URL second segment if it's a valid SportKey (the authoritative source
 *      when the user is on /odds/mlb, /picks/tennis, etc.).
 *   2. Last sport stored in localStorage (survives across global→per-sport
 *      navigation — e.g., you're on /arbitrage and click "Odds", you land
 *      on /odds/{lastSport} instead of always bouncing to MLB).
 *   3. "mlb" as the final fallback.
 *
 * Also writes the URL-derived sport back to localStorage when it's valid.
 */
export function useCurrentSport(): SportKey {
  const pathname = usePathname() ?? "";
  const parts = pathname.split("/").filter(Boolean);
  const fromPath: SportKey | null = isSportKey(parts[1] ?? "")
    ? (parts[1] as SportKey)
    : null;

  const [sticky, setSticky] = useState<SportKey>("mlb");

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored && isSportKey(stored)) setSticky(stored as SportKey);
    } catch {
      // swallow — localStorage may be disabled in some envs
    }
  }, []);

  useEffect(() => {
    if (fromPath) {
      try {
        window.localStorage.setItem(STORAGE_KEY, fromPath);
      } catch {}
      setSticky(fromPath);
    }
  }, [fromPath]);

  return fromPath ?? sticky;
}
