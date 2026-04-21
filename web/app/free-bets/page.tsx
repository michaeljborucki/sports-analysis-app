"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";
import clsx from "clsx";

import {
  apiPaths,
  type FreeBetOpportunity,
  type FreeBetResponse,
} from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { BookIncludeDropdown } from "@/components/book-include-dropdown";
import { BookLogo } from "@/components/book-logo";
import { matchesLiveFilter } from "@/components/live-status-filter";
import { useLiveFilter } from "@/lib/use-live-filter";
import { RefreshButton } from "@/components/refresh-button";
import { BOOK_ORDER } from "@/lib/books";
import { SPORTS, type SportKey } from "@/lib/sports";

const MIN_CONVERSION_PRESETS = [
  { label: "All", value: 0 },
  { label: "≥ 70%", value: 70 },
  { label: "≥ 80%", value: 80 },
  { label: "≥ 90%", value: 90 },
];

function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}

function marketLabel(op: FreeBetOpportunity): string {
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

function conversionColor(pct: number): string {
  if (pct >= 80) return "text-price-up";
  if (pct >= 70) return "text-accent";
  if (pct >= 60) return "text-flash";
  return "text-text-2";
}

export default function FreeBetsPage() {
  const { visible } = useVisibleBooks();
  const [minConversion, setMinConversion] = useState<number>(0);
  // Backend min_free_odds stays at +100 (anything below is strictly worse
  // than cash) — the user-facing filter is now conversion-rate-based.
  const MIN_FREE_ODDS = 100;

  const { data, error, isLoading, isValidating, mutate } =
    useSWR<FreeBetResponse>(
      apiPaths.freeBets([...visible].sort(), MIN_FREE_ODDS),
      { refreshInterval: 15_000 }
    );

  const allBooksInPlay = useMemo(() => {
    const s = new Set<string>();
    for (const op of data?.opportunities ?? []) {
      s.add(op.free_leg.book);
      s.add(op.hedge_leg.book);
    }
    const known = BOOK_ORDER.filter(b => s.has(b));
    const unknown = [...s].filter(b => !BOOK_ORDER.includes(b)).sort();
    return [...known, ...unknown];
  }, [data]);

  // Books that appear as the free-bet leg in the current dataset — the
  // dropdown is scoped to these since the filter is specifically for the
  // free-bet leg, not the hedge.
  const freeBookOptions = useMemo(() => {
    const s = new Set<string>();
    for (const op of data?.opportunities ?? []) {
      s.add(op.free_leg.book);
    }
    const known = BOOK_ORDER.filter(b => s.has(b));
    const unknown = [...s].filter(b => !BOOK_ORDER.includes(b)).sort();
    return [...known, ...unknown];
  }, [data]);

  const [freeLegFilter, setFreeLegFilter] = useState<Set<string>>(new Set());
  const { value: liveFilter } = useLiveFilter();
  const filteredOpps = useMemo(() => {
    let ops = data?.opportunities ?? [];
    if (liveFilter !== "all") {
      ops = ops.filter(op => matchesLiveFilter(op.commence_time, liveFilter));
    }
    if (minConversion > 0) {
      ops = ops.filter(op => op.conversion_pct >= minConversion);
    }
    if (freeLegFilter.size > 0) {
      ops = ops.filter(op => freeLegFilter.has(op.free_leg.book));
    }
    return ops;
  }, [data, freeLegFilter, minConversion, liveFilter]);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">Free Bets</h1>
          <span className="text-xs text-text-3 tabular">
            hedged free-bet conversion · sorted by conversion rate
          </span>
          {data && (
            <span className="text-xs text-text-3 tabular">
              {freeLegFilter.size > 0 && filteredOpps.length !== data.opportunities.length
                ? `${filteredOpps.length} / ${data.opportunities.length}`
                : `${data.opportunities.length}`}{" "}
              opportunities
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
            {MIN_CONVERSION_PRESETS.map(p => (
              <button
                key={p.value}
                onClick={() => setMinConversion(p.value)}
                className={clsx(
                  "px-3 py-1 text-xs tracking-wide uppercase transition-colors rounded-sm tabular",
                  minConversion === p.value
                    ? "bg-bg-2 text-text-1"
                    : "text-text-2 hover:text-text-1"
                )}
                title={
                  p.value === 0
                    ? "Show all conversions"
                    : `Show conversions at ${p.value}% or higher`
                }
              >
                {p.label}
              </button>
            ))}
          </div>
          <BookIncludeDropdown
            label="Free-bet book"
            availableBooks={freeBookOptions}
            selected={freeLegFilter}
            onChange={setFreeLegFilter}
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
          {minConversion > 0 || freeLegFilter.size > 0
            ? "No free-bet conversions match the current filters. Lower the minimum conversion threshold or widen the free-bet book filter."
            : "No free-bet conversions found."}
        </div>
      ) : data ? (
        <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
          <table className="w-full text-xs">
            <thead className="bg-bg-1 text-text-2">
              <tr>
                <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px] w-[80px]">
                  Conv %
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
                  Free bet leg
                </th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                  Hedge leg
                </th>
                <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[80px]">
                  Hedge / $100
                </th>
                <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[60px]">
                  Starts
                </th>
              </tr>
            </thead>
            <tbody>
              {filteredOpps.map((op, i) => (
                <tr
                  key={`${op.event_id}-${op.market_kind}-${op.point ?? "na"}-${i}`}
                  className="border-t border-border-subtle hover:bg-bg-1/40"
                >
                  <td className="px-3 py-2">
                    <span
                      className={clsx(
                        "tabular font-semibold",
                        conversionColor(op.conversion_pct)
                      )}
                    >
                      {op.conversion_pct.toFixed(1)}%
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
                      <BookLogo bookKey={op.free_leg.book} mode="label" />
                      <span className="text-text-2 text-[11px] max-w-[140px] truncate">
                        {op.free_leg.outcome_name}
                      </span>
                      <span className="text-price-up font-semibold tabular">
                        {formatAmerican(op.free_leg.price_american)}
                      </span>
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex items-center gap-2">
                      <BookLogo bookKey={op.hedge_leg.book} mode="label" />
                      <span className="text-text-2 text-[11px] max-w-[140px] truncate">
                        {op.hedge_leg.outcome_name}
                      </span>
                      <span className="text-text-1 font-semibold tabular">
                        {formatAmerican(op.hedge_leg.price_american)}
                      </span>
                    </div>
                  </td>
                  <td className="px-2 py-2 text-right tabular text-text-1">
                    ${op.hedge_stake_per_100.toFixed(2)}
                  </td>
                  <td className="px-2 py-2 text-right text-text-3 tabular text-[11px]">
                    {commenceLabel(op.commence_time)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
