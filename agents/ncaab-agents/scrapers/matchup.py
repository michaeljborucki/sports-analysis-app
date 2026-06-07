"""Compute NCAAB matchup context from team stats."""
import logging
from config import HOME_COURT_ADVANTAGE, POWER_CONFERENCES

logger = logging.getLogger("mirofish.scrapers.matchup")

# Known rivalries (subset)
RIVALRIES = {
    frozenset({"Duke", "North Carolina"}),
    frozenset({"Kentucky", "Louisville"}),
    frozenset({"Kansas", "Kansas State"}),
    frozenset({"Michigan", "Michigan State"}),
    frozenset({"Indiana", "Purdue"}),
    frozenset({"North Carolina", "NC State"}),
    frozenset({"UCLA", "USC"}),
    frozenset({"Arizona", "Arizona State"}),
    frozenset({"Cincinnati", "Xavier"}),
    frozenset({"Georgetown", "Syracuse"}),
    frozenset({"Gonzaga", "Saint Mary's"}),
    frozenset({"Florida", "Florida State"}),
    frozenset({"Virginia", "Virginia Tech"}),
    frozenset({"Oregon", "Oregon State"}),
}


def get_matchup_context(away_stats: dict, home_stats: dict,
                         game_info: dict = None) -> dict:
    """Compute matchup context from team efficiency profiles.

    Returns dict with keys: projected_tempo, projected_poss, efficiency_gap,
    projected_total, conference_game, rivalry, tournament_context,
    quad_classification, home_court_advantage, mismatch_desc, travel_context
    """
    game_info = game_info or {}

    away_tempo = away_stats.get("adj_tempo", 68)
    home_tempo = home_stats.get("adj_tempo", 68)
    projected_tempo = (away_tempo + home_tempo) / 2
    projected_poss = projected_tempo  # 40-min game = tempo is possessions

    away_oe = away_stats.get("adj_oe", 100)
    away_de = away_stats.get("adj_de", 100)
    home_oe = home_stats.get("adj_oe", 100)
    home_de = home_stats.get("adj_de", 100)

    # Efficiency gap (positive = home advantage)
    home_em = home_oe - home_de  # home AdjEM
    away_em = away_oe - away_de  # away AdjEM
    efficiency_gap = home_em - away_em

    # Projected total: cross-match offense vs opposing defense
    # away_score_rate = away_oe * (home_de / 100), home_score_rate = home_oe * (away_de / 100)
    away_score_eff = away_oe * home_de / 100
    home_score_eff = home_oe * away_de / 100
    projected_total = round((away_score_eff + home_score_eff) * projected_poss / 100, 1)

    # Tempo mismatch description
    tempo_diff = abs(away_tempo - home_tempo)
    if tempo_diff > 5:
        faster = away_stats.get("team", "Away") if away_tempo > home_tempo else home_stats.get("team", "Home")
        slower = home_stats.get("team", "Home") if away_tempo > home_tempo else away_stats.get("team", "Away")
        mismatch_desc = f"Significant ({tempo_diff:.1f} poss gap) -- {faster} wants to push, {slower} wants to slow"
    elif tempo_diff > 2:
        mismatch_desc = f"Moderate ({tempo_diff:.1f} poss gap)"
    else:
        mismatch_desc = f"Similar pace ({tempo_diff:.1f} poss gap)"

    # Conference game detection
    conference_game = game_info.get("conference_game", False)

    # Rivalry detection
    away_name = away_stats.get("team", "")
    home_name = home_stats.get("team", "")
    rivalry = frozenset({away_name, home_name}) in RIVALRIES

    # Tournament context
    tournament_id = game_info.get("tournament_id")
    if tournament_id:
        tourney_context = "Tournament game"
    else:
        tourney_context = "Regular season"

    # Home court advantage
    neutral = game_info.get("neutral_site", False)
    hca = 0 if neutral else HOME_COURT_ADVANTAGE

    # Quad classification (simplified -- based on opponent ranking + location)
    opp_rank = away_stats.get("trank", 200)  # from home team's perspective
    if neutral:
        if opp_rank <= 50: quad = "Quad 1"
        elif opp_rank <= 100: quad = "Quad 2"
        elif opp_rank <= 200: quad = "Quad 3"
        else: quad = "Quad 4"
    else:  # home game
        if opp_rank <= 30: quad = "Quad 1"
        elif opp_rank <= 75: quad = "Quad 2"
        elif opp_rank <= 160: quad = "Quad 3"
        else: quad = "Quad 4"

    return {
        "projected_tempo": round(projected_tempo, 1),
        "projected_poss": round(projected_poss, 1),
        "efficiency_gap": round(efficiency_gap, 1),
        "projected_total": projected_total,
        "conference_game": conference_game,
        "rivalry": rivalry,
        "tournament_context": tourney_context,
        "quad_classification": quad,
        "home_court_advantage": hca,
        "mismatch_desc": mismatch_desc,
        "travel_context": game_info.get("travel_context", "N/A"),
        "neutral_site": neutral,
    }
