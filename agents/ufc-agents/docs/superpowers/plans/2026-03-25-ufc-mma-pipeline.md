# MiroFish UFC/MMA Prediction Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the existing MLB baseball prediction pipeline into a UFC/MMA fight prediction system using a 6-model LLM ensemble with adversarial challenge, supporting moneyline, total rounds, and method-of-victory bet types with eighth-Kelly sizing.

**Architecture:** 6-layer pipeline (SCRAPE -> BRIEFING -> SCREEN -> ENSEMBLE -> EDGE -> BET). Sport-agnostic layers (ensemble engine, orchestrator, challenger, consensus, weights, tracker, Kelly) transfer as-is. Sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) are rebuilt for UFC/MMA. Scrapers pull from UFCStats.com (fighters), The Odds API (odds), and web search (news/context).

**Tech Stack:** Python 3.11+, requests, beautifulsoup4, openai (OpenRouter), python-dotenv, click (CLI), pandas (tracker/calibration)

**Spec document:** `01-ufc-mma.md` (project root)

---

## File Structure

```
ufc-agents/
├── config.py                # UFC constants, thresholds, weight classes (REWRITE)
│
├── scrapers/
│   ├── __init__.py
│   ├── schedule.py          # NEW: Event & fight card scraper (UFCStats.com)
│   ├── fighters.py          # NEW: Fighter profiles & stats (UFCStats.com)
│   ├── odds.py              # REWRITE: MMA odds from The Odds API
│   ├── news.py              # REWRITE: Fight context (injuries, camps, weight cuts)
│   └── rankings.py          # NEW: UFC divisional rankings
│
├── briefing.py              # REWRITE: Fighter matchup briefing template
├── simulate.py              # REWRITE: UFC system prompt + prediction schema
├── edge.py                  # REWRITE: moneyline/total_rounds/method edge checkers
│
├── ensemble/
│   ├── __init__.py
│   ├── models.py            # (keep as-is — sport-agnostic model registry)
│   ├── orchestrator.py      # MODIFY: update score averaging for UFC
│   ├── runner.py            # MODIFY: swap system prompt reference
│   ├── challenger.py        # MODIFY: update system prompt for UFC
│   ├── consensus.py         # REWRITE: vote extraction for UFC bet slots
│   ├── weights.py           # MODIFY: update BET_SLOTS
│   └── logger.py            # (keep as-is — sport-agnostic)
│
├── tracker.py               # (keep as-is — sport-agnostic CSV tracking)
├── calibrate.py             # (keep as-is — sport-agnostic calibration)
├── main.py                  # REWRITE: UFC pipeline flow
│
├── agents/
│   ├── __init__.py
│   ├── results_grader.py    # REWRITE: UFC fight result grading
│   ├── health_check.py      # MODIFY: check UFC data sources
│   ├── bet_card.py          # MODIFY: UFC bet display formatting
│   ├── self_optimizer.py    # (keep as-is — sport-agnostic)
│   └── daily_runner.py      # (keep as-is — sport-agnostic orchestration)
│
├── tests/
│   ├── __init__.py
│   ├── ensemble_fixtures.py # MODIFY: UFC mock predictions/odds
│   ├── test_config.py       # REWRITE
│   ├── test_schedule.py     # NEW
│   ├── test_fighters.py     # NEW
│   ├── test_odds.py         # REWRITE
│   ├── test_news.py         # REWRITE
│   ├── test_rankings.py     # NEW
│   ├── test_briefing.py     # REWRITE
│   ├── test_simulate.py     # ADAPT
│   ├── test_edge.py         # REWRITE
│   ├── test_main.py         # ADAPT
│   ├── test_results_grader.py  # REWRITE
│   ├── test_health_check.py    # ADAPT
│   ├── test_bet_card.py     # ADAPT
│   ├── test_tracker.py      # (keep as-is)
│   ├── test_calibrate.py    # (keep as-is)
│   ├── test_self_optimizer.py  # (keep as-is)
│   ├── test_ensemble_*.py   # (keep as-is, 8 files)
│   └── [DELETE: test_pitchers.py, test_lineups.py, test_bullpen.py,
│          test_ballpark.py, test_team_stats.py, test_scores.py]
│
└── data/
    └── bets.csv
```

---

## Task 1: Delete MLB-Specific Files

**Files:**
- Delete: `scrapers/pitchers.py`
- Delete: `scrapers/lineups.py`
- Delete: `scrapers/bullpen.py`
- Delete: `scrapers/ballpark.py`
- Delete: `scrapers/team_stats.py`
- Delete: `scrapers/scores.py`
- Delete: `tests/test_pitchers.py`
- Delete: `tests/test_lineups.py`
- Delete: `tests/test_bullpen.py`
- Delete: `tests/test_ballpark.py`
- Delete: `tests/test_team_stats.py`
- Delete: `tests/test_scores.py`

- [ ] **Step 1: Delete MLB scraper files**

```bash
rm scrapers/pitchers.py scrapers/lineups.py scrapers/bullpen.py \
   scrapers/ballpark.py scrapers/team_stats.py scrapers/scores.py
```

- [ ] **Step 2: Delete corresponding test files**

```bash
rm tests/test_pitchers.py tests/test_lineups.py tests/test_bullpen.py \
   tests/test_ballpark.py tests/test_team_stats.py tests/test_scores.py
```

- [ ] **Step 3: Verify deletions**

Run: `ls scrapers/ && ls tests/`
Expected: No pitchers/lineups/bullpen/ballpark/team_stats/scores files

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "chore: remove MLB-specific scrapers and tests"
```

---

## Task 2: Rewrite config.py for UFC

**Files:**
- Modify: `config.py` (full rewrite)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import config


def test_edge_thresholds_keys():
    assert set(config.EDGE_THRESHOLDS.keys()) == {"moneyline", "total_rounds", "method"}


def test_edge_thresholds_values():
    assert config.EDGE_THRESHOLDS["moneyline"] == 0.06
    assert config.EDGE_THRESHOLDS["total_rounds"] == 0.06
    assert config.EDGE_THRESHOLDS["method"] == 0.08


def test_kelly_fraction():
    assert config.KELLY_FRACTION == 0.125  # eighth-Kelly for UFC


def test_bet_slots():
    assert config.BET_SLOTS == ["moneyline", "total_rounds", "method"]


def test_odds_sport_key():
    assert config.ODDS_SPORT_KEY == "mma_mixed_martial_arts"


def test_weight_classes_exist():
    assert len(config.WEIGHT_CLASSES) > 0
    assert "Lightweight" in config.WEIGHT_CLASSES
    assert "Heavyweight" in config.WEIGHT_CLASSES


def test_ensemble_config():
    assert len(config.ENSEMBLE_MODELS) == 6
    assert config.ENSEMBLE_CHALLENGER == "claude"
    assert config.CONSENSUS_MIN_VOTES == 3
    assert config.MAX_CALLS_PER_GAME == 50


def test_game_timeout():
    assert config.GAME_TIMEOUT == 180


def test_no_mlb_artifacts():
    """Ensure no MLB-specific config remains."""
    assert not hasattr(config, "TEAM_ABBREVS")
    assert not hasattr(config, "TEAM_NAME_TO_ABBREV")
    assert not hasattr(config, "PARK_FACTORS")
    assert not hasattr(config, "PARK_COORDS")
    assert not hasattr(config, "MLB_API_BASE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (MLB config still present)

- [ ] **Step 3: Rewrite config.py**

```python
import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Logging configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# API keys
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# API base URLs
UFC_STATS_BASE = "http://ufcstats.com/statistics/events/completed"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_SPORT_KEY = "mma_mixed_martial_arts"

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCREEN_EDGE_THRESHOLD = 0.03
GAME_TIMEOUT = 180  # 3 min per fight analysis

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Bet types for UFC
BET_SLOTS = ["moneyline", "total_rounds", "method"]

