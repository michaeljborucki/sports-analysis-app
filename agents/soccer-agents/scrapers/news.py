"""Fetch soccer news and injury aggregation."""
import logging
from scrapers.injuries import get_squad_injuries

logger = logging.getLogger("mirofish.scrapers.news")


def get_injuries(league: str = "MLS", teams: list[str] = None) -> list[dict]:
    if not teams:
        return []

    all_injuries = []
    for team in teams:
        injuries = get_squad_injuries(team, league=league)
        all_injuries.extend(injuries)

    logger.info("[news] Fetched %d injuries across %d teams", len(all_injuries), len(teams))
    return all_injuries
