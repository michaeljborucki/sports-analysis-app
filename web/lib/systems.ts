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
