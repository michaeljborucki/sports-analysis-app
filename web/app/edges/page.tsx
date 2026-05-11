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
  type ProfitBoostResponse,
  type LowHoldResponse,
} from "@/lib/api";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { useLiveFilter } from "@/lib/use-live-filter";
import { matchesLiveFilter } from "@/components/live-status-filter";
import { BookIncludeDropdown } from "@/components/book-include-dropdown";
import { RefreshButton } from "@/components/refresh-button";
import { FreshnessChip } from "@/components/freshness-chip";
import { EmptyState } from "@/components/empty-state";
import {
  FilterX,
  Gift,
  Inbox,
  Percent,
  Scale,
  TrendingUp,
} from "lucide-react";
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
import { useEdgesPrefs } from "@/lib/use-edges-prefs";
import { computeRowStakeDollars } from "@/lib/stake-calc";

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

// Max-odds filter is a free-form number input. American + odds start at
// +100 (even money) and go up; we cap input at 5000 which is effectively
// "all" — any longer than +5000 prices are pure noise anyway. Step 25
// gives finer control around the practical band (+150…+400) without
// fighting +1 increments on the keyboard.
const MAX_ODDS_INPUT_MIN = 100;
const MAX_ODDS_INPUT_MAX = 5000;
const MAX_ODDS_INPUT_STEP = 25;
const MAX_ODDS_DEFAULT = 800;
// "Effectively no filter" — the filter step below treats any value >= this
// as a no-op so users can type 5000 or click the "All" toggle to disable.
const MAX_ODDS_OFF_THRESHOLD = 5000;

function clampMaxOdds(n: number): number {
  if (!Number.isFinite(n) || n <= 0) return MAX_ODDS_DEFAULT;
  return Math.max(
    MAX_ODDS_INPUT_MIN,
    Math.min(MAX_ODDS_INPUT_MAX, Math.round(n)),
  );
}

// Coral33 parlay-eligibility filter. Only meaningful in EV mode.
//   any      — no filter (default)
//   straight — drop coral33 lines that are parlay-only; keep every other book
//   parlay   — show only coral33 lines that are parlay-eligible; drop everything else
type WagerFilter = "any" | "straight" | "parlay";

const WAGER_FILTER_OPTIONS: { label: string; value: WagerFilter }[] = [
  { label: "Any", value: "any" },
  { label: "Straight", value: "straight" },
  { label: "Parlay", value: "parlay" },
];

function parseWagerFilter(raw: string | null): WagerFilter {
  if (raw === "straight" || raw === "parlay") return raw;
  return "any";
}

// Time-to-commence window. "today" is local-calendar-day (00:00 → 24:00),
// the others are rolling N-hour windows from now. Live games pass every
// option except "today" (which can exclude a game that started yesterday).
type TimeWindow = "all" | "today" | "24h" | "48h" | "72h";

const TIME_WINDOW_OPTIONS: { label: string; value: TimeWindow }[] = [
  { label: "All", value: "all" },
  { label: "Today", value: "today" },
  { label: "24h", value: "24h" },
  { label: "48h", value: "48h" },
  { label: "72h", value: "72h" },
];

function parseTimeWindow(raw: string | null): TimeWindow {
  if (!raw) return "all";
  return TIME_WINDOW_OPTIONS.some(o => o.value === raw)
    ? (raw as TimeWindow)
    : "all";
}

function matchesTimeWindow(commenceIso: string, win: TimeWindow): boolean {
  if (win === "all") return true;
  const t = new Date(commenceIso).getTime();
  if (!Number.isFinite(t)) return false;
  const now = Date.now();
  if (win === "today") {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 1);
    return t >= start.getTime() && t < end.getTime();
  }
  const hours = win === "24h" ? 24 : win === "48h" ? 48 : 72;
  return t <= now + hours * 3600 * 1000;
}

function clampStake(n: number): number {
  if (!Number.isFinite(n)) return 1000;
  return Math.max(50, Math.min(1_000_000, Math.round(n)));
}

