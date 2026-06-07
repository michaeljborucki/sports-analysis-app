# MiroFish Esports Pipeline — Design Specification

**Date**: 2026-03-20
**Status**: Draft
**Scope**: Transform the existing MLB betting pipeline into an esports-focused system supporting CS2 and League of Legends, with complete removal of all MLB functionality.

---

## 1. Overview

### What We're Building

A 6-layer esports betting prediction pipeline that uses a multi-model LLM ensemble to predict match outcomes, detect edge vs. market odds, and output bet cards with Kelly-criterion sizing. Starting with CS2, then adding League of Legends.

### Pipeline Flow

```
SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET
```

### What Changes vs. Current MLB System

| Layer | MLB (current) | Esports (target) |
|-------|---------------|-------------------|
| Scrapers | MLB API, pybaseball, weather | HLTV, Oracle's Elixir, OddsPapi, Liquipedia |
| Odds | The Odds API (`baseball_mlb`) | OddsPapi (primary) + The Odds API fallback |
| Briefing | Pitcher matchup, bullpen, ballpark | Map pool, patch meta, roster stability |
| System Prompt | 6 baseball analysts | 6 esports analysts (game-specific) |
| Bet Slots | moneyline, run_line, total, F5 ML, F5 total | moneyline, map_handicap, total_maps |
| Edge Thresholds | Flat per bet type | Format-aware (Bo1/Bo3/Bo5) |
| Config | 30 MLB teams, park factors | Tournament tiers, game registries |
| Ensemble | Adapted | BET_SLOTS, PROB_FIELDS, vote maps made dynamic via game module |
| Tracker | Unchanged | Unchanged (sport-agnostic) |
| Agents | Unchanged (minor adaptations) | Unchanged (minor adaptations) |

### What Gets Deleted (MLB Removal)

**Files to delete entirely:**
- `scrapers/pitchers.py` — MLB pitcher stats
- `scrapers/scores.py` — MLB final scores
- `scrapers/team_stats.py` — MLB team records
- `scrapers/lineups.py` — MLB confirmed lineups
- `scrapers/bullpen.py` — MLB bullpen state
- `scrapers/ballpark.py` — Park factors + weather
- `tests/test_pitchers.py`
- `tests/test_scores.py`
- `tests/test_team_stats.py`
- `tests/test_lineups.py`
- `tests/test_bullpen.py`
- `tests/test_ballpark.py`
- `data/bets.csv` — MLB bet history
- `data/model_predictions.csv` — MLB prediction logs
- `data/model_weights.json` — MLB model weights (reset for esports)

**Config to remove:**
- `MLB_API_BASE`
- `WEATHER_API_KEY`, `WEATHER_API_BASE`
- `TEAM_ABBREVS` (30 MLB teams)
- `TEAM_NAME_TO_ABBREV` (MLB name mapping)
- `PARK_FACTORS` (30 ballparks)
- `PARK_COORDS` (ballpark coordinates)
- MLB-specific `EDGE_THRESHOLDS` (run_line, first_5_ml, first_5_total)

---

## 2. Architecture

### Directory Structure

```
esports-agents/
├── main.py                      # CLI entrypoint (adapted for esports)
├── config.py                    # Global config: API keys, ensemble, Kelly
├── briefing.py                  # Dispatch to game-specific briefing builder
├── simulate.py                  # Plan B screen + ensemble interface
├── edge.py                      # Edge detection + Kelly sizing (adapted)
├── tracker.py                   # CSV bet logging (unchanged)
├── calibrate.py                 # Calibration (unchanged)
│
├── games/                       # Game-specific modules (NEW)
│   ├── __init__.py              # Game registry: GAMES = {"cs2": cs2, "lol": lol}
│   ├── cs2/
│   │   ├── __init__.py
│   │   ├── scrapers.py          # HLTV team data, schedule, head-to-head
│   │   ├── briefing.py          # CS2 briefing template
│   │   ├── config.py            # CS2 bet slots, thresholds, analyst roles
│   │   └── prompt.py            # CS2 expert panel system prompt
│   └── lol/
│       ├── __init__.py
│       ├── scrapers.py          # Oracle's Elixir CSV, Riot data
│       ├── briefing.py          # LoL briefing template
│       ├── config.py            # LoL bet slots, thresholds, analyst roles
│       └── prompt.py            # LoL expert panel system prompt
│
├── scrapers/                    # Shared scrapers (cross-game)
│   ├── __init__.py
│   ├── odds.py                  # OddsPapi + The Odds API (rewritten)
│   ├── schedule.py              # Unified match schedule (NEW)
│   ├── meta.py                  # Patch notes fetcher + LLM summarizer (NEW)
│   └── news.py                  # Roster changes, team news (rewritten)
│
├── ensemble/                    # Multi-model ensemble (UNCHANGED)
│   ├── __init__.py
│   ├── orchestrator.py
│   ├── runner.py
│   ├── models.py
│   ├── challenger.py
│   ├── weights.py
│   ├── consensus.py
│   └── logger.py
│
├── agents/                      # Task agents (minor adaptations)
│   ├── __init__.py
│   ├── daily_runner.py          # Adapted for multi-game daily loop
│   ├── results_grader.py        # Adapted for esports result formats
│   ├── health_check.py          # Adapted for new API endpoints
│   ├── bet_card.py              # Adapted for esports bet types
│   └── self_optimizer.py        # Unchanged
│
├── tests/                       # Test suite (rebuilt for esports)
│   ├── __init__.py
│   ├── ensemble_fixtures.py     # Updated with esports mock data
│   ├── test_ensemble_*.py       # Unchanged (sport-agnostic)
│   ├── test_odds.py             # Rewritten for OddsPapi
│   ├── test_cs2_scrapers.py     # NEW
│   ├── test_lol_scrapers.py     # NEW
│   ├── test_schedule.py         # NEW
│   ├── test_meta.py             # NEW
│   ├── test_edge.py             # Updated for esports bet types
│   ├── test_briefing.py         # Updated for esports
│   └── ...
│
├── data/                        # Runtime data (reset for esports)
│   ├── bets.csv
│   ├── model_predictions.csv
│   └── model_weights.json
│
└── docs/
    └── superpowers/specs/
        ├── 2026-03-20-esports-pipeline-design.md  (this file)
        └── decisions-log.md
```

