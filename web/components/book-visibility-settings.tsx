"use client";
import { useMemo } from "react";
import clsx from "clsx";

import { BOOKS, BOOK_ORDER, DEFAULT_VISIBLE_BOOKS, type Region } from "@/lib/books";
import { BookLogo } from "@/components/book-logo";


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

  function toggle(key: string) {
    const next = new Set(value);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }
  function setAll(keys: string[]) {
    onChange(new Set(keys));
  }

  return (
    <div className="border border-border-subtle rounded-md bg-bg-0 overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3 bg-bg-1 border-b border-border-subtle">
        <span className="text-sm font-semibold text-text-1">Visible Books</span>
        <span className="text-[11px] text-text-3 tabular">
          {shown} / {total} enabled · click Save at the top to persist
        </span>
        <div className="ml-auto flex items-center gap-2 text-xs">
          <button
            onClick={() => setAll(BOOK_ORDER)}
            className="text-accent hover:underline"
          >
            All
          </button>
          <span className="text-text-3">·</span>
          <button
            onClick={() => setAll([])}
            className="text-text-2 hover:text-text-1"
          >
            None
          </button>
          <span className="text-text-3">·</span>
          <button
            onClick={() => setAll(DEFAULT_VISIBLE_BOOKS)}
            className="text-text-2 hover:text-text-1"
          >
            Defaults
          </button>
        </div>
      </div>

      {REGIONS.map(r => {
        const keys = byRegion[r.key];
        if (keys.length === 0) return null;
        return (
          <div
            key={r.key}
            className="px-4 py-3 border-b border-border-subtle last:border-b-0"
          >
            <div className="pb-2 text-[10px] uppercase tracking-wider text-text-3">
              {r.label} · {keys.length}
            </div>
            <div className="grid grid-cols-3 gap-1">
              {keys.map(key => {
                const info = BOOKS[key];
                const on = value.has(key);
                return (
                  <button
                    key={key}
                    onClick={() => toggle(key)}
                    className={clsx(
                      "flex items-center gap-2 h-8 px-2 rounded-sm text-left",
                      "text-xs transition-colors",
                      on
                        ? "bg-bg-2 text-text-1"
                        : "bg-transparent text-text-2 hover:bg-bg-2/50"
                    )}
                  >
                    <span
                      className={clsx(
                        "inline-flex w-3.5 h-3.5 rounded-sm border items-center justify-center text-[9px] shrink-0",
                        on ? "bg-accent border-accent text-bg-0" : "border-text-3"
                      )}
                    >
                      {on && "✓"}
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
    </div>
  );
}
