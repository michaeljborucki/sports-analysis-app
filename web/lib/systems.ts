export type SystemStatus =
  | "qualified"
  | "no_match"
  | "no_slate"
  | "unable_to_evaluate"
  | "disabled";

export type SystemsTimeframe = "today" | "tomorrow" | "upcoming";

export interface SystemEvaluation {
  system_id: string;
  short_id: string;
  system_name: string;
  sport: "mlb" | "ncaaf" | "nfl";
  bet_type: string;
  source_claim: string;
  rule_status: string;
  status: SystemStatus;
  match_count: number;
  evaluated_games: number;
  skipped_games: number;
  missing_fields: string[];
}

export interface SystemSignal {
  system_id: string;
  system_name: string;
  sport: string;
  event_id: string;
  home_team: string;
  away_team: string;
  commence_time: string;
  bet_type: string;
  selection: string;
  market_line: number | null;
  price_american: number | null;
  book: string | null;
  qualification_reason: string;
  data_timestamp: string;
  evaluated_at: string;
}

export interface WagerCandidate {
  sport: string;
  event_id: string;
  home_team: string;
  away_team: string;
  commence_time: string;
  bet_type: string;
  selection: string;
  market_line: number | null;
  price_american: number | null;
  book: string | null;
  qualification_reason: string;
  data_timestamp: string;
  supporting_system_ids: string[];
  supporting_system_names: string[];
}

export interface SystemsResponse {
  requested_date: string;
  timeframe: SystemsTimeframe | "date";
  timezone: string;
  evaluated_at: string;
  evaluations: SystemEvaluation[];
  signals: SystemSignal[];
  wagers: WagerCandidate[];
  summary: {
    qualifying_systems: number;
    qualifying_wagers: number;
    no_match: number;
    no_slate: number;
    unable_to_evaluate: number;
    disabled: number;
  };
  context_warnings: string[];
}

/** Opposing system directions, even at different lines; not a bet settlement test. */
export function conflictingWagers(wagers: WagerCandidate[]): Set<WagerCandidate> {
  const groups = new Map<string, { sides: Set<string>; wagers: WagerCandidate[] }>();
  for (const wager of wagers) {
    let side: string | undefined;
    if (wager.bet_type === "total") {
      side = /^(over|under)\b/i.exec(wager.selection)?.[1].toLowerCase();
    } else if (wager.bet_type === "spread" || wager.bet_type === "moneyline") {
      for (const team of [wager.home_team, wager.away_team]) {
        if (wager.selection === team || wager.selection.startsWith(`${team} `)) side = team;
      }
    }
    if (!side) continue;
    const key = JSON.stringify([wager.sport, wager.event_id, wager.bet_type]);
    const group = groups.get(key) ?? { sides: new Set<string>(), wagers: [] };
    group.sides.add(side);
    group.wagers.push(wager);
    groups.set(key, group);
  }
  return new Set([...groups.values()].filter(group => group.sides.size > 1).flatMap(group => group.wagers));
}

export const SPORT_LABELS = {
  mlb: "MLB",
  ncaaf: "College football",
  nfl: "NFL",
} as const;

export function groupEvaluations<T extends { sport: keyof typeof SPORT_LABELS }>(
  evaluations: T[],
): Record<string, T[]> {
  const grouped: Record<string, T[]> = {};
  for (const key of ["mlb", "ncaaf", "nfl"] as const) {
    grouped[SPORT_LABELS[key]] = evaluations.filter(item => item.sport === key);
  }
  return grouped;
}

export function parseTimeframe(value: string | null): SystemsTimeframe {
  return value === "tomorrow" || value === "upcoming" ? value : "today";
}

export function statusLabel(status: SystemStatus, timeframe: SystemsTimeframe = "today"): string {
  return {
    qualified: "Qualified",
    no_match: timeframe === "today" ? "No match today" : timeframe === "tomorrow" ? "No match tomorrow" : "No upcoming match",
    no_slate: timeframe === "today" ? "No games today" : timeframe === "tomorrow" ? "No games tomorrow" : "No upcoming games",
    unable_to_evaluate: "Unable to evaluate",
    disabled: "Disabled",
  }[status];
}

export function formatAmerican(value: number | null): string {
  if (value == null) return "—";
  return value > 0 ? `+${value}` : String(value);
}

const CONTEXT_SPORTS: [RegExp, string][] = [
  [/college-football|\bncaaf\b/i, "College football"],
  [/\/football\/nfl|\bnfl\b/i, "NFL"],
  [/\/baseball\/mlb|\bmlb\b/i, "MLB"],
];

/**
 * Plain-language headline for the raw context warnings. The raw messages
 * (upstream URLs, HTTP errors) belong in a details disclosure, not here.
 */
export function contextWarningTitle(warnings: string[], unableToEvaluate: number): string {
  const text = warnings.join("\n");
  const sports = CONTEXT_SPORTS.filter(([re]) => re.test(text)).map(([, label]) => label);
  const what = sports.length > 0 ? `${sports.join(" and ")} context` : "Some game context";
  const source = /espn/i.test(text) ? " from ESPN" : "";
  if (unableToEvaluate > 0) {
    return `${what}${source} is unavailable, so ${unableToEvaluate} system${unableToEvaluate === 1 ? "" : "s"} can't be evaluated.`;
  }
  return `${what}${source} couldn't be refreshed. Results may use older cached context.`;
}