### Game Registry Pattern

```python
# games/__init__.py
from games import cs2, lol

GAMES = {
    "cs2": cs2,
    "lol": lol,
}

def get_game(game_key: str):
    """Return game module by key. Each module exposes:
    - scrapers: fetch_matches(), fetch_team_profile(), fetch_head_to_head()
    - briefing: build_briefing(match_data) -> str
    - config: BET_SLOTS, EDGE_THRESHOLDS, ANALYST_ROLES
    - prompt: SYSTEM_PROMPT, OUTPUT_SCHEMA
    """
    return GAMES[game_key]
```

Each game module is a self-contained package. The main pipeline asks the registry for the right module, then calls its standard interface. Adding a new game (Valorant, Dota 2) means adding a new subdirectory — zero changes to core code.

---

## 3. Odds Layer — OddsPapi Integration

### Why OddsPapi

The Odds API was tested live. Results:
- `esports_lol`: recognized key, zero events returned
- `esports_csgo`: "Unknown sport" error
- All other esports keys: unrecognized

OddsPapi provides: 350+ bookmakers (including Pinnacle), CS2/LoL/Dota2/Valorant coverage, free tier (250 req/month), historical odds with timestamps.

### OddsData Dataclass (Rewritten)

```python
@dataclass
class OddsData:
    team_a: str                    # First team (replaces "home")
    team_b: str                    # Second team (replaces "away")
    commence_time: str
    game_title: str                # "cs2" or "lol"
    tournament: str                # Tournament name
    format: str                    # "bo1", "bo3", "bo5"
    moneyline: dict = field(default_factory=dict)
    # {"team_a": -150, "team_b": 130}
    map_handicap: dict = field(default_factory=dict)
    # {"team_a_line": -1.5, "team_a_odds": -110,
    #  "team_b_line": 1.5, "team_b_odds": -110}
    total_maps: dict = field(default_factory=dict)
    # {"line": 2.5, "over_odds": -110, "under_odds": -110}
    implied_probs: dict = field(default_factory=dict)
    # {"ml_team_a": 0.60, "ml_team_b": 0.40, ...}
    bookmaker_count: int = 0       # How many books have this match
    pinnacle_odds: dict = field(default_factory=dict)  # Pinnacle specifically (for CLV)
```

### Odds Fetching Flow

```python
def get_esports_odds(game_key: str) -> list[OddsData]:
    """Fetch odds from OddsPapi (primary) with The Odds API fallback."""
    # 1. Try OddsPapi
    odds = _fetch_oddspapi(game_key)
    if odds:
        return odds

    # 2. Fallback: The Odds API (only works for LoL, sometimes)
    if game_key == "lol":
        odds = _fetch_the_odds_api("esports_lol")
        if odds:
            return odds

    # 3. No odds available
    return []
```

### OddsPapi API Integration

```python
ODDSPAPI_BASE = "https://api.oddspapi.com/v1"
ODDSPAPI_SPORT_IDS = {
    "cs2": 17,
    "lol": 18,
    "dota2": 16,
    "valorant": 61,
}

def _fetch_oddspapi(game_key: str) -> list[OddsData]:
    """Fetch from OddsPapi REST API."""
    sport_id = ODDSPAPI_SPORT_IDS[game_key]
    resp = requests.get(f"{ODDSPAPI_BASE}/odds", params={
        "sport_id": sport_id,
        "market": "match_winner,map_handicap,total_maps",
    })
    # Parse response into OddsData objects
    # Extract Pinnacle odds separately for CLV tracking
    ...
```

### Implied Probability Calculation

Same `american_to_implied_prob()` function — it's math, not sport-specific. Vig removal via normalization stays identical.

For Pinnacle-specific CLV tracking:
```python
def compute_clv(our_prob: float, pinnacle_closing_prob: float) -> float:
    """Closing Line Value = our edge vs Pinnacle closing line."""
    return our_prob - pinnacle_closing_prob
```

---

## 4. CS2 Scrapers

### 4.1 Team Profile Scraper (`games/cs2/scrapers.py`)

**Source**: HLTV via `hltv-async-api` Python package

```python
async def fetch_team_profile(team_name: str) -> dict:
    """Fetch CS2 team profile from HLTV."""
    return {
        "name": str,
        "hltv_ranking": int,          # Current world ranking
        "win_rate_3m": float,         # Win rate last 3 months
        "win_rate_6m": float,         # Win rate last 6 months
        "lan_record": str,            # "15-8" (LAN matches)
        "online_record": str,         # "22-12" (online matches)
        "roster": [str, str, str, str, str],  # 5 players
        "coach": str,
        "days_since_roster_change": int,
        "map_pool": {
            "mirage": {"win_rate": float, "games": int},
            "inferno": {"win_rate": float, "games": int},
            "nuke": {"win_rate": float, "games": int},
            "ancient": {"win_rate": float, "games": int},
            "anubis": {"win_rate": float, "games": int},
            "dust2": {"win_rate": float, "games": int},
            "vertigo": {"win_rate": float, "games": int},
        },
        "recent_form": [  # Last 10 matches
            {"date": str, "opponent": str, "score": str, "tournament": str},
        ],
    }
```

### 4.2 Schedule Scraper

**Source**: HLTV upcoming matches

```python
async def fetch_upcoming_matches() -> list[dict]:
    """Fetch upcoming CS2 matches from HLTV."""
    return [{
        "team_a": str,
        "team_b": str,
        "tournament": str,
        "format": str,          # "bo1", "bo3", "bo5"
        "tier": int,            # 1, 2, or 3
        "date": str,
        "lan": bool,            # True if LAN event
    }]
```

### 4.3 Head-to-Head

