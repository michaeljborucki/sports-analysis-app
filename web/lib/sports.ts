import type { components } from "@/types/api";

export type SportKey =
  | "mlb"
  | "tennis"
  | "nba"
  | "wnba"
  | "nhl"
  | "baseball_ncaa"
  | "asian_baseball"
  | "soccer"
  | "ufc"
  | "boxing"
  | "cricket";

export type DisplayKind = "moneyline" | "spread" | "total" | "yes_no";

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
      // NRFI = "no run first inning" — Yes/No on whether either team scores
      // in the 1st. Equivalent to U/O 0.5 runs in the 1st inning, but books
      // post it as a dedicated market with its own juice. Coral33 emits it
      // via the SCORE IN 1ST extras subtype (mapped to market_key="nrfi"
      // since 2026-05-03).
      { label: "NRFI", mainKey: "nrfi", display: "yes_no" },
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
  nba: {
    key: "nba",
    label: "NBA",
    teamDisplay: "last_name",
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
      { label: "Spread", mainKey: "spreads", altKey: "alternate_spreads", display: "spread" },
      { label: "Total", mainKey: "totals", altKey: "alternate_totals", display: "total" },
      // Halves
      { label: "1H ML", mainKey: "h2h_h1", display: "moneyline" },
      { label: "1H Spread", mainKey: "spreads_h1", altKey: "alternate_spreads_h1", display: "spread" },
      { label: "1H Total", mainKey: "totals_h1", altKey: "alternate_totals_h1", display: "total" },
      { label: "2H ML", mainKey: "h2h_h2", display: "moneyline" },
      { label: "2H Spread", mainKey: "spreads_h2", altKey: "alternate_spreads_h2", display: "spread" },
      { label: "2H Total", mainKey: "totals_h2", altKey: "alternate_totals_h2", display: "total" },
      // Quarters (Q1–Q4; data already pulled by the Odds API periods tier
      // via markets=h2h_qN / spreads_qN / totals_qN and their alt variants).
      { label: "Q1 ML", mainKey: "h2h_q1", display: "moneyline" },
      { label: "Q1 Spread", mainKey: "spreads_q1", altKey: "alternate_spreads_q1", display: "spread" },
      { label: "Q1 Total", mainKey: "totals_q1", altKey: "alternate_totals_q1", display: "total" },
      { label: "Q2 ML", mainKey: "h2h_q2", display: "moneyline" },
      { label: "Q2 Spread", mainKey: "spreads_q2", altKey: "alternate_spreads_q2", display: "spread" },
      { label: "Q2 Total", mainKey: "totals_q2", altKey: "alternate_totals_q2", display: "total" },
      { label: "Q3 ML", mainKey: "h2h_q3", display: "moneyline" },
      { label: "Q3 Spread", mainKey: "spreads_q3", altKey: "alternate_spreads_q3", display: "spread" },
      { label: "Q3 Total", mainKey: "totals_q3", altKey: "alternate_totals_q3", display: "total" },
      { label: "Q4 ML", mainKey: "h2h_q4", display: "moneyline" },
      { label: "Q4 Spread", mainKey: "spreads_q4", altKey: "alternate_spreads_q4", display: "spread" },
      { label: "Q4 Total", mainKey: "totals_q4", altKey: "alternate_totals_q4", display: "total" },
    ],
  },
  wnba: {
    key: "wnba",
    label: "WNBA",
    teamDisplay: "last_name",
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
      { label: "Spread", mainKey: "spreads", altKey: "alternate_spreads", display: "spread" },
      { label: "Total", mainKey: "totals", altKey: "alternate_totals", display: "total" },
      // Halves (1H confirmed across multiple books; 2H sparse on Odds API
      // and absent from coral33's catalog so omitted from the tab list)
      { label: "1H ML", mainKey: "h2h_h1", display: "moneyline" },
      { label: "1H Spread", mainKey: "spreads_h1", altKey: "alternate_spreads_h1", display: "spread" },
      { label: "1H Total", mainKey: "totals_h1", altKey: "alternate_totals_h1", display: "total" },
      // Q1 — coral33 supports it, Odds API has 6-7 books posting it
      { label: "Q1 ML", mainKey: "h2h_q1", display: "moneyline" },
      { label: "Q1 Spread", mainKey: "spreads_q1", altKey: "alternate_spreads_q1", display: "spread" },
      { label: "Q1 Total", mainKey: "totals_q1", altKey: "alternate_totals_q1", display: "total" },
    ],
  },
  nhl: {
    key: "nhl",
    label: "NHL",
    teamDisplay: "last_name",
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
      { label: "Puck Line", mainKey: "spreads", altKey: "alternate_spreads", display: "spread" },
      { label: "Total", mainKey: "totals", altKey: "alternate_totals", display: "total" },
      { label: "1P ML", mainKey: "h2h_p1", display: "moneyline" },
      { label: "1P Spread", mainKey: "spreads_p1", altKey: "alternate_spreads_p1", display: "spread" },
      { label: "1P Total", mainKey: "totals_p1", altKey: "alternate_totals_p1", display: "total" },
    ],
  },
  baseball_ncaa: {
    key: "baseball_ncaa",
    label: "NCAA Baseball",
    teamDisplay: "full",
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
      { label: "Run Line", mainKey: "spreads", altKey: "alternate_spreads", display: "spread" },
      { label: "Total", mainKey: "totals", altKey: "alternate_totals", display: "total" },
      { label: "F5 ML", mainKey: "h2h_1st_5_innings", display: "moneyline" },
      { label: "F5 RL", mainKey: "spreads_1st_5_innings", display: "spread" },
      { label: "F5 Total", mainKey: "totals_1st_5_innings", display: "total" },
    ],
  },
  asian_baseball: {
    key: "asian_baseball",
    label: "Asian Baseball",
    teamDisplay: "full",
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
      { label: "Run Line", mainKey: "spreads", altKey: "alternate_spreads", display: "spread" },
      { label: "Total", mainKey: "totals", altKey: "alternate_totals", display: "total" },
    ],
  },
  soccer: {
    key: "soccer",
    label: "Soccer",
    teamDisplay: "full",
    // Soccer h2h is 3-way (home/draw/away) — the 2-row odds grid will show
    // home + away legs and drop the draw row for now. Data is stored as 3
    // rows in the cache for scanner consumption; a 3-way UI pass comes later.
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
      { label: "Spread", mainKey: "spreads", display: "spread" },
      { label: "Total", mainKey: "totals", display: "total" },
    ],
  },
  ufc: {
    key: "ufc",
    label: "UFC",
    // Fighter names are short ("Sean Strickland") — render full so the grid
    // shows both first + last.
    teamDisplay: "full",
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
      // `totals` here is rounds over/under (e.g., O/U 2.5 rounds).
      { label: "Total Rounds", mainKey: "totals", display: "total" },
    ],
  },
  boxing: {
    key: "boxing",
    label: "Boxing",
    teamDisplay: "full",
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
      { label: "Total Rounds", mainKey: "totals", display: "total" },
    ],
  },
  cricket: {
    key: "cricket",
    label: "Cricket",
    teamDisplay: "full",
    marketGroups: [
      { label: "Moneyline", mainKey: "h2h", display: "moneyline" },
    ],
  },
};

export const SPORT_ORDER: SportKey[] = [
  "mlb", "nba", "wnba", "nhl", "baseball_ncaa", "asian_baseball",
  "tennis", "soccer", "ufc", "boxing", "cricket",
];

export function isSportKey(v: string): v is SportKey {
  return (
    v === "mlb" ||
    v === "tennis" ||
    v === "nba" ||
    v === "wnba" ||
    v === "nhl" ||
    v === "baseball_ncaa" ||
    v === "asian_baseball" ||
    v === "soccer" ||
    v === "ufc" ||
    v === "boxing" ||
    v === "cricket"
  );
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