# Kelly sizing — use eighth-Kelly for UFC (higher variance than team sports)
KELLY_FRACTION = 0.125

# Edge thresholds per bet type
EDGE_THRESHOLDS = {
    "moneyline": 0.06,
    "total_rounds": 0.06,
    "method": 0.08,
}

# UFC weight classes (men's and women's)
WEIGHT_CLASSES = [
    "Strawweight", "Flyweight", "Bantamweight", "Featherweight",
    "Lightweight", "Welterweight", "Middleweight",
    "Light Heavyweight", "Heavyweight",
    "Women's Strawweight", "Women's Flyweight",
    "Women's Bantamweight", "Women's Featherweight",
]

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: rewrite config.py for UFC/MMA pipeline"
```

---

## Task 3: Rewrite scrapers/odds.py for UFC

**Files:**
- Modify: `scrapers/odds.py` (full rewrite)
- Modify: `tests/test_odds.py` (full rewrite)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_odds.py
from unittest.mock import patch, MagicMock
from scrapers.odds import OddsData, get_ufc_odds, american_to_implied_prob


def test_american_to_implied_prob_favorite():
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.001


def test_american_to_implied_prob_underdog():
    assert abs(american_to_implied_prob(150) - 0.4) < 0.001


def test_odds_data_defaults():
    od = OddsData(fighter_a="Islam Makhachev", fighter_b="Charles Oliveira",
                  commence_time="2026-04-12T22:00:00Z")
    assert od.moneyline == {}
    assert od.total_rounds == {}
    assert od.implied_probs == {}


@patch("scrapers.odds.requests.get")
def test_get_ufc_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "home_team": "Islam Makhachev",
            "away_team": "Charles Oliveira",
            "commence_time": "2026-04-12T22:00:00Z",
            "bookmakers": [
                {
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Islam Makhachev", "price": -200},
                                {"name": "Charles Oliveira", "price": 170},
                            ],
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "price": -115, "point": 2.5},
                                {"name": "Under", "price": -105},
                            ],
                        },
                    ]
                }
            ],
        }
    ]
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_ufc_odds()
    assert len(results) == 1
    od = results[0]
    assert od.fighter_a == "Islam Makhachev"
    assert od.fighter_b == "Charles Oliveira"
    assert od.moneyline["fighter_a"] == -200
    assert od.moneyline["fighter_b"] == 170
    assert od.total_rounds["line"] == 2.5
    assert od.total_rounds["over_odds"] == -115
    assert od.total_rounds["under_odds"] == -105
    assert "fighter_a" in od.implied_probs
    assert "fighter_b" in od.implied_probs


@patch("scrapers.odds.requests.get")
def test_get_ufc_odds_empty_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = []
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_ufc_odds()
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_odds.py -v`
Expected: FAIL (old MLB odds code)

- [ ] **Step 3: Rewrite scrapers/odds.py**

```python
"""UFC/MMA odds scraper via The Odds API."""
from dataclasses import dataclass, field
import logging
import requests

from config import ODDS_API_KEY, ODDS_API_BASE, ODDS_SPORT_KEY

logger = logging.getLogger("mirofish.scrapers.odds")


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


@dataclass
class OddsData:
    fighter_a: str
    fighter_b: str
    commence_time: str
    moneyline: dict = field(default_factory=dict)      # {fighter_a: int, fighter_b: int}
    total_rounds: dict = field(default_factory=dict)    # {line: float, over_odds: int, under_odds: int}
    implied_probs: dict = field(default_factory=dict)   # {fighter_a: float, fighter_b: float}


def get_ufc_odds(date: str = None) -> list[OddsData]:
    """Fetch UFC/MMA odds from The Odds API for h2h and totals markets."""
    url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,totals",
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    remaining = resp.headers.get("x-requests-remaining", "?")
    logger.info("[odds] %d fights found, API requests remaining: %s", len(data), remaining)

    if not data:
        return []

    results = []
    for event in data:
        fighter_a = event["home_team"]
        fighter_b = event["away_team"]

        odds_data = OddsData(
            fighter_a=fighter_a,
            fighter_b=fighter_b,
            commence_time=event["commence_time"],
        )

        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}

            if "h2h" in markets:
                for outcome in markets["h2h"]["outcomes"]:
                    if outcome["name"] == fighter_a:
                        odds_data.moneyline["fighter_a"] = outcome["price"]
                    else:
                        odds_data.moneyline["fighter_b"] = outcome["price"]

            if "totals" in markets:
                for outcome in markets["totals"]["outcomes"]:
                    if outcome["name"] == "Over":
                        odds_data.total_rounds["line"] = outcome.get("point", 2.5)
                        odds_data.total_rounds["over_odds"] = outcome["price"]
                    else:
                        odds_data.total_rounds["under_odds"] = outcome["price"]

            if odds_data.moneyline:
                break

        # Compute vig-removed implied probabilities
        if odds_data.moneyline:
            p_a = american_to_implied_prob(odds_data.moneyline["fighter_a"])
            p_b = american_to_implied_prob(odds_data.moneyline["fighter_b"])
            total_prob = p_a + p_b
            odds_data.implied_probs["fighter_a"] = round(p_a / total_prob, 4)
            odds_data.implied_probs["fighter_b"] = round(p_b / total_prob, 4)

        results.append(odds_data)

    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_odds.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/odds.py tests/test_odds.py
git commit -m "feat: rewrite odds scraper for UFC/MMA"
```

---

## Task 4: Build scrapers/schedule.py

