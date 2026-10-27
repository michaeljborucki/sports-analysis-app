/**
 * NBA possession-efficiency projections (`/api/nba/predictions`).
 * Model: server/nba/efficiency.py. Shapes mirror server/nba/service.py.
 */

/** "current" = this season's games; "last_season" = under the switch-over sample. */
export type NbaRatingSource = "current" | "last_season";

export interface NbaTeam {
  team_id: string;
  name: string;
  short_name: string | null;
  abbreviation: string | null;
  logo: string | null;
  source: NbaRatingSource;
  games: number;
  /** Possessions per game. */
  pace: number | null;
  /** Points per possession. */
  off_eff: number | null;
  /** Points allowed per opponent possession (lower is better). */
  def_eff: number | null;
}

export interface NbaSide extends NbaTeam {
  off_estimate: number | null;
  def_estimate: number | null;
  predicted_points: number | null;
  /** Same efficiencies over one shared pace (avg of both teams'). */
  pace_matched_points: number | null;
  actual_points: number | null;
}

export interface NbaGame {
  event_id: string;
  commence_time: string;
  neutral_site: boolean;
  /** ESPN season type: 1 pre, 2 regular, 3 playoffs, 5 play-in. */
  season_type: number;
  completed: boolean;
  status_detail: string | null;
  home: NbaSide;
  away: NbaSide;
  predicted_total: number | null;
  /** Home-perspective, betting sign: −7 = home favored by 7. */
  predicted_spread_home: number | null;
  pace_matched_total: number | null;
  pace_matched_spread_home: number | null;
  market_total?: number | null;
  market_spread_home?: number | null;
}

export interface NbaTeamRow extends NbaTeam {
  current_games: number;
  points_for_per_game: number;
  points_against_per_game: number;
}

export interface NbaPredictionsResponse {
  season: number;
  /** Slate day, YYYY-MM-DD (ESPN's US-Eastern day). */
  date: string;
  today: string;
  min_current_games: number;
  games_used: number;
  games_skipped: number;
  prior_games_used: number;
  built_at: string;
  games: NbaGame[];
  teams: NbaTeamRow[];
}

/** "1.159" — efficiencies are points per possession. */
export function fmtEff(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(3);
}

export function fmtPts(v: number | null | undefined, digits = 1): string {
  return v == null ? "—" : v.toFixed(digits);
}

/** "BOS −4.5" from a home-perspective spread; "PK" at zero. */
export function fmtSpread(
  spreadHome: number | null | undefined,
  home: NbaTeam,
  away: NbaTeam,
): string {
  if (spreadHome == null) return "—";
  if (Math.abs(spreadHome) < 0.05) return "PK";
  const fav = spreadHome < 0 ? home : away;
  return `${teamLabel(fav)} −${Math.abs(spreadHome).toFixed(1)}`;
}

/** Model-vs-market gaps below this are noise for a model this simple. */
export const LEAN_MIN = 0.5;

export interface NbaLeans {
  /** Model total − market total (positive = Over). */
  total: number | null;
  /** Points the model is stronger on `spreadTeam` than the market is. */
  spread: number | null;
  spreadTeam: NbaSide | null;
}

export function gameLeans(g: NbaGame): NbaLeans {
  const total =
    g.predicted_total != null && g.market_total != null
      ? g.predicted_total - g.market_total
      : null;
  // Positive = model rates home stronger than the market does.
  const spread =
    g.predicted_spread_home != null && g.market_spread_home != null
      ? g.market_spread_home - g.predicted_spread_home
      : null;
  const spreadTeam = spread == null ? null : spread > 0 ? g.home : g.away;
  return { total, spread: spread == null ? null : Math.abs(spread), spreadTeam };
}

export function teamLabel(t: NbaTeam): string {
  return t.abbreviation ?? t.short_name ?? t.name;
}

export function nbaGameHref(g: NbaGame, date: string): string {
  return `/nba/game/${encodeURIComponent(g.event_id)}?date=${date}`;
}

/** Shift a YYYY-MM-DD day by `days` (calendar math in UTC — no DST drift). */
export function shiftDay(day: string, days: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

const DAY_LABEL = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

export function fmtDay(day: string): string {
  return DAY_LABEL.format(new Date(`${day}T00:00:00Z`));
}

export function isDay(v: string | null): v is string {
  return v != null && /^\d{4}-\d{2}-\d{2}$/.test(v);
}

export function sourceTitle(t: NbaTeam, minGames: number): string {
  return t.source === "last_season"
    ? `Last season's numbers (${t.games} games) — switches to this season at ${minGames} games`
    : `This season, ${t.games} games`;
}

// ───────────────────────── SGP screener (`/api/nba/sgp`) ─────────────────────────
// Model: server/nba/sgp.py.

export type SgpStat = "points" | "rebounds" | "assists";

export const SGP_STATS: { key: SgpStat; label: string; short: string }[] = [
  { key: "points", label: "Points", short: "PTS" },
  { key: "rebounds", label: "Rebounds", short: "REB" },
  { key: "assists", label: "Assists", short: "AST" },
];

export interface SgpLeg {
  line: number;
  hits: number;
  n: number;
  rate: number;
}

export interface SgpPlayer {
  athlete_id: string;
  name: string;
  headshot: string | null;
  team_id: string;
  opp_id: string;
  /** G / F / C */
  position: string;
  injury: string | null;
  source: NbaRatingSource;
  games: number;
  current_games: number;
  minutes: number;
  usage: number | null;
  /** Fantasy points per game the opponent allows to this position. */
  opp_dvp: number | null;
  /** 1 = allows the most to this position (worst defense). */
  opp_dvp_rank: number | null;
  opp_dvp_source: NbaRatingSource;
  pass_usage: boolean;
  pass_matchup: boolean;
  pass_legs: boolean;
  /** Finished games only: the player's real line. */
  actual: Record<SgpStat, number> | null;
  /** Finished games only: did all three legs hit? */
  parlay_hit: boolean | null;
  n: number;
  legs: Record<SgpStat, SgpLeg | null>;
  joint: { hits: number; n: number; rate: number } | null;
  product: number | null;
  floor: number | null;
  conservative: number | null;
  breakeven: number | null;
  conservative_breakeven: number | null;
}

export interface SgpGame {
  event_id: string;
  commence_time: string;
  completed: boolean;
  home: NbaTeam;
  away: NbaTeam;
  players: SgpPlayer[];
}

export interface SgpResponse {
  season: number;
  date: string;
  today: string;
  criteria: {
    usage_min: number;
    dvp_bottom: number;
    hit_min: number;
    min_sample: number;
    fantasy_scoring: string;
    ladders: Record<SgpStat, number[]>;
  };
  built_at: string;
  games: SgpGame[];
}

export function sgpQualifies(p: SgpPlayer): boolean {
  return p.pass_usage && p.pass_matchup && p.pass_legs;
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  return v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
}

/** "−700" / "+150"; "any" when the sample never missed (p = 1). */
export function fmtAmerican(v: number | null | undefined, p?: number | null): string {
  if (v == null) return p != null && p >= 1 ? "any" : "—";
  return v > 0 ? `+${v}` : `−${Math.abs(v)}`;
}
