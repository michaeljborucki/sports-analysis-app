"""NCAAB scrapers — schedule, team stats, odds, scores, injuries, roster, matchup."""

from scrapers.schedule import get_ncaab_schedule
from scrapers.team_stats import get_all_team_ratings, get_team_efficiency
from scrapers.odds import get_ncaab_odds
from scrapers.scores import get_final_scores
from scrapers.injuries import get_ncaab_injuries
from scrapers.roster import get_roster_context
from scrapers.matchup import get_matchup_context

__all__ = [
    "get_ncaab_schedule",
    "get_all_team_ratings",
    "get_team_efficiency",
    "get_ncaab_odds",
    "get_final_scores",
    "get_ncaab_injuries",
    "get_roster_context",
    "get_matchup_context",
]
