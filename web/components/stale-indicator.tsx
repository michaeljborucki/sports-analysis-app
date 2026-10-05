"use client";
import { Freshness } from "@/components/ui";

/** Freshness for grids that report their own `stale_seconds`. */
export function StaleIndicator({ staleSeconds }: { staleSeconds: number }) {
  return <Freshness ageSeconds={staleSeconds} staleAfter={90} what="Prices" />;
}