```python
async def fetch_head_to_head(team_a: str, team_b: str) -> dict:
    """Fetch H2H history from HLTV."""
    return {
        "total_matches": int,
        "team_a_wins": int,
        "team_b_wins": int,
        "recent_5": [{"date": str, "winner": str, "score": str, "tournament": str}],
    }
```

### 4.4 Results Scraper (for grading)

```python
async def fetch_match_result(team_a: str, team_b: str, date: str) -> dict:
    """Fetch completed match result for bet grading."""
    return {
        "winner": str,
        "score": str,             # "2-1", "2-0", "1-0"
        "maps_played": int,       # Total maps
        "map_scores": [           # Per-map results
            {"map": str, "team_a_rounds": int, "team_b_rounds": int},
        ],
    }
```

---

## 5. LoL Scrapers

### 5.1 Team Profile Scraper (`games/lol/scrapers.py`)

**Source**: Oracle's Elixir CSV downloads (updated daily)

```python
def fetch_team_profile(team_name: str, region: str) -> dict:
    """Fetch LoL team profile from Oracle's Elixir data."""
    return {
        "name": str,
        "region": str,                # LCK, LPL, LEC, LCS, etc.
        "league_standing": str,       # "3rd in LCK Spring 2026"
        "win_rate": float,            # Overall
        "blue_side_wr": float,        # Blue side win rate
        "red_side_wr": float,         # Red side win rate
        "avg_game_duration": float,   # Minutes
        "first_blood_rate": float,
        "first_tower_rate": float,
        "first_dragon_rate": float,
        "gold_diff_15": float,        # Average GD@15
        "roster": [str, str, str, str, str],  # Top, Jg, Mid, ADC, Sup
        "coach": str,
        "days_since_roster_change": int,
        "recent_form": [
            {"date": str, "opponent": str, "score": str, "tournament": str},
        ],
    }
```

### 5.2 Oracle's Elixir Data Loader

```python
import pandas as pd

OE_CSV_URL = "https://oracleselixir.com/tools/downloads"

def load_oracle_data(year: int = 2026) -> pd.DataFrame:
    """Download and cache Oracle's Elixir match data CSV.

    Cache locally in data/oracle_elixir_{year}.csv.
    Re-download if file is older than 24 hours.
    """
    ...
```

### 5.3 Results Scraper

```python
def fetch_match_result(team_a: str, team_b: str, date: str) -> dict:
    """Fetch completed LoL match result for grading."""
    return {
        "winner": str,
        "score": str,             # "2-1", "3-1", "2-0"
        "maps_played": int,       # Standardized key (same as CS2, even though LoL calls them "games")
        "game_details": [
            {"game_num": int, "winner": str, "duration": float, "gold_diff": int},
        ],
    }
```

---

## 6. Shared Scrapers

### 6.1 Patch/Meta Scraper (`scrapers/meta.py`)

This is where LLMs add unique value — parsing natural-language patch notes.

```python
def fetch_patch_context(game_key: str) -> dict:
    """Fetch current patch info and summarize key changes via LLM."""
    if game_key == "cs2":
        url = "https://blog.counter-strike.net/index.php/category/updates/"
    elif game_key == "lol":
        url = "https://www.leagueoflegends.com/en-us/news/tags/patch-notes/"

    # 1. Fetch latest patch notes page
    # 2. Extract patch version and raw notes text
    # 3. Send to cheap LLM (Kimi) with prompt:
    #    "Summarize the competitive impact of these patch notes in 3-5 bullet points.
    #     Focus on: weapon/champion balance changes, map changes, economy changes.
    #     Rate impact: minor/moderate/major."
    # 4. Cache result keyed by patch version (don't re-fetch same patch)

    return {
        "patch_version": str,
        "days_since_patch": int,
        "key_changes": [str],          # LLM-summarized bullet points
        "impact_rating": str,          # "minor", "moderate", "major"
        "raw_url": str,                # Link to full patch notes
    }
```

### 6.2 News/Roster Scraper (`scrapers/news.py`)

```python
def fetch_match_context(game_key: str, team_a: str, team_b: str) -> dict:
    """Fetch contextual news for a specific match."""
    return {
        "roster_news": {
            "team_a": [str],           # Recent roster changes, stand-ins
            "team_b": [str],
        },
        "tournament_context": {
            "stage": str,              # "group stage", "playoff", "grand final"
            "stakes": str,             # "elimination", "qualification", etc.
            "format": str,             # "bo1", "bo3", "bo5"
        },
        "narrative": str,             # Rivalries, storylines
        "online_lan": str,            # "online" or "lan"
    }
```

### 6.3 Schedule Aggregator (`scrapers/schedule.py`)

```python
def get_todays_matches(game_keys: list[str] = None) -> list[dict]:
    """Get all upcoming matches across all games, filtered by tier.

    Only returns Tier 1 and Tier 2 events.
    """
    if game_keys is None:
        game_keys = ["cs2", "lol"]

    all_matches = []
    for game_key in game_keys:
        game = get_game(game_key)
        matches = game.scrapers.fetch_upcoming_matches()
        # Filter: tier <= 2 only
        matches = [m for m in matches if m["tier"] <= 2]
        for m in matches:
            m["game_key"] = game_key
        all_matches.extend(matches)

    return sorted(all_matches, key=lambda m: m["date"])
```

---

## 7. Briefing Templates

### 7.1 CS2 Briefing (`games/cs2/briefing.py`)

