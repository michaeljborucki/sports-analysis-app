"use client";
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { BOOKS, DEFAULT_VISIBLE_BOOKS, bookInfo, type Region } from "@/lib/books";
import { BookLogo } from "./book-logo";

const REGIONS: { key: Region; label: string }[] = [
  { key: "US", label: "United States" },
  { key: "UK", label: "United Kingdom" },
  { key: "EU", label: "Europe" },
  { key: "ROW", label: "Other" },
];

export function BookFilter({
  availableBooks,
  visible,
  onToggle,
  onSetAll,
}: {
  availableBooks: string[];
  visible: Set<string>;
  onToggle: (key: string) => void;
  onSetAll: (keys: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node) &&
        btnRef.current &&
        !btnRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const availableSet = new Set(availableBooks);
  const shown = availableBooks.filter(b => visible.has(b)).length;
  const total = availableBooks.length;

  const byRegion: Record<Region, string[]> = { US: [], UK: [], EU: [], ROW: [] };
  for (const key of availableBooks) {
    const info = BOOKS[key] ?? bookInfo(key);
    byRegion[info.region].push(key);
  }

  return (
    <div className="relative">
      <button
        ref={btnRef}
        onClick={() => setOpen(v => !v)}
        className={clsx(
          "inline-flex items-center gap-2 h-8 px-3 rounded-md text-xs font-medium",
          "bg-bg-1 border border-border-subtle text-text-2 hover:text-text-1",
          "transition-colors"
        )}
      >
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden>
          <path
            d="M2 4h12M4 8h8M6 12h4"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
        <span>
          Books <span className="tabular text-text-1">{shown}</span>
          <span className="text-text-3"> / {total}</span>
        </span>
      </button>

      {open && (
        <div
          ref={panelRef}
          className={clsx(
            "absolute top-full right-0 mt-2 z-10",
            "w-[480px] max-h-[70vh] overflow-y-auto",
            "bg-bg-1 border border-border-subtle rounded-md shadow-2xl"
          )}
        >
          <div className="sticky top-0 bg-bg-1 border-b border-border-subtle p-3 flex items-center justify-between z-10">
            <span className="text-xs font-semibold text-text-1">
              Visible sportsbooks
            </span>
            <div className="flex gap-2 text-xs">
              <button
                onClick={() => onSetAll(availableBooks)}
                className="text-accent hover:underline"
              >
                All
              </button>
              <span className="text-text-3">·</span>
              <button
                onClick={() => onSetAll([])}
                className="text-text-2 hover:text-text-1"
              >
                None
              </button>
              <span className="text-text-3">·</span>
              <button
                onClick={() =>
                  onSetAll(
                    DEFAULT_VISIBLE_BOOKS.filter(b => availableSet.has(b))
                  )
                }
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
              <div key={r.key} className="px-2 py-2 border-b border-border-subtle last:border-b-0">
                <div className="px-2 pb-1 text-[10px] uppercase tracking-wider text-text-3">
                  {r.label} · {keys.length}
                </div>
                <div className="grid grid-cols-2 gap-1">
                  {keys.map(key => {
                    const info = bookInfo(key);
                    const on = visible.has(key);
                    return (
                      <button
                        key={key}
                        onClick={() => onToggle(key)}
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
                            "inline-flex w-3.5 h-3.5 rounded-sm border items-center justify-center text-[9px]",
                            on
                              ? "bg-accent border-accent text-bg-0"
                              : "border-text-3"
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
      )}
    </div>
  );
}
