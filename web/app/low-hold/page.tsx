"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";
import clsx from "clsx";

import {
  apiPaths,
  type LowHoldOpportunity,
  type LowHoldResponse,
} from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { BookIncludeDropdown } from "@/components/book-include-dropdown";
import { matchesLiveFilter } from "@/components/live-status-filter";
import { useLiveFilter } from "@/lib/use-live-filter";
import { BookLogo } from "@/components/book-logo";
import { RefreshButton } from "@/components/refresh-button";
import { BOOK_ORDER } from "@/lib/books";
import { SPORTS, type SportKey } from "@/lib/sports";

const HOLD_CAP_PRESETS = [1, 2.5, 5];

function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}

function marketLabel(op: LowHoldOpportunity): string {
  if (op.market_kind === "h2h") return "Moneyline";
  if (op.market_kind === "totals")
    return op.point != null ? `Total ${op.point}` : "Total";
  if (op.market_kind === "spreads")
    return op.point != null ? `Spread ±${op.point}` : "Spread";
  return op.market_kind;
}

function commenceLabel(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffH = (d.getTime() - now.getTime()) / 3_600_000;
  if (diffH < 0) return "LIVE";
  if (diffH < 1) return `${Math.round(diffH * 60)}m`;
  if (diffH < 24) return `${Math.round(diffH)}h`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function holdColor(pct: number): string {
  if (pct < 0.5) return "text-price-up";
  if (pct < 1.5) return "text-accent";
  if (pct < 2.5) return "text-flash";
  return "text-text-2";
}

export default function LowHoldPage() {
  const { visible } = useVisibleBooks();
  const [maxHold, setMaxHold] = useState<number>(1);

  const { data, error, isLoading, isValidating, mutate } =
    useSWR<LowHoldResponse>(
      apiPaths.lowHold([...visible].sort(), maxHold),
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
  }, [data]);

  const [pageFilter, setPageFilter] = useState<Set<string>>(new Set());
  const { value: liveFilter } = useLiveFilter();
  const filteredOpps = useMemo(() => {
    let ops = data?.opportunities ?? [];
    if (liveFilter !== "all") {
      ops = ops.filter(op => matchesLiveFilter(op.commence_time, liveFilter));
    }
    if (pageFilter.size > 0) {
      ops = ops.filter(op => op.sides.some(s => pageFilter.has(s.book)));
    }
    return ops;
  }, [data, pageFilter, liveFilter]);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">Low Hold</h1>
          <span className="text-xs text-text-3 tabular">
            tightest two-way markets · sorted by hold ascending
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
          <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
            {HOLD_CAP_PRESETS.map(h => (
              <button
                key={h}
                onClick={() => setMaxHold(h)}
                className={clsx(
                  "px-3 py-1 text-xs tracking-wide uppercase transition-colors rounded-sm tabular",
                  maxHold === h
                    ? "bg-bg-2 text-text-1"
                    : "text-text-2 hover:text-text-1"
                )}
              >
                ≤ {h}%
              </button>
            ))}
          </div>
          <BookIncludeDropdown
            label="Must include"
            availableBooks={allBooksInPlay}
            selected={pageFilter}
            onChange={setPageFilter}
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
      {data && filteredOpps.length === 0 ? (
        <div className="text-center text-text-3 py-16 text-sm">
          {pageFilter.size > 0
            ? "No low-hold lines match the selected book filter."
            : `No low-hold lines under ${maxHold}% across your selected books. Try raising the cap or including sharper books (Pinnacle, Novig, Betfair exchanges, Kalshi).`}
        </div>
      ) : data ? (
        <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
          <table className="w-full text-xs">
            <thead className="bg-bg-1 text-text-2">
              <tr>
                <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px] w-[70px]">
                  Hold
                </th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[60px]">
                  Sport
                </th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                  Event
                </th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                  Market
                </th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                  Side A
                </th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                  Side B
                </th>
                <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[60px]">
                  Starts
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredOpps.map((op, i) => {
                const a = op.sides[0];
                const b = op.sides[1];
                return (
                  <tr
                    key={`${op.event_id}-${op.market_kind}-${op.point ?? "na"}-${i}`}
                    className="border-t border-border-subtle hover:bg-bg-1/40"
                  >
                    <td className="px-3 py-2">
                      <span
                        className={clsx(
                          "tabular font-semibold",
                          holdColor(op.hold_pct)
                        )}
                      >
                        {op.hold_pct.toFixed(2)}%
                      </span>
                    </td>
                    <td className="px-2 py-2 text-text-2 text-[11px] uppercase tracking-wide">
                      {sportLabel(op.sport_key)}
                    </td>
                    <td className="px-2 py-2 text-text-1 whitespace-nowrap">
                      {op.away_team} @ {op.home_team}
                    </td>
                    <td className="px-2 py-2 text-text-2">{marketLabel(op)}</td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-2">
                        <BookLogo bookKey={a.book} mode="label" />
                        <span className="text-text-2 text-[11px]">
                          {a.outcome_name}
                        </span>
                        <span className="text-price-up font-semibold tabular">
                          {formatAmerican(a.price_american)}
                        </span>
                      </div>
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-2">
                        <BookLogo bookKey={b.book} mode="label" />
                        <span className="text-text-2 text-[11px]">
                          {b.outcome_name}
                        </span>
                        <span className="text-price-up font-semibold tabular">
                          {formatAmerican(b.price_american)}
                        </span>
                      </div>
                    </td>
                    <td className="px-2 py-2 text-right text-text-3 tabular text-[11px]">
                      {commenceLabel(op.commence_time)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
