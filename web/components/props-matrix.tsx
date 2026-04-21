"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import clsx from "clsx";

import { apiPaths, type Game, type Market, type MarketOutcome, type SettingsResponse } from "@/lib/api";
import { useVisibleBooks } from "@/lib/use-visible-books";
import { useLiveFilter } from "@/lib/use-live-filter";
import { BOOK_ORDER } from "@/lib/books";
import type { SportKey } from "@/lib/sports";
import { matchesLiveFilter } from "./live-status-filter";
import { BookMatrixTable, type MatrixRow } from "./book-matrix-table";


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
  const { visible } = useVisibleBooks();
  const { value: liveFilter } = useLiveFilter();
  const { data: settings } = useSWR<SettingsResponse>(apiPaths.settings);

  // Apply the global Live / Pre / All filter to the games list first — all
  // downstream logic (tab discovery, book columns, row building) respects it.
  const filteredGames = useMemo(() => {
    if (liveFilter === "all") return games;
    return games.filter(g => matchesLiveFilter(g.commence_time, liveFilter));
  }, [games, liveFilter]);

  // Markets in-play across the current dataset's games (so tabs don't dangle
  // with zero data behind them).
  const marketsInData = useMemo(() => {
    const s = new Set<string>();
    for (const g of filteredGames)
      for (const m of g.markets ?? []) {
        if (isPropMarket(m.market_key)) s.add(m.market_key);
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

  const [activeMarket, setActiveMarket] = useState<string | null>(null);
  const [playerFilter, setPlayerFilter] = useState("");
  const [gameFilter, setGameFilter] = useState<string>("all");
  const [sideMode, setSideMode] = useState<"both" | "over" | "under">("both");

  // Seed active tab once the tab list resolves.
  useEffect(() => {
    if (activeMarket && enabledTabs.includes(activeMarket)) return;
    if (enabledTabs.length > 0) setActiveMarket(enabledTabs[0]);
    else setActiveMarket(null);
  }, [enabledTabs, activeMarket]);

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
  const rows = useMemo<MatrixRow[]>(() => {
    if (!activeMarket) return [];
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
    return Array.from(buckets.values())
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
  }, [activeMarket, filteredGames, gameFilter, playerFilter]);

  const gameOptions = useMemo(() => {
    return filteredGames.map(g => ({
      value: g.event_id,
      label: `${g.away_team} @ ${g.home_team}`,
    }));
  }, [filteredGames]);

  return (
    <div className="flex flex-col gap-3">
      {/* Market tabs */}
      <div className="flex items-center gap-2 flex-wrap">
        {enabledTabs.length === 0 ? (
          <span className="text-xs text-text-3">
            No prop markets enabled in Settings for this sport.
          </span>
        ) : (
          enabledTabs.map(key => (
            <button
              key={key}
              onClick={() => setActiveMarket(key)}
              className={clsx(
                "px-3 py-1 rounded-md text-xs font-medium tracking-wide transition-colors",
                activeMarket === key
                  ? "bg-bg-2 text-text-1 border border-accent/50"
                  : "bg-bg-1 text-text-2 hover:text-text-1 border border-border-subtle"
              )}
              title={key}
            >
              {formatMarketLabel(key)}
            </button>
          ))
        )}
      </div>

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
      {activeMarket && (
        <BookMatrixTable
          rows={rows}
          books={bookColumns}
          sideMode={sideMode}
          rowLabelHeader="Player"
          emptyMessage={
            playerFilter
              ? `No players match "${playerFilter}"`
              : `No data for ${formatMarketLabel(activeMarket)} yet.`
          }
        />
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
