import type { MarketGroup } from "./sports";

interface GameWithMarkets {
  markets?: Array<{ market_key: string }> | null;
}

/** Soccer alternate spreads are fetched per event, so coverage is event-specific. */
export function canExpandAltLines(
  game: GameWithMarkets,
  sportKey: string,
  group: Pick<MarketGroup, "mainKey" | "altKey">,
): boolean {
  if (sportKey !== "soccer" || group.altKey !== "alternate_spreads") return true;
  return game.markets?.some((market) => market.market_key === group.altKey) ?? false;
}

export function validAltLineSelection<T extends GameWithMarkets & { event_id: string }>(
  games: T[],
  selectedEventId: string | null,
  sportKey: string,
  group: Pick<MarketGroup, "mainKey" | "altKey">,
): string | null {
  if (selectedEventId == null) return null;
  const selectedGame = games.find((game) => game.event_id === selectedEventId);
  return selectedGame && canExpandAltLines(selectedGame, sportKey, group)
    ? selectedEventId
    : null;
}
