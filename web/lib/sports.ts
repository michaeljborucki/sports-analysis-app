import type { components } from "@/types/api";

export type SportKey = "mlb" | "tennis";

export type DisplayKind = "moneyline" | "spread" | "total";

export interface MarketGroup {
  label: string;
  mainKey: string;
  altKey?: string;
  display: DisplayKind;
}

export interface Sport {
  key: SportKey;
  label: string;
  /**
   * How team/player names render in the grid.
   *   abbrev    — MLB 3-letter codes (e.g., NYY, BOS)
   *   last_name — strip to the last token (tennis players: "R. Nadal" → "Nadal")
   *   full      — use the full string returned by the API
   */
  teamDisplay: "abbrev" | "last_name" | "full";
  marketGroups: MarketGroup[];
}

export const SPORTS: Record<SportKey, Sport> = {
  mlb: {
    key: "mlb",
    label: "MLB",
    teamDisplay: "abbrev",
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
      { label: "Run Line", mainKey: "spreads", altKey: "alternate_spreads", display: "spread" },
      { label: "Total", mainKey: "totals", altKey: "alternate_totals", display: "total" },
      { label: "F5 ML", mainKey: "h2h_1st_5_innings", display: "moneyline" },
      { label: "F5 RL", mainKey: "spreads_1st_5_innings", display: "spread" },
      { label: "F5 Total", mainKey: "totals_1st_5_innings", display: "total" },
    ],
  },
  tennis: {
    key: "tennis",
    label: "Tennis",
    teamDisplay: "last_name",
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
      { label: "Game Spread", mainKey: "spreads", altKey: "alternate_spreads", display: "spread" },
      { label: "Total Games", mainKey: "totals", altKey: "alternate_totals", display: "total" },
    ],
  },
};

export const SPORT_ORDER: SportKey[] = ["mlb", "tennis"];

export function isSportKey(v: string): v is SportKey {
  return v === "mlb" || v === "tennis";
}

export function getSport(key: SportKey): Sport {
  return SPORTS[key];
}

/** Team/player display driven by the per-sport registry. */
export function renderTeam(name: string, sport: Sport): string {
  if (sport.teamDisplay === "full") return name;
  if (sport.teamDisplay === "last_name") {
    // "R. Nadal", "Rafael Nadal" → "Nadal"
    const parts = name.trim().split(/\s+/);
    return parts[parts.length - 1] || name;
  }
  // abbrev — fall back to first-letter concat when we don't have a map
  const map: Record<string, string> = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK", "Athletics": "OAK",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD",
    "Seattle Mariners": "SEA", "San Francisco Giants": "SF", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
  };
  return (
    map[name] ??
    name
      .split(" ")
      .map(w => w[0])
      .join("")
      .slice(0, 3)
      .toUpperCase()
  );
}

export type ApiSport = components["schemas"]["SportModel"];
