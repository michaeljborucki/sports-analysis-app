"use client";
import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import { Check, ChevronRight } from "lucide-react";

import { BOOKS, BOOK_ORDER, DEFAULT_VISIBLE_BOOKS, type Region } from "@/lib/books";
import { BookLogo } from "@/components/book-logo";

// localStorage key for the expand/collapse state of the book panel. Kept
// separate from the selection itself so a collapsed panel doesn't hide
// pending edits the user made before scrolling away.
const EXPANDED_STORAGE_KEY = "settings_book_visibility_expanded_v1";


const REGIONS: { key: Region; label: string }[] = [
  { key: "US", label: "United States" },
  { key: "UK", label: "United Kingdom" },
  { key: "EU", label: "Europe" },
  { key: "ROW", label: "Other" },
];


/**
 * Book visibility panel rendered on the Settings page. Controlled component:
 * the *pending* visible set is owned by the Settings page and committed to
 * the backend on the Save click. Persisting here is intentionally NOT
 * automatic — it rides the same save flow as the sport/market toggles, so a
 * hard refresh restores whatever the server has, not whatever local state
 * happened to be lingering.
 */
export function BookVisibilitySettings({
  value,
  onChange,
}: {
  value: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  const byRegion = useMemo(() => {
    const out: Record<Region, string[]> = { US: [], UK: [], EU: [], ROW: [] };
    for (const key of BOOK_ORDER) {
      const info = BOOKS[key];
      if (info) out[info.region].push(key);
    }
    return out;
  }, []);

  const shown = value.size;
  const total = BOOK_ORDER.length;

  // Collapsed by default — the 60-book grid takes ~60% of the Settings page
  // and is rarely the thing the user is editing. Hydrate from localStorage
  // after mount so SSR doesn't mismatch on the expanded state.
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(EXPANDED_STORAGE_KEY);
      if (raw === "1") setExpanded(true);
    } catch {}
  }, []);
  useEffect(() => {
    try {
      window.localStorage.setItem(EXPANDED_STORAGE_KEY, expanded ? "1" : "0");
    } catch {}
  }, [expanded]);

  const dirtyHint = ". Save at the top to persist.";

  function toggle(key: string) {
    const next = new Set(value);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }
  function setAll(keys: string[]) {
    onChange(new Set(keys));
  }

  const quiet =
    "h-7 rounded-md px-2 text-[length:var(--fs-12)] font-medium text-text-2 transition-colors hover:bg-bg-2 hover:text-text-1";

  return (
    <section className="overflow-hidden rounded-lg border border-border-subtle bg-bg-1">
      <div
        className={clsx(
          "flex h-11 items-center gap-3 px-4",
          expanded && "border-b border-border-subtle",
        )}
      >
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          className="flex items-center gap-2 text-left"
          title={expanded ? "Collapse book list" : "Expand book list"}
          aria-expanded={expanded}
        >
          <ChevronRight
            aria-hidden
            size={14}
            className={clsx("text-text-3 transition-transform", expanded && "rotate-90")}
          />
          <h2 className="text-[length:var(--fs-14)] font-semibold text-text-1">Visible books</h2>
        </button>
        <span className="text-[length:var(--fs-12)] text-text-3">
          <span className="tabular">{shown}</span> of <span className="tabular">{total}</span> shown
          {expanded && dirtyHint}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button type="button" onClick={() => setAll(BOOK_ORDER)} className={quiet}>
            All
          </button>
          <button type="button" onClick={() => setAll([])} className={quiet}>
            None
          </button>
          <button type="button" onClick={() => setAll(DEFAULT_VISIBLE_BOOKS)} className={quiet}>
            Defaults
          </button>
        </div>
      </div>

      {expanded && REGIONS.map(r => {
        const keys = byRegion[r.key];
        if (keys.length === 0) return null;
        return (
          <div
            key={r.key}
            className="border-b border-border-subtle px-4 py-3 last:border-b-0"
          >
            <div className="pb-2 text-[length:var(--fs-12)] text-text-3">
              {r.label} <span className="tabular">({keys.length})</span>
            </div>
            <div className="grid grid-cols-1 gap-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {keys.map(key => {
                const info = BOOKS[key];
                const on = value.has(key);
                return (
                  <button
                    type="button"
                    key={key}
                    onClick={() => toggle(key)}
                    aria-pressed={on}
                    className={clsx(
                      "flex h-8 items-center gap-2 rounded-md px-2 text-left text-[length:var(--fs-13)] transition-colors",
                      on ? "bg-bg-2 text-text-1" : "text-text-3 hover:bg-bg-2 hover:text-text-2",
                    )}
                  >
                    <span
                      className={clsx(
                        "inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                        on ? "border-text-1 bg-text-1 text-bg-0" : "border-text-3",
                      )}
                    >
                      {on && <Check size={11} strokeWidth={3} aria-hidden />}
                    </span>
                    <BookLogo bookKey={key} mode="label" />
                    <span className="truncate">{info.name}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </section>
  );
}