```python
def build_briefing(match_data: dict) -> str:
    """Build CS2 match briefing from scraped data."""
    return f"""
CS2 MATCH PREDICTION ANALYSIS
==============================
{match_data['tournament']} — {match_data['date']} | {match_data['format']} (Bo{match_data['bo_count']})
{match_data['team_a']['name']} vs {match_data['team_b']['name']} | Tier: {match_data['tier']}

BETTING LINES:
  Moneyline: {team_a_name} {ml_a} / {team_b_name} {ml_b}
  Map Handicap: {team_a_name} {hc_a} ({hc_a_odds}) / {team_b_name} {hc_b} ({hc_b_odds})
  Total Maps: {line} (Over {over_odds} / Under {under_odds})
  Implied Win Prob: {team_a_name} {prob_a:.1%} / {team_b_name} {prob_b:.1%}

== TEAM PROFILES ==

{team_a_name} — HLTV Rank #{rank_a}
  Record (3mo): {record_3m_a} | Win Rate: {wr_3m_a}%
  LAN Record: {lan_record_a} | Online Record: {online_record_a}
  Roster: {player1}, {player2}, {player3}, {player4}, {player5}
  Last Roster Change: {days_since_change_a} days ago
  Map Pool:
    {map1}: {wr}% ({games} games) | {map2}: {wr}% | ...
  Recent Form (Last 10):
    {date} vs {opp}: {score} ({tournament})

{team_b_name} — HLTV Rank #{rank_b}
  [same structure]

== MAP VETO ANALYSIS ==
  {team_a_name} likely bans: {ban1}, {ban2}
  {team_b_name} likely bans: {ban1}, {ban2}
  Likely maps played: {map1}, {map2}, {map3}
  Map pool overlap/advantage: {analysis}

== META & PATCH CONTEXT ==
  Current Patch: {version} (released {days_ago} days ago)
  Key Changes: {summary}
  Impact on This Match: {how patch affects team playstyles}

== CONTEXT ==
  Tournament Stage: {stage}
  Stakes: {stakes}
  Online/LAN: {online_lan}
  Head-to-Head (Last 5): {h2h_record}

== PREDICTION TASK ==
Analyze this match and provide predictions for ALL of the following:

1. MATCH WINNER: Win probability for each team. Which side has moneyline value?
2. MAP HANDICAP ({team_a_name} {hc_a}): Will the favored team win by 2+ maps?
3. TOTAL MAPS (O/U {line}): Will it be a sweep or go to a decider?

For each, provide: probability estimate, whether market offers value, confidence, key factors.
"""
```

### 7.2 LoL Briefing (`games/lol/briefing.py`)

Similar structure but with LoL-specific sections:
- Side win rates (blue/red) instead of map pool
- GD@15, first blood rate, dragon control instead of map veto analysis
- Champion pool / meta impact instead of weapon balance

---

## 8. System Prompts

### 8.1 CS2 Expert Panel (`games/cs2/prompt.py`)

```python
CS2_SYSTEM_PROMPT = """
You are an elite CS2 prediction system analyzing a professional match.
Simulate a panel of 6 expert analysts:

1. FRAGGING ANALYST: Individual player skill, AWP matchup, entry fragging,
   clutch statistics, star player form. Who wins the aim duels?

2. TACTICAL ANALYST: Team strategy, utility usage, site executes, default
   setups, anti-eco management. Which team has the tactical edge?

3. MAP POOL ANALYST: Map veto scenarios, per-map win rates, comfort picks
   vs opponent's map pool. What is the likely map selection?

4. FORM & MOMENTUM ANALYST: Recent results, tournament runs, roster changes,
   bootcamp status, LAN vs online. Who is peaking?

5. MARKET ANALYST: Betting line value. Where is public money flowing? Are
   odds reflecting rankings or actual form? Where is the market inefficient?

6. CONTRARIAN: Challenges consensus. What upset scenario is overlooked?
   Is the favorite's form on unsustainable maps? Hidden roster issues?

Respond in valid JSON only:
{
  "analyst_assessments": [
    {"role": "fragging", "pick": "TEAM", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "team_a_win_prob": 0.XX,
      "team_b_win_prob": 0.XX,
      "value_side": "team_a|team_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "map_handicap": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_maps": {
      "projected_maps": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_result": {"winner": "TEAM", "score": "2-1"},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
"""
```

### 8.2 LoL Expert Panel (`games/lol/prompt.py`)

```python
LOL_SYSTEM_PROMPT = """
You are an elite League of Legends prediction system analyzing a professional match.
Simulate a panel of 6 expert analysts:

1. LANING ANALYST: Individual lane matchups, player champion pools, mechanical
   skill comparison, historical lane performance and gold differentials at 15.

2. MACRO ANALYST: Team macro strategy, objective control (dragon, baron, herald),
   vision score, split push vs teamfight tendencies. Which team controls the map?

3. DRAFT ANALYST: Champion select analysis, meta adaptation, flex picks, counter
   picks, composition synergy and scaling curves. Who wins the draft?

4. FORM & MOMENTUM ANALYST: Recent results, playoff pressure, roster changes,
   blue/red side performance splits. Who is in better form?

5. MARKET ANALYST: Betting line value. Regional bias in odds? Is the market
   pricing based on reputation or current performance? Where is value?

6. CONTRARIAN: Challenges consensus. Is the underdog's recent form against
   weaker opponents? Is the favorite overvalued due to name recognition?

Respond in valid JSON only:
{
  "analyst_assessments": [
    {"role": "laning", "pick": "TEAM", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "team_a_win_prob": 0.XX,
      "team_b_win_prob": 0.XX,
      "value_side": "team_a|team_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "map_handicap": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_maps": {
      "projected_maps": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_result": {"winner": "TEAM", "score": "2-1"},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
"""
```

---

## 9. Ensemble Adaptations (CRITICAL)

The ensemble is NOT fully sport-agnostic in its current form. The following constants in the ensemble module are hardcoded to MLB and MUST be made dynamic by reading from the game module.

### Constants That Must Change

```python
# ensemble/orchestrator.py — CURRENTLY hardcoded:
BET_SLOTS = ["moneyline", "run_line", "total", "first_5_ml", "first_5_total"]

PROB_FIELDS = {
    "moneyline": ["home_win_prob", "away_win_prob"],
    "run_line": ["favorite_cover_prob"],
    "total": ["over_prob", "under_prob", "projected_total"],
    "first_5": ["f5_home_win_prob", "f5_away_win_prob", "f5_projected_total"],
}

SLOT_SECTION = {
    "moneyline": "moneyline",
    "run_line": "run_line",
    "total": "total",
    "first_5_ml": "first_5",
    "first_5_total": "first_5",
}

PRIMARY_PROB_FIELD = {
    "moneyline": "home_win_prob",
    "run_line": "favorite_cover_prob",
    "total": "over_prob",
    "first_5_ml": "f5_home_win_prob",
    "first_5_total": "f5_projected_total",
}
```

