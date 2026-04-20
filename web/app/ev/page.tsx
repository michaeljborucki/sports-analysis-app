"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import clsx from "clsx";

import {
  apiPaths,
  type EVOpportunity,
  type EVResponse,
} from "@/lib/api";
import { formatAmerican } from "@/lib/format";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { BookFilter } from "@/components/book-filter";
import { BookIncludeDropdown } from "@/components/book-include-dropdown";
import {
  LiveStatusFilter,
  matchesLiveFilter,
  type LiveStatus,
} from "@/components/live-status-filter";
import { BookLogo } from "@/components/book-logo";
import { RefreshButton } from "@/components/refresh-button";
import { BOOK_ORDER } from "@/lib/books";
import { SPORTS, type SportKey } from "@/lib/sports";

const MIN_EV_PRESETS = [
  { label: "All",  value: -100 },
  { label: "≥ 1%", value: 1 },
  { label: "≥ 2%", value: 2 },
  { label: "≥ 3%", value: 3 },
  { label: "≥ 5%", value: 5 },
];

const MAX_ODDS_PRESETS = [
  { label: "All",   value: 5000 },
  { label: "≤ +300", value: 300 },
  { label: "≤ +500", value: 500 },
  { label: "≤ +800", value: 800 },
];

type SourceFilter = "all" | "pinnacle" | "consensus";

function sportLabel(key: string): string {
  if (key in SPORTS) return SPORTS[key as SportKey].label;
  return key.toUpperCase();
}

function marketLabel(op: EVOpportunity): string {
  const mk = op.market_kind;
  if (mk === "h2h" || mk === "h2h_3_way") return "Moneyline";
  if (mk === "totals") return op.point != null ? `Total ${op.point}` : "Total";
  if (mk === "alternate_totals") return op.point != null ? `Alt Total ${op.point}` : "Alt Total";
  if (mk === "spreads") return op.point != null ? `Spread ±${Math.abs(op.point)}` : "Spread";
  if (mk === "alternate_spreads")
    return op.point != null ? `Alt Spread ±${Math.abs(op.point)}` : "Alt Spread";
  if (mk === "team_totals") return op.point != null ? `Team Total ${op.point}` : "Team Total";
  if (mk === "alternate_team_totals")
    return op.point != null ? `Alt Team Total ${op.point}` : "Alt Team Total";
  // Period markets: h2h_h1, spreads_q1, etc.
  if (/_h[12]$/.test(mk)) return mk.replace(/_h([12])$/, " (H$1)");
  if (/_q[1-4]$/.test(mk)) return mk.replace(/_q([1-4])$/, " (Q$1)");
  if (/_p[1-3]$/.test(mk)) return mk.replace(/_p([1-3])$/, " (P$1)");
  if (/_f[3-9]$/.test(mk)) return mk.replace(/_f(\d)$/, " (F$1)");
  return mk;
}