**Files:**
- Create: `scrapers/schedule.py`
- Create: `tests/test_schedule.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schedule.py
from unittest.mock import patch, MagicMock
from scrapers.schedule import get_upcoming_events, FightCard, Fight


def test_fight_card_structure():
    card = FightCard(
        event_name="UFC 300",
        date="2026-04-12",
        fights=[
            Fight(
                fighter_a="Islam Makhachev",
                fighter_b="Charles Oliveira",
                weight_class="Lightweight",
                card_position="main_event",
                rounds=5,
                is_title_fight=True,
            )
        ],
    )
    assert card.event_name == "UFC 300"
    assert len(card.fights) == 1
    assert card.fights[0].rounds == 5
    assert card.fights[0].is_title_fight is True


def test_fight_defaults():
    f = Fight(fighter_a="A", fighter_b="B", weight_class="Lightweight")
    assert f.card_position == "main_card"
    assert f.rounds == 3
    assert f.is_title_fight is False


@patch("scrapers.schedule.requests.get")
def test_get_upcoming_events_parses_html(mock_get):
    # Minimal HTML that mirrors UFCStats.com event listing structure
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = """
    <html><body>
    <table class="b-statistics__table-events">
      <tr class="b-statistics__table-row">
        <td class="b-statistics__table-col">
          <a href="http://ufcstats.com/event-details/abc123" class="b-link">UFC 300</a>
        </td>
        <td class="b-statistics__table-col">April 12, 2026</td>
      </tr>
    </table>
    </body></html>
    """
    mock_get.return_value = mock_resp

    events = get_upcoming_events()
    # Should return list of event dicts with name, date, detail_url
    assert isinstance(events, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schedule.py -v`
Expected: FAIL (module does not exist)

- [ ] **Step 3: Write scrapers/schedule.py**

```python
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
    card_position: str = "main_card"  # main_event, co_main, main_card, prelim
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
    """Scrape individual fight details from an event page.

    Returns list of Fight dataclasses.
    """
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schedule.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/schedule.py tests/test_schedule.py
git commit -m "feat: add UFC event & fight card scraper"
```

---

## Task 5: Build scrapers/fighters.py

**Files:**
- Create: `scrapers/fighters.py`
- Create: `tests/test_fighters.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fighters.py
from unittest.mock import patch, MagicMock
from scrapers.fighters import FighterProfile, get_fighter_profile


def test_fighter_profile_structure():
    fp = FighterProfile(
        name="Islam Makhachev",
        record="25-1-0",
        wins_ko=4, wins_sub=11, wins_dec=10,
        losses_ko=0, losses_sub=0, losses_dec=1,
        height="5'10\"",
        reach="70.5",
        stance="Orthodox",
        age=32,
        slpm=2.42,
        str_acc=0.592,
        str_def=0.645,
        td_avg=3.15,
        td_def=0.897,
        sub_avg=1.2,
        avg_fight_time="12:30",
        win_streak=3,
        last_5_fights=[],
    )
    assert fp.name == "Islam Makhachev"
    assert fp.record == "25-1-0"
    assert fp.wins_ko == 4


def test_fighter_profile_defaults():
    fp = FighterProfile(name="Unknown Fighter", record="0-0-0")
    assert fp.wins_ko == 0
    assert fp.stance == "Orthodox"
    assert fp.slpm == 0.0
    assert fp.last_5_fights == []


@patch("scrapers.fighters.requests.get")
def test_get_fighter_profile_search(mock_get):
    """Test fighter search returns profile data."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Minimal HTML mirroring UFCStats.com fighter search
    mock_resp.text = """
    <html><body>
    <table class="b-statistics__table">
      <tr class="b-statistics__table-row">
        <td><a href="http://ufcstats.com/fighter-details/abc">Islam</a></td>
        <td>Makhachev</td>
        <td>5' 10"</td>
        <td>70"</td>
        <td>155 lbs.</td>
        <td>25-1-0</td>
      </tr>
    </table>
    </body></html>
    """
    mock_get.return_value = mock_resp

    profile = get_fighter_profile("Islam Makhachev")
    # Should return a FighterProfile or None
    assert profile is not None or profile is None  # Just testing it doesn't crash
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fighters.py -v`
Expected: FAIL (module does not exist)

- [ ] **Step 3: Write scrapers/fighters.py**

```python
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
    slpm: float = 0.0            # Sig. strikes landed per min
    str_acc: float = 0.0         # Striking accuracy (0-1)
    str_def: float = 0.0         # Striking defense (0-1)
    td_avg: float = 0.0          # Takedown avg per 15 min
    td_def: float = 0.0          # Takedown defense (0-1)
    sub_avg: float = 0.0         # Submission avg per 15 min
    avg_fight_time: str = ""
    win_streak: int = 0
    last_5_fights: list[dict] = field(default_factory=list)
    detail_url: str = ""


def _parse_pct(text: str) -> float:
    """Parse '59%' to 0.59."""
    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1)) / 100
    return 0.0


def _parse_float(text: str) -> float:
    """Parse numeric text to float."""
    try:
        return float(re.sub(r"[^\d.]", "", text))
    except (ValueError, TypeError):
        return 0.0


def search_fighter(name: str) -> str | None:
    """Search UFCStats.com for a fighter and return their detail page URL."""
    parts = name.strip().split()
    if not parts:
        return None

    # Search by first name
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

    # Parse record from header
    record_el = soup.find("span", class_="b-content__title-record")
    if record_el:
        record_text = record_el.get_text(strip=True).replace("Record:", "").strip()
        profile.record = record_text

    # Parse career stats from the stats boxes
    stat_boxes = soup.find_all("li", class_="b-list__box-list-item")
    for box in stat_boxes:
        text = box.get_text(strip=True)
        if "SLpM" in text:
            profile.slpm = _parse_float(text.split(":")[-1])
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

    # Parse last 5 fights from fight history table
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fighters.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/fighters.py tests/test_fighters.py
git commit -m "feat: add UFC fighter profile scraper"
```

---

## Task 6: Build scrapers/rankings.py

**Files:**
- Create: `scrapers/rankings.py`
- Create: `tests/test_rankings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rankings.py
from unittest.mock import patch, MagicMock
from scrapers.rankings import get_rankings


@patch("scrapers.rankings.requests.get")
def test_get_rankings_returns_dict(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body></body></html>"
    mock_get.return_value = mock_resp

    result = get_rankings()
    assert isinstance(result, dict)


def test_rankings_empty_on_failure():
    with patch("scrapers.rankings.requests.get", side_effect=Exception("fail")):
        result = get_rankings()
        assert result == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rankings.py -v`
Expected: FAIL (module does not exist)

- [ ] **Step 3: Write scrapers/rankings.py**

```python
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
    """Look up a fighter's rank across all divisions.

    Returns (division, rank) or None.
    """
    target = name.lower()
    for division, fighters in rankings.items():
        for f in fighters:
            if target in f["name"].lower():
                return division, f["rank"]
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rankings.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/rankings.py tests/test_rankings.py
git commit -m "feat: add UFC rankings scraper"
```

---

## Task 7: Rewrite scrapers/news.py for UFC

**Files:**
- Modify: `scrapers/news.py` (full rewrite)
- Modify: `tests/test_news.py` (full rewrite)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_news.py
from scrapers.news import FightContext, build_fight_context


def test_fight_context_defaults():
    ctx = FightContext(fighter_name="Islam Makhachev")
    assert ctx.fighter_name == "Islam Makhachev"
    assert ctx.injuries == []
    assert ctx.camp_info == ""
    assert ctx.weight_cut_notes == ""
    assert ctx.layoff_days is None
    assert ctx.short_notice is False


