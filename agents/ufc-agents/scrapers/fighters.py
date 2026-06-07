"""UFC fighter profile scraper from UFCStats.com."""
from dataclasses import dataclass, field
import logging
import re
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("mirofish.scrapers.fighters")

UFCSTATS_SEARCH = "http://ufcstats.com/statistics/fighters/search"
UFCSTATS_FIGHTER = "http://ufcstats.com/fighter-details/"


@dataclass
class FighterProfile:
    name: str
    record: str  # "W-L-D"
    wins_ko: int = 0
    wins_sub: int = 0
    wins_dec: int = 0
    losses_ko: int = 0
    losses_sub: int = 0
    losses_dec: int = 0
    height: str = ""
    reach: str = ""
    stance: str = "Orthodox"
    age: int = 0
    slpm: float = 0.0
    sapm: float = 0.0            # Sig. strikes absorbed per min
    str_acc: float = 0.0
    str_def: float = 0.0
    td_avg: float = 0.0
    td_def: float = 0.0
    sub_avg: float = 0.0
    avg_fight_time: str = ""
    win_streak: int = 0
    last_5_fights: list[dict] = field(default_factory=list)
    detail_url: str = ""


def _parse_pct(text: str) -> float:
    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1)) / 100
    return 0.0


def _parse_float(text: str) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", text))
    except (ValueError, TypeError):
        return 0.0


def search_fighter(name: str) -> str | None:
    """Search UFCStats.com for a fighter and return their detail page URL."""
    parts = name.strip().split()
    if not parts:
        return None

    params = {"query": parts[0]}
    try:
        resp = requests.get(UFCSTATS_SEARCH, params=params, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Fighter search failed for %s: %s", name, e)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    target = name.lower()

    for row in soup.find_all("tr", class_="b-statistics__table-row"):
        link = row.find("a")
        if not link:
            continue
        cols = row.find_all("td")
        if len(cols) >= 2:
            first = cols[0].get_text(strip=True).lower()
            last = cols[1].get_text(strip=True).lower()
            full = f"{first} {last}"
            if full == target or target in full:
                return link.get("href", "")

    return None


def get_fighter_profile(name: str) -> FighterProfile | None:
    """Build a full fighter profile by scraping UFCStats.com."""
    detail_url = search_fighter(name)
    if not detail_url:
        logger.warning("Fighter not found: %s", name)
        return FighterProfile(name=name, record="0-0-0")

    try:
        resp = requests.get(detail_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Failed to fetch fighter details for %s: %s", name, e)
        return FighterProfile(name=name, record="0-0-0", detail_url=detail_url)

    soup = BeautifulSoup(resp.text, "html.parser")
    profile = FighterProfile(name=name, record="0-0-0", detail_url=detail_url)

    record_el = soup.find("span", class_="b-content__title-record")
    if record_el:
        record_text = record_el.get_text(strip=True).replace("Record:", "").strip()
        profile.record = record_text

    stat_boxes = soup.find_all("li", class_="b-list__box-list-item")
    for box in stat_boxes:
        text = box.get_text(strip=True)
        if "SLpM" in text:
            profile.slpm = _parse_float(text.split(":")[-1])
        elif "SApM" in text:
            profile.sapm = _parse_float(text.split(":")[-1])
        elif "Str. Acc" in text:
            profile.str_acc = _parse_pct(text)
        elif "Str. Def" in text:
            profile.str_def = _parse_pct(text)
        elif "TD Avg" in text:
            profile.td_avg = _parse_float(text.split(":")[-1])
        elif "TD Def" in text:
            profile.td_def = _parse_pct(text)
        elif "Sub. Avg" in text:
            profile.sub_avg = _parse_float(text.split(":")[-1])
        elif "Height" in text:
            profile.height = text.split(":")[-1].strip()
        elif "Reach" in text:
            profile.reach = text.split(":")[-1].strip()
        elif "STANCE" in text.upper():
            profile.stance = text.split(":")[-1].strip()

    fight_rows = soup.find_all("tr", class_="b-fight-details__table-row")
    for row in fight_rows[:5]:
        cols = row.find_all("td")
        if len(cols) < 8:
            continue
        result = cols[0].get_text(strip=True)
        fighters = cols[1].find_all("a")
        opponent = ""
        for f in fighters:
            f_name = f.get_text(strip=True)
            if f_name.lower() != name.lower():
                opponent = f_name

        method = cols[7].get_text(strip=True) if len(cols) > 7 else ""
        rnd = cols[8].get_text(strip=True) if len(cols) > 8 else ""

        profile.last_5_fights.append({
            "result": result,
            "opponent": opponent,
            "method": method,
            "round": rnd,
        })

    logger.info("Fetched profile for %s: %s", name, profile.record)
    return profile