### Solution: Game Module Provides These Constants

Each game module's `config.py` exports these mappings. The orchestrator reads them dynamically.

```python
# games/cs2/config.py (and games/lol/config.py — identical for now)
BET_SLOTS = ["moneyline", "map_handicap", "total_maps"]

PROB_FIELDS = {
    "moneyline": ["team_a_win_prob", "team_b_win_prob"],
    "map_handicap": ["favorite_cover_prob"],
    "total_maps": ["over_prob", "under_prob", "projected_maps"],
}

SLOT_SECTION = {
    "moneyline": "moneyline",
    "map_handicap": "map_handicap",
    "total_maps": "total_maps",
}

PRIMARY_PROB_FIELD = {
    "moneyline": "team_a_win_prob",
    "map_handicap": "favorite_cover_prob",
    "total_maps": "over_prob",
}
```

### Orchestrator Changes

```python
# ensemble/orchestrator.py — adapted to accept game config
def run_ensemble(briefing: str, odds: dict, game_config: object) -> dict | None:
    """Run 3-phase ensemble. game_config provides BET_SLOTS, PROB_FIELDS, etc."""
    bet_slots = game_config.BET_SLOTS
    prob_fields = game_config.PROB_FIELDS
    slot_section = game_config.SLOT_SECTION
    primary_prob = game_config.PRIMARY_PROB_FIELD
    # ... rest of orchestrator uses these instead of module-level constants
```

### Consensus Vote Map Changes

```python
# ensemble/consensus.py — CURRENTLY hardcoded:
BET_SLOT_FIELDS = {
    "moneyline": ("home_win_prob", "home", "away"),
    "run_line": ("favorite_cover_prob", "favorite_rl", "underdog_rl"),
    ...
}

# ESPORTS replacement:
BET_SLOT_FIELDS = {
    "moneyline": ("team_a_win_prob", "team_a", "team_b"),
    "map_handicap": ("favorite_cover_prob", "favorite", "underdog"),
    "total_maps": ("over_prob", "over", "under"),
}
```

This also becomes dynamic — consensus module accepts `bet_slot_fields` from game config.

### Predicted Result Handling

The MLB system uses `predicted_score: {"away": 3, "home": 5}` (numeric, averaged across models).
Esports uses `predicted_result: {"winner": "TEAM", "score": "2-1"}` (string, not averageable).

**Solution**: In `build_ensemble_result()`, use majority vote for `predicted_result` instead of averaging:
```python
# Count predicted scores across models, pick the most common
score_votes = Counter(r["predictions"]["predicted_result"]["score"] for r in runs)
winner_votes = Counter(r["predictions"]["predicted_result"]["winner"] for r in runs)
ensemble_result["predictions"]["predicted_result"] = {
    "winner": winner_votes.most_common(1)[0][0],
    "score": score_votes.most_common(1)[0][0],
}
```

### Odds Serialization Contract

The ensemble receives odds as a `dict` (via `odds.to_dict()` on the `OddsData` dataclass):

```python
class OddsData:
    ...
    def to_dict(self) -> dict:
        """Serialize for passing to ensemble layers."""
        return {
            "team_a": self.team_a,
            "team_b": self.team_b,
            "moneyline": self.moneyline,
            "map_handicap": self.map_handicap,
            "total_maps": self.total_maps,
            "implied_probs": self.implied_probs,
            "format": self.format,
        }
```

The consensus module's `normalize_vote()` references `odds.get("map_handicap", {})` instead of the old `odds.get("run_line", {})`.

---

## 10. Screen Pass Adaptations (CRITICAL)

The screen pass (`simulate.py`) currently has a hardcoded MLB system prompt. This MUST be adapted in Phase 1, not Phase 4, because the screen pass is the gate that determines which matches proceed to the full ensemble.

### Solution: Game-Aware Screen Pass

```python
# simulate.py — adapted
def run_plan_b(briefing: str, game_config: object) -> dict | None:
    """Screen pass using cheap model. Uses game-specific system prompt."""
    system_prompt = game_config.SYSTEM_PROMPT  # From games/cs2/prompt.py or games/lol/prompt.py

    response = openai_client.chat.completions.create(
        model=KIMI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": briefing},
        ],
        temperature=0.7,
        max_tokens=4096,
    )
    # Parse JSON response using game-specific schema
    ...

def run_mirofish(briefing: str, odds: dict, game_config: object, runs: int = 3) -> dict | None:
    """Full ensemble. Passes game_config through to orchestrator."""
    return run_ensemble(briefing, odds, game_config)
```

---

## 11. Edge Detection Adaptations

### Bet Slots

```python
# games/cs2/config.py and games/lol/config.py
BET_SLOTS = ["moneyline", "map_handicap", "total_maps"]
```

### Format-Aware Edge Thresholds

```python
EDGE_THRESHOLDS = {
    "bo1": {
        "moneyline": 0.07,       # 7% — high variance
        # map_handicap N/A for Bo1
        # total_maps N/A for Bo1
    },
    "bo3": {
        "moneyline": 0.05,       # 5%
        "map_handicap": 0.06,    # 6%
        "total_maps": 0.05,      # 5%
    },
    "bo5": {
        "moneyline": 0.04,       # 4% — low variance
        "map_handicap": 0.05,    # 5%
        "total_maps": 0.04,      # 4%
    },
}
```

### Edge Check Functions — New Signatures