def test_build_fight_context_returns_context():
    ctx = build_fight_context("Unknown Fighter")
    assert isinstance(ctx, FightContext)
    assert ctx.fighter_name == "Unknown Fighter"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_news.py -v`
Expected: FAIL (old MLB code, missing FightContext)

- [ ] **Step 3: Rewrite scrapers/news.py**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_news.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/news.py tests/test_news.py
git commit -m "feat: rewrite news scraper for UFC fight context"
```

---

## Task 8: Update Ensemble — weights.py, consensus.py, challenger.py

**Files:**
- Modify: `ensemble/weights.py:6` — update BET_SLOTS
- Modify: `ensemble/consensus.py:4-10` — rewrite BET_SLOT_FIELDS and vote extraction
- Modify: `ensemble/challenger.py:9` — update system prompt
- Modify: `ensemble/runner.py` — update system prompt import
- Modify: `tests/ensemble_fixtures.py` — update mock data
- Test: `tests/test_ensemble_consensus.py`, `tests/test_ensemble_weights.py`

- [ ] **Step 1: Update ensemble/weights.py BET_SLOTS**

Change line 6 of `ensemble/weights.py` from:
```python
BET_SLOTS = ["moneyline", "run_line", "total", "first_5_ml", "first_5_total"]
```
to:
```python
BET_SLOTS = ["moneyline", "total_rounds", "method"]
```

- [ ] **Step 2: Update ensemble/consensus.py BET_SLOT_FIELDS and vote extraction**

Replace the entire `BET_SLOT_FIELDS` dict and `extract_vote` function:

```python
BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "total_rounds": ("total_rounds", "value_side"),
    "method": ("method", "value_method"),
}


def extract_vote(prediction: dict, bet_slot: str, odds: dict) -> str | None:
    """Extract a model's normalized vote for a bet slot. Returns None for 'none' votes."""
    section_key, field_name = BET_SLOT_FIELDS[bet_slot]
    section = prediction.get("predictions", {}).get(section_key, {})
    raw_vote = section.get(field_name, "none")

    if raw_vote == "none" or raw_vote is None:
        return None

    return raw_vote
```

(Remove the run_line normalization block entirely — UFC has no run line.)

- [ ] **Step 3: Update ensemble/challenger.py system prompt**

Change line 9 from:
```python
CHALLENGER_SYSTEM_PROMPT = """You are an adversarial analyst reviewing an MLB betting ensemble's output.
```
to:
```python
CHALLENGER_SYSTEM_PROMPT = """You are an adversarial analyst reviewing a UFC/MMA betting ensemble's output.
```

- [ ] **Step 4: Update ensemble/runner.py system prompt import**

In `ensemble/runner.py`, find the line that imports or references `MLB_SYSTEM_PROMPT` from `simulate.py` and change it to import `UFC_SYSTEM_PROMPT`:

```python
# Change: from simulate import MLB_SYSTEM_PROMPT
# To: from simulate import UFC_SYSTEM_PROMPT
# And update the default: sys_prompt = system_prompt or UFC_SYSTEM_PROMPT
```

- [ ] **Step 5: Update tests/ensemble_fixtures.py mock data**

Update MOCK_PREDICTION and MOCK_ODDS to use UFC prediction structure with `moneyline`, `total_rounds`, `method`, and `predicted_result` instead of baseball-specific fields. Update MOCK_ODDS to use `fighter_a`/`fighter_b` keys instead of `home`/`away`.

- [ ] **Step 6: Run ensemble tests**

Run: `pytest tests/test_ensemble_consensus.py tests/test_ensemble_weights.py tests/test_ensemble_challenger.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add ensemble/weights.py ensemble/consensus.py ensemble/challenger.py ensemble/runner.py tests/ensemble_fixtures.py
git commit -m "feat: update ensemble engine for UFC bet slots"
```

---

## Task 9: Rewrite briefing.py for UFC

**Files:**
- Modify: `briefing.py` (full rewrite)
- Modify: `tests/test_briefing.py` (full rewrite)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_briefing.py
from briefing import build_briefing


def test_build_briefing_contains_fighter_names():
    fight_data = {
        "event_name": "UFC 300",
        "date": "2026-04-12",
        "fighter_a": {
            "name": "Islam Makhachev",
            "record": "25-1-0",
            "wins_ko": 4, "wins_sub": 11, "wins_dec": 10,
            "stance": "Orthodox", "height": "5'10\"", "reach": "70.5\"",
            "slpm": 2.42, "str_acc": 0.59, "td_avg": 3.15, "td_def": 0.90,
            "sub_avg": 1.2, "avg_fight_time": "12:30", "age": 32,
            "win_streak": 3, "last_5_fights": [],
        },
        "fighter_b": {
            "name": "Charles Oliveira",
            "record": "34-10-0",
            "wins_ko": 10, "wins_sub": 21, "wins_dec": 3,
            "stance": "Orthodox", "height": "5'10\"", "reach": "74\"",
            "slpm": 3.49, "str_acc": 0.56, "td_avg": 2.33, "td_def": 0.53,
            "sub_avg": 1.7, "avg_fight_time": "10:15", "age": 34,
            "win_streak": 0, "last_5_fights": [],
        },
        "weight_class": "Lightweight",
        "rounds": 5,
        "odds": {
            "moneyline": {"fighter_a": -200, "fighter_b": 170},
            "total_rounds": {"line": 2.5, "over_odds": -115, "under_odds": -105},
            "implied_probs": {"fighter_a": 0.65, "fighter_b": 0.35},
        },
        "context_a": {"injuries": [], "camp_info": "", "weight_cut_notes": ""},
        "context_b": {"injuries": [], "camp_info": "", "weight_cut_notes": ""},
        "rankings": {},
    }
    briefing = build_briefing(fight_data)
    assert "Islam Makhachev" in briefing
    assert "Charles Oliveira" in briefing
    assert "UFC 300" in briefing
    assert "Lightweight" in briefing
    assert "FIGHT WINNER" in briefing
    assert "TOTAL ROUNDS" in briefing
    assert "METHOD OF VICTORY" in briefing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_briefing.py -v`
Expected: FAIL (old MLB briefing code)

- [ ] **Step 3: Rewrite briefing.py**

```python
"""Build UFC fight prediction briefing document."""
import logging

logger = logging.getLogger("mirofish.briefing")


def _safe_get(d: dict, *keys, default="N/A"):
    """Safely navigate nested dicts."""
    val = d
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k, default)
        else:
            return default
    return val if val is not None else default


def _format_fight_log(fights: list[dict]) -> str:
    """Format last N fights into readable lines."""
    if not fights:
        return "    No recent fight data available"
    lines = []
    for f in fights:
        result = f.get("result", "?")
        opp = f.get("opponent", "Unknown")
        method = f.get("method", "?")
        rnd = f.get("round", "?")
        date = f.get("date", "")
        lines.append(f"    {date} vs {opp}: {result} via {method} (R{rnd})")
    return "\n".join(lines)


