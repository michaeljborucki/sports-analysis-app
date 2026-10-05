"use client";
import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Check, ChevronDown } from "lucide-react";

import { bookInfo } from "@/lib/books";
import { BookLogo } from "./book-logo";

/** Short summary of a book selection: "all books" / "DraftKings" / "3 books". */
export function bookSelectionSummary(selected: Set<string>, allLabel = "All books"): string {
  if (selected.size === 0) return allLabel;
  if (selected.size === 1) return bookInfo([...selected][0]).name;
  return `${selected.size} books`;
}

/**
 * The checkbox list behind the book filter. Rendered inside the dropdown
 * below, or directly inside a popover (Edges sentence filter).
 *
 * Semantics:
 *   selected.size === 0 → no filter (show everything)
 *   selected.size > 0   → only rows where a relevant side's book ∈ selected
 */
export function BookIncludeList({
  availableBooks,
  selected,
  onChange,
  className,
}: {
  availableBooks: string[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  className?: string;
}) {
  function toggle(key: string) {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }

  return (
    <div className={clsx("w-[300px] max-h-[60vh] overflow-y-auto", className)}>
      <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-subtle bg-bg-1 px-3 py-2">
        <span className="text-[length:var(--fs-12)] text-text-3">
          {selected.size === 0 ? (
            "All books included"
          ) : (
            <>
              <span className="tabular">{selected.size}</span> of{" "}
              <span className="tabular">{availableBooks.length}</span> selected
            </>
          )}
        </span>
        <div className="flex gap-3 text-[length:var(--fs-12)]">
          <button
            type="button"
            onClick={() => onChange(new Set())}
            className="text-text-2 hover:text-text-1"
          >
            Clear
          </button>
          <button
            type="button"
            onClick={() => onChange(new Set(availableBooks))}
            className="text-text-2 hover:text-text-1"
          >
            Select all
          </button>
        </div>
      </div>
      {availableBooks.length === 0 ? (
        <div className="p-4 text-center text-[length:var(--fs-13)] text-text-3">
          No books in the current results.
        </div>
      ) : (
        <div className="py-1">
          {availableBooks.map(key => {
            const info = bookInfo(key);
            const on = selected.has(key);
            return (
              <button
                key={key}
                type="button"
                role="checkbox"
                aria-checked={on}
                onClick={() => toggle(key)}
                className={clsx(
                  "flex w-full items-center gap-2 px-3 py-1.5 text-left text-[length:var(--fs-13)] transition-colors",
                  on ? "bg-bg-2 text-text-1" : "text-text-2 hover:bg-bg-2 hover:text-text-1",
                )}
              >
                <span
                  className={clsx(
                    "inline-flex h-3.5 w-3.5 items-center justify-center rounded-sm border",
                    on ? "border-text-1 bg-text-1 text-bg-0" : "border-text-3",
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
  );
}

/**
 * Button + dropdown wrapper around `BookIncludeList`. A lighter-weight
 * page-level book filter than the global BookFilter.
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

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
        className={clsx(
          "inline-flex h-8 items-center gap-2 rounded-md px-3 text-[length:var(--fs-13)] font-medium",
          "border border-border-subtle bg-bg-1 text-text-2 transition-colors hover:text-text-1",
          buttonClassName,
        )}
      >
        <span className="text-text-3">{label}</span>
        <span className="text-text-1">{bookSelectionSummary(selected, "All")}</span>
        <ChevronDown size={12} aria-hidden />
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-2 overflow-hidden rounded-lg border border-border-subtle bg-bg-1 shadow-[0_8px_24px_rgb(0_0_0/0.35)]">
          <BookIncludeList
            availableBooks={availableBooks}
            selected={selected}
            onChange={onChange}
          />
        </div>
      )}
    </div>
  );
}