```python
def analyze_all_edges(sim: dict, odds: OddsData, format: str, game_config: object) -> list[dict]:
    """Run all edge checks for esports bet types.

    Args:
        sim: Ensemble simulation result
        odds: OddsData with implied probs
        format: "bo1", "bo3", or "bo5" — determines thresholds
        game_config: Game module config with EDGE_THRESHOLDS
    """
    thresholds = game_config.EDGE_THRESHOLDS[format]

    checkers = [
        ("moneyline", check_moneyline_edge),
        ("map_handicap", check_map_handicap_edge),
        ("total_maps", check_total_maps_edge),
    ]

    bets = []
    for bet_type, checker_fn in checkers:
        if bet_type not in thresholds:
            continue  # Skip N/A bet types (e.g., map_handicap in Bo1)
        result = checker_fn(sim, odds, thresholds[bet_type])
        if result:
            result["bet_type"] = bet_type
            bets.append(result)
    return bets

def check_moneyline_edge(sim: dict, odds: OddsData, threshold: float) -> dict | None:
    """Compare sim prob vs implied prob for match winner."""
    team_a_edge = sim["team_a_win_prob"] - odds.implied_probs["ml_team_a"]
    team_b_edge = sim["team_b_win_prob"] - odds.implied_probs["ml_team_b"]

    if team_a_edge >= threshold and team_a_edge >= team_b_edge:
        return _build_bet("team_a", odds.moneyline["team_a"], sim["team_a_win_prob"],
                         odds.implied_probs["ml_team_a"], team_a_edge, sim.get("confidence"))
    elif team_b_edge >= threshold:
        return _build_bet("team_b", odds.moneyline["team_b"], sim["team_b_win_prob"],
                         odds.implied_probs["ml_team_b"], team_b_edge, sim.get("confidence"))
    return None

def check_map_handicap_edge(sim: dict, odds: OddsData, threshold: float) -> dict | None:
    """Favorite cover prob vs implied from handicap odds."""
    fav_implied = american_to_implied_prob(odds.map_handicap.get("team_a_odds", -110))
    dog_implied = american_to_implied_prob(odds.map_handicap.get("team_b_odds", -110))
    total = fav_implied + dog_implied
    fav_implied /= total

    fav_edge = sim["favorite_cover_prob"] - fav_implied
    dog_edge = (1 - sim["favorite_cover_prob"]) - (1 - fav_implied)

    if fav_edge >= threshold:
        return _build_bet("favorite", odds.map_handicap["team_a_odds"],
                         sim["favorite_cover_prob"], fav_implied, fav_edge, sim.get("confidence"))
    elif dog_edge >= threshold:
        return _build_bet("underdog", odds.map_handicap["team_b_odds"],
                         1 - sim["favorite_cover_prob"], 1 - fav_implied, dog_edge, sim.get("confidence"))
    return None

def check_total_maps_edge(sim: dict, odds: OddsData, threshold: float) -> dict | None:
    """Over/under on total maps played."""
    over_implied = american_to_implied_prob(odds.total_maps.get("over_odds", -110))
    under_implied = american_to_implied_prob(odds.total_maps.get("under_odds", -110))
    total = over_implied + under_implied
    over_implied /= total
    under_implied /= total

    over_edge = sim["over_prob"] - over_implied
    under_edge = sim["under_prob"] - under_implied

    if over_edge >= threshold and over_edge >= under_edge:
        return _build_bet("over", odds.total_maps["over_odds"],
                         sim["over_prob"], over_implied, over_edge, sim.get("confidence"))
    elif under_edge >= threshold:
        return _build_bet("under", odds.total_maps["under_odds"],
                         sim["under_prob"], under_implied, under_edge, sim.get("confidence"))
    return None
```

### Kelly Sizing

Unchanged: quarter-Kelly (0.25 fraction). Same formula:
```
kelly_pct = 0.25 * (b * p - q) / b
```

---

## 12. Results Grading Adaptations

### CS2/LoL Match Grading

```python
def grade_moneyline(bet_side: str, result: dict) -> str:
    """Grade moneyline bet. Straightforward winner comparison."""
    return "W" if bet_side == result["winner"] else "L"

def grade_map_handicap(bet_side: str, handicap: float, result: dict) -> str:
    """Grade map handicap bet.

    E.g., Team A -1.5 maps, actual score 2-1 → adjusted = 0.5-1 → L (didn't cover)
    E.g., Team A -1.5 maps, actual score 2-0 → adjusted = 0.5-0 → W (covered)
    """
    score_parts = result["score"].split("-")
    team_a_maps = int(score_parts[0])
    team_b_maps = int(score_parts[1])

    if bet_side == "team_a":
        adjusted = team_a_maps + handicap  # handicap is negative for favorite
        return "W" if adjusted > team_b_maps else "L"
    else:
        adjusted = team_b_maps + handicap
        return "W" if adjusted > team_a_maps else "L"

def grade_total_maps(bet_side: str, line: float, result: dict) -> str:
    """Grade total maps bet.

    Bo3: 2 maps (sweep) or 3 maps (decider)
    Bo5: 3, 4, or 5 maps
    """
    maps_played = result["maps_played"]
    if bet_side == "over":
        return "W" if maps_played > line else ("P" if maps_played == line else "L")
    else:
        return "W" if maps_played < line else ("P" if maps_played == line else "L")
```

---

## 13. Config Adaptations

### New `config.py`

```python
import os
from dotenv import load_dotenv

load_dotenv()

# API keys
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDSPAPI_API_KEY = os.getenv("ODDSPAPI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# API base URLs
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDSPAPI_BASE = "https://api.oddspapi.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
SCREEN_EDGE_THRESHOLD = 0.03
GAME_TIMEOUT = 180  # 3 min per match (esports matches are simpler than MLB)

# Ensemble configuration (unchanged — sport-agnostic)
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing
KELLY_FRACTION = 0.25

# Supported games
SUPPORTED_GAMES = ["cs2", "lol"]

# Tournament tier filter (only bet on Tier 1 and 2)
MAX_TIER = 2

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
```

---

## 14. Daily Runner Flow

