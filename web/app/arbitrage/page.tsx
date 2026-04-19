"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { apiPaths, type ArbResponse } from "@/lib/api";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { ArbitrageTable } from "@/components/arbitrage-table";
import { BookFilter } from "@/components/book-filter";
import { BookIncludeDropdown } from "@/components/book-include-dropdown";
import { RefreshButton } from "@/components/refresh-button";
import { BOOK_ORDER } from "@/lib/books";

export default function ArbitragePage() {
  const { visible, toggle, setAll } = useVisibleBooks();
  const booksKey = useMemo(
    () => [...visible].sort().join(","),
    [visible]
  );

  const { data, error, isLoading, isValidating, mutate } = useSWR<ArbResponse>(
    apiPaths.arbitrage([...visible].sort()),
    { refreshInterval: 15_000 }
  );

  const allBooksInPlay = useMemo(() => {
    const s = new Set<string>();
    for (const op of data?.opportunities ?? []) {
      for (const side of op.sides) s.add(side.book);
    }
    const known = BOOK_ORDER.filter(b => s.has(b));
    const unknown = [...s].filter(b => !BOOK_ORDER.includes(b)).sort();
    return [...known, ...unknown];
  }, [data, booksKey]);

  // Page-level filter: restrict to opportunities where at least one side
  // uses a selected book. Empty set = no filter.
  const [pageFilter, setPageFilter] = useState<Set<string>>(new Set());
  const filteredOpps = useMemo(() => {
    const ops = data?.opportunities ?? [];
    if (pageFilter.size === 0) return ops;
    return ops.filter(op => op.sides.some(s => pageFilter.has(s.book)));
  }, [data, pageFilter]);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">Arbitrage</h1>
          <span className="text-xs text-text-3 tabular">
            cross-sport · ranked by ROI
          </span>
          {data && (
            <span className="text-xs text-text-3 tabular">
              {pageFilter.size > 0 && filteredOpps.length !== data.opportunities.length
                ? `${filteredOpps.length} / ${data.opportunities.length}`
                : `${data.opportunities.length}`}{" "}
              opportunities
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <BookIncludeDropdown
            label="Must include"
            availableBooks={allBooksInPlay}
            selected={pageFilter}
            onChange={setPageFilter}
          />
          <BookFilter
            availableBooks={allBooksInPlay.length ? allBooksInPlay : BOOK_ORDER}
            visible={visible}
            onToggle={toggle}
            onSetAll={setAll}
          />
          <RefreshButton onRefresh={() => mutate()} isValidating={isValidating} />
        </div>
      </header>

      {error && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && (
        <div className="text-text-2 text-sm">Scanning cache…</div>
      )}
      {data && <ArbitrageTable opportunities={filteredOpps} />}
    </div>
  );
}