function outcomeLabel(op: EVOpportunity): string {
  // For spreads, annotate with the signed point relative to the outcome.
  if (op.market_kind === "spreads" || op.market_kind === "alternate_spreads") {
    const sign = op.point != null && op.point > 0 ? "+" : "";
    return op.point != null ? `${op.outcome_name} ${sign}${op.point}` : op.outcome_name;
  }
  return op.outcome_name;
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

function evColor(pct: number): string {
  if (pct >= 5) return "text-price-up";
  if (pct >= 2) return "text-accent";
  if (pct >= 1) return "text-flash";
  return "text-text-2";
}

function clampStake(n: number): number {
  if (!Number.isFinite(n)) return 1000;
  return Math.max(100, Math.min(100000, Math.round(n)));
}

export default function EVPage() {
  const { visible, toggle, setAll } = useVisibleBooks();
  const [minEv, setMinEv] = useState<number>(2);
  const [maxOdds, setMaxOdds] = useState<number>(800);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [liveFilter, setLiveFilter] = useState<LiveStatus>("all");
  const [pageFilter, setPageFilter] = useState<Set<string>>(new Set());
  const [stake, setStake] = useState<number>(1000);

  useEffect(() => {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem("ev-stake") : null;
    if (raw) {
      const n = Number(raw);
      if (Number.isFinite(n)) setStake(clampStake(n));
    }
  }, []);
  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem("ev-stake", String(stake));
    }
  }, [stake]);

  // Server-side filter: pull lowest tier (min_ev=1), filter client-side for
  // the preset chips. Max-odds is server-side because it meaningfully reduces
  // payload size for longshot-heavy sports.
  const { data, error, isLoading, isValidating, mutate } =
    useSWR<EVResponse>(
      apiPaths.ev([...visible].sort(), { minEv: 1, maxLongshotOdds: maxOdds }),
      { refreshInterval: 15_000 }
    );

  const allBooksInPlay = useMemo(() => {
    const s = new Set<string>();
    for (const op of data?.opportunities ?? []) s.add(op.book);
    const known = BOOK_ORDER.filter(b => s.has(b));
    const unknown = [...s].filter(b => !BOOK_ORDER.includes(b)).sort();
    return [...known, ...unknown];
  }, [data]);

  const filteredOpps = useMemo(() => {
    let ops = data?.opportunities ?? [];
    if (liveFilter !== "all") {
      ops = ops.filter(op => matchesLiveFilter(op.commence_time, liveFilter));
    }
    if (minEv > 0) {
      ops = ops.filter(op => op.ev_pct >= minEv);
    }
    if (sourceFilter !== "all") {
      ops = ops.filter(op => op.source === sourceFilter);
    }
    if (pageFilter.size > 0) {
      ops = ops.filter(op => pageFilter.has(op.book));
    }
    return ops;
  }, [data, minEv, sourceFilter, liveFilter, pageFilter]);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">+EV</h1>
          <span
            className="text-xs text-text-3 tabular"
            title="Limits and closing-line movement typically erode ~1–2% from displayed paper EV."
          >
            offered price vs sharp fair · sorted EV desc · displayed EV is theoretical
          </span>
          {data && (
            <span className="text-xs text-text-3 tabular">
              {(minEv > 0 || sourceFilter !== "all" || pageFilter.size > 0) &&
              filteredOpps.length !== data.opportunities.length
                ? `${filteredOpps.length} / ${data.opportunities.length}`
                : `${data.opportunities.length}`}{" "}
              opportunities
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {/* Min EV */}
          <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
            {MIN_EV_PRESETS.map(p => (
              <button
                key={p.value}
                onClick={() => setMinEv(p.value)}
                className={clsx(
                  "px-3 py-1 text-xs tracking-wide uppercase transition-colors rounded-sm tabular",
                  minEv === p.value
                    ? "bg-bg-2 text-text-1"
                    : "text-text-2 hover:text-text-1"
                )}
                title={p.value <= 0 ? "Show all EV levels" : `Show EV ≥ ${p.value}%`}
              >
                {p.label}
              </button>
            ))}
          </div>
          {/* Max odds */}
          <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
            {MAX_ODDS_PRESETS.map(p => (
              <button
                key={p.value}
                onClick={() => setMaxOdds(p.value)}
                className={clsx(
                  "px-3 py-1 text-xs tracking-wide uppercase transition-colors rounded-sm tabular",
                  maxOdds === p.value
                    ? "bg-bg-2 text-text-1"
                    : "text-text-2 hover:text-text-1"
                )}
                title={`Filter out offered prices longer than ${p.value === 5000 ? "any" : `+${p.value}`}`}
              >
                {p.label}
              </button>
            ))}
          </div>
          {/* Source toggle */}
          <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
            {(["all", "pinnacle", "consensus"] as SourceFilter[]).map(s => (
              <button
                key={s}
                onClick={() => setSourceFilter(s)}
                className={clsx(
                  "px-3 py-1 text-xs tracking-wide uppercase transition-colors rounded-sm",
                  sourceFilter === s
                    ? "bg-bg-2 text-text-1"
                    : "text-text-2 hover:text-text-1"
                )}
                title={
                  s === "all"
                    ? "All sources"
                    : s === "pinnacle"
                    ? "Only Pinnacle-anchored EV (high confidence)"
                    : "Only consensus-anchored EV (lower confidence, props)"
                }
              >
                {s === "all" ? "All" : s === "pinnacle" ? "PIN" : "CON"}
              </button>
            ))}
          </div>
          <LiveStatusFilter value={liveFilter} onChange={setLiveFilter} />
          <BookIncludeDropdown
            label="Offered book"
            availableBooks={allBooksInPlay}
            selected={pageFilter}
            onChange={setPageFilter}
          />
          {/* Stake */}
          <div className="inline-flex items-center gap-1 rounded-md bg-bg-1 border border-border-subtle px-2 py-1">
            <span className="text-text-3 text-[11px] uppercase tracking-wide">Stake</span>
            <span className="text-text-3 text-xs">$</span>
            <input
              type="number"
              value={stake}
              onChange={e => setStake(clampStake(Number(e.target.value)))}
              min={100}
              max={100000}
              step={50}
              className="w-20 bg-transparent text-xs tabular text-text-1 outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
              title="Stake used for Kelly $ column (quarter-Kelly). Persisted locally."
            />
          </div>
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
      {data && filteredOpps.length === 0 ? (
        <div className="text-center text-text-3 py-16 text-sm">
          {minEv > 0 || sourceFilter !== "all" || pageFilter.size > 0
            ? "No +EV edges match current filters — try lowering min EV or widening max odds."
            : "No +EV edges found. Ensure Pinnacle is included in your book visibility (global filter)."}
        </div>
      ) : data ? (
        <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
          <table className="w-full text-xs">
            <thead className="bg-bg-1 text-text-2">
              <tr>
                <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px] w-[70px]">EV %</th>
                <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[60px]">Kelly</th>
                <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[66px]">$</th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[50px]">Sport</th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Event</th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Market</th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Outcome</th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Offered</th>
                <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Fair</th>
                <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[70px]">Starts</th>
                <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px] w-[72px]">Flags</th>
              </tr>
            </thead>
            <tbody>
              {filteredOpps.map((op, i) => {
                const kellyDollars = (op.kelly_quarter_pct / 100) * stake;
                const isStale = op.offered_age_s > 120;
                return (
                  <tr
                    key={`${op.event_id}-${op.market_kind}-${op.point ?? "na"}-${op.outcome_name}-${op.book}-${i}`}
                    className={clsx(
                      "border-t border-border-subtle hover:bg-bg-1/40",
                      isStale && "opacity-70"
                    )}
                  >
                    <td className="px-3 py-2">
                      <span className={clsx("tabular font-semibold", evColor(op.ev_pct))}>
                        {op.ev_pct >= 0 ? "+" : ""}
                        {op.ev_pct.toFixed(2)}%
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right tabular">
                      <span className={op.kelly_quarter_pct < 0.25 ? "text-text-3" : "text-text-1"}>
                        {op.kelly_quarter_pct.toFixed(2)}%
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right tabular text-text-2">
                      ${kellyDollars.toFixed(2)}
                    </td>
                    <td className="px-2 py-2 text-text-2 text-[11px] uppercase tracking-wide">
                      {sportLabel(op.sport_key)}
                    </td>
                    <td className="px-2 py-2 text-text-1 whitespace-nowrap">
                      {op.away_team} @ {op.home_team}
                    </td>
                    <td className="px-2 py-2 text-text-2">{marketLabel(op)}</td>
                    <td className="px-2 py-2 text-text-2 text-[11px] max-w-[180px] truncate">
                      {outcomeLabel(op)}
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-2">
                        <BookLogo bookKey={op.book} mode="label" />
                        <span className="text-price-up font-semibold tabular">
                          {formatAmerican(op.offered_price_american)}
                        </span>
                      </div>
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-2">
                        <span
                          className={clsx(
                            "inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider",
                            op.source === "pinnacle"
                              ? "text-accent bg-accent/10"
                              : "text-text-3 bg-bg-2"
                          )}
                          title={
                            op.source === "pinnacle"
                              ? "Pinnacle no-vig — high confidence"
                              : `Consensus of ${op.anchor_book_count} books — lower confidence`
                          }
                        >
                          {op.source === "pinnacle" ? "PIN" : "CON"}
                        </span>
                        <span className="text-text-1 tabular">
                          {formatAmerican(op.fair_price_american)}
                        </span>
                      </div>
                    </td>
                    <td className="px-2 py-2 text-right text-text-3 tabular text-[11px]">
                      {commenceLabel(op.commence_time)}
                    </td>
                    <td className="px-2 py-2 text-right">
                      <div className="inline-flex gap-1">
                        {op.also_in_arb && (
                          <span
                            className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-price-up bg-price-up/20"
                            title="This opportunity is also an arbitrage — see the Arbitrage tab."
                          >
                            ARB
                          </span>
                        )}
                        {op.confidence === "low" && (
                          <span
                            className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-price-down bg-price-down/10"
                            title="EV > 15% — likely stale or mispriced; verify before betting."
                          >
                            SUS
                          </span>
                        )}
                        {isStale && (
                          <span
                            className="inline-flex items-center px-1 rounded-sm text-[9px] font-semibold tracking-wider text-text-3 bg-bg-2"
                            title={`Offered price is ${op.offered_age_s}s old.`}
                          >
                            STALE
                          </span>
                        )}
                      </div>
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
