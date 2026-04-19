"use client";
import { useMemo } from "react";
import useSWR from "swr";

import { apiPaths, type ArbResponse } from "@/lib/api";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { ArbitrageTable } from "@/components/arbitrage-table";
import { BookFilter } from "@/components/book-filter";
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

  // All books that actually appear across the current arb set — so the filter
  // panel can show a meaningful list even without a prior odds-page visit.
  const allBooksInPlay = useMemo(() => {
    const s = new Set<string>();
    for (const op of data?.opportunities ?? []) {
      for (const side of op.sides) s.add(side.book);
    }
    // Preserve registry order for books we recognize; append strangers alphabetically.
    const known = BOOK_ORDER.filter(b => s.has(b));
    const unknown = [...s].filter(b => !BOOK_ORDER.includes(b)).sort();
    return [...known, ...unknown];
  }, [data, booksKey]);

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
              {data.opportunities.length} opportunities
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
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
      {data && <ArbitrageTable opportunities={data.opportunities} />}
    </div>
  );
}