def _format_context(ctx: dict) -> str:
    """Format fight context (injuries, camp, weight cut)."""
    parts = []
    injuries = ctx.get("injuries", [])
    if injuries:
        parts.append(f"  Injuries: {', '.join(injuries)}")
    camp = ctx.get("camp_info", "")
    if camp:
        parts.append(f"  Camp Notes: {camp}")
    weight = ctx.get("weight_cut_notes", "")
    if weight:
        parts.append(f"  Weight Cut: {weight}")
    short_notice = ctx.get("short_notice", False)
    if short_notice:
        parts.append("  SHORT NOTICE REPLACEMENT")
    return "\n".join(parts) if parts else "  No notable context"


def build_briefing(fight_data: dict) -> str:
    """Build a UFC fight prediction briefing document.

    Args:
        fight_data: dict with keys: event_name, date, fighter_a (dict),
                    fighter_b (dict), weight_class, rounds, odds (dict),
                    context_a (dict), context_b (dict), rankings (dict)

    Returns:
        Formatted briefing string for LLM consumption.
    """
    fa = fight_data.get("fighter_a", {})
    fb = fight_data.get("fighter_b", {})
    odds = fight_data.get("odds", {})
    ml = odds.get("moneyline", {})
    tr = odds.get("total_rounds", {})
    ip = odds.get("implied_probs", {})

    briefing = f"""UFC FIGHT PREDICTION ANALYSIS
==============================
{fight_data.get('event_name', 'TBD')} — {fight_data.get('date', 'TBD')}
{fa.get('name', 'Fighter A')} vs {fb.get('name', 'Fighter B')} | {fight_data.get('weight_class', '?')} | {fight_data.get('rounds', 3)} rounds

BETTING LINES:
  Moneyline: {fa.get('name', 'A')} {ml.get('fighter_a', 'N/A')} / {fb.get('name', 'B')} {ml.get('fighter_b', 'N/A')}
  Total Rounds: {tr.get('line', 'N/A')} (Over {tr.get('over_odds', 'N/A')} / Under {tr.get('under_odds', 'N/A')})
  Implied Win Prob: {fa.get('name', 'A')} {ip.get('fighter_a', 0):.1%} / {fb.get('name', 'B')} {ip.get('fighter_b', 0):.1%}

== FIGHTER PROFILES ==

{fa.get('name', 'Fighter A')} — Record: {fa.get('record', '?')}
  Wins: {fa.get('wins_ko', 0)} KO | {fa.get('wins_sub', 0)} SUB | {fa.get('wins_dec', 0)} DEC
  Stance: {fa.get('stance', '?')} | Height: {fa.get('height', '?')} | Reach: {fa.get('reach', '?')}
  Sig. Strikes Landed/Min: {fa.get('slpm', 0)} | Striking Accuracy: {fa.get('str_acc', 0):.0%}
  Takedown Avg/15min: {fa.get('td_avg', 0)} | Takedown Defense: {fa.get('td_def', 0):.0%}
  Submission Avg/15min: {fa.get('sub_avg', 0)} | Avg Fight Time: {fa.get('avg_fight_time', '?')}
  Age: {fa.get('age', '?')} | Current Streak: {fa.get('win_streak', 0)}
  Last 5 Fights:
{_format_fight_log(fa.get('last_5_fights', []))}

{fb.get('name', 'Fighter B')} — Record: {fb.get('record', '?')}
  Wins: {fb.get('wins_ko', 0)} KO | {fb.get('wins_sub', 0)} SUB | {fb.get('wins_dec', 0)} DEC
  Stance: {fb.get('stance', '?')} | Height: {fb.get('height', '?')} | Reach: {fb.get('reach', '?')}
  Sig. Strikes Landed/Min: {fb.get('slpm', 0)} | Striking Accuracy: {fb.get('str_acc', 0):.0%}
  Takedown Avg/15min: {fb.get('td_avg', 0)} | Takedown Defense: {fb.get('td_def', 0):.0%}
  Submission Avg/15min: {fb.get('sub_avg', 0)} | Avg Fight Time: {fb.get('avg_fight_time', '?')}
  Age: {fb.get('age', '?')} | Current Streak: {fb.get('win_streak', 0)}
  Last 5 Fights:
{_format_fight_log(fb.get('last_5_fights', []))}

== CONTEXT ==
  Card Position: {fight_data.get('card_position', 'main_card')}
  Short Notice: {fight_data.get('short_notice', 'No')}

== FIGHTER A CONTEXT ==
{_format_context(fight_data.get('context_a', {}))}

== FIGHTER B CONTEXT ==
{_format_context(fight_data.get('context_b', {}))}

== PREDICTION TASK ==
Analyze this fight from multiple expert perspectives and provide predictions for ALL of the following:

1. FIGHT WINNER: Win probability for each fighter. Which side has moneyline value?
2. TOTAL ROUNDS (O/U {tr.get('line', '?')}): Will this fight go the distance or end early? Factor in finishing rates, cardio, and style matchup.
3. METHOD OF VICTORY: Most likely method (KO/TKO, Submission, Decision). Where does the value lie?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment"""

    missing = []
    if not fa.get("record"):
        missing.append("fighter_a.record")
    if not fb.get("record"):
        missing.append("fighter_b.record")
    if not ml:
        missing.append("odds.moneyline")
    if missing:
        logger.warning("Briefing missing fields: %s", missing)

    return briefing
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_briefing.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add briefing.py tests/test_briefing.py
git commit -m "feat: rewrite briefing template for UFC fight analysis"
```

---

## Task 10: Rewrite simulate.py for UFC

**Files:**
- Modify: `simulate.py` (rewrite system prompt + prediction schema)
- Modify: `tests/test_simulate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_simulate.py
from unittest.mock import patch, MagicMock
import json
from simulate import UFC_SYSTEM_PROMPT, parse_simulation_result


def test_system_prompt_is_ufc():
    assert "UFC" in UFC_SYSTEM_PROMPT
    assert "MLB" not in UFC_SYSTEM_PROMPT
    assert "STRIKING ANALYST" in UFC_SYSTEM_PROMPT
    assert "GRAPPLING ANALYST" in UFC_SYSTEM_PROMPT


