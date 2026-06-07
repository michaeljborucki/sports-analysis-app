"""UFC event & fight card scraper from UFCStats.com."""
from dataclasses import dataclass, field
import logging
import requests
from bs4 import BeautifulSoup

from config import UFC_STATS_BASE

logger = logging.getLogger("mirofish.scrapers.schedule")


@dataclass
class Fight:
    fighter_a: str
    fighter_b: str
    weight_class: str
    card_position: str = "main_card"
    rounds: int = 3
    is_title_fight: bool = False


@dataclass
class FightCard:
    event_name: str
    date: str
    fights: list[Fight] = field(default_factory=list)


def get_upcoming_events() -> list[dict]:
    """Fetch list of upcoming UFC events from UFCStats.com.
    Returns list of dicts: [{event_name, date, detail_url}, ...]
    """
    url = f"{UFC_STATS_BASE}?page=all"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    events = []

    table = soup.find("table", class_="b-statistics__table-events")
    if not table:
        logger.warning("No events table found on UFCStats.com")
        return events

    for row in table.find_all("tr", class_="b-statistics__table-row"):
        cols = row.find_all("td", class_="b-statistics__table-col")
        if len(cols) < 2:
            continue

        link = cols[0].find("a", class_="b-link")
        if not link:
            continue

        event_name = link.get_text(strip=True)
        detail_url = link.get("href", "")
        date_text = cols[1].get_text(strip=True)

        if event_name:
            events.append({
                "event_name": event_name,
                "date": date_text,
                "detail_url": detail_url,
            })

    logger.info("Found %d events on UFCStats.com", len(events))
    return events


def get_fight_card(event_url: str) -> list[Fight]:
    """Scrape individual fight details from an event page."""
    resp = requests.get(event_url, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    fights = []

    for row in soup.find_all("tr", class_="b-fight-details__table-row"):
        cols = row.find_all("td", class_="b-fight-details__table-col")
        if len(cols) < 8:
            continue

        fighters = cols[1].find_all("a")
        if len(fighters) < 2:
            continue

        fighter_a = fighters[0].get_text(strip=True)
        fighter_b = fighters[1].get_text(strip=True)

        weight_class = cols[6].get_text(strip=True) if len(cols) > 6 else "Unknown"
        rounds_text = cols[7].get_text(strip=True) if len(cols) > 7 else "3"

        try:
            rounds = int(rounds_text)
        except ValueError:
            rounds = 3

        is_title = "title" in weight_class.lower()

        fights.append(Fight(
            fighter_a=fighter_a,
            fighter_b=fighter_b,
            weight_class=weight_class,
            rounds=5 if is_title or rounds == 5 else 3,
            is_title_fight=is_title,
        ))

    logger.info("Parsed %d fights from %s", len(fights), event_url)
    return fights
