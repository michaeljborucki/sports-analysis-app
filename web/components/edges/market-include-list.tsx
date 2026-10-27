"use client";
import { useState } from "react";
import clsx from "clsx";
import { Check } from "lucide-react";

import { marketKindLabel } from "@/lib/edges";

export interface MarketOption {
  key: string;
  label: string;
  count: number;
}

/** Short summary of a market selection: "all markets" / "Batter Hits" / "3 markets". */
export function marketSelectionSummary(selected: Set<string>): string {
  if (selected.size === 0) return "all markets";
  if (selected.size === 1) return marketKindLabel([...selected][0]);
  return `${selected.size} markets`;
}

/**
 * Checkbox list behind the Edges market filter. Same semantics as the book
 * list: nothing selected → no filter; otherwise only rows in a selected
 * market. Selected markets that dropped off the board stay listed (count 0)
 * so they can still be unchecked.
 */
export function MarketIncludeList({
  options,
  selected,
  onChange,
}: {
  options: MarketOption[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = q ? options.filter(o => o.label.toLowerCase().includes(q)) : options;

  function toggle(key: string) {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onChange(next);
  }

  return (
    <div className="w-[300px] max-h-[60vh] overflow-y-auto">
      <div className="sticky top-0 z-10 flex flex-col gap-2 border-b border-border-subtle bg-bg-1 px-3 py-2">
        <div className="flex items-center justify-between">
          <span className="text-[length:var(--fs-12)] text-text-3">
            {selected.size === 0 ? (
              "All markets included"
            ) : (
              <>
                <span className="tabular">{selected.size}</span> of{" "}
                <span className="tabular">{options.length}</span> selected
              </>
            )}
          </span>
          <button
            type="button"
            onClick={() => onChange(new Set())}
            className="text-[length:var(--fs-12)] text-text-2 hover:text-text-1"
          >
            Clear
          </button>
        </div>
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search markets"
          autoFocus
          aria-label="Search markets"
          className="h-7 rounded-md border border-border-subtle bg-bg-2 px-2 text-[length:var(--fs-13)] text-text-1 outline-none placeholder:text-text-3 focus:border-text-3"
        />
      </div>
      {shown.length === 0 ? (
        <div className="p-4 text-center text-[length:var(--fs-13)] text-text-3">
          {options.length === 0 ? "No markets in the current results." : "No markets match."}
        </div>
      ) : (
        <div className="py-1">
          {shown.map(o => {
            const on = selected.has(o.key);
            return (
              <button
                key={o.key}
                type="button"
                role="checkbox"
                aria-checked={on}
                onClick={() => toggle(o.key)}
                title={o.key}
                className={clsx(
                  "flex w-full items-center gap-2 px-3 py-1.5 text-left text-[length:var(--fs-13)] transition-colors",
                  on ? "bg-bg-2 text-text-1" : "text-text-2 hover:bg-bg-2 hover:text-text-1",
                )}
              >
                <span
                  className={clsx(
                    "inline-flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border",
                    on ? "border-text-1 bg-text-1 text-bg-0" : "border-text-3",
                  )}
                >
                  {on && <Check size={10} strokeWidth={3} aria-hidden />}
                </span>
                <span className="truncate">{o.label}</span>
                <span className="tabular ml-auto text-[length:var(--fs-12)] text-text-3">{o.count}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
