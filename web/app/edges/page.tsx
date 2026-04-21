"use client";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import clsx from "clsx";

import {
  apiPaths,
  type ArbResponse,
  type EVResponse,
  type FreeBetResponse,
  type LowHoldResponse,
} from "@/lib/api";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { useLiveFilter } from "@/lib/use-live-filter";
import { matchesLiveFilter } from "@/components/live-status-filter";
import { BookIncludeDropdown } from "@/components/book-include-dropdown";
import { RefreshButton } from "@/components/refresh-button";
import { FreshnessChip } from "@/components/freshness-chip";
import { EmptyState } from "@/components/empty-state";
import { BOOK_ORDER } from "@/lib/books";
import { SPORTS, type SportKey } from "@/lib/sports";
import {
  EDGE_MODES,
  MODE_LABEL,
  MODE_LONG_LABEL,
  mergeEdges,
  sortEdges,
  type EdgeMode,
  type EdgeOpportunity,
  type SortDir,
  type SortKey,
} from "@/lib/edges";

import { ModeToggle } from "@/components/edges/mode-toggle";
import { EdgesTable } from "@/components/edges/edges-table";

// ─────────────────────── URL state helpers ────────────────────────

// Single-select: pick the first valid mode in the URL, else default to "arb".
// Arb is chosen as the cold-boot default because it doesn't depend on a sharp
// anchor book (Pinnacle/Circa) being visible — it's the only mode that can't
// be starved by a mis-scoped Visible Books set.
const DEFAULT_MODE: EdgeMode = "arb";
function parseModes(raw: string | null): Set<EdgeMode> {
  if (!raw) return new Set([DEFAULT_MODE]);
  const pieces = raw.split(",").filter(Boolean) as EdgeMode[];
  const first = pieces.find(p => EDGE_MODES.includes(p));
  return new Set([first ?? DEFAULT_MODE]);
}

const MAX_ODDS_OPTIONS = [
  { label: "≤ +300", value: 300 },
  { label: "≤ +500", value: 500 },
  { label: "≤ +800", value: 800 },
  { label: "≤ +1500", value: 1500 },
  { label: "All", value: 5000 },
];

function clampStake(n: number): number {
  if (!Number.isFinite(n)) return 1000;
  return Math.max(50, Math.min(1_000_000, Math.round(n)));
}

function sportKeyOrAll(raw: string | null): string {
  if (!raw) return "all";
  if (raw in SPORTS) return raw;
  return "all";
}

export default function EdgesPage() {
  return (
    <Suspense fallback={null}>
      <EdgesPageInner />
    </Suspense>
  );
}

function EdgesPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // ─── Filter state (hydrated from URL) ──────────────────────────
  const [modes, setModes] = useState<Set<EdgeMode>>(() =>
    parseModes(searchParams.get("modes")),
  );
  const [sport, setSport] = useState<string>(() =>
    sportKeyOrAll(searchParams.get("sport")),
  );
  const [minEdge, setMinEdge] = useState<number>(() => {
    const raw = searchParams.get("minEdge");
    const n = raw ? Number(raw) : 0;
    return Number.isFinite(n) ? Math.max(0, Math.min(10, n)) : 0;
  });
  const [maxOdds, setMaxOdds] = useState<number>(() => {
    const raw = searchParams.get("maxOdds");
    const n = raw ? Number(raw) : 800;
    const allowed = MAX_ODDS_OPTIONS.some(o => o.value === n);
    return allowed ? n : 800;
  });
  const [bookFilter, setBookFilter] = useState<Set<string>>(() => {
    const raw = searchParams.get("books");
    if (!raw) return new Set();
    return new Set(raw.split(",").filter(Boolean));
  });
  const [stake, setStake] = useState<number>(() => {
    const raw = searchParams.get("stake");
    return clampStake(Number(raw));
  });

  // Stake localStorage fallback — carries over from the old /ev page.
  useEffect(() => {
    if (searchParams.get("stake")) return;
    try {
      const raw = window.localStorage.getItem("ev-stake");
      if (raw) {
        const n = Number(raw);
        if (Number.isFinite(n)) setStake(clampStake(n));
      }
    } catch {}
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    try {
      window.localStorage.setItem("ev-stake", String(stake));
    } catch {}
  }, [stake]);

  // ─── URL sync ──────────────────────────────────────────────────
  useEffect(() => {
    const qs = new URLSearchParams();
    // Always serialize the active mode — we're single-select now, so the URL
    // should make the current mode unambiguous (bookmarks, back button, etc.).
    const onlyMode = [...modes][0];
    if (onlyMode && onlyMode !== DEFAULT_MODE) {
      qs.set("modes", onlyMode);
    }
    if (sport !== "all") qs.set("sport", sport);
    if (minEdge > 0) qs.set("minEdge", String(minEdge));
    if (maxOdds !== 800) qs.set("maxOdds", String(maxOdds));
    if (bookFilter.size > 0) qs.set("books", [...bookFilter].sort().join(","));
    if (stake !== 1000) qs.set("stake", String(stake));
    const qstring = qs.toString();
    const url = qstring ? `/edges?${qstring}` : "/edges";
    router.replace(url, { scroll: false });
  }, [modes, sport, minEdge, maxOdds, bookFilter, stake, router]);

  // ─── Data fetching — 4 parallel SWR keys ───────────────────────
  const { visible } = useVisibleBooks();
  const booksSorted = useMemo(() => [...visible].sort(), [visible]);

  const arbSwr = useSWR<ArbResponse>(
    modes.has("arb") ? apiPaths.arbitrage(booksSorted) : null,
    { refreshInterval: 15_000 },
  );
  const lhSwr = useSWR<LowHoldResponse>(
    modes.has("low_hold") ? apiPaths.lowHold(booksSorted, 2.5) : null,
    { refreshInterval: 15_000 },
  );
  const evSwr = useSWR<EVResponse>(
    modes.has("ev")
      ? apiPaths.ev(booksSorted, { minEv: 1, maxLongshotOdds: maxOdds })
      : null,
    { refreshInterval: 15_000 },
  );
  const fbSwr = useSWR<FreeBetResponse>(
    modes.has("free_bet") ? apiPaths.freeBets(booksSorted, 100) : null,
    { refreshInterval: 15_000 },
  );

  const refreshAll = useCallback(() => {
    if (modes.has("arb")) void arbSwr.mutate();
    if (modes.has("low_hold")) void lhSwr.mutate();
    if (modes.has("ev")) void evSwr.mutate();
    if (modes.has("free_bet")) void fbSwr.mutate();
  }, [modes, arbSwr, lhSwr, evSwr, fbSwr]);

  const anyLoading =
    (modes.has("arb") && arbSwr.isLoading) ||
    (modes.has("low_hold") && lhSwr.isLoading) ||
    (modes.has("ev") && evSwr.isLoading) ||
    (modes.has("free_bet") && fbSwr.isLoading);
  const anyValidating =
    (modes.has("arb") && arbSwr.isValidating) ||
    (modes.has("low_hold") && lhSwr.isValidating) ||
    (modes.has("ev") && evSwr.isValidating) ||
    (modes.has("free_bet") && fbSwr.isValidating);
  const anyError =
    (modes.has("arb") && arbSwr.error) ||
    (modes.has("low_hold") && lhSwr.error) ||
    (modes.has("ev") && evSwr.error) ||
    (modes.has("free_bet") && fbSwr.error);

  // ─── Merge + filter ────────────────────────────────────────────
  const merged = useMemo(
    () =>
      mergeEdges({
        arb: modes.has("arb") ? arbSwr.data?.opportunities : undefined,
        lowHold: modes.has("low_hold") ? lhSwr.data?.opportunities : undefined,
        ev: modes.has("ev") ? evSwr.data?.opportunities : undefined,
        freeBet: modes.has("free_bet") ? fbSwr.data?.opportunities : undefined,
      }),
    [
      modes,
      arbSwr.data,
      lhSwr.data,
      evSwr.data,
      fbSwr.data,
    ],
  );

  const rawCount = merged.length;

  const { value: liveFilter } = useLiveFilter();

  const allBooksInPlay = useMemo(() => {
    const s = new Set<string>();
    for (const op of merged) {
      for (const leg of op.legs) {
        if (leg.role !== "fair") s.add(leg.book);
      }
    }
    const known = BOOK_ORDER.filter(b => s.has(b));
    const unknown = [...s].filter(b => !BOOK_ORDER.includes(b)).sort();
    return [...known, ...unknown];
  }, [merged]);

  const filtered = useMemo(() => {
    let rows = merged;
    if (liveFilter !== "all") {
      rows = rows.filter(op =>
        matchesLiveFilter(op.commence_time, liveFilter),
      );
    }
    if (sport !== "all") {
      rows = rows.filter(op => op.sport_key === sport);
    }
    if (minEdge > 0) {
      // Unified filter. Note: for low-hold, edge_pct is negative (it's
      // -hold_pct). A minEdge filter > 0 filters those rows out, which
      // is *usually* correct when the user is asking for "≥ N% real
      // edge" — low-hold pairs only have a real edge when combined
      // with a promo. For arb/ev the comparison is direct. For
      // free-bet, conversion % is always well above 0 so it passes.
      rows = rows.filter(op => {
        // Low-hold rows have no standalone positive edge — they're only
        // profitable combined with a promo/rakeback. A "min-edge > 0"
        // filter is asking for real edges, so we hide them.
        if (op.mode === "low_hold") return false;
        if (op.mode === "free_bet") return op.raw.conversion_pct >= minEdge;
        return op.edge_pct >= minEdge;
      });
    }
    if (maxOdds > 0 && maxOdds < 5000) {
      rows = rows.filter(op => {
        // Filter out rows where the "offered" leg is longer than maxOdds.
        const priced = op.legs.filter(l => l.role !== "fair");
        return priced.every(l => l.price_american <= maxOdds);
      });
    }
    if (bookFilter.size > 0) {
      rows = rows.filter(op =>
        op.legs.some(l => l.role !== "fair" && bookFilter.has(l.book)),
      );
    }
    return rows;
  }, [merged, liveFilter, sport, minEdge, maxOdds, bookFilter]);

  // ─── Sort ──────────────────────────────────────────────────────
  const [sortKey, setSortKey] = useState<SortKey>("edge");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const onSort = useCallback(
    (key: SortKey) => {
      if (key === sortKey) {
        setSortDir(d => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortKey(key);
        setSortDir("desc");
      }
    },
    [sortKey],
  );
  const sorted = useMemo(
    () => sortEdges(filtered, sortKey, sortDir),
    [filtered, sortKey, sortDir],
  );

  // ─── Workbench expansion state ─────────────────────────────────
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggleExpand = useCallback((key: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // ─── Sport dropdown options ────────────────────────────────────
  const sportOptions = useMemo(
    () => [
      { value: "all", label: "All sports" },
      ...Object.values(SPORTS).map(s => ({ value: s.key, label: s.label })),
    ],
    [],
  );

  // ─── Empty-state selection ─────────────────────────────────────
  // Defer to after we have loaded at least *some* data. If everything
  // is still in-flight we render the "scanning cache" string.
  const allHaveData =
    (!modes.has("arb") || arbSwr.data != null) &&
    (!modes.has("low_hold") || lhSwr.data != null) &&
    (!modes.has("ev") || evSwr.data != null) &&
    (!modes.has("free_bet") || fbSwr.data != null);

  // Freshness age for tone + hint copy.
  const scannedAtIso = useMemo(() => {
    const candidates = [
      modes.has("arb") ? arbSwr.data?.scanned_at : undefined,
      modes.has("low_hold") ? lhSwr.data?.scanned_at : undefined,
      modes.has("ev") ? evSwr.data?.scanned_at : undefined,
      modes.has("free_bet") ? fbSwr.data?.scanned_at : undefined,
    ].filter((s): s is string => !!s);
    if (candidates.length === 0) return null;
    return candidates.sort()[0]; // oldest
  }, [modes, arbSwr.data, lhSwr.data, evSwr.data, fbSwr.data]);
  const ageSeconds = scannedAtIso
    ? Math.max(
        0,
        Math.floor((Date.now() - new Date(scannedAtIso).getTime()) / 1000),
      )
    : null;
  const cacheStale = ageSeconds != null && ageSeconds > 300;
  const ageLabel =
    ageSeconds == null
      ? "unknown age"
      : ageSeconds < 60
      ? `${ageSeconds}s`
      : ageSeconds < 3600
      ? `${Math.round(ageSeconds / 60)}m`
      : `${Math.round(ageSeconds / 3600)}h`;

  const emptyStateElement = useMemo(() => {
    if (!allHaveData || sorted.length > 0) return null;

    // Filtered-to-zero (user-applied filter made this empty).
    if (rawCount > 0) {
      const modeLabel =
        modes.size === 1
          ? MODE_LONG_LABEL[[...modes][0]]
          : "cross-mode";
      return (
        <EmptyState
          title={`Your filters eliminated all ${modeLabel} edges`}
          body={`The underlying cache has ${rawCount} opportunit${rawCount === 1 ? "y" : "ies"}, but none pass your current filter combination. Relax a filter or clear the book scope to restore the list.`}
          hints={[
            {
              label: "Filter scope",
              hint: "book filter narrows which book the edge is on, not which books are used as anchors.",
            },
            {
              label: "Min-edge + max-odds",
              hint: "a tight min-edge combined with a short max-odds can eliminate all rows together even when either alone would pass.",
            },
          ]}
          action={{
            label: "Clear filters",
            onClick: () => {
              setBookFilter(new Set());
              setMinEdge(0);
              setMaxOdds(5000);
              setSport("all");
            },
          }}
        />
      );
    }

    // Single-mode empty.
    if (modes.size === 1) {
      const only = [...modes][0];
      if (only === "arb") {
        return (
          <EmptyState
            title="No arbitrage pairs in the current cache"
            body="Arbitrage requires two visible books offering opposite sides of the same market with implied probabilities summing under 100%. Right now that combination doesn't exist across your visible set."
            tone={cacheStale ? "warning" : "neutral"}
            hints={[
              {
                label: "Two-book minimum",
                hint: `your visible set has ${visible.size} book${visible.size !== 1 ? "s" : ""}; arbs need at least two that both post the same market.`,
              },
              {
                label: "Line matching",
                hint: "arbs also need matching points. Alt-line arbs are more common than mainline arbs but only surface if both sides of a non-main line are cached.",
              },
              {
                label: "Cache staleness",
                hint: `lines shift; a ${ageLabel}-old cache will keep showing yesterday's closed arbs or, more often, none.`,
              },
            ]}
            action={
              visible.size < 2
                ? {
                    label: "Enable more books in Settings",
                    onClick: () => router.push("/settings"),
                  }
                : { label: "Refresh now", onClick: refreshAll }
            }
          />
        );
      }
      if (only === "ev") {
        return (
          <EmptyState
            title={`No +EV plays above +${minEdge || 1}%`}
            body="Scanner compared every offered price against the de-vigged sharp consensus; nothing currently clears your min_ev floor. Lower the floor or wait for prices to move."
            tone={cacheStale ? "warning" : "neutral"}
            hints={[
              {
                label: "Anchor books",
                hint: "+EV uses Pinnacle (or Circa / the sharp consensus) as fair. If Pinnacle is hidden in Settings, the anchor falls back to consensus and the edge signal weakens.",
              },
              {
                label: "Filter overlap",
                hint: `min_ev ≥ ${minEdge || 1}% + max_odds ≤ +${maxOdds} can eliminate all rows together even when either alone would pass. Widen one.`,
              },
              {
                label: "Cache stale",
                hint: `scanner drops offered prices older than 300s. A stale cache can only surface closed edges; fresh ones come in after a fetcher cycle.`,
              },
            ]}
            action={{
              label: "Lower min EV to +1%",
              onClick: () => setMinEdge(1),
            }}
          />
        );
      }
      if (only === "low_hold") {
        return (
          <EmptyState
            title="No low-hold pairs under 2.5%"
            body="Low-hold means two offered prices that, together, produce a book's edge under your threshold — profitable when combined with promo or rakeback. None of the current visible pairs clear the bar."
            tone={cacheStale ? "warning" : "neutral"}
            hints={[
              {
                label: "Two-book minimum",
                hint: "same mechanic as arbs; low-hold requires opposite sides on different books at matched lines.",
              },
              {
                label: "Threshold tightness",
                hint: "most real-world pairs sit at 1.5–3%; sub-1% is rare outside promo windows.",
              },
              {
                label: "Cache age",
                hint: `prices drift fast at the 2%-hold band; a ${ageLabel}-old cache shows lagging rather than current pairs.`,
              },
            ]}
            action={{ label: "Refresh now", onClick: refreshAll }}
          />
        );
      }
      if (only === "free_bet") {
        return (
          <EmptyState
            title="No free-bet conversions match your stake"
            body={`Free-bet mode calculates the long-odds leg that maximizes EV when cashing a promo credit. Nothing in the cache currently returns enough $ at the configured stake of $${stake}.`}
            tone={cacheStale ? "warning" : "neutral"}
            hints={[
              {
                label: "Odds range",
                hint: `free-bet EV rises with longer odds; if max_odds ≤ +${maxOdds}, the long legs are capped out of the profitable zone.`,
              },
              {
                label: "Book availability",
                hint: "the long leg has to exist on a book you actually have a promo balance on. Filter the offered-book dropdown to match your active promos.",
              },
              {
                label: "Cache age",
                hint: `long-odds props and futures drift less often but stale out the same way; refresh if ${ageLabel} > a few minutes.`,
              },
            ]}
            action={{
              label: "Widen max odds to +1500",
              onClick: () => setMaxOdds(1500),
            }}
          />
        );
      }
    }

    // Defensive fallback — modes is a size-1 Set today, but keeps the
    // function total in case a future mode is added and one of the branches
    // above forgets to handle it.
    return (
      <EmptyState
        title="No edges right now"
        body={`Scanner last ran against a cache ${ageLabel} old.`}
        tone={cacheStale ? "warning" : "neutral"}
        action={{ label: "Refresh now", onClick: refreshAll }}
      />
    );
  }, [
    allHaveData,
    sorted.length,
    rawCount,
    modes,
    cacheStale,
    ageLabel,
    visible.size,
    minEdge,
    maxOdds,
    stake,
    refreshAll,
    router,
  ]);

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-4">
          <h1 className="text-2xl font-bold tracking-tight">Edges</h1>
          <span className="text-xs text-text-3 tabular">
            {MODE_LONG_LABEL[[...modes][0]]} scanner · {MODE_LABEL[[...modes][0]]} mode
          </span>
          {allHaveData && (
            <span className="text-xs text-text-3 tabular">
              {sorted.length !== rawCount
                ? `${sorted.length} / ${rawCount}`
                : `${rawCount}`}{" "}
              opportunities
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <FreshnessChip staleAfterSeconds={300} />
          <RefreshButton
            onRefresh={refreshAll}
            isValidating={anyValidating}
          />
        </div>
      </header>

      <div className="flex items-center gap-3 flex-wrap">
        <ModeToggle value={modes} onChange={setModes} />

        <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle">
          <select
            value={sport}
            onChange={e => setSport(e.target.value)}
            className="h-8 bg-bg-1 text-xs text-text-1 px-2 rounded-md border-0 outline-none"
            title="Filter by sport"
          >
            {sportOptions.map(o => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        <div className="inline-flex items-center gap-2 rounded-md bg-bg-1 border border-border-subtle h-8 px-2">
          <span className="text-[10px] uppercase tracking-wider text-text-3">
            Min edge
          </span>
          <input
            type="range"
            min={0}
            max={10}
            step={0.5}
            value={minEdge}
            onChange={e => setMinEdge(Number(e.target.value))}
            className="w-24 accent-accent"
          />
          <span className="tabular text-xs text-text-1 w-10 text-right">
            {minEdge === 0 ? "any" : `${minEdge}%`}
          </span>
        </div>

        <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
          {MAX_ODDS_OPTIONS.map(o => (
            <button
              key={o.value}
              type="button"
              onClick={() => setMaxOdds(o.value)}
              className={clsx(
                "px-2.5 py-1 text-[11px] tracking-wide uppercase transition-colors rounded-sm tabular",
                maxOdds === o.value
                  ? "bg-bg-2 text-text-1"
                  : "text-text-2 hover:text-text-1",
              )}
            >
              {o.label}
            </button>
          ))}
        </div>

        <BookIncludeDropdown
          label="Book"
          availableBooks={allBooksInPlay}
          selected={bookFilter}
          onChange={setBookFilter}
        />

        <div className="inline-flex items-center gap-1 rounded-md bg-bg-1 border border-border-subtle px-2 h-8">
          <span className="text-text-3 text-[10px] uppercase tracking-wider">
            Stake
          </span>
          <span className="text-text-3 text-xs">$</span>
          <input
            type="number"
            value={stake}
            onChange={e => setStake(clampStake(Number(e.target.value)))}
            min={50}
            max={1_000_000}
            step={50}
            className="w-20 bg-transparent text-xs tabular text-text-1 outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
            title="Per-row stake used for the Stake column. Persisted locally and via URL."
          />
        </div>
      </div>

      {anyError && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {anyLoading && !allHaveData && (
        <div className="text-text-2 text-sm">Scanning cache…</div>
      )}

      {allHaveData && sorted.length === 0 && emptyStateElement}

      {allHaveData && sorted.length > 0 && (
        <EdgesTable
          rows={sorted as EdgeOpportunity[]}
          expanded={expanded}
          onToggleExpand={toggleExpand}
          stake={stake}
          sortKey={sortKey}
          sortDir={sortDir}
          onSort={onSort}
        />
      )}
    </div>
  );
}