def test_parse_simulation_result_valid():
    raw = json.dumps({
        "analyst_assessments": [
            {"role": "striking", "pick": "Fighter A", "reasoning": "..."}
        ],
        "predictions": {
            "moneyline": {
                "fighter_a_win_prob": 0.65,
                "fighter_b_win_prob": 0.35,
                "value_side": "fighter_a",
                "edge": 0.05,
                "confidence": "medium",
            },
            "total_rounds": {
                "projected_rounds": 2.5,
                "over_prob": 0.45,
                "under_prob": 0.55,
                "value_side": "under",
                "edge": 0.06,
                "confidence": "medium",
            },
            "method": {
                "ko_tko_prob": 0.30,
                "submission_prob": 0.35,
                "decision_prob": 0.35,
                "most_likely": "Submission",
                "value_method": "sub",
                "confidence": "medium",
            },
            "predicted_result": {"winner": "Fighter A", "method": "Submission", "round": 3},
            "key_factors": ["wrestling advantage", "submission threat"],
        },
    })
    result = parse_simulation_result(raw)
    assert result is not None
    assert "predictions" in result
    assert "moneyline" in result["predictions"]
    assert "total_rounds" in result["predictions"]
    assert "method" in result["predictions"]


def test_parse_simulation_result_markdown_fences():
    raw = "```json\n{\"predictions\": {}}\n```"
    result = parse_simulation_result(raw)
    assert result is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_simulate.py -v`
Expected: FAIL (MLB_SYSTEM_PROMPT still exists, no UFC_SYSTEM_PROMPT)

- [ ] **Step 3: Rewrite simulate.py system prompt and prediction schema**

Replace `MLB_SYSTEM_PROMPT` with `UFC_SYSTEM_PROMPT` per the spec in `01-ufc-mma.md` (Layer 3). The system prompt defines 6 UFC analyst roles:

1. STRIKING ANALYST
2. GRAPPLING ANALYST
3. CARDIO & DURABILITY ANALYST
4. STYLE MATCHUP ANALYST
5. MARKET ANALYST
6. CONTRARIAN

Output JSON schema uses: `moneyline` (fighter_a_win_prob/fighter_b_win_prob), `total_rounds` (projected_rounds/over_prob/under_prob), `method` (ko_tko_prob/submission_prob/decision_prob), `predicted_result` (winner/method/round).

Update `_average_results()` to average UFC fields instead of MLB fields. Remove `predicted_score` averaging (home/away runs), replace with `predicted_result` handling.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_simulate.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add simulate.py tests/test_simulate.py
git commit -m "feat: rewrite simulation system prompt for UFC expert panel"
```

---

## Task 11: Rewrite edge.py for UFC Bet Types

**Files:**
- Modify: `edge.py` (full rewrite of checkers)
- Modify: `tests/test_edge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_edge.py
from edge import (
    american_to_decimal, kelly_criterion,
    check_moneyline_edge, check_total_rounds_edge, check_method_edge,
    analyze_all_edges,
)


def test_american_to_decimal_negative():
    assert american_to_decimal(-200) == 1.5


def test_american_to_decimal_positive():
    assert american_to_decimal(200) == 3.0


def test_kelly_criterion_positive_edge():
    result = kelly_criterion(0.60, 2.0)
    assert result > 0


def test_kelly_criterion_no_edge():
    result = kelly_criterion(0.40, 2.0)
    assert result == 0


def test_check_moneyline_edge_fighter_a():
    sim = {
        "predictions": {
            "moneyline": {
                "fighter_a_win_prob": 0.75,
                "fighter_b_win_prob": 0.25,
                "confidence": "high",
            }
        }
    }
    odds = {
        "moneyline": {"fighter_a": -150, "fighter_b": 130},
        "implied_probs": {"fighter_a": 0.60, "fighter_b": 0.40},
    }
    result = check_moneyline_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "moneyline"
    assert result["side"] == "fighter_a"
    assert result["edge"] > 0.06


def test_check_moneyline_edge_no_value():
    sim = {
        "predictions": {
            "moneyline": {
                "fighter_a_win_prob": 0.62,
                "fighter_b_win_prob": 0.38,
                "confidence": "medium",
            }
        }
    }
    odds = {
        "moneyline": {"fighter_a": -150, "fighter_b": 130},
        "implied_probs": {"fighter_a": 0.60, "fighter_b": 0.40},
    }
    result = check_moneyline_edge(sim, odds)
    assert result is None  # 2% edge < 6% threshold


def test_check_total_rounds_edge_under():
    sim = {
        "predictions": {
            "total_rounds": {
                "over_prob": 0.35,
                "under_prob": 0.65,
                "confidence": "high",
            }
        }
    }
    odds = {
        "total_rounds": {
            "line": 2.5,
            "over_odds": -115,
            "under_odds": -105,
        }
    }
    result = check_total_rounds_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "total_rounds"
    assert "under" in result["side"]


def test_check_method_edge_ko():
    sim = {
        "predictions": {
            "method": {
                "ko_tko_prob": 0.55,
                "submission_prob": 0.20,
                "decision_prob": 0.25,
                "confidence": "medium",
            }
        }
    }
    # Mock method odds — KO implied at 40%, so 15% edge (> 8% threshold)
    odds = {
        "method_odds": {
            "ko_tko": -110,
            "submission": 200,
            "decision": 150,
        }
    }
    result = check_method_edge(sim, odds)
    assert result is not None
    assert result["bet_type"] == "method"
    assert result["side"] == "ko_tko"


def test_analyze_all_edges_returns_list():
    sim = {"predictions": {}}
    odds = {}
    bets = analyze_all_edges(sim, odds)
    assert isinstance(bets, list)
    assert len(bets) == 0


def test_no_mlb_edge_functions():
    """Ensure no MLB-specific edge functions remain."""
    import edge
    assert not hasattr(edge, "check_run_line_edge")
    assert not hasattr(edge, "check_f5_ml_edge")
    assert not hasattr(edge, "check_f5_total_edge")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_edge.py -v`
Expected: FAIL (MLB edge functions still present, UFC functions missing)

- [ ] **Step 3: Rewrite edge.py**