```python
# agents/daily_runner.py (adapted)
async def run_daily(date: str = None, games: list[str] = None):
    """Daily esports prediction pipeline."""
    games = games or SUPPORTED_GAMES

    # 1. Health check
    check_health()

    # 2. Grade yesterday's results
    grade_pending_bets(date=yesterday)

    # 3. For each game title:
    for game_key in games:
        game = get_game(game_key)

        # 3a. Fetch today's matches (Tier 1-2 only)
        matches = game.scrapers.fetch_upcoming_matches()
        matches = [m for m in matches if m["tier"] <= MAX_TIER]

        # 3b. Fetch odds for all matches
        odds_list = get_esports_odds(game_key)

        # 3c. For each match with odds:
        for match in matched_games:
            # Fetch team profiles, H2H, patch context, news
            match_data = assemble_match_data(game, match, odds)

            # Build briefing
            briefing = game.briefing.build_briefing(match_data)

            # Screen pass (Plan B) — game-aware
            screen = run_plan_b(briefing, game_config=game.config)
            if max_edge(screen) < SCREEN_EDGE_THRESHOLD:
                continue  # Skip, no edge detected

            # Full ensemble — game-aware
            result = run_mirofish(briefing, odds=match_data["odds"].to_dict(),
                                  game_config=game.config)
            if result is None:
                continue  # Challenger killed all bets

            # Edge detection — format-aware
            bets = analyze_all_edges(result, match_data["odds"],
                                     format=match["format"], game_config=game.config)

            # Log bets
            for bet in bets:
                bet["game_title"] = game_key
                bet["tournament"] = match["tournament"]
                log_bet(bet)

    # 4. Output bet card
    display_bet_card(date)
```

---

## 15. Health Check Adaptations

```python
def check_health():
    """Validate all API connections for esports pipeline."""
    checks = {
        "OpenRouter": _check_openrouter(),
        "OddsPapi": _check_oddspapi(),
        "The Odds API": _check_odds_api(),
        "HLTV": _check_hltv(),
        "Oracle's Elixir": _check_oracle_elixir(),
    }
    for name, ok in checks.items():
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {name}")

    if not all(checks.values()):
        raise RuntimeError("Health check failed")
```

---

## 16. OddsPapi Rate Limiting & Request Budgeting

The free tier allows 250 requests/month. We must track usage.

```python
# scrapers/odds.py
import json
from datetime import datetime

REQUEST_BUDGET_FILE = os.path.join(DATA_DIR, "oddspapi_usage.json")

def _load_usage() -> dict:
    """Load monthly request counter."""
    if os.path.exists(REQUEST_BUDGET_FILE):
        with open(REQUEST_BUDGET_FILE) as f:
            data = json.load(f)
        if data.get("month") == datetime.now().strftime("%Y-%m"):
            return data
    return {"month": datetime.now().strftime("%Y-%m"), "requests": 0}

def _record_request():
    """Increment request counter."""
    usage = _load_usage()
    usage["requests"] += 1
    with open(REQUEST_BUDGET_FILE, "w") as f:
        json.dump(usage, f)
    remaining = 250 - usage["requests"]
    if remaining < 50:
        print(f"[odds] WARNING: OddsPapi budget low — {remaining} requests remaining this month")

def _fetch_oddspapi(game_key: str) -> list[OddsData]:
    usage = _load_usage()
    if usage["requests"] >= 240:  # Reserve 10 for health checks
        print("[odds] OddsPapi monthly budget exhausted, using fallback only")
        return []
    _record_request()
    # ... actual API call
```

### Caching Strategy

