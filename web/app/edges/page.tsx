"use client";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";

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
import { BookIncludeList, bookSelectionSummary } from "@/components/book-include-dropdown";
import { RefreshButton } from "@/components/refresh-button";
import { FreshnessChip } from "@/components/freshness-chip";
import { EmptyState } from "@/components/empty-state";
import { BackendUnreachable, PageHeader, Segmented } from "@/components/ui";
import {
  FilterX,
  Gift,
  Inbox,
  Percent,
  Scale,
  TrendingUp,
} from "lucide-react";
import { BOOK_ORDER } from "@/lib/books";
import { SPORTS } from "@/lib/sports";
import {
  EDGE_MODES,
  mergeEdges,
  NOVIG_MAKER,
  sortEdges,
  type EdgeMode,
  type EdgeOpportunity,
  type SortDir,
  type SortKey,
} from "@/lib/edges";

import { ModeToggle } from "@/components/edges/mode-toggle";
import { EdgesTable } from "@/components/edges/edges-table";
import {
  FilterSentence,
  PopoverNumberInput,
  PopoverOptionList,
  type SentenceClause,
} from "@/components/edges/filter-sentence";
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

// Coral33 parlay-eligibility filter. Applies to arb, low-hold, EV and
// free-bet modes (every mode except profit-boost). For the paired modes it
// keys off the opportunity's coral33 leg — see server/odds/wager_filter.py.
//   any      — no filter (default)
//   straight — drop coral33 lines that are parlay-only; keep every other book
//   parlay   — show only coral33 lines that are parlay-eligible; drop everything else
type WagerFilter = "any" | "straight" | "parlay";

const WAGER_FILTER_OPTIONS: { label: string; value: WagerFilter }[] = [
  { label: "Any", value: "any" },
  { label: "Straight", value: "straight" },
  { label: "Parlay", value: "parlay" },
];

const WAGER_SENTENCE: Record<WagerFilter, string> = {
  any: "straight or parlay",
  straight: "straight only",
  parlay: "parlay-eligible only",
};

/** What the sentence filter calls each mode's rows: "Showing arbs in …". */
const MODE_NOUN: Record<EdgeMode, string> = {
  arb: "arbs",
  low_hold: "low-hold pairs",
  ev: "positive-EV bets",
  free_bet: "free-bet conversions",
  profit_boost: "profit-boost conversions",
};

// Novig pricing: "take" scans Novig at what you can fill right now; "maker"
// also scans the price you'd post (one tick above the best bid), so edges
// that only exist if your resting order fills show up too. Applies to the
// modes where a leg can be a resting order — never to free-bet / boost
// hedges, which must fill.
type NovigPricing = "take" | "maker";

const NOVIG_PRICING_OPTIONS: { label: string; value: NovigPricing }[] = [
  { label: "Take", value: "take" },
  { label: "Take + maker", value: "maker" },
];

const NOVIG_PRICING_SENTENCE: Record<NovigPricing, string> = {
  take: "take prices",
  maker: "take + maker prices",
};

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