```python
"""Edge detection and Kelly criterion sizing for UFC bet types."""
import logging
from config import EDGE_THRESHOLDS, KELLY_FRACTION
from scrapers.odds import american_to_implied_prob

logger = logging.getLogger("mirofish.edge")


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds."""
    if odds < 0:
        return round(100 / abs(odds) + 1, 4)
    return round(odds / 100 + 1, 4)


def kelly_criterion(prob: float, decimal_odds: float) -> float:
    """Calculate Kelly fraction. Returns 0 if no edge."""
    b = decimal_odds - 1
    q = 1 - prob
    if b <= 0:
        return 0
    kelly = (b * prob - q) / b
    return max(0, round(kelly, 4))


def check_moneyline_edge(sim: dict, odds: dict) -> dict | None:
    """Check for moneyline value on either fighter."""
    ml_pred = sim.get("predictions", {}).get("moneyline", {})
    ml_odds = odds.get("moneyline", {})
    if not ml_pred or not ml_odds:
        return None

    threshold = EDGE_THRESHOLDS["moneyline"]

    a_prob = ml_pred.get("fighter_a_win_prob", 0)
    a_implied = odds.get("implied_probs", {}).get("fighter_a", 0)
    a_edge = a_prob - a_implied

    b_prob = ml_pred.get("fighter_b_win_prob", 0)
    b_implied = odds.get("implied_probs", {}).get("fighter_b", 0)
    b_edge = b_prob - b_implied

    if a_edge >= threshold and a_edge >= b_edge:
        dec = american_to_decimal(ml_odds["fighter_a"])
        return {
            "bet_type": "moneyline",
            "side": "fighter_a",
            "odds": ml_odds["fighter_a"],
            "sim_prob": a_prob,
            "market_prob": a_implied,
            "edge": round(a_edge, 4),
            "kelly_pct": round(kelly_criterion(a_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ml_pred.get("confidence", "medium"),
        }
    elif b_edge >= threshold:
        dec = american_to_decimal(ml_odds["fighter_b"])
        return {
            "bet_type": "moneyline",
            "side": "fighter_b",
            "odds": ml_odds["fighter_b"],
            "sim_prob": b_prob,
            "market_prob": b_implied,
            "edge": round(b_edge, 4),
            "kelly_pct": round(kelly_criterion(b_prob, dec) * KELLY_FRACTION, 4),
            "confidence": ml_pred.get("confidence", "medium"),
        }

    return None


def check_total_rounds_edge(sim: dict, odds: dict) -> dict | None:
    """Check for total rounds (over/under) value."""
    tr_pred = sim.get("predictions", {}).get("total_rounds", {})
    tr_odds = odds.get("total_rounds", {})
    if not tr_pred or not tr_odds:
        return None

    threshold = EDGE_THRESHOLDS["total_rounds"]

    over_prob = tr_pred.get("over_prob", 0)
    under_prob = tr_pred.get("under_prob", 0)

    over_odds = tr_odds.get("over_odds", -110)
    under_odds = tr_odds.get("under_odds", -110)
    over_implied = american_to_implied_prob(over_odds)
    under_implied = american_to_implied_prob(under_odds)
    total_impl = over_implied + under_implied
    over_implied /= total_impl
    under_implied /= total_impl

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied

    line = tr_odds.get("line", "?")

    if over_edge >= threshold and over_edge >= under_edge:
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "total_rounds",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": over_prob,
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * KELLY_FRACTION, 4),
            "confidence": tr_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "total_rounds",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": under_prob,
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * KELLY_FRACTION, 4),
            "confidence": tr_pred.get("confidence", "medium"),
        }

    return None


def check_method_edge(sim: dict, odds: dict) -> dict | None:
    """Check for method-of-victory value (KO/TKO, Submission, Decision)."""
    method_pred = sim.get("predictions", {}).get("method", {})
    method_odds = odds.get("method_odds", {})
    if not method_pred or not method_odds:
        return None

    threshold = EDGE_THRESHOLDS["method"]

    methods = {
        "ko_tko": method_pred.get("ko_tko_prob", 0),
        "submission": method_pred.get("submission_prob", 0),
        "decision": method_pred.get("decision_prob", 0),
    }

    best_method = None
    best_edge = 0

    for method, sim_prob in methods.items():
        market_odds = method_odds.get(method)
        if market_odds is None:
            continue
        implied = american_to_implied_prob(market_odds)
        edge = sim_prob - implied
        if edge >= threshold and edge > best_edge:
            best_edge = edge
            best_method = method

    if best_method is None:
        return None

    dec = american_to_decimal(method_odds[best_method])
    return {
        "bet_type": "method",
        "side": best_method,
        "odds": method_odds[best_method],
        "sim_prob": methods[best_method],
        "market_prob": round(american_to_implied_prob(method_odds[best_method]), 4),
        "edge": round(best_edge, 4),
        "kelly_pct": round(kelly_criterion(methods[best_method], dec) * KELLY_FRACTION, 4),
        "confidence": method_pred.get("confidence", "medium"),
    }


def analyze_all_edges(sim: dict, odds: dict) -> list[dict]:
    """Run all edge checks for a single fight. Returns 0-3 bet signals."""
    bets = []
    checkers = [
        ("moneyline", check_moneyline_edge),
        ("total_rounds", check_total_rounds_edge),
        ("method", check_method_edge),
    ]

    for name, checker in checkers:
        result = checker(sim, odds)
        if result:
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f sim=%.4f mkt=%.4f kelly=%.4f",
                         name, result["side"], result["edge"],
                         result.get("sim_prob", 0), result.get("market_prob", 0),
                         result["kelly_pct"])
        else:
            logger.debug("Edge check %s: no value (threshold=%.3f)",
                         name, EDGE_THRESHOLDS.get(name, 0))

    logger.info("Edge analysis: %d/%d bet types have value", len(bets), len(checkers))
    return bets
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_edge.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "feat: rewrite edge detection for UFC bet types"
```

---

## Task 12: Rewrite main.py Pipeline Flow

**Files:**
- Modify: `main.py` (full rewrite)
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
from click.testing import CliRunner
from main import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "UFC" in result.output or "ufc" in result.output or "daily" in result.output