Cache odds per match for 30 minutes (lines don't move that fast in esports):
```python
ODDS_CACHE_TTL = 1800  # 30 minutes
_odds_cache = {}  # {cache_key: (timestamp, data)}

def _get_cached_odds(game_key: str) -> list[OddsData] | None:
    key = f"{game_key}_{datetime.now().strftime('%Y-%m-%d')}"
    if key in _odds_cache:
        ts, data = _odds_cache[key]
        if (datetime.now() - ts).seconds < ODDS_CACHE_TTL:
            return data
    return None
```

---

## 17. CS2 Map Pool Configuration

The active duty map pool changes when Valve rotates maps. This MUST be a config constant, not hardcoded in scrapers.

```python
# games/cs2/config.py
# Last updated: 2026-03-20 — review after each Valve major update
ACTIVE_DUTY_MAPS = [
    "mirage", "inferno", "nuke", "ancient",
    "anubis", "dust2", "vertigo",
]
```

The CS2 scrapers reference `ACTIVE_DUTY_MAPS` instead of hardcoding map names. When the pool changes, update this single constant.

---

## 18. Async / Sync Interface Contract

CS2 scrapers use `async def` (HLTV library is async). LoL scrapers use regular `def` (CSV loading is sync). The schedule aggregator and daily runner must handle both.

**Solution**: Each game module exposes a sync wrapper:

```python
# games/cs2/__init__.py
import asyncio
from games.cs2 import scrapers as _async_scrapers

class ScrapersSync:
    """Sync wrapper around async HLTV scrapers."""
    def fetch_upcoming_matches(self):
        return asyncio.run(_async_scrapers.fetch_upcoming_matches())
    def fetch_team_profile(self, team_name):
        return asyncio.run(_async_scrapers.fetch_team_profile(team_name))
    def fetch_head_to_head(self, team_a, team_b):
        return asyncio.run(_async_scrapers.fetch_head_to_head(team_a, team_b))
    def fetch_match_result(self, team_a, team_b, date):
        return asyncio.run(_async_scrapers.fetch_match_result(team_a, team_b, date))

scrapers = ScrapersSync()
```

The daily runner and schedule aggregator always call `game.scrapers.method()` synchronously. Async details are encapsulated within the game module.

---

## 19. Testing Strategy

### What to Keep
- All `test_ensemble_*.py` files — sport-agnostic, just need fixture updates
- `test_tracker.py` — CSV logging is sport-agnostic
- `test_calibrate.py` — math is sport-agnostic

### What to Keep
- All `test_ensemble_*.py` files — sport-agnostic, just need fixture updates
- `test_tracker.py` — CSV logging is sport-agnostic
- `test_calibrate.py` — math is sport-agnostic

### What to Rewrite
- `test_odds.py` → test OddsPapi integration + The Odds API fallback
- `test_edge.py` → test esports bet types + format-aware thresholds
- `test_briefing.py` → test CS2 and LoL briefing builders
- `test_main.py` → test esports daily flow
- `test_results_grader.py` → test esports grading logic
- `test_health_check.py` → test new API health checks

### What to Add
- `test_cs2_scrapers.py` — mock HLTV responses, test team profile parsing
- `test_lol_scrapers.py` — mock Oracle's Elixir CSV, test team profile parsing
- `test_schedule.py` — test match schedule aggregation + tier filtering
- `test_meta.py` — test patch notes fetching + LLM summarization
- `test_game_registry.py` — validate each game module exposes required interface (scrapers, briefing, config, prompt)

### Test Fixtures Update

Note: `MOCK_ESPORTS_ODDS` includes `pinnacle_odds` for CLV testing.

```python
# tests/ensemble_fixtures.py
MOCK_ESPORTS_PREDICTION = {
    "analyst_assessments": [
        {"role": "fragging", "pick": "Team A", "reasoning": "Better AWP player"},
        {"role": "tactical", "pick": "Team A", "reasoning": "Stronger T-side"},
        {"role": "map_pool", "pick": "Team B", "reasoning": "Deeper map pool"},
        {"role": "form", "pick": "Team A", "reasoning": "3-match win streak"},
        {"role": "market", "pick": "Team A", "reasoning": "Value on moneyline"},
        {"role": "contrarian", "pick": "Team B", "reasoning": "Stand-in risk"},
    ],
    "predictions": {
        "moneyline": {
            "team_a_win_prob": 0.62,
            "team_b_win_prob": 0.38,
            "value_side": "team_a",
            "edge": 0.07,
            "confidence": "medium",
        },
        "map_handicap": {
            "favorite_cover_prob": 0.45,
            "value_side": "none",
            "edge": 0.02,
            "confidence": "low",
        },
        "total_maps": {
            "projected_maps": 2.6,
            "over_prob": 0.58,
            "under_prob": 0.42,
            "value_side": "over",
            "edge": 0.06,
            "confidence": "medium",
        },
        "predicted_result": {"winner": "Team A", "score": "2-1"},
        "key_factors": ["AWP advantage", "Map pool depth", "LAN experience"],
    },
}

MOCK_ESPORTS_ODDS = OddsData(
    team_a="Natus Vincere",
    team_b="FaZe Clan",
    commence_time="2026-03-20T15:00:00Z",
    game_title="cs2",
    tournament="IEM Katowice 2026",
    format="bo3",
    moneyline={"team_a": -175, "team_b": 145},
    map_handicap={
        "team_a_line": -1.5, "team_a_odds": 150,
        "team_b_line": 1.5, "team_b_odds": -180,
    },
    total_maps={"line": 2.5, "over_odds": -130, "under_odds": 110},
    implied_probs={"ml_team_a": 0.636, "ml_team_b": 0.364},
    bookmaker_count=12,
    pinnacle_odds={"team_a": -180, "team_b": 150},
)
```

---

## 20. Dependencies

### Add to `requirements.txt`

```
hltv-async-api>=0.8.0       # CS2 data from HLTV
aiohttp>=3.9.0               # Async HTTP for HLTV scraper
```

### Remove from `requirements.txt`

```
pybaseball>=2.3.0            # MLB-specific, no longer needed
```

### Keep

```
requests>=2.31.0
openai>=1.12.0
python-dotenv>=1.0.0
click>=8.1.0
pandas>=2.1.0
pytest>=7.4.0
```

---

## 21. Environment Variables

### New `.env` entries needed

```
ODDSPAPI_API_KEY=xxx         # OddsPapi API key (free tier)
```

### Removed

```
WEATHER_API_KEY=xxx          # No longer needed (no ballpark weather)
```

### Kept

```
ODDS_API_KEY=xxx             # Fallback for LoL odds
OPENROUTER_API_KEY=xxx       # Ensemble LLM calls
LOG_LEVEL=INFO
```

---

## 22. Implementation Priority

### Phase 1: Core Infrastructure (CS2)
1. Delete all MLB files and config
2. Create `games/` directory structure with `__init__.py` game registry
3. Rewrite `scrapers/odds.py` for OddsPapi (with rate limiting + caching)
4. Implement `games/cs2/config.py` (BET_SLOTS, PROB_FIELDS, EDGE_THRESHOLDS, ACTIVE_DUTY_MAPS)
5. Implement `games/cs2/scrapers.py` (HLTV integration + sync wrappers)
6. Implement `games/cs2/briefing.py` and `games/cs2/prompt.py`
7. Adapt `simulate.py` for game-aware screen pass (CRITICAL — must be Phase 1)
8. Adapt `edge.py` for esports bet types + format-aware thresholds (new signatures)
9. Adapt `config.py` (remove MLB, add esports config)
10. Adapt `ensemble/orchestrator.py` to read BET_SLOTS, PROB_FIELDS, etc. from game_config
11. Adapt `ensemble/consensus.py` vote maps to be dynamic from game_config
12. Add `OddsData.to_dict()` serialization method
13. Adapt `agents/results_grader.py` for esports grading
14. Update test fixtures and write CS2 + game registry tests

### Phase 2: LoL Support
15. Implement `games/lol/config.py`
16. Implement `games/lol/scrapers.py` (Oracle's Elixir CSV loader)
17. Implement `games/lol/briefing.py` and `games/lol/prompt.py`
18. Write LoL tests

### Phase 3: Cross-Cutting Features
19. Implement `scrapers/meta.py` (patch notes + LLM summarizer)
20. Implement `scrapers/news.py` (roster changes, context)
21. Implement `scrapers/schedule.py` (unified schedule aggregator)
22. Adapt `agents/daily_runner.py` for multi-game loop
23. Adapt `agents/health_check.py` for new APIs
24. Adapt `agents/bet_card.py` for esports format
25. Update `main.py` CLI for game selection

### Phase 4: Polish
26. Reset `data/` directory (fresh bets.csv, model_weights.json)
27. End-to-end integration test
28. Update documentation
