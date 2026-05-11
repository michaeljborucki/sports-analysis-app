"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import clsx from "clsx";
import { EyeOff, FilterX, Inbox, MoreHorizontal, SearchX, Star } from "lucide-react";

import { apiPaths, type Game, type Market, type MarketOutcome, type SettingsResponse } from "@/lib/api";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { useLiveFilter } from "@/lib/use-live-filter";
import { usePinnedMarkets } from "@/lib/use-pinned-markets";
import { BOOK_ORDER } from "@/lib/books";
import type { SportKey } from "@/lib/sports";
import { matchesLiveFilter } from "./live-status-filter";
import { BookMatrixTable, type MatrixRow } from "./book-matrix-table";
import { EmptyState } from "./empty-state";


/**
 * Render player-prop book-by-book matrix for a given sport.
 *
 * Tabs (market_keys shown along the top) come from the user's Settings —
 * specifically the `player_props` tier for this sport, minus any
 * user-disabled markets. So if the user has only `player_points` and
 * `player_rebounds` enabled, only those tabs appear.
 *
 * One market at a time. Rows = (player, point) with Over/Under stacked.
 * Columns = visible books. Best price in each row is tinted.
 */
export function PropsMatrix({ sport, games }: { sport: SportKey; games: Game[] }) {
  const router = useRouter();
  const { visible } = useVisibleBooks();
  const { value: liveFilter, setValue: setLiveFilter } = useLiveFilter();
  const { data: settings } = useSWR<SettingsResponse>(apiPaths.settings);
  const { pins, toggle: togglePin, isPinned } = usePinnedMarkets(sport);

  // Apply the global Live / Pre / All filter to the games list first — all
  // downstream logic (tab discovery, book columns, row building) respects it.
  const filteredGames = useMemo(() => {
    if (liveFilter === "all") return games;
    return games.filter(g => matchesLiveFilter(g.commence_time, liveFilter));
  }, [games, liveFilter]);

  // Markets in-play across the current dataset's games (so tabs don't dangle
  // with zero data behind them). We also require at least one outcome that
  // the row parser can actually split into "<Player> Over/Under" — otherwise
  // markets like "First Team Basket" (win/lose style) show an enabled tab
  // that renders an empty matrix.
  const marketsInData = useMemo(() => {
    const s = new Set<string>();
    for (const g of filteredGames)
      for (const m of g.markets ?? []) {
        if (!isPropMarket(m.market_key)) continue;
        if (!m.outcomes.some(o => splitOutcome(o.outcome_name))) continue;
        s.add(m.market_key);
      }
    return s;
  }, [filteredGames]);

  // Enabled prop markets from Settings: the player_props tier for this sport
  // minus anything in disabled_markets. Intersect with what's actually in
  // the data so we don't show empty tabs.
  const enabledTabs = useMemo(() => {
    if (!settings) return [];
    const sportCfg = settings.sports.find(s => s.key === sport);
    if (!sportCfg) return [];
    const propsTier = sportCfg.tiers.find(t => t.name === "player_props");
    if (!propsTier) return [];
    const enabled = propsTier.markets
      .filter(m => m.enabled)
      .map(m => m.key)
      .filter(k => marketsInData.has(k));
    return enabled;
  }, [settings, sport, marketsInData]);

  // Diagnostic: did the user enable ANY prop markets for this sport in
  // Settings? Used by the empty-state to distinguish "Settings has nothing
  // enabled" (send them to /settings) from "Settings has markets enabled but
  // none are in the cache yet" (cache/fetcher issue).
  const propsEnabledInSettings = useMemo(() => {
    if (!settings) return false;
    const sportCfg = settings.sports.find(s => s.key === sport);
    if (!sportCfg) return false;
    const propsTier = sportCfg.tiers.find(t => t.name === "player_props");
    if (!propsTier) return false;
    return propsTier.markets.some(m => m.enabled);
  }, [settings, sport]);

  // Split enabledTabs into pinned (in user's pin-order) and unpinned (alpha by
  // label). Pin entries for markets currently disabled in Settings stay in
  // localStorage but drop out of `pinnedTabs` here — re-enabling restores them.
  const { pinnedTabs, unpinnedTabs } = useMemo(() => {
    const enabledSet = new Set(enabledTabs);
    const pinnedOrdered = pins.filter(k => enabledSet.has(k));
    const pinnedSet = new Set(pinnedOrdered);
    const unpinnedAlpha = enabledTabs
      .filter(k => !pinnedSet.has(k))
      .sort((a, b) => formatMarketLabel(a).localeCompare(formatMarketLabel(b)));
    return { pinnedTabs: pinnedOrdered, unpinnedTabs: unpinnedAlpha };
  }, [enabledTabs, pins]);

  const [activeMarket, setActiveMarket] = useState<string | null>(null);
  const [playerFilter, setPlayerFilter] = useState("");
  const [gameFilter, setGameFilter] = useState<string>("all");
  const [sideMode, setSideMode] = useState<"both" | "over" | "under">("both");
  const [moreOpen, setMoreOpen] = useState(false);

  // Remember the last-used market tab per sport so the props page doesn't
  // reset to market[0] every time the user switches sports or comes back
  // from another page. Keyed by sport so NBA's "Points" doesn't leak into
  // MLB's tab list.
  const activeMarketStorageKey = `props_active_market_${sport}`;

  // Seed active tab: prefer persisted value if still valid, otherwise the
  // first *pinned* enabled tab, otherwise the first enabled tab at all.
  // Pinning biases the first-open selection toward something the user cares
  // about, but an explicit last-active still wins even if it's unpinned
  // (so the user's last context isn't lost when they come back).
  useEffect(() => {
    if (activeMarket && enabledTabs.includes(activeMarket)) return;
    const persisted =
      typeof window !== "undefined"
        ? window.localStorage.getItem(activeMarketStorageKey)
        : null;
    if (persisted && enabledTabs.includes(persisted)) {
      setActiveMarket(persisted);
      return;
    }
    if (pinnedTabs.length > 0) {
      setActiveMarket(pinnedTabs[0]);
      return;
    }
    if (enabledTabs.length > 0) setActiveMarket(enabledTabs[0]);
    else setActiveMarket(null);
  }, [enabledTabs, pinnedTabs, activeMarket, activeMarketStorageKey]);

  // Persist whenever active tab changes (but only after it's been set).
  useEffect(() => {
    if (!activeMarket) return;
    if (typeof window !== "undefined") {
      window.localStorage.setItem(activeMarketStorageKey, activeMarket);
    }
  }, [activeMarket, activeMarketStorageKey]);

  // Active tab is rendered inline ("transient") if it's enabled but not
  // currently pinned — the in-between slot between pinned tabs and More.
  // If active is pinned we skip the inline slot since the pinned tab itself
  // already shows the active state.
  const activeIsTransient =
    activeMarket != null &&
    enabledTabs.includes(activeMarket) &&
    !pinnedTabs.includes(activeMarket);

  // Books to render as columns: visible set ∩ books that have prices in this
  // market across the filtered games. Ordered by registry priority.
  const bookColumns = useMemo(() => {
    if (!activeMarket) return [];
    const present = new Set<string>();
    for (const g of filteredGames) {
      if (gameFilter !== "all" && g.event_id !== gameFilter) continue;
      for (const m of g.markets ?? []) {
        if (m.market_key !== activeMarket) continue;
        for (const o of m.outcomes) {
          for (const p of o.prices) {
            if (visible.has(p.bookmaker_key)) present.add(p.bookmaker_key);
          }
        }
      }
    }
    return BOOK_ORDER.filter(b => present.has(b));
  }, [activeMarket, filteredGames, gameFilter, visible]);

  // Rows: one MatrixRow per (player, point). Over/Under come from the pair
  // of outcomes with "<Player> Over" / "<Player> Under" names at that point.
  // We return `rawRowCount` alongside so the empty-state can distinguish
  // "tab has no data at all" from "filter matched nothing".
  const { rows, rawRowCount } = useMemo<{ rows: MatrixRow[]; rawRowCount: number }>(() => {
    if (!activeMarket) return { rows: [], rawRowCount: 0 };
    type Bucket = { player: string; point: number | null; over?: MarketOutcome; under?: MarketOutcome };
    const buckets = new Map<string, Bucket>();
    for (const g of filteredGames) {
      if (gameFilter !== "all" && g.event_id !== gameFilter) continue;
      for (const m of g.markets ?? []) {
        if (m.market_key !== activeMarket) continue;
        for (const o of m.outcomes) {
          const parsed = splitOutcome(o.outcome_name);
          if (!parsed) continue;
          const point = firstPoint(o);
          const bk = `${parsed.player}|${point ?? "na"}`;
          let b = buckets.get(bk);
          if (!b) {
            b = { player: parsed.player, point };
            buckets.set(bk, b);
          }
          if (parsed.side === "Over") b.over = o;
          else if (parsed.side === "Under") b.under = o;
        }
      }
    }
    const filter = playerFilter.trim().toLowerCase();
    const rowsOut = Array.from(buckets.values())
      .filter(b =>
        filter === "" || b.player.toLowerCase().includes(filter)
      )
      .sort((a, b) => {
        const p = a.player.localeCompare(b.player);
        if (p !== 0) return p;
        return (a.point ?? 0) - (b.point ?? 0);
      })
      .map(b => ({
        key: `${b.player}|${b.point ?? "na"}`,
        label: b.player,
        sublabel: b.point != null ? `@ ${b.point}` : undefined,
        over: b.over,
        under: b.under,
      }));
    return { rows: rowsOut, rawRowCount: buckets.size };
  }, [activeMarket, filteredGames, gameFilter, playerFilter]);

  const gameOptions = useMemo(() => {
    return filteredGames.map(g => ({
      value: g.event_id,
      label: `${g.away_team} @ ${g.home_team}`,
    }));
  }, [filteredGames]);

  return (
    <div className="flex flex-col gap-3">
      {/* Market tabs: pinned tabs + (optional) transient active + More chip.
          The strip NEVER wraps — a horizontal scroll with a subtle right-edge
          fade handles the rare "user pinned a ton" case. Unpinned markets
          hide behind the More popover to keep the default tab set usable. */}
      {enabledTabs.length > 0 && (
        <div className="relative">
          <div className="overflow-x-auto no-scrollbar pr-6">
            <div className="inline-flex items-center gap-2 min-w-max">
              {pinnedTabs.map(key => (
                <MarketTab
                  key={key}
                  marketKey={key}
                  active={activeMarket === key}
                  pinned
                  onActivate={() => setActiveMarket(key)}
                  onTogglePin={() => togglePin(key)}
                />
              ))}
              {activeIsTransient && activeMarket && (
                <MarketTab
                  key={`transient-${activeMarket}`}
                  marketKey={activeMarket}
                  active
                  pinned={false}
                  transient
                  onActivate={() => { /* already active */ }}
                  onTogglePin={() => togglePin(activeMarket)}
                />
              )}
              <MoreChip
                count={unpinnedTabs.length}
                open={moreOpen}
                onOpenChange={setMoreOpen}
                unpinned={unpinnedTabs}
                activeMarket={activeMarket}
                onActivate={key => {
                  setActiveMarket(key);
                  setMoreOpen(false);
                }}
                onTogglePin={togglePin}
                isPinned={isPinned}
              />
            </div>
          </div>
          {/* Right-edge fade hints at horizontal overflow without a visible
              scrollbar. pointer-events-none so it doesn't eat clicks. */}
          <div
            aria-hidden
            className="pointer-events-none absolute top-0 right-0 h-full w-6 bg-gradient-to-l from-bg-0 to-transparent"
          />
        </div>
      )}

      {/* No-tabs empty state: either Settings has no player_props enabled,
          or Settings has some enabled but none appear in the cached data
          yet. Distinguish the two so the copy is actionable. */}
      {enabledTabs.length === 0 && (
        <EmptyState
          icon={<Inbox size={28} />}
          title={
            propsEnabledInSettings
              ? `No player-prop data cached yet for ${sport.toUpperCase()}`
              : `No player props enabled for ${sport.toUpperCase()}`
          }
          body={
            propsEnabledInSettings
              ? "Settings has prop markets enabled, but the cache has no prop outcomes for this sport yet. The fetcher pulls props on a slow tier — it may not have run this cycle."
              : "The player_props tier for this sport has nothing checked in Settings, so the fetcher isn't pulling any prop markets."
          }
          hints={
            propsEnabledInSettings
              ? [
                  { label: "Live filter", hint: `Current filter is "${liveFilter}" — Pre/Live can hide all games if the slate is on the wrong side.` },
                  { label: "Fetcher tier", hint: "Props sit on the slowest fetcher tier; a fresh cache cycle may not have populated them yet." },
                  { label: "Book coverage", hint: "If no visible book carries props for this sport, the matrix stays empty even with cached data." },
                ]
              : [
                  { label: "Enable markets", hint: "Open Settings, expand this sport, and check one or more markets under Player Props." },
                  { label: "Hot-reload", hint: "Saving Settings restarts the fetcher — prop data will appear within a cycle or two." },
                ]
          }
          action={{
            label: "Open Settings",
            onClick: () => router.push("/settings"),
          }}
          tone={propsEnabledInSettings ? "warning" : "neutral"}
        />
      )}

      {/* Filter bar */}
      {activeMarket && (
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="text"
            placeholder="Filter players…"
            value={playerFilter}
            onChange={e => setPlayerFilter(e.target.value)}
            className="h-8 px-3 rounded-md text-xs bg-bg-1 border border-border-subtle text-text-1 outline-none focus:border-accent/70 w-48"
          />
          <select
            value={gameFilter}
            onChange={e => setGameFilter(e.target.value)}
            className="h-8 px-2 rounded-md text-xs bg-bg-1 border border-border-subtle text-text-1 outline-none"
          >
            <option value="all">All games ({filteredGames.length})</option>
            {gameOptions.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
            {(["both", "over", "under"] as const).map(m => (
              <button
                key={m}
                onClick={() => setSideMode(m)}
                className={clsx(
                  "px-2.5 py-1 text-[11px] tracking-wide uppercase rounded-sm transition-colors",
                  sideMode === m
                    ? "bg-bg-2 text-text-1"
                    : "text-text-2 hover:text-text-1"
                )}
              >
                {m === "both" ? "O / U" : m === "over" ? "Over" : "Under"}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-text-3 tabular ml-2">
            {rows.length} row{rows.length === 1 ? "" : "s"} · {bookColumns.length} book{bookColumns.length === 1 ? "" : "s"}
          </span>
        </div>
      )}

      {/* Matrix */}
      {activeMarket && bookColumns.length === 0 && rawRowCount > 0 && (
        // Case 4 (pre-empt BookMatrixTable's own books=0 fallback): rows
        // exist in cache but no visible book carries this market. Likely a
        // sharp-only market with all sharp books hidden, or visible set
        // doesn't include any book that prices this prop.
        <EmptyState
          icon={<EyeOff size={28} />}
          title="No visible books carry this market"
          body={`${formatMarketLabel(activeMarket)} has cached prices, but none of your visible books currently post this market. Toggle a book on in Settings to see prices.`}
          hints={[
            { label: "Book visibility", hint: "Your visible-books set filters columns everywhere; turning one on lights up this matrix." },
            { label: "Sharp coverage", hint: "Mainstream books carry most props; niche markets often require a sharp book or an exchange." },
          ]}
          action={{
            label: "Open Settings",
            onClick: () => router.push("/settings"),
          }}
        />
      )}
      {activeMarket && !(bookColumns.length === 0 && rawRowCount > 0) && (
        <BookMatrixTable
          rows={rows}
          books={bookColumns}
          sideMode={sideMode}
          rowLabelHeader="Player"
          emptyMessage={
            rawRowCount === 0 ? (
              // Case 2: cache has zero rows for this market tab. Could be
              // cache age, live-filter killing the slate, or a single-game
              // filter. Give the user a one-click path to clear the filters
              // that *they* control.
              <EmptyState
                icon={<FilterX size={28} />}
                title={`No ${formatMarketLabel(activeMarket)} data yet for the current filters`}
                body="The tab is enabled and the fetcher is configured for this market, but nothing matches right now. Usually one of the filters below is masking the data."
                hints={[
                  {
                    label: "Live filter",
                    hint:
                      liveFilter === "all"
                        ? `"All" is active — this isn't hiding anything.`
                        : `Currently "${liveFilter}" — switching to All often reveals a slate on the other side.`,
                  },
                  {
                    label: "Game filter",
                    hint:
                      gameFilter === "all"
                        ? "All games selected — not masking anything."
                        : "A single game is selected; that game may not have this market posted.",
                  },
                  { label: "Cache age", hint: "Props sit on the slowest fetcher tier; a fresh cycle may not have populated them yet." },
                ]}
                action={
                  liveFilter !== "all" || gameFilter !== "all"
                    ? {
                        label: "Clear game & live filters",
                        onClick: () => {
                          setGameFilter("all");
                          setLiveFilter("all");
                        },
                      }
                    : undefined
                }
                tone="warning"
              />
            ) : playerFilter ? (
              // Case 3: the user typed a player filter that matched nothing.
              // Single-click clear is the right affordance.
              <EmptyState
                icon={<SearchX size={28} />}
                title={`No players match "${playerFilter}" in ${formatMarketLabel(activeMarket)}`}
                body={`The tab has ${rawRowCount} player${rawRowCount === 1 ? "" : "s"} cached, but none match your text filter.`}
                action={{
                  label: "Clear filter",
                  onClick: () => setPlayerFilter(""),
                }}
              />
            ) : (
              // Fallback: rows=0 but no player filter and rawRowCount>0 —
              // shouldn't normally happen since rows and rawRowCount move
              // together without a text filter. Keep terse.
              "No rows match current filters."
            )
          }
        />
      )}
    </div>
  );
}


/**
 * Single market tab pill. Star icon on the right toggles pin; body click
 * activates the tab. "Transient" variant (active-but-unpinned) gets a
 * dashed accent border and italic label — a restrained hint that this
 * tab isn't in the user's pinned set.
 */
function MarketTab({
  marketKey,
  active,
  pinned,
  transient = false,
  onActivate,
  onTogglePin,
}: {
  marketKey: string;
  active: boolean;
  pinned: boolean;
  transient?: boolean;
  onActivate: () => void;
  onTogglePin: () => void;
}) {
  return (
    <div
      className={clsx(
        "inline-flex items-center rounded-md text-xs font-medium tracking-wide transition-colors border",
        active
          ? "bg-bg-2 text-text-1"
          : "bg-bg-1 text-text-2 hover:text-text-1",
        active && !transient && "border-accent/50",
        active && transient && "border-accent/40 border-dashed",
        !active && "border-border-subtle"
      )}
      title={marketKey}
    >
      <button
        type="button"
        onClick={onActivate}
        className={clsx(
          "pl-3 pr-1.5 py-1 outline-none",
          transient && "italic"
        )}
      >
        {formatMarketLabel(marketKey)}
      </button>
      <button
        type="button"
        onClick={e => {
          // Pin toggle MUST NOT activate the tab — stop propagation so the
          // wrapper's click handlers (if any) don't fire.
          e.stopPropagation();
          onTogglePin();
        }}
        aria-label={pinned ? "Unpin market" : "Pin market"}
        title={pinned ? "Unpin market" : "Pin market"}
        className={clsx(
          "px-1.5 py-1 rounded-r-md transition-colors outline-none",
          pinned
            ? "text-accent hover:text-accent/80"
            : "text-text-3 hover:text-text-1"
        )}
      >
        <Star
          size={11}
          aria-hidden
          strokeWidth={1.6}
          fill={pinned ? "currentColor" : "none"}
        />
      </button>
    </div>
  );
}


/**
 * "More (N)" chip with popover. Lists all unpinned markets alphabetically;
 * click the body to activate (does NOT auto-pin — user opts in via star),
 * click the star to toggle pin (popover stays open so the user can
 * promote several at once). Closes on outside-click + Escape, matching
 * the BookIncludeDropdown pattern used elsewhere.
 */
function MoreChip({
  count,
  open,
  onOpenChange,
  unpinned,
  activeMarket,
  onActivate,
  onTogglePin,
  isPinned,
}: {
  count: number;
  open: boolean;
  onOpenChange: (v: boolean) => void;
  unpinned: string[];
  activeMarket: string | null;
  onActivate: (key: string) => void;
  onTogglePin: (key: string) => void;
  isPinned: (key: string) => boolean;
}) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        onOpenChange(false);
      }
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open, onOpenChange]);

  // Nothing to surface — hide the chip entirely to reduce chrome.
  if (count === 0) return null;

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className={clsx(
          "inline-flex items-center gap-1.5 px-3 py-1 rounded-md text-xs font-medium tracking-wide transition-colors",
          "bg-bg-1 text-text-2 hover:text-text-1 border border-border-subtle",
          open && "text-text-1 border-accent/40"
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <MoreHorizontal size={10} aria-hidden />
        More ({count})
      </button>
      {open && (
        <div
          className={clsx(
            "absolute top-full left-0 mt-2 z-20",
            "w-[260px] max-h-[70vh] overflow-y-auto",
            "bg-bg-1 border border-border-subtle rounded-md shadow-2xl"
          )}
          role="listbox"
        >
          <div className="sticky top-0 bg-bg-1 border-b border-border-subtle px-3 py-2 z-10">
            <span className="text-[11px] text-text-3 uppercase tracking-wider">
              Unpinned markets
            </span>
          </div>
          <div className="py-1">
            {unpinned.map(key => {
              const pinnedNow = isPinned(key);
              const isActive = activeMarket === key;
              return (
                <div
                  key={key}
                  className={clsx(
                    "flex items-center w-full text-xs transition-colors",
                    isActive ? "bg-bg-2 text-text-1" : "text-text-2 hover:bg-bg-2/50"
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onActivate(key)}
                    className="flex-1 px-3 py-1.5 text-left hover:text-text-1 outline-none"
                  >
                    {formatMarketLabel(key)}
                  </button>
                  <button
                    type="button"
                    onClick={e => {
                      e.stopPropagation();
                      onTogglePin(key);
                    }}
                    aria-label={pinnedNow ? "Unpin market" : "Pin market"}
                    title={pinnedNow ? "Unpin market" : "Pin market"}
                    className={clsx(
                      "px-2 py-1.5 transition-colors outline-none",
                      pinnedNow
                        ? "text-accent hover:text-accent/80"
                        : "text-text-3 hover:text-text-1"
                    )}
                  >
                    <Star
                      size={11}
                      aria-hidden
                      strokeWidth={1.6}
                      fill={pinnedNow ? "currentColor" : "none"}
                    />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}


function isPropMarket(key: string): boolean {
  return (
    key.startsWith("player_") ||
    key.startsWith("pitcher_") ||
    key.startsWith("batter_")
  );
}


function splitOutcome(raw: string): { player: string; side: "Over" | "Under" } | null {
  const trimmed = raw.trim();
  if (trimmed.endsWith(" Over")) return { player: trimmed.slice(0, -5), side: "Over" };
  if (trimmed.endsWith(" Under")) return { player: trimmed.slice(0, -6), side: "Under" };
  return null;
}


function firstPoint(o: MarketOutcome): number | null {
  return (
    o.best_price?.point ??
    o.prices[0]?.point ??
    null
  );
}


function formatMarketLabel(key: string): string {
  // Strip a leading sport-prefix (`player_`, `pitcher_`, `batter_`) and
  // title-case the rest. `player_points` → "Points",
  // `batter_total_bases` → "Total Bases".
  let core = key;
  for (const prefix of ["player_", "pitcher_", "batter_"]) {
    if (core.startsWith(prefix)) {
      core = core.slice(prefix.length);
      break;
    }
  }
  return core
    .replace(/_/g, " ")
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(/Rbis/g, "RBIs");
}