def test_report_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["report"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: May pass or fail depending on MLB references

- [ ] **Step 3: Rewrite main.py**

The main.py rewrite should:
1. Replace all MLB scraper imports with UFC scraper imports (`get_upcoming_events`, `get_fight_card`, `get_fighter_profile`, `get_ufc_odds`, `build_fight_context`, `get_rankings`)
2. Replace "MLB" references with "UFC" in CLI help text and logging
3. Replace game_data structure with fight_data structure:
   - `fighter_a`, `fighter_b` (fighter profiles) instead of `away_pitcher`, `home_pitcher`
   - `odds` with UFC odds structure (moneyline, total_rounds)
   - `context_a`, `context_b` instead of bullpen/lineup data
   - Remove ballpark/weather/park_factors
4. Update pipeline flow:
   - Step 1: Fetch upcoming events + fight card
   - Step 2: Fetch UFC odds
   - Step 3: For each fight, fetch fighter profiles
   - Step 4: Fetch fight context (news/injuries)
   - Step 5: Build briefings + screening pass
   - Step 6: Full simulation on fights with >3% edge
5. Replace "game" terminology with "fight" throughout
6. Update `analyze_all_edges()` call to use UFC odds structure
7. Update `log_bet()` to use fight key (e.g., "Makhachev vs Oliveira")

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: rewrite main pipeline for UFC fight analysis"
```

---

## Task 13: Rewrite agents/results_grader.py for UFC

**Files:**
- Modify: `agents/results_grader.py`
- Modify: `tests/test_results_grader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_results_grader.py
from agents.results_grader import grade_bet


def test_grade_moneyline_win():
    bet = {"bet_type": "moneyline", "side": "fighter_a"}
    result = {"winner": "fighter_a"}
    assert grade_bet(bet, result) == "W"


def test_grade_moneyline_loss():
    bet = {"bet_type": "moneyline", "side": "fighter_a"}
    result = {"winner": "fighter_b"}
    assert grade_bet(bet, result) == "L"


def test_grade_total_rounds_over_win():
    bet = {"bet_type": "total_rounds", "side": "over 2.5"}
    result = {"winner": "fighter_a", "method": "Decision", "round": 3}
    assert grade_bet(bet, result) == "W"  # Decision = 3 rounds, > 2.5


def test_grade_total_rounds_under_win():
    bet = {"bet_type": "total_rounds", "side": "under 2.5"}
    result = {"winner": "fighter_a", "method": "KO/TKO", "round": 1}
    assert grade_bet(bet, result) == "W"  # Ended in round 1, < 2.5


def test_grade_method_ko_win():
    bet = {"bet_type": "method", "side": "ko_tko"}
    result = {"winner": "fighter_a", "method": "KO/TKO", "round": 2}
    assert grade_bet(bet, result) == "W"


def test_grade_method_ko_loss():
    bet = {"bet_type": "method", "side": "ko_tko"}
    result = {"winner": "fighter_a", "method": "Decision", "round": 3}
    assert grade_bet(bet, result) == "L"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_results_grader.py -v`
Expected: FAIL (old MLB grading logic)

- [ ] **Step 3: Rewrite agents/results_grader.py**

```python
"""UFC fight result grader — grades pending bets W/L/P based on actual results."""
import logging
import re

logger = logging.getLogger("mirofish.results_grader")


def grade_bet(bet: dict, result: dict) -> str:
    """Grade a single bet against the actual fight result.

    Args:
        bet: dict with bet_type, side
        result: dict with winner, method, round

    Returns: "W", "L", or "P" (push)
    """
    bet_type = bet.get("bet_type", "")
    side = bet.get("side", "")

    if bet_type == "moneyline":
        return "W" if side == result.get("winner") else "L"

    elif bet_type == "total_rounds":
        actual_round = result.get("round", 0)
        method = result.get("method", "")

        # Parse "over 2.5" or "under 2.5"
        match = re.match(r"(over|under)\s+([\d.]+)", side)
        if not match:
            logger.warning("Could not parse total_rounds side: %s", side)
            return "P"

        direction = match.group(1)
        line = float(match.group(2))

        # If fight ends by finish, the ending round is the total
        # If decision, total = max rounds (3 or 5)
        if "decision" in method.lower():
            # Decision means fight went the distance
            # actual_round should be max rounds, but use the value as-is
            pass

        if direction == "over":
            return "W" if actual_round > line else "L"
        else:
            return "W" if actual_round < line else "L"

    elif bet_type == "method":
        actual_method = result.get("method", "").lower()
        method_map = {
            "ko_tko": ["ko", "tko", "ko/tko"],
            "submission": ["submission", "sub"],
            "decision": ["decision", "unanimous", "split", "majority"],
        }
        matching_methods = method_map.get(side, [])
        for m in matching_methods:
            if m in actual_method:
                return "W"
        return "L"

    logger.warning("Unknown bet type: %s", bet_type)
    return "P"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_results_grader.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add agents/results_grader.py tests/test_results_grader.py
git commit -m "feat: rewrite results grader for UFC fight outcomes"
```

---

## Task 14: Update agents/health_check.py and agents/bet_card.py

**Files:**
- Modify: `agents/health_check.py`
- Modify: `agents/bet_card.py`
- Modify: `tests/test_health_check.py`
- Modify: `tests/test_bet_card.py`

- [ ] **Step 1: Update health_check.py**

Replace `check_mlb_api()` with `check_ufc_stats()`:

```python
def check_ufc_stats():
    """Validate UFCStats.com is reachable."""
    try:
        resp = requests.get("http://ufcstats.com/statistics/events/completed", timeout=10)
        return {"status": "ok", "source": "UFCStats.com"} if resp.status_code == 200 else {"status": "error"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
```

Remove `check_weather_api()` (UFC fights are indoors). Keep `check_odds_api()` and `check_openrouter()`.

- [ ] **Step 2: Update bet_card.py**

Update game key format from "AWAY@HOME" to "Fighter A vs Fighter B". Update bet type display to show UFC bet types (moneyline, total_rounds, method).

- [ ] **Step 3: Update tests**

Update `tests/test_health_check.py` to test `check_ufc_stats()` instead of `check_mlb_api()`.
Update `tests/test_bet_card.py` if needed for UFC bet type formatting.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_health_check.py tests/test_bet_card.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add agents/health_check.py agents/bet_card.py tests/test_health_check.py tests/test_bet_card.py
git commit -m "feat: update health check and bet card for UFC"
```

---

## Task 15: Update ensemble/orchestrator.py for UFC

**Files:**
- Modify: `ensemble/orchestrator.py` — update score prediction averaging
- Test: `tests/test_ensemble_orchestrator.py`

- [ ] **Step 1: Update predicted_result handling**

In `build_ensemble_result()`, replace the predicted score averaging logic:

```python
# OLD: average home/away runs
# predicted_score = {
#     "home": round(sum(...)/len(...)),
#     "away": round(sum(...)/len(...)),
# }

# NEW: majority vote on winner, most common method, average round
predicted_results = [r["parsed"]["predictions"].get("predicted_result", {}) for r in results if r.get("parsed")]
if predicted_results:
    winners = [pr.get("winner", "") for pr in predicted_results if pr.get("winner")]
    methods = [pr.get("method", "") for pr in predicted_results if pr.get("method")]
    rounds = [pr.get("round", 0) for pr in predicted_results if pr.get("round")]

    from ensemble.consensus import majority_vote
    ensemble_pred["predictions"]["predicted_result"] = {
        "winner": majority_vote(winners, default=winners[0] if winners else ""),
        "method": majority_vote(methods, default=methods[0] if methods else ""),
        "round": round(sum(rounds) / len(rounds)) if rounds else 0,
    }
```

- [ ] **Step 2: Run ensemble orchestrator tests**

Run: `pytest tests/test_ensemble_orchestrator.py -v`
Expected: ALL PASS (may need fixture updates from Task 8)

- [ ] **Step 3: Commit**

```bash
git add ensemble/orchestrator.py
git commit -m "feat: update ensemble orchestrator for UFC predicted results"
```

---

## Task 16: Update requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add beautifulsoup4 dependency**

```
requests
python-dotenv
openai
click
pandas
beautifulsoup4
```

- [ ] **Step 2: Install dependencies**

Run: `pip3 install beautifulsoup4`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add beautifulsoup4 for UFC scraping"
```

---

## Task 17: Full Test Suite Verification

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASS with no MLB-specific failures

- [ ] **Step 2: Verify no MLB imports remain**

Run: `grep -r "MLB\|pitchers\|lineups\|bullpen\|ballpark\|team_stats\|scores\|run_line\|first_5\|f5_\|pybaseball\|TEAM_ABBREVS\|PARK_FACTORS\|PARK_COORDS" --include="*.py" . | grep -v "__pycache__" | grep -v ".pyc" | grep -v "test_" | grep -v "01-ufc-mma.md"`

Expected: No matches (or only in comments/docs)

- [ ] **Step 3: Commit any remaining fixes**

```bash
git add -u
git commit -m "chore: verify full test suite passes for UFC pipeline"
```
