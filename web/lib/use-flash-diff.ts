"use client";

/**
 * Build a stable cell key from (event_id, book, market, outcome, point)
 * — matches the backend primary key tuple so diff keys are consistent
 * across re-fetches.
 */
export function cellKey(parts: {
  event_id: string;
  bookmaker_key: string;
  market_key: string;
  outcome_name: string;
  point: number | null;
}): string {
  return [
    parts.event_id,
    parts.bookmaker_key,
    parts.market_key,
    parts.outcome_name,
    parts.point ?? "",
  ].join("|");
}
