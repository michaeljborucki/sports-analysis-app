"use client";
import { useEffect, useMemo, useState } from "react";

import type { Game } from "@/lib/api";
import { BOOK_ORDER } from "@/lib/books";
import { useVisibleBooks } from "@/lib/use-visible-books";
import type { Sport, MarketGroup } from "@/lib/sports";
import { groupSoccerGames } from "@/lib/soccer-leagues";
import { validAltLineSelection } from "@/lib/alt-line-availability";
import { MarketTabs } from "./market-tabs";
import { useLiveFilter } from "@/lib/use-live-filter";
import { matchesLiveFilter } from "../live-status-filter";
import { AltLinesSideSheet } from "./alt-lines-side-sheet";
import { LeagueSection, OddsGamesTable } from "./league-section";

export function OddsGrid({
  games: allGames,
  sport,
}: {
  games: Game[];
  sport: Sport;
}) {
  const { value: liveFilter } = useLiveFilter();
  // Re-evaluate live status against the browser clock rather than trusting
  // the server-computed `g.is_live` flag — the cache can be minutes stale
  // (esp. with the Odds API fetcher frozen) and a game that actually kicked
  // off an hour ago would otherwise still show as "pre".
  const games = useMemo(() => {
    if (liveFilter === "all") return allGames;
    return allGames.filter(g => matchesLiveFilter(g.commence_time, liveFilter));
  }, [allGames, liveFilter]);

  // Which market_groups actually have any data in this dataset
  const availableGroups = useMemo(() => {
    const present = new Set<string>();
    for (const g of games)
      for (const m of g.markets ?? []) present.add(m.market_key);
    return sport.marketGroups.filter(mg => present.has(mg.mainKey));
  }, [games, sport]);

  const fallbackGroup: MarketGroup =
    availableGroups[0] ?? sport.marketGroups[0];
  const [activeKey, setActiveKey] = useState<string>(fallbackGroup.mainKey);

  // If the sport changes (user switches via nav), clamp the selected market
  useEffect(() => {
    if (!sport.marketGroups.some(mg => mg.mainKey === activeKey)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- preserve the existing sport-switch clamp behavior
      setActiveKey(sport.marketGroups[0].mainKey);
    }
  }, [sport, activeKey]);

  const activeGroup: MarketGroup =
    sport.marketGroups.find(mg => mg.mainKey === activeKey) ??
    sport.marketGroups[0];

  // Which game's alt-lines sheet is open (null when closed). We store just
  // the event id and derive the game/market from current props + activeKey,
  // so switching market tabs with the sheet open transparently updates the
  // sheet body rather than forcing a close.
  const [sheetEventId, setSheetEventId] = useState<string | null>(null);
  const { visible } = useVisibleBooks();

  // If the open game disappears from the filtered list or loses the active
  // alternate-market coverage, the sheet would dangle with no content — close it.
  useEffect(() => {
    if (sheetEventId == null) return;
    if (validAltLineSelection(games, sheetEventId, sport.key, activeGroup) == null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- close the sheet when its selected game is filtered out
      setSheetEventId(null);
    }
  }, [games, sheetEventId, sport.key, activeGroup]);

  // Books present in this dataset, ordered by registry priority.
  const availableBooks = useMemo(() => {
    const present = new Set<string>();
    for (const g of games)
      for (const m of g.markets ?? [])
        for (const o of m.outcomes) for (const p of o.prices) present.add(p.bookmaker_key);
    const ordered = BOOK_ORDER.filter(b => present.has(b));
    const extras = [...present].filter(b => !BOOK_ORDER.includes(b)).sort();
    return [...ordered, ...extras];
  }, [games]);

  const books = useMemo(
    () => availableBooks.filter(b => visible.has(b)),
    [availableBooks, visible]
  );

  const soccerLeagueGroups = useMemo(
    () => sport.key === "soccer" ? groupSoccerGames(games) : [],
    [games, sport.key],
  );

  const tabs = availableGroups.map(g => ({ key: g.mainKey, label: g.label }));

  return (
    <div className="flex flex-col gap-3" data-sheet-keep-open>
      <div className="flex items-center gap-4 justify-between">
        <div className="flex items-center gap-4 flex-wrap">
          {tabs.length > 0 && (
            <MarketTabs
              value={activeKey}
              onChange={setActiveKey}
              tabs={tabs}
            />
          )}
          <div className="text-xs text-text-3 tabular">
            {games.length}
            {games.length !== allGames.length && ` / ${allGames.length}`} games
          </div>
        </div>
      </div>

      {sport.key === "soccer" && soccerLeagueGroups.length > 0 ? (
        <div className="flex flex-col gap-4">
          {soccerLeagueGroups.map(group => (
            <LeagueSection
              key={group.key}
              title={group.title}
              games={group.games}
              sport={sport}
              activeGroup={activeGroup}
              activeKey={activeKey}
              books={books}
              visible={visible}
              sheetEventId={sheetEventId}
              onToggleSheet={setSheetEventId}
            />
          ))}
        </div>
      ) : (
        <OddsGamesTable
          games={games}
          sport={sport}
          activeGroup={activeGroup}
          activeKey={activeKey}
          books={books}
          visible={visible}
          sheetEventId={sheetEventId}
          onToggleSheet={setSheetEventId}
        />
      )}

      <AltLinesSideSheet
        open={sheetEventId != null}
        onClose={() => setSheetEventId(null)}
        game={games.find(g => g.event_id === sheetEventId) ?? null}
        sport={sport}
        group={activeGroup}
        visible={visible}
      />
    </div>
  );
}
