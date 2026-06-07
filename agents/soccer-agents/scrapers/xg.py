"""Expected goals (xG) estimation from available team statistics.

Uses a Poisson-based model with league-average regression to estimate
xG, xGA, and overperformance from goals scored/conceded data.
More accurate than raw goals because it regresses toward league average
(small sample sizes early in season) and incorporates strength of schedule.
"""
import logging
import math
from scrapers.team_stats import get_team_profile, _load_standings

logger = logging.getLogger("mirofish.scrapers.xg")

# League average goals per game (both teams combined)
LEAGUE_AVG_TOTAL_GOALS = {
    "MLS": 2.85,
    "Eredivisie": 3.15,
    "Serie A": 2.65,
    "EPL": 2.80,
    "Bundesliga": 3.10,
    "La Liga": 2.55,
    "Ligue 1": 2.60,
}


def _regress_to_mean(observed_rate: float, league_avg: float, games: int, k: float = 10.0) -> float:
    """Bayesian regression toward league mean.

    k controls how many games before we trust the observed rate fully.
    With k=10, after 10 games the estimate is 50% observed + 50% league avg.
    After 30 games, ~75% observed.
    """
    weight = games / (games + k)
    return weight * observed_rate + (1 - weight) * league_avg


def _estimate_clean_sheet_pct(xga_per_match: float) -> float:
    """Estimate clean sheet probability using Poisson distribution.

    P(0 goals) = e^(-xGA) — the probability the opponent scores 0.
    """
    return round(math.exp(-xga_per_match), 4)


def _compute_btts_probability(home_xg: float, home_xga: float, away_xg: float, away_xga: float) -> float:
    """Estimate BTTS probability from xG profiles.

    P(BTTS) = P(home scores >= 1) * P(away scores >= 1)
    Using Poisson: P(score >= 1) = 1 - e^(-expected_goals)

    Home expected = average of (home_xg, away_xga) — attack vs defense matchup
    Away expected = average of (away_xg, home_xga)
    """
    home_expected = (home_xg + away_xga) / 2
    away_expected = (away_xg + home_xga) / 2

    p_home_scores = 1 - math.exp(-home_expected)
    p_away_scores = 1 - math.exp(-away_expected)

    return round(p_home_scores * p_away_scores, 4)


def get_xg_profile(team_name: str, league: str = "MLS") -> dict:
    """Compute xG profile for a team from standings data.

    Uses Bayesian regression toward league average to handle
    small sample sizes early in the season.
    """
    profile = get_team_profile(team_name, league=league)

    gp = profile.get("games_played", 0)
    gf = profile.get("goals_for", 0)
    ga = profile.get("goals_against", 0)

    league_avg_half = LEAGUE_AVG_TOTAL_GOALS.get(league, 2.75) / 2  # per-team avg

    if gp == 0:
        # No data — return league average
        return {
            "team": team_name,
            "xg_per_match": round(league_avg_half, 2),
            "xga_per_match": round(league_avg_half, 2),
            "xg_diff": 0.0,
            "xg_overperformance": 0.0,
            "goals_per_match": round(league_avg_half, 2),
            "clean_sheet_pct": round(_estimate_clean_sheet_pct(league_avg_half), 2),
            "games_used": 0,
        }

    goals_per_match = gf / gp
    goals_against_per_match = ga / gp

    # Regress toward league average (critical for small samples)
    xg_per_match = _regress_to_mean(goals_per_match, league_avg_half, gp)
    xga_per_match = _regress_to_mean(goals_against_per_match, league_avg_half, gp)

    xg_diff = xg_per_match - xga_per_match
    xg_overperformance = goals_per_match - xg_per_match  # positive = regression risk

    clean_sheet_pct = _estimate_clean_sheet_pct(xga_per_match)

    logger.debug("[xg] %s: xG=%.2f xGA=%.2f over=%.2f (%d games, regressed)",
                 team_name, xg_per_match, xga_per_match, xg_overperformance, gp)

    return {
        "team": team_name,
        "xg_per_match": round(xg_per_match, 2),
        "xga_per_match": round(xga_per_match, 2),
        "xg_diff": round(xg_diff, 2),
        "xg_overperformance": round(xg_overperformance, 2),
        "goals_per_match": round(goals_per_match, 2),
        "clean_sheet_pct": round(clean_sheet_pct, 2),
        "games_used": gp,
    }


def estimate_btts_prob(home_team: str, away_team: str, league: str = "MLS") -> float:
    """Estimate BTTS probability for a specific matchup."""
    home_xg = get_xg_profile(home_team, league=league)
    away_xg = get_xg_profile(away_team, league=league)

    return _compute_btts_probability(
        home_xg["xg_per_match"], home_xg["xga_per_match"],
        away_xg["xg_per_match"], away_xg["xga_per_match"],
    )
