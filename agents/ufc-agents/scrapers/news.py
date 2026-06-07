"""UFC fight context: injuries, camp info, weight cuts, layoff."""
from dataclasses import dataclass, field
import logging

logger = logging.getLogger("mirofish.scrapers.news")


@dataclass
class FightContext:
    fighter_name: str
    injuries: list[str] = field(default_factory=list)
    camp_info: str = ""
    weight_cut_notes: str = ""
    layoff_days: int | None = None
    short_notice: bool = False
    notable_quotes: list[str] = field(default_factory=list)


def build_fight_context(fighter_name: str) -> FightContext:
    """Build fight context for a fighter.
    Currently returns a stub with empty data.
    Future: scrape MMA news sites, social media, press conferences.
    """
    logger.info("Building fight context for %s (stub)", fighter_name)
    return FightContext(fighter_name=fighter_name)