// Min-stake filter floor in dollars. 0 = no filter (default). Capped at
// $1M just so a stray bookmark doesn't render the page empty forever.
function clampMinStake(n: number): number {
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.max(0, Math.min(1_000_000, Math.round(n)));
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
  // minEdge can go negative — useful in EV mode to surface the sharpest
  // *minus-EV* plays (short-side of the market, which a sharp bettor may
  // want to avoid or fade). Clamp [-10, +10] for sanity.
  const [minEdge, setMinEdge] = useState<number>(() => {
    const raw = searchParams.get("minEdge");
    const n = raw ? Number(raw) : 0;
    return Number.isFinite(n) ? Math.max(-10, Math.min(10, n)) : 0;
  });
  const [maxOdds, setMaxOdds] = useState<number>(() => {
    const raw = searchParams.get("maxOdds");
    if (!raw) return MAX_ODDS_DEFAULT;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? clampMaxOdds(n) : MAX_ODDS_DEFAULT;
  });
  const [timeWindow, setTimeWindow] = useState<TimeWindow>(() =>
    parseTimeWindow(searchParams.get("when")),
  );
  const [wagerFilter, setWagerFilter] = useState<WagerFilter>(() =>
    parseWagerFilter(searchParams.get("wager")),
  );
  const [bookFilter, setBookFilter] = useState<Set<string>>(() => {
    const raw = searchParams.get("books");
    if (!raw) return new Set();
    return new Set(raw.split(",").filter(Boolean));
  });
  const [stake, setStake] = useState<number>(() => {
    const raw = searchParams.get("stake");
    return clampStake(Number(raw));
  });
  const [minStake, setMinStake] = useState<number>(() =>
    clampMinStake(Number(searchParams.get("minStake"))),
  );
  // Profit-boost percentage. Clamped [0,100]; default 30 matches the
  // typical DraftKings/FanDuel "30% Profit Boost" promo.
  const [boostPct, setBoostPct] = useState<number>(() => {
    const raw = searchParams.get("boost");
    const n = raw ? Number(raw) : 30;
    if (!Number.isFinite(n)) return 30;
    return Math.max(0, Math.min(100, Math.round(n)));
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

  // Switching into low_hold flips the slider's meaning to "max hold %",
  // which has no useful negative value. Clamp once on entry so the
  // displayed widget doesn't desync from a bookmarked −1.5 from EV mode.
  useEffect(() => {
    if (modes.has("low_hold") && minEdge < 0) {
      setMinEdge(0);
    }
  }, [modes, minEdge]);

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
    if (minEdge !== 0) qs.set("minEdge", String(minEdge));
    if (maxOdds !== MAX_ODDS_DEFAULT) qs.set("maxOdds", String(maxOdds));
    if (bookFilter.size > 0) qs.set("books", [...bookFilter].sort().join(","));
    if (stake !== 1000) qs.set("stake", String(stake));
    if (minStake > 0) qs.set("minStake", String(minStake));
    if (timeWindow !== "all") qs.set("when", timeWindow);
    if (wagerFilter !== "any") qs.set("wager", wagerFilter);
    if (modes.has("profit_boost") && boostPct !== 30) qs.set("boost", String(boostPct));
    const qstring = qs.toString();
    const url = qstring ? `/edges?${qstring}` : "/edges";
    router.replace(url, { scroll: false });
  }, [modes, sport, minEdge, maxOdds, bookFilter, stake, minStake, timeWindow, wagerFilter, boostPct, router]);

  // Bankroll / Kelly / rounding for the per-row Kelly stake. Same store
  // the table's StakeCell reads — so the minStake filter compares to the
  // exact $ amount users see in the column.
  const prefs = useEdgesPrefs();

  // ─── Data fetching — 4 parallel SWR keys ───────────────────────
  const { visible } = useVisibleBooks();
  const booksSorted = useMemo(() => [...visible].sort(), [visible]);

  const arbSwr = useSWR<ArbResponse>(
    modes.has("arb") ? apiPaths.arbitrage(booksSorted) : null,
    { refreshInterval: 60_000 },
  );
  const lhSwr = useSWR<LowHoldResponse>(
    modes.has("low_hold") ? apiPaths.lowHold(booksSorted, 2.5) : null,
    { refreshInterval: 60_000 },
  );
  // minEdge is a FLOOR on edge_pct. Backend always sorts desc, so without
  // a high max_results cap the bottom of the positive-EV tail gets cut off
  // (e.g. 500 rows of >3% hide the 0–3% band entirely). 5000 is enough to
  // surface the full positive (and slightly-negative) range without the UI
  // breaking.
  const evSwr = useSWR<EVResponse>(
    modes.has("ev")
      ? apiPaths.ev(booksSorted, {
          minEv: minEdge,
          maxLongshotOdds: maxOdds,
          sort: "desc",
          maxResults: 5000,
          wagerFilter,
        })
      : null,
    { refreshInterval: 60_000 },
  );
  // In free-bet mode, the page's book filter re-purposes as the promo-book
  // scope: the free-bet leg MUST land at one of those books. Hedge leg is
  // allowed to use the full `booksSorted` (the visible universe).
  const freeBetBooksSorted = useMemo(
    () => [...bookFilter].sort(),
    [bookFilter],
  );
  const fbSwr = useSWR<FreeBetResponse>(
    modes.has("free_bet")
      ? apiPaths.freeBets(booksSorted, 100, freeBetBooksSorted)
      : null,
    { refreshInterval: 60_000 },
  );
  // Profit-boost: two-leg conversion scan. Boost is applied to one leg at
  // the user's "boost book" set (same UX as free-bet's `freeBetBooks`),
  // hedged on the opposite side at any other book in `booksSorted`. Boost
  // % goes into the SWR key so changing the input refetches.
  const pbSwr = useSWR<ProfitBoostResponse>(
    modes.has("profit_boost")
      ? apiPaths.profitBoost(booksSorted, {
          boostPct,
          boostBooks: freeBetBooksSorted,
          minConversion: Math.max(0, minEdge),
        })
      : null,
    { refreshInterval: 60_000 },
  );

  const refreshAll = useCallback(() => {
    if (modes.has("arb")) void arbSwr.mutate();
    if (modes.has("low_hold")) void lhSwr.mutate();
    if (modes.has("ev")) void evSwr.mutate();
    if (modes.has("free_bet")) void fbSwr.mutate();
    if (modes.has("profit_boost")) void pbSwr.mutate();
  }, [modes, arbSwr, lhSwr, evSwr, fbSwr, pbSwr]);

  const anyLoading =
    (modes.has("arb") && arbSwr.isLoading) ||
    (modes.has("low_hold") && lhSwr.isLoading) ||
    (modes.has("ev") && evSwr.isLoading) ||
    (modes.has("free_bet") && fbSwr.isLoading) ||
    (modes.has("profit_boost") && pbSwr.isLoading);
  const anyValidating =
    (modes.has("arb") && arbSwr.isValidating) ||
    (modes.has("low_hold") && lhSwr.isValidating) ||
    (modes.has("ev") && evSwr.isValidating) ||
    (modes.has("free_bet") && fbSwr.isValidating) ||
    (modes.has("profit_boost") && pbSwr.isValidating);
  const anyError =
    (modes.has("arb") && arbSwr.error) ||
    (modes.has("low_hold") && lhSwr.error) ||
    (modes.has("ev") && evSwr.error) ||
    (modes.has("free_bet") && fbSwr.error) ||
    (modes.has("profit_boost") && pbSwr.error);

  // ─── Merge + filter ────────────────────────────────────────────
  const merged = useMemo(
    () =>
      mergeEdges({
        arb: modes.has("arb") ? arbSwr.data?.opportunities : undefined,
        lowHold: modes.has("low_hold") ? lhSwr.data?.opportunities : undefined,
        ev: modes.has("ev") ? evSwr.data?.opportunities : undefined,
        freeBet: modes.has("free_bet") ? fbSwr.data?.opportunities : undefined,
        profitBoost: modes.has("profit_boost") ? pbSwr.data?.opportunities : undefined,
      }),
    [
      modes,
      arbSwr.data,
      lhSwr.data,
      evSwr.data,
      fbSwr.data,
      pbSwr.data,
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
    if (timeWindow !== "all") {
      rows = rows.filter(op => matchesTimeWindow(op.commence_time, timeWindow));
    }
    if (sport !== "all") {
      rows = rows.filter(op => op.sport_key === sport);
    }
    if (minEdge !== 0) {
      // Mode-aware semantics — the slider value's meaning flips per mode
      // because each mode's edge_pct lives in a different sign convention:
      //   arb:      edge_pct = roi_pct (≥ 0). Slider = MIN edge → keep ≥ value.
      //   ev:       edge_pct = ev_pct (any sign). Slider = MIN edge → keep ≥ value.
      //   free_bet: edge_pct = conversion_pct (≥ 0). Slider = MIN edge → keep ≥ value.
      //   low_hold: edge_pct = −hold_pct (≤ 0). Slider value here means
      //     MAX hold %, so a user picking 1.5 means "show me holds ≤ 1.5%",
      //     i.e. edge_pct ≥ −1.5. Negative slider values are nonsensical
      //     for low-hold and just no-op.
      if (modes.has("low_hold")) {
        if (minEdge > 0) {
          rows = rows.filter(op => op.edge_pct >= -minEdge);
        }
      } else {
        rows = rows.filter(op => op.edge_pct >= minEdge);
      }
    }
    if (maxOdds > 0 && maxOdds < MAX_ODDS_OFF_THRESHOLD) {
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
    // Min-stake floor — drop rows whose computed per-row $ stake is
    // below `minStake`. Inclusive: a row at exactly $X passes a filter
    // of $X. Uses the same math `StakeCell` renders, so what you set is
    // what you see in the column.
    if (minStake > 0) {
      rows = rows.filter(
        op =>
          computeRowStakeDollars(op, {
            bankroll: prefs.bankroll,
            kellyFrac: prefs.kellyFrac,
            rounding: prefs.rounding,
            stake,
          }) >= minStake,
      );
    }
    return rows;
  }, [merged, modes, liveFilter, sport, minEdge, maxOdds, bookFilter, timeWindow, minStake, stake, prefs.bankroll, prefs.kellyFrac, prefs.rounding]);

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
    (!modes.has("free_bet") || fbSwr.data != null) &&
    (!modes.has("profit_boost") || pbSwr.data != null);

  // Freshness age for tone + hint copy.
  const scannedAtIso = useMemo(() => {
    const candidates = [
      modes.has("arb") ? arbSwr.data?.scanned_at : undefined,
      modes.has("low_hold") ? lhSwr.data?.scanned_at : undefined,
      modes.has("ev") ? evSwr.data?.scanned_at : undefined,
      modes.has("free_bet") ? fbSwr.data?.scanned_at : undefined,
      modes.has("profit_boost") ? pbSwr.data?.scanned_at : undefined,
    ].filter((s): s is string => !!s);
    if (candidates.length === 0) return null;
    return candidates.sort()[0]; // oldest
  }, [modes, arbSwr.data, lhSwr.data, evSwr.data, fbSwr.data, pbSwr.data]);
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
          icon={<FilterX size={28} />}
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
              setMaxOdds(MAX_ODDS_INPUT_MAX);
              setSport("all");
              setTimeWindow("all");
              setWagerFilter("any");
              setMinStake(0);
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
            icon={<Scale size={28} />}
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
            icon={<TrendingUp size={28} />}
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
            icon={<Percent size={28} />}
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
            icon={<Gift size={28} />}
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
      if (only === "profit_boost") {
        return (
          <EmptyState
            icon={<TrendingUp size={28} />}
            title={`No profit-boost conversions at +${boostPct}% boost`}
            body="Profit-boost mode finds two-leg conversions: boost one side at your promo book, hedge the opposite side at another book to lock in profit. None of the current pairs clear the conversion threshold."
            tone={cacheStale ? "warning" : "neutral"}
            hints={[
              {
                label: "Boost beats vig",
                hint: "for a pair to convert, the boosted leg's improvement has to overcome the book's hold. Tight markets (-110/-110) need ~25%+ boost; long lines convert at smaller boost %.",
              },
              {
                label: "Book scope",
                hint: "use the Book filter to set which book has your boost token. The hedge leg always lands at a DIFFERENT book in your visible set.",
              },
              {
                label: "Min conversion",
                hint: `the min-edge slider doubles as a min-conversion-% floor here. Lower it (or set negative) to surface near-breakeven pairs that may still be worth grinding.`,
              },
            ]}
            action={{
              label: "Lower min conversion to 0%",
              onClick: () => setMinEdge(0),
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
        icon={<Inbox size={28} />}
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
    boostPct,
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
            isValidating={anyValidating} />
        </div>
      </header>

      {/* Mode picker on its own line — separates the "what kind of edge"
          choice (which reshapes the filter row's contents) from the
          "narrow this list" filters underneath. */}
      <div className="flex items-center">
        <ModeToggle value={modes} onChange={setModes} />
      </div>

      <div className="flex items-center gap-3 flex-wrap">
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
            {modes.has("low_hold") ? "Max hold" : "Min edge"}
          </span>
          <input
            type="range"
            min={modes.has("low_hold") ? 0 : -10}
            max={10}
            step={0.5}
            value={minEdge}
            onChange={e => setMinEdge(Number(e.target.value))}
            className="w-24 accent-accent"
            title={
              modes.has("low_hold")
                ? "Max hold %: show pairs whose hold is at or below this"
                : "Min edge %: show rows whose edge is at or above this"
            }
          />
          <span className="tabular text-xs text-text-1 w-12 text-right">
            {minEdge === 0
              ? "any"
              : modes.has("low_hold")
                ? `≤${minEdge}%`
                : `${minEdge > 0 ? "+" : ""}${minEdge}%`}
          </span>
        </div>

        {modes.has("ev") && (
          <div
            className="inline-flex items-center gap-1 rounded-md bg-bg-1 border border-border-subtle h-8 px-2"
            title={`Filter out long-odds offered prices (devig noise grows with odds). Type any value from +${MAX_ODDS_INPUT_MIN} to +${MAX_ODDS_INPUT_MAX} (effectively off).`}
          >
            <span className="text-[10px] uppercase tracking-wider text-text-3">
              Max odds
            </span>
            <span className="text-text-3 text-xs">≤</span>
            <span className="text-text-3 text-xs">+</span>
            <input
              type="number"
              value={maxOdds}
              onChange={e => setMaxOdds(clampMaxOdds(Number(e.target.value)))}
              min={MAX_ODDS_INPUT_MIN}
              max={MAX_ODDS_INPUT_MAX}
              step={MAX_ODDS_INPUT_STEP}
              className="w-16 bg-transparent text-xs tabular text-text-1 outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
            />
            {maxOdds >= MAX_ODDS_OFF_THRESHOLD && (
              <span className="text-text-3 text-[10px] uppercase tracking-wider ml-0.5">
                off
              </span>
            )}
          </div>
        )}

        {modes.has("profit_boost") && (
          <div
            className="inline-flex items-center gap-1 rounded-md bg-bg-1 border border-border-subtle h-8 px-2"
            title="Profit-boost percentage applied to each offered price's winnings. 30 matches a typical DraftKings/FanDuel 30% boost. Range 0–100."
          >
            <span className="text-[10px] uppercase tracking-wider text-text-3">
              Boost
            </span>
            <input
              type="number"
              value={boostPct}
              onChange={e => {
                const n = Number(e.target.value);
                if (!Number.isFinite(n)) return;
                setBoostPct(Math.max(0, Math.min(100, Math.round(n))));
              }}
              min={0}
              max={100}
              step={5}
              className="w-12 bg-transparent text-xs tabular text-text-1 outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none text-right"
            />
            <span className="text-text-3 text-xs">%</span>
          </div>
        )}

        <div
          className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5"
          title="Filter by game start time"
        >
          {TIME_WINDOW_OPTIONS.map(o => (
            <button
              key={o.value}
              type="button"
              onClick={() => setTimeWindow(o.value)}
              className={clsx(
                "px-2.5 py-1 text-[11px] tracking-wide uppercase transition-colors rounded-sm tabular",
                timeWindow === o.value
                  ? "bg-bg-2 text-text-1"
                  : "text-text-2 hover:text-text-1",
              )}
            >
              {o.label}
            </button>
          ))}
        </div>

        {modes.has("ev") && (
          <div
            className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5"
            title="Coral33 wager-type filter — Straight (default tab) vs Parlay-eligible only"
          >
            {WAGER_FILTER_OPTIONS.map(o => (
              <button
                key={o.value}
                type="button"
                onClick={() => setWagerFilter(o.value)}
                className={clsx(
                  "px-2.5 py-1 text-[11px] tracking-wide uppercase transition-colors rounded-sm tabular",
                  wagerFilter === o.value
                    ? "bg-bg-2 text-text-1"
                    : "text-text-2 hover:text-text-1",
                )}
              >
                {o.label}
              </button>
            ))}
          </div>
        )}

        <BookIncludeDropdown
          label={
            modes.has("free_bet") && modes.size === 1
              ? "Free-bet book"
              : modes.has("profit_boost") && modes.size === 1
                ? "Boost book"
                : "Book"
          }
          availableBooks={allBooksInPlay}
          selected={bookFilter}
          onChange={setBookFilter}
        />

        {!modes.has("ev") && (
          <div className="inline-flex items-center gap-1 rounded-md bg-bg-1 border border-border-subtle px-2 h-8">
            <span className="text-text-3 text-[10px] uppercase tracking-wider">
              {modes.has("free_bet") ? "Free face" : "Stake"}
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
        )}

        {/* Min-stake floor — drops rows whose per-row $ stake (matches
            the Stake column exactly) is below this threshold. 0 = off. */}
        <div
          className="inline-flex items-center gap-1 rounded-md bg-bg-1 border border-border-subtle px-2 h-8"
          title="Hide rows whose per-row stake is below this $ amount. Inclusive: a row at exactly $X passes a filter of $X."
        >
          <span className="text-text-3 text-[10px] uppercase tracking-wider">
            Min stake
          </span>
          <span className="text-text-3 text-xs">$</span>
          <input
            type="number"
            value={minStake}
            onChange={e => setMinStake(clampMinStake(Number(e.target.value)))}
            min={0}
            max={1_000_000}
            step={5}
            placeholder="0"
            className="w-16 bg-transparent text-xs tabular text-text-1 outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
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
