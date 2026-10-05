import { bookInfo } from "@/lib/books";
import { SPORTS, isSportKey } from "@/lib/sports";

/** Books that feed the unified ledger (synced or imported). */
export const LEDGER_BOOKS: { value: string; label: string }[] = [
  { value: "coral33", label: "Coral33" },
  { value: "kalshi", label: "Kalshi" },
  { value: "polymarket", label: "Polymarket" },
  { value: "imported", label: "Imported" },
];

export function bookName(key: string | null | undefined): string {
  if (!key) return "—";
  return LEDGER_BOOKS.find(b => b.value === key)?.label ?? bookInfo(key).name;
}

export function sportName(key: string | null | undefined): string {
  if (!key) return "—";
  return isSportKey(key) ? SPORTS[key].label : key;
}

/** Market keys arrive snake_case ("totals_1st_5_innings"); show them readable. */
export function marketName(key: string | null | undefined): string {
  if (!key) return "—";
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
