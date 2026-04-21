"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import clsx from "clsx";

import { apiPaths, type Game, type Market, type MarketOutcome, type SettingsResponse } from "@/lib/api";
import { BOOK_ORDER } from "@/lib/books";
import { renderTeam } from "@/lib/sports";
import type { Sport } from "@/lib/sports";
import { BookMatrixTable, type MatrixRow, type SideLabels } from "./book-matrix-table";


type TabKey = "spreads" | "totals" | "team_totals";

// How many alt lines to keep on each side of a main row when collapsed.
// Picks a reasonable "±5 around mainline" default that keeps the drawer
// under ~11 rows per main without a user-configurable knob.
const COLLAPSE_WINDOW = 5;


interface TabConfig {
  key: TabKey;
  label: string;
  mainKey: string;
  altKey: string;
  sideLabels: SideLabels;
  rowLabelHeader: string;
}


/**
 * Per-game alt-line matrix. Used inside `MarketExpansionPanel` as the drawer
 * body when the outer odds-grid game row is expanded. Shows mains + alts in
 * one unified ladder, rows × books, with mainline row highlighted.
 *
 * Sub-tabs (Spreads / Totals / Team Totals) are driven by the Settings
 * page's `alternates` tier enable flags for this sport — a disabled market
 * doesn't show a tab. Default tab follows the outer market context so
 * clicking a Spread tab → expand gives an immediate Spread alt ladder.
 */
