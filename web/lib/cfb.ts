/**
 * College-football points-per-play projections (`/api/cfb/predictions`).
 * Model: server/cfb/ppp.py. Shapes mirror server/cfb/service.py.
 */

export type CfbDivision = "fbs" | "fcs";

export interface CfbTeam {
  team_id: string;
  /** "fcs" = played an FCS-vs-FCS game (incl. non-D1 opponents of FCS teams). */
  division: CfbDivision;
  name: string;
  short_name: string | null;
  abbreviation: string | null;
  logo: string | null;
  games: number;
  plays_per_game: number | null;
  off_ppp: number | null;
  def_ppp: number | null;
}

export interface CfbSide extends CfbTeam {
  off_estimate: number | null;
  def_estimate: number | null;
  predicted_points: number | null;
  actual_points: number | null;
}

export interface CfbGame {
  event_id: string;
  commence_time: string;
  neutral_site: boolean;
  /** "fbs" = at least one FBS team; "fcs" = FCS vs FCS. */
  division: CfbDivision;
  completed: boolean;
  status_detail: string | null;
  home: CfbSide;
  away: CfbSide;
  predicted_total: number | null;
  /** Home-perspective, betting sign: −7 = home favored by 7. */
  predicted_spread_home: number | null;
  market_total?: number | null;
  market_spread_home?: number | null;
}

export interface CfbTeamRow extends CfbTeam {
  points_for_per_game: number;
  points_against_per_game: number;
}

export interface CfbPredictionsResponse {
  season: number;
  week: number;
  current_week: number;
  games_used: number;
  games_skipped: number;
  built_at: string;
  games: CfbGame[];
  teams: CfbTeamRow[];
}

/** Below this many games a team's rates are mostly noise. */
export const SMALL_SAMPLE_GAMES = 3;

export function fmtPpp(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(3).replace(/^0(?=\.)/, "");
}

export function fmtPts(v: number | null | undefined, digits = 1): string {
  return v == null ? "—" : v.toFixed(digits);
}

/** "TROY −4.5" from a home-perspective spread; "PK" at zero. */
export function fmtSpread(
  spreadHome: number | null | undefined,
  home: CfbTeam,
  away: CfbTeam,
): string {
  if (spreadHome == null) return "—";
  if (Math.abs(spreadHome) < 0.05) return "PK";
  const fav = spreadHome < 0 ? home : away;
  const label = fav.abbreviation ?? fav.short_name ?? fav.name;
  return `${label} −${Math.abs(spreadHome).toFixed(1)}`;
}

/** Model-vs-market gaps below this are noise for a model this simple. */
export const LEAN_MIN = 0.5;

export interface CfbLeans {
  /** Model total − market total (positive = Over). */
  total: number | null;
  /** Points the model is stronger on `team` than the market is. */
  spread: number | null;
  spreadTeam: CfbSide | null;
}

export function gameLeans(g: CfbGame): CfbLeans {
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

export function teamLabel(t: CfbTeam): string {
  return t.abbreviation ?? t.short_name ?? t.name;
}

export function cfbGameHref(g: CfbGame, week: number): string {
  return `/cfb/game/${encodeURIComponent(g.event_id)}?week=${week}`;
}
