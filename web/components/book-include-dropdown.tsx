"use client";
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Check, ChevronDown } from "lucide-react";

import { bookInfo } from "@/lib/books";
import { BookLogo } from "./book-logo";

/**
 * A lighter-weight page-level book filter than the global BookFilter. Used on
 * arbitrage / low-hold / free-bets pages to narrow the visible results to
 * opportunities that involve a specific book (or one of a set of books).
 *
 * Semantics:
 *   selected.size === 0 → no filter (show everything)
 *   selected.size > 0   → only rows where a relevant side's book ∈ selected
 */
export function BookIncludeDropdown({
  label,
  availableBooks,
  selected,
  onChange,
  buttonClassName,
}: {
  label: string;
  availableBooks: string[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  buttonClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
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

  function toggle(key: string) {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }

  const summary =
    selected.size === 0
      ? "All"
      : selected.size === 1
      ? bookInfo([...selected][0]).name
      : `${selected.size} selected`;

  return (
    <div className="relative" ref={rootRef}>
      <button
        onClick={() => setOpen(v => !v)}
        className={clsx(
          "inline-flex items-center gap-2 h-8 px-3 rounded-md text-xs font-medium",
          "bg-bg-1 border border-border-subtle text-text-2 hover:text-text-1",
          "transition-colors",
          buttonClassName
        )}
      >
        <span className="text-text-3 text-[10px] uppercase tracking-wider">
          {label}
        </span>
        <span className="text-text-1">{summary}</span>
        <ChevronDown size={10} aria-hidden />
      </button>
      {open && (
        <div
          className={clsx(
            "absolute top-full right-0 mt-2 z-20",
            "w-[320px] max-h-[70vh] overflow-y-auto",
            "bg-bg-1 border border-border-subtle rounded-md shadow-2xl"
          )}
        >
          <div className="sticky top-0 bg-bg-1 border-b border-border-subtle px-3 py-2 flex items-center justify-between z-10">
            <span className="text-[11px] text-text-3">
              {selected.size === 0
                ? "All books included"
                : `${selected.size} of ${availableBooks.length}`}
            </span>
            <div className="flex gap-2 text-[11px]">
              <button
                onClick={() => onChange(new Set())}
                className="text-text-2 hover:text-text-1"
              >
                Clear
              </button>
              <span className="text-text-3">·</span>
              <button
                onClick={() => onChange(new Set(availableBooks))}
                className="text-accent hover:underline"
              >
                All
              </button>
            </div>
          </div>
          {availableBooks.length === 0 ? (
            <div className="p-4 text-xs text-text-3 text-center">
              No books in the current result set.
            </div>
          ) : (
            <div className="py-1">
              {availableBooks.map(key => {
                const info = bookInfo(key);
                const on = selected.has(key);
                return (
                  <button
                    key={key}
                    onClick={() => toggle(key)}
                    className={clsx(
                      "w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left",
                      "transition-colors",
                      on
                        ? "bg-bg-2 text-text-1"
                        : "text-text-2 hover:bg-bg-2/50 hover:text-text-1"
                    )}
                  >
                    <span
                      className={clsx(
                        "inline-flex w-3.5 h-3.5 rounded-sm border items-center justify-center",
                        on
                          ? "bg-accent border-accent text-bg-0"
                          : "border-text-3"
                      )}
                    >
                      {on && <Check size={10} strokeWidth={3} aria-hidden />}
                    </span>
                    <BookLogo bookKey={key} mode="label" />
                    <span className="truncate">{info.name}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
