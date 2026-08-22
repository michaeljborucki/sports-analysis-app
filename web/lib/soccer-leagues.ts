import type { components } from "@/types/api";

type Game = components["schemas"]["Game"];

export interface SoccerLeagueGroup {
  key: string;
  title: string;
  games: Game[];
  hasLive: boolean;
  earliestKickoff: string;
}

const OTHER_SOCCER_KEY = "__other_soccer__";

/** Groups soccer games for display, keeping live leagues ahead of upcoming leagues. */
export function groupSoccerGames(games: Game[]): SoccerLeagueGroup[] {
  const groupsByKey = new Map<string, SoccerLeagueGroup>();

  for (const game of games) {
    const key = game.league_key ?? OTHER_SOCCER_KEY;
    const group = groupsByKey.get(key) ?? {
      key,
      title: game.league_title || "Other Soccer",
      games: [],
      hasLive: false,
      earliestKickoff: game.commence_time,
    };

    group.games.push(game);
    group.hasLive ||= game.is_live;
    if (game.commence_time < group.earliestKickoff) {
      group.earliestKickoff = game.commence_time;
    }
    groupsByKey.set(key, group);
  }

  return [...groupsByKey.values()]
    .map((group) => ({
      ...group,
      games: group.games.sort((a, b) => a.commence_time.localeCompare(b.commence_time)),
    }))
    .sort((a, b) => {
      if (a.key === OTHER_SOCCER_KEY) return 1;
      if (b.key === OTHER_SOCCER_KEY) return -1;
      if (a.hasLive !== b.hasLive) return Number(b.hasLive) - Number(a.hasLive);
      return a.earliestKickoff.localeCompare(b.earliestKickoff) || a.title.localeCompare(b.title);
    });
}
