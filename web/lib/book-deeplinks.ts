/**
 * Per-book deeplink registry — STUB.
 *
 * To add a real deeplink for a book, write a function under `BOOK_DEEPLINKS`
 * keyed by the book's registry key that returns the bet-slip URL (or event
 * page URL, if a slip URL isn't available). Return `null` if the opportunity
 * can't be deeplinked (e.g. the market_kind isn't supported by the book's
 * URL schema).
 *
 * The workbench uses `getBookDeeplink(op, leg)` to render per-leg "Open in
 * {book}" buttons; a null return disables the button with a tooltip.
 *
 * No production URLs are configured yet — every book currently returns
 * null. This file is the single place to extend.
 */
import type { EdgeOpportunity, EdgeLeg } from "@/lib/edges";

type DeeplinkFn = (op: EdgeOpportunity, leg: EdgeLeg) => string | null;

/**
 * Registry. Keys match the book's `key` field in `lib/books.ts`. Leave
 * books out of the map to have them automatically fall through to the
 * disabled state.
 */
export const BOOK_DEEPLINKS: Record<string, DeeplinkFn> = {
  // Example when you're ready to wire one up:
  //
  // draftkings: (op, leg) => {
  //   // Construct whatever URL shape DraftKings supports.
  //   return `https://sportsbook.draftkings.com/event/${op.event_id}`;
  // },
};

export function getBookDeeplink(
  op: EdgeOpportunity,
  leg: EdgeLeg,
): string | null {
  const fn = BOOK_DEEPLINKS[leg.book];
  return fn ? fn(op, leg) : null;
}
