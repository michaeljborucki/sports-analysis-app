/**
 * Sharp books (spec §1: `sharp` marks these and nothing else). Their column
 * headers get a `--sharp-20` tint; prices inside are treated like any other.
 */
const SHARP_BOOKS: ReadonlySet<string> = new Set([
  "pinnacle",
  "circasports",
  "circa",
  "betonlineag",
  "lowvig",
]);

export function isSharpBook(bookKey: string): boolean {
  return SHARP_BOOKS.has(bookKey);
}

/** Header-cell class for a book column: sharp books get the lilac tint. */
export function bookHeaderTint(bookKey: string): string | undefined {
  return SHARP_BOOKS.has(bookKey) ? "bg-[var(--sharp-20)]" : undefined;
}

/**
 * Sentence-case a market label from lib/sports ("Run Line" → "Run line",
 * "F5 Total" → "F5 total"). Acronyms and tokens with digits ("F5", "1H",
 * "ML", "NRFI") are left alone.
 */
export function sentenceCaseLabel(label: string): string {
  return label
    .split(" ")
    .map((w, i) => (i > 0 && /^[A-Z][a-z]+$/.test(w) ? w.toLowerCase() : w))
    .join(" ");
}
