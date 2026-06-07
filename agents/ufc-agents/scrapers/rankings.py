"""UFC divisional rankings scraper."""
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("mirofish.scrapers.rankings")

RANKINGS_URL = "https://www.ufc.com/rankings"


def get_rankings() -> dict:
    """Scrape current UFC rankings by division.
    Returns: {division: [{rank: int, name: str}, ...], ...}
    """
    try:
        resp = requests.get(RANKINGS_URL, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MiroFish/1.0)"
        })
        resp.raise_for_status()
    except Exception as e:
        logger.error("Failed to fetch rankings: %s", e)
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")
    rankings = {}

    for division_block in soup.find_all("div", class_="view-grouping"):
        title_el = division_block.find("div", class_="view-grouping-header")
        if not title_el:
            continue
        division = title_el.get_text(strip=True)

        fighters = []
        for i, row in enumerate(division_block.find_all("tr"), start=1):
            name_el = row.find("a")
            if name_el:
                fighters.append({
                    "rank": i,
                    "name": name_el.get_text(strip=True),
                })

        if fighters:
            rankings[division] = fighters

    logger.info("Parsed rankings for %d divisions", len(rankings))
    return rankings


def get_fighter_rank(name: str, rankings: dict) -> tuple[str, int] | None:
    """Look up a fighter's rank across all divisions."""
    target = name.lower()
    for division, fighters in rankings.items():
        for f in fighters:
            if target in f["name"].lower():
                return division, f["rank"]
    return None