export function AltLinesMatrix({
  game,
  sport,
  visible,
  outerMarketKey,
}: {
  game: Game;
  sport: Sport;
  visible: Set<string>;
  /** The outer odds-grid tab's mainKey — used to seed the initial sub-tab. */
  outerMarketKey?: string;
}) {
  const { data: settings } = useSWR<SettingsResponse>(apiPaths.settings);

  // Which sub-tabs are enabled for this sport (Settings-driven + data-present)
  const availableTabs = useMemo(() => {
    const hasMarketData = (key: string) =>
      (game.markets ?? []).some(m => m.market_key === key);

    const allTabs: TabConfig[] = [
      {
        key: "spreads",
        label: "Spreads",
        mainKey: "spreads",
        altKey: "alternate_spreads",
        sideLabels: { over: renderTeam(game.away_team, sport), under: renderTeam(game.home_team, sport) },
        rowLabelHeader: "Line",
      },
      {
        key: "totals",
        label: "Totals",
        mainKey: "totals",
        altKey: "alternate_totals",
        sideLabels: { over: "O", under: "U" },
        rowLabelHeader: "Line",
      },
      {
        key: "team_totals",
        label: "Team Totals",
        mainKey: "team_totals",
        altKey: "alternate_team_totals",
        sideLabels: { over: "O", under: "U" },
        rowLabelHeader: "Team · Line",
      },
    ];

    const altEnabled = (marketKey: string) => {
      if (!settings) return true; // Before settings load, assume enabled
      const sportCfg = settings.sports.find(s => s.key === sport.key);
      if (!sportCfg) return true;
      const altTier = sportCfg.tiers.find(t => t.name === "alternates");
      if (!altTier) return true;
      // If the market isn't in the alternates tier at all, consider it "enabled"
      // for display purposes (mainline-only is still valid).
      const m = altTier.markets.find(x => x.key === marketKey);
      return m ? m.enabled : true;
    };

    return allTabs.filter(t =>
      // Show the tab if the mainline has data OR the alt is enabled and has data
      hasMarketData(t.mainKey) || (altEnabled(t.altKey) && hasMarketData(t.altKey))
    );
  }, [game, sport, settings]);

  // Default to the outer tab's group if that group is a spread/total/tt.
  const initialTab = useMemo<TabKey>(() => {
    const byOuter: Record<string, TabKey> = {
      spreads: "spreads",
      totals: "totals",
      team_totals: "team_totals",
    };
    const seeded = outerMarketKey ? byOuter[outerMarketKey] : undefined;
    if (seeded && availableTabs.some(t => t.key === seeded)) return seeded;
    return availableTabs[0]?.key ?? "spreads";
  }, [outerMarketKey, availableTabs]);

  const [activeTab, setActiveTab] = useState<TabKey>(initialTab);
  useEffect(() => {
    if (!availableTabs.some(t => t.key === activeTab)) {
      setActiveTab(availableTabs[0]?.key ?? "spreads");
    }
  }, [availableTabs, activeTab]);

  const tabCfg = availableTabs.find(t => t.key === activeTab);

  // Build rows: merge main + alt outcomes, keep a flag for which points are
  // the mainline so we can visually pin them.
  const { rows, books } = useMemo(() => {
    if (!tabCfg) return { rows: [] as MatrixRow[], books: [] as string[] };
    const mainM = game.markets?.find(m => m.market_key === tabCfg.mainKey);
    const altM = game.markets?.find(m => m.market_key === tabCfg.altKey);

    if (tabCfg.key === "spreads") {
      return buildSpreadRows(game, sport, mainM, altM, visible);
    }
    if (tabCfg.key === "totals") {
      return buildTotalRows(mainM, altM, visible);
    }
    return buildTeamTotalRows(game, sport, mainM, altM, visible);
  }, [tabCfg, game, sport, visible]);

  // Keep "collapsed vs expanded" state per-tab — switching tabs shouldn't
  // carry the user's last choice from a different market family.
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    setExpanded(false);
  }, [activeTab]);

  const displayedRows = useMemo(
    () => (expanded ? rows : collapseAroundMain(rows, COLLAPSE_WINDOW)),
    [rows, expanded],
  );
  const hiddenCount = rows.length - displayedRows.length;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        {availableTabs.length > 1 && (
          <div className="inline-flex self-start rounded-md bg-bg-1 border border-border-subtle p-0.5">
            {availableTabs.map(t => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                className={clsx(
                  "px-3 py-1 text-xs tracking-wide uppercase transition-colors rounded-sm",
                  activeTab === t.key
                    ? "bg-bg-2 text-text-1"
                    : "text-text-2 hover:text-text-1"
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
        {(hiddenCount > 0 || expanded) && (
          <button
            onClick={() => setExpanded(v => !v)}
            className="text-[11px] px-2 h-7 rounded-md border border-border-subtle text-text-2 hover:text-text-1 hover:border-accent/50 transition-colors tracking-wide"
            title={
              expanded
                ? `Collapse back to ±${COLLAPSE_WINDOW} alts around each main line`
                : `${hiddenCount} more alt line${hiddenCount === 1 ? "" : "s"} hidden`
            }
          >
            {expanded ? "Collapse" : `Show all (${rows.length})`}
          </button>
        )}
        <span className="text-[11px] text-text-3 tabular">
          {displayedRows.length} row{displayedRows.length === 1 ? "" : "s"} · {books.length} book{books.length === 1 ? "" : "s"}
        </span>
      </div>

      {tabCfg && (
        <BookMatrixTable
          rows={displayedRows}
          books={books}
          sideMode="both"
          sideLabels={tabCfg.sideLabels}
          rowLabelHeader={tabCfg.rowLabelHeader}
          emptyMessage={`No ${tabCfg.label.toLowerCase()} lines cached for this game yet.`}
        />
      )}
    </div>
  );
}


/**
 * Keep a small window of rows around each "main-line cluster". Main rows are
 * clustered (consecutive mains within `window*2` indices collapse into one
 * group) so dense main-line counts — which happen when many books quote
 * slightly different mainlines on the same side — don't blow the window up.
 * Each cluster contributes exactly `2*window+1` rows centered on its median
 * main. For team_totals, home and away form separate clusters naturally.
 */
function collapseAroundMain(rows: MatrixRow[], window: number): MatrixRow[] {
  if (rows.length <= window * 2 + 1) return rows;
  const mains = rows
    .map((r, i) => (r.isMain ? i : -1))
    .filter(i => i >= 0);
  const keep = new Set<number>();
  const addWindow = (anchor: number) => {
    for (let i = anchor - window; i <= anchor + window; i++) {
      if (i >= 0 && i < rows.length) keep.add(i);
    }
  };
  if (mains.length === 0) {
    addWindow(Math.floor(rows.length / 2));
  } else {
    const clusters: number[][] = [];
    for (const m of mains) {
      const last = clusters[clusters.length - 1];
      if (last && m - last[last.length - 1] <= window * 2) {
        last.push(m);
      } else {
        clusters.push([m]);
      }
    }
    for (const cluster of clusters) {
      addWindow(cluster[Math.floor(cluster.length / 2)]);
    }
  }
  return rows.filter((_, i) => keep.has(i));
}


// ------- row builders per market family -------

function pointOf(o: MarketOutcome): number | null {
  return o.best_price?.point ?? o.prices[0]?.point ?? null;
}

function visibleBooksFromMarkets(
  markets: (Market | undefined)[],
  visible: Set<string>
): string[] {
  const present = new Set<string>();
  for (const m of markets) {
    if (!m) continue;
    for (const o of m.outcomes) {
      for (const p of o.prices) {
        if (visible.has(p.bookmaker_key)) present.add(p.bookmaker_key);
      }
    }
  }
  return BOOK_ORDER.filter(b => present.has(b));
}


function buildSpreadRows(
  game: Game,
  sport: Sport,
  main: Market | undefined,
  alt: Market | undefined,
  visible: Set<string>
): { rows: MatrixRow[]; books: string[] } {
  // Main-line |point| set drives the MAIN badge
  const mainAbs = new Set<number>();
  for (const o of main?.outcomes ?? []) {
    const p = pointOf(o);
    if (p != null) mainAbs.add(Math.abs(p));
  }
  const all = [...(main?.outcomes ?? []), ...(alt?.outcomes ?? [])];
  // Group by |point|; pick one representative signed point per grouping (use
  // the home team's point — negative if home favored).
  const byAbs = new Map<
    number,
    { away?: MarketOutcome; home?: MarketOutcome; homePoint?: number }
  >();
  for (const o of all) {
    const p = pointOf(o);
    if (p == null) continue;
    const abs = round1(Math.abs(p));
    const bucket = byAbs.get(abs) ?? {};
    if (o.outcome_name === game.home_team) {
      bucket.home = o;
      bucket.homePoint = p;
    } else if (o.outcome_name === game.away_team) {
      bucket.away = o;
      if (bucket.homePoint === undefined) bucket.homePoint = -p;
    }
    byAbs.set(abs, bucket);
  }
  const rows: MatrixRow[] = [...byAbs.entries()]
    .sort(([, a], [, b]) => (a.homePoint ?? 0) - (b.homePoint ?? 0))
    .map(([absPoint, { away, home, homePoint }]) => {
      const signed = homePoint ?? absPoint;
      const label = signed > 0 ? `+${signed}` : `${signed}`;
      return {
        key: `s-${absPoint}`,
        label,
        sublabel: `${renderTeam(game.home_team, sport)} line`,
        over: away,   // left column = away team
        under: home,  // right column = home team
        isMain: mainAbs.has(absPoint),
      };
    });
  return { rows, books: visibleBooksFromMarkets([main, alt], visible) };
}


function buildTotalRows(
  main: Market | undefined,
  alt: Market | undefined,
  visible: Set<string>
): { rows: MatrixRow[]; books: string[] } {
  const mainPoints = new Set<number>();
  for (const o of main?.outcomes ?? []) {
    const p = pointOf(o);
    if (p != null) mainPoints.add(round1(p));
  }
  const byPoint = new Map<number, { over?: MarketOutcome; under?: MarketOutcome }>();
  for (const o of [...(main?.outcomes ?? []), ...(alt?.outcomes ?? [])]) {
    const p = pointOf(o);
    if (p == null) continue;
    const rp = round1(p);
    const bucket = byPoint.get(rp) ?? {};
    if (o.outcome_name === "Over") bucket.over = o;
    else if (o.outcome_name === "Under") bucket.under = o;
    byPoint.set(rp, bucket);
  }
  const rows: MatrixRow[] = [...byPoint.entries()]
    .sort(([a], [b]) => a - b)
    .map(([point, { over, under }]) => ({
      key: `t-${point}`,
      label: `${point}`,
      over,
      under,
      isMain: mainPoints.has(point),
    }));
  return { rows, books: visibleBooksFromMarkets([main, alt], visible) };
}


function buildTeamTotalRows(
  game: Game,
  sport: Sport,
  main: Market | undefined,
  alt: Market | undefined,
  visible: Set<string>
): { rows: MatrixRow[]; books: string[] } {
  // Main (team, point) keys for MAIN badge. Outcome names are now encoded as
  // "<team> Over" / "<team> Under" after the normalize.py team_totals fix,
  // so we extract the team by stripping the trailing side word.
  const mainKeys = new Set<string>();
  for (const o of main?.outcomes ?? []) {
    const { team, side } = splitTeamTotal(o.outcome_name);
    if (!side) continue;
    const p = pointOf(o);
    if (p == null) continue;
    mainKeys.add(`${team}|${round1(p)}`);
  }

  type Bucket = { team: string; point: number; over?: MarketOutcome; under?: MarketOutcome };
  const buckets = new Map<string, Bucket>();
  for (const o of [...(main?.outcomes ?? []), ...(alt?.outcomes ?? [])]) {
    const { team, side } = splitTeamTotal(o.outcome_name);
    if (!team || !side) continue;
    const p = pointOf(o);
    if (p == null) continue;
    const rp = round1(p);
    const k = `${team}|${rp}`;
    let b = buckets.get(k);
    if (!b) {
      b = { team, point: rp };
      buckets.set(k, b);
    }
    if (side === "Over") b.over = o;
    else b.under = o;
  }

  // Sort: home team first, then by point asc; then away team, then by point asc.
  const home = game.home_team;
  const away = game.away_team;
  const rows: MatrixRow[] = [...buckets.values()]
    .sort((a, b) => {
      const teamOrder = (t: string) => (t === home ? 0 : t === away ? 1 : 2);
      const to = teamOrder(a.team) - teamOrder(b.team);
      if (to !== 0) return to;
      return a.point - b.point;
    })
    .map(b => ({
      key: `tt-${b.team}-${b.point}`,
      label: `${renderTeam(b.team, sport)} ${b.point}`,
      over: b.over,
      under: b.under,
      isMain: mainKeys.has(`${b.team}|${b.point}`),
    }));

  return { rows, books: visibleBooksFromMarkets([main, alt], visible) };
}


function splitTeamTotal(outcomeName: string): { team: string; side: "Over" | "Under" | null } {
  const s = outcomeName.trim();
  if (s.endsWith(" Over")) return { team: s.slice(0, -5), side: "Over" };
  if (s.endsWith(" Under")) return { team: s.slice(0, -6), side: "Under" };
  // Pre-fix rows (outcome_name was just "Over"/"Under" without team) — return
  // empty team so we skip the row rather than collide across teams.
  return { team: "", side: null };
}


function round1(n: number): number {
  return Math.round(n * 10) / 10;
}