const TIME_WINDOW_SENTENCE: Record<TimeWindow, string> = {
  all: "any time",
  today: "today",
  "24h": "within 24h",
  "48h": "within 48h",
  "72h": "within 72h",
};

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
  const [novigPricing, setNovigPricing] = useState<NovigPricing>(() =>
    searchParams.get("novig") === "maker" ? "maker" : "take",
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
    if (novigPricing === "maker") qs.set("novig", "maker");
    if (modes.has("profit_boost") && boostPct !== 30) qs.set("boost", String(boostPct));
    const qstring = qs.toString();
    const url = qstring ? `/edges?${qstring}` : "/edges";
    router.replace(url, { scroll: false });
  }, [modes, sport, minEdge, maxOdds, bookFilter, stake, minStake, timeWindow, wagerFilter, novigPricing, boostPct, router]);

  // Bankroll / Kelly / rounding for the per-row Kelly stake. Same store
  // the table's StakeCell reads — so the minStake filter compares to the
  // exact $ amount users see in the column.
  const prefs = useEdgesPrefs();

  // ─── Data fetching — 4 parallel SWR keys ───────────────────────
  const { visible } = useVisibleBooks();
  const booksSorted = useMemo(() => [...visible].sort(), [visible]);
  // Arb / low-hold / EV scan the virtual maker book only when asked to —
  // the backend never considers it otherwise (server/odds/venues.py).
  const makerModeActive =
    novigPricing === "maker" &&
    (modes.has("arb") || modes.has("low_hold") || modes.has("ev"));
  const scanBooks = useMemo(
    () => (makerModeActive ? [...booksSorted, NOVIG_MAKER].sort() : booksSorted),
    [booksSorted, makerModeActive],
  );

  const arbSwr = useSWR<ArbResponse>(
    modes.has("arb") ? apiPaths.arbitrage(scanBooks, wagerFilter) : null,
    { refreshInterval: 60_000 },
  );
  const lhSwr = useSWR<LowHoldResponse>(
    modes.has("low_hold")
      ? apiPaths.lowHold(scanBooks, 2.5, wagerFilter)
      : null,
    { refreshInterval: 60_000 },
  );
  // minEdge is a FLOOR on edge_pct. Backend always sorts desc, so without
  // a high max_results cap the bottom of the positive-EV tail gets cut off
  // (e.g. 500 rows of >3% hide the 0–3% band entirely). 5000 is enough to
  // surface the full positive (and slightly-negative) range without the UI
  // breaking.
  const evSwr = useSWR<EVResponse>(
    modes.has("ev")
      ? apiPaths.ev(scanBooks, {
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
      ? apiPaths.freeBets(booksSorted, 100, freeBetBooksSorted, wagerFilter)
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
      //   low_hold: edge_pct = −hold_pct (positive for arbs). Slider means
      //     MAX hold %, so a user picking 1.5 means "show me holds ≤ 1.5%",
      //     i.e. edge_pct ≥ −1.5, which naturally retains all positive arbs.
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
      const only = [...modes][0];
      return (
        <EmptyState
          icon={<FilterX size={28} />}
          title={`Your filters hide all ${rawCount} ${MODE_NOUN[only]}`}
          body="Relax a filter in the sentence above, or clear them all."
          hints={[
            {
              label: "Books",
              hint: "the book filter narrows which book the edge is on, not which books are used as anchors.",
            },
            {
              label: "Combined filters",
              hint: "a high minimum edge plus a low odds cap can hide everything even when each alone would not.",
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

    const stalenessHint = {
      label: "Cache age",
      hint: `prices are ${ageLabel} old. Edges close fast, so an old cache shows fewer of them.`,
    };

    // Single-mode empty.
    if (modes.size === 1) {
      const only = [...modes][0];
      if (only === "arb") {
        return (
          <EmptyState
            icon={<Scale size={28} />}
            title="No arbs right now"
            body="An arb needs two visible books pricing opposite sides of the same market for less than 100% combined. None do at the moment."
            tone={cacheStale ? "warning" : "neutral"}
            hints={[
              {
                label: "Books",
                hint: `you have ${visible.size} visible book${visible.size !== 1 ? "s" : ""}. Arbs need at least two posting the same market and line.`,
              },
              stalenessHint,
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
            title={`No positive-EV bets above ${minEdge || 1}%`}
            body="Every offered price was compared against the de-vigged sharp price. Nothing clears your minimum edge."
            tone={cacheStale ? "warning" : "neutral"}
            hints={[
              {
                label: "Anchor",
                hint: "fair price comes from Pinnacle, or a consensus if Pinnacle is hidden in Settings (a weaker signal).",
              },
              {
                label: "Odds cap",
                hint: `you're capping odds at +${maxOdds}. Raise it or lower the minimum edge.`,
              },
              {
                label: "Cache age",
                hint: "offered prices older than 5 minutes are dropped from the scan.",
              },
            ]}
            action={{
              label: "Lower minimum edge to 1%",
              onClick: () => setMinEdge(1),
            }}
          />
        );
      }
      if (only === "low_hold") {
        return (
          <EmptyState
            icon={<Percent size={28} />}
            title="No pairs with hold under 2.5%"
            body="Low hold is two opposite sides at different books whose combined margin is small, useful with promos or rakeback. None clear the bar right now."
            tone={cacheStale ? "warning" : "neutral"}
            hints={[
              {
                label: "Typical range",
                hint: "most real pairs sit at 1.5–3% hold. Under 1% is rare outside promo windows.",
              },
              stalenessHint,
            ]}
            action={{ label: "Refresh now", onClick: refreshAll }}
          />
        );
      }
      if (only === "free_bet") {
        return (
          <EmptyState
            icon={<Gift size={28} />}
            title="No free-bet conversions right now"
            body={`Nothing in the cache converts a $${stake.toLocaleString()} free bet well enough to show.`}
            tone={cacheStale ? "warning" : "neutral"}
            hints={[
              {
                label: "Free-bet book",
                hint: "the free bet must land on a book where you hold the promo. Check the book clause above.",
              },
              {
                label: "Long odds",
                hint: "free-bet value rises with longer odds, so wider markets convert better.",
              },
              stalenessHint,
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
            title={`No conversions at a ${boostPct}% boost`}
            body="Profit boost pairs a boosted side at your promo book with a hedge at another book. No pair locks in enough profit right now."
            tone={cacheStale ? "warning" : "neutral"}
            hints={[
              {
                label: "Boost size",
                hint: "the boost has to beat the market's hold. Tight -110/-110 markets need about 25% or more.",
              },
              {
                label: "Boost book",
                hint: "set which book holds your boost token. The hedge always lands at a different book.",
              },
            ]}
            action={{
              label: "Lower minimum conversion to 0%",
              onClick: () => setMinEdge(0),
            }}
          />
        );
      }
    }

    // Defensive fallback — modes is a size-1 Set today.
    return (
      <EmptyState
        icon={<Inbox size={28} />}
        title="No edges right now"
        body={`The scanner last ran against prices ${ageLabel} old.`}
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

  // ─── Sentence filter clauses ───────────────────────────────────
  const activeMode = [...modes][0] ?? DEFAULT_MODE;
  const isLowHold = modes.has("low_hold");
  const isConversion = modes.has("free_bet") || modes.has("profit_boost");

  const clauses: SentenceClause[] = [];
  clauses.push({
    id: "sport",
    before: "in",
    value: sport === "all" ? "all sports" : (sportOptions.find(o => o.value === sport)?.label ?? sport),
    heading: "Sport",
    flush: true,
    control: () => (
      <PopoverOptionList options={sportOptions} value={sport} onChange={setSport} />
    ),
  });
  clauses.push({
    id: "edge",
    before: isLowHold ? "hold below" : isConversion ? "conversion above" : "edge above",
    value:
      minEdge === 0 ? (
        "any"
      ) : (
        <span className="tabular">
          {!isLowHold && minEdge > 0 ? "+" : ""}
          {minEdge}%
        </span>
      ),
    heading: isLowHold ? "Maximum hold" : isConversion ? "Minimum conversion" : "Minimum edge",
    title: isLowHold
      ? "Max hold %: show pairs whose hold is at or below this"
      : "Min edge %: show rows whose edge is at or above this",
    control: () => (
      <span className="flex items-center gap-3">
        <input
          type="range"
          min={isLowHold ? 0 : -10}
          max={10}
          step={0.5}
          value={minEdge}
          onChange={e => setMinEdge(Number(e.target.value))}
          className="w-40 accent-text-1"
          aria-label={isLowHold ? "Maximum hold" : "Minimum edge"}
        />
        <span className="tabular w-12 text-right text-[length:var(--fs-13)] text-text-1">
          {minEdge === 0 ? "any" : `${!isLowHold && minEdge > 0 ? "+" : ""}${minEdge}%`}
        </span>
      </span>
    ),
  });
  if (modes.has("ev")) {
    const off = maxOdds >= MAX_ODDS_OFF_THRESHOLD;
    clauses.push({
      id: "maxOdds",
      before: "at odds up to",
      value: off ? "any" : <span className="tabular">+{maxOdds}</span>,
      heading: "Maximum odds",
      title: `Filter out long-odds offered prices (devig noise grows with odds). Type any value from +${MAX_ODDS_INPUT_MIN} to +${MAX_ODDS_INPUT_MAX} (effectively off).`,
      control: () => (
        <span className="flex flex-col gap-2">
          <PopoverNumberInput
            prefix="+"
            value={maxOdds}
            onChange={n => setMaxOdds(clampMaxOdds(n))}
            min={MAX_ODDS_INPUT_MIN}
            max={MAX_ODDS_INPUT_MAX}
            step={MAX_ODDS_INPUT_STEP}
          />
          <span className="text-[length:var(--fs-12)] text-text-3">
            <span className="tabular">+{MAX_ODDS_INPUT_MAX}</span> turns the cap off.
          </span>
        </span>
      ),
    });
  }
  if (modes.has("profit_boost")) {
    clauses.push({
      id: "boost",
      before: "with a",
      value: <span className="tabular">{boostPct}%</span>,
      after: "boost",
      heading: "Profit boost",
      title: "Profit-boost percentage applied to each offered price's winnings. 30 matches a typical DraftKings/FanDuel 30% boost. Range 0–100.",
      control: () => (
        <PopoverNumberInput
          suffix="%"
          value={boostPct}
          onChange={n => {
            if (!Number.isFinite(n)) return;
            setBoostPct(Math.max(0, Math.min(100, Math.round(n))));
          }}
          min={0}
          max={100}
          step={5}
        />
      ),
    });
  }
  clauses.push({
    id: "when",
    before: "starting",
    value: TIME_WINDOW_SENTENCE[timeWindow],
    heading: "Start time",
    control: () => (
      <Segmented
        size="sm"
        ariaLabel="Start time"
        options={TIME_WINDOW_OPTIONS}
        value={timeWindow}
        onChange={setTimeWindow}
      />
    ),
  });
  if (modes.has("arb") || modes.has("low_hold") || modes.has("ev")) {
    clauses.push({
      id: "novig",
      before: "with Novig at",
      value: NOVIG_PRICING_SENTENCE[novigPricing],
      heading: "Novig pricing",
      title:
        "Take: Novig at the price you can fill now. Take + maker: also scan the price you'd post one tick above the best bid (or joining it on a one-tick spread); rows that need your order to fill are marked Maker.",
      control: () => (
        <Segmented
          size="sm"
          ariaLabel="Novig pricing"
          options={NOVIG_PRICING_OPTIONS}
          value={novigPricing}
          onChange={setNovigPricing}
        />
      ),
    });
  }
  if (!modes.has("profit_boost")) {
    clauses.push({
      id: "wager",
      value: WAGER_SENTENCE[wagerFilter],
      heading: "Coral33 wager type",
      title: "Coral33 wager-type filter: straight vs parlay-eligible lines",
      control: () => (
        <Segmented
          size="sm"
          ariaLabel="Coral33 wager type"
          options={WAGER_FILTER_OPTIONS}
          value={wagerFilter}
          onChange={setWagerFilter}
        />
      ),
    });
  }
  clauses.push({
    id: "books",
    before:
      modes.has("free_bet") && modes.size === 1
        ? "with the free bet at"
        : modes.has("profit_boost") && modes.size === 1
          ? "with the boost at"
          : "at",
    value: bookSelectionSummary(
      bookFilter,
      modes.has("free_bet") || modes.has("profit_boost") ? "any book" : "all books",
    ),
    heading:
      modes.has("free_bet") && modes.size === 1
        ? "Free-bet book"
        : modes.has("profit_boost") && modes.size === 1
          ? "Boost book"
          : "Books",
    flush: true,
    control: () => (
      <BookIncludeList
        availableBooks={allBooksInPlay}
        selected={bookFilter}
        onChange={setBookFilter}
      />
    ),
  });
  if (!modes.has("ev")) {
    const stakeControl = () => (
      <PopoverNumberInput
        prefix="$"
        value={stake}
        onChange={n => setStake(clampStake(n))}
        min={50}
        max={1_000_000}
        step={50}
        title="Per-row stake used for the Stake column. Persisted locally and via URL."
      />
    );
    const stakeValue = <span className="tabular">${stake.toLocaleString()}</span>;
    if (modes.has("free_bet")) {
      clauses.push({
        id: "stake",
        before: "converting a",
        value: stakeValue,
        after: "free bet",
        heading: "Free-bet amount",
        control: stakeControl,
      });
    } else if (modes.has("profit_boost")) {
      clauses.push({
        id: "stake",
        before: "boosting",
        value: stakeValue,
        heading: "Boosted-leg stake",
        control: stakeControl,
      });
    } else {
      clauses.push({
        id: "stake",
        before: "staking",
        value: stakeValue,
        after: modes.has("low_hold") ? "per pair" : "per arb",
        heading: "Total stake per row",
        control: stakeControl,
      });
    }
  }
  clauses.push({
    id: "minStake",
    before: "with stakes of at least",
    value: minStake > 0 ? <span className="tabular">${minStake.toLocaleString()}</span> : "any size",
    heading: "Minimum stake",
    title: "Hide rows whose per-row stake is below this $ amount. Inclusive: a row at exactly $X passes a filter of $X.",
    control: () => (
      <PopoverNumberInput
        prefix="$"
        value={minStake}
        onChange={n => setMinStake(clampMinStake(n))}
        min={0}
        max={1_000_000}
        step={5}
        placeholder="0"
      />
    ),
  });

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Edges"
        inline={
          <ModeToggle
            value={modes}
            onChange={setModes}
            counts={{ [activeMode]: allHaveData ? sorted.length : null }}
          />
        }
        meta={<FreshnessChip staleAfterSeconds={300} />}
        actions={<RefreshButton onRefresh={refreshAll} isValidating={anyValidating} />}
      >
        <FilterSentence
          lead={<>Showing {MODE_NOUN[activeMode]}</>}
          clauses={clauses}
          aside={
            allHaveData ? (
              sorted.length !== rawCount ? (
                <>
                  <span className="tabular text-text-2">{sorted.length.toLocaleString()}</span> of{" "}
                  <span className="tabular">{rawCount.toLocaleString()}</span> shown
                </>
              ) : (
                <>
                  <span className="tabular text-text-2">{rawCount.toLocaleString()}</span> found
                </>
              )
            ) : null
          }
        />
      </PageHeader>

      {anyError && <BackendUnreachable error={anyError} />}
      {anyLoading && !allHaveData && (
        <div className="text-[length:var(--fs-13)] text-text-3">Scanning the cache…</div>
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
          showMaker={makerModeActive}
        />
      )}
    </div>
  );
}
