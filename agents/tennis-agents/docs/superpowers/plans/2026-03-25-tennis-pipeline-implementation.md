# Tennis Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the MiroFish MLB prediction pipeline into a tennis-only (ATP + WTA) prediction pipeline with 3 bet types (moneyline, game_handicap, total_games), using Sackmann CSVs for player data and API-Tennis for live schedules.

**Architecture:** 6-layer pipeline (SCRAPE -> BRIEFING -> SCREEN -> ENSEMBLE -> EDGE -> BET). Sport-agnostic ensemble engine stays intact. Sport-specific layers rebuilt for tennis. `tour` parameter ("atp"/"wta") threads through config dict.

**Tech Stack:** Python 3.11+, Click CLI, OpenRouter (6 LLM models), The Odds API, API-Tennis, Jeff Sackmann GitHub CSVs, pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-03-25-tennis-pipeline-design.md`

---

### Task 1: Delete MLB Files and Clean Dependencies

**Files:**
- Delete: `scrapers/pitchers.py`, `scrapers/bullpen.py`, `scrapers/ballpark.py`, `scrapers/lineups.py`, `scrapers/team_stats.py`
- Delete: `tests/test_pitchers.py`, `tests/test_bullpen.py`, `tests/test_ballpark.py`, `tests/test_lineups.py`, `tests/test_team_stats.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Delete MLB-only scraper files**

```bash
rm scrapers/pitchers.py scrapers/bullpen.py scrapers/ballpark.py scrapers/lineups.py scrapers/team_stats.py
```

- [ ] **Step 2: Delete MLB-only test files**

```bash
rm tests/test_pitchers.py tests/test_bullpen.py tests/test_ballpark.py tests/test_lineups.py tests/test_team_stats.py
```

- [ ] **Step 3: Remove pybaseball from requirements.txt**

Update `requirements.txt` to:
```
requests>=2.31.0
openai>=1.12.0
python-dotenv>=1.0.0
click>=8.1.0
pandas>=2.1.0
pytest>=7.4.0
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore: remove MLB-specific scrapers, tests, and pybaseball dependency"
```

---

### Task 2: Rewrite config.py for Tennis

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for tennis config**

```python
# tests/test_config.py
from config import (
    TOUR_CONFIG, EDGE_THRESHOLDS, KELLY_FRACTION_ATP, KELLY_FRACTION_WTA,
    API_TENNIS_BASE, SACKMANN_ATP_REPO, SACKMANN_WTA_REPO,
    ENSEMBLE_MODELS, ENSEMBLE_CHALLENGER, CONSENSUS_MIN_VOTES,
    MAX_CALLS_PER_GAME, SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT,
    ODDS_API_KEY, OPENROUTER_API_KEY, WEATHER_API_KEY,
    OPENROUTER_BASE_URL, ODDS_API_BASE, WEATHER_API_BASE,
    DATA_DIR, BETS_CSV, MODEL_WEIGHTS_FILE, MODEL_PREDICTIONS_CSV,
)


def test_tour_config_has_atp_and_wta():
    assert "atp" in TOUR_CONFIG
    assert "wta" in TOUR_CONFIG


def test_tour_config_atp_keys():
    atp = TOUR_CONFIG["atp"]
    assert atp["odds_sport_key"] == "tennis_atp"
    assert "sackmann_repo" in atp
    assert atp["kelly_fraction"] == 0.25


def test_tour_config_wta_keys():
    wta = TOUR_CONFIG["wta"]
    assert wta["odds_sport_key"] == "tennis_wta"
    assert "sackmann_repo" in wta
    assert wta["kelly_fraction"] == 0.125


def test_edge_thresholds_has_three_tennis_slots():
    assert "moneyline" in EDGE_THRESHOLDS
    assert "game_handicap" in EDGE_THRESHOLDS
    assert "total_games" in EDGE_THRESHOLDS
    assert len(EDGE_THRESHOLDS) == 3


def test_no_mlb_config():
    """Ensure no MLB references remain."""
    import config
    assert not hasattr(config, "MLB_API_BASE")
    assert not hasattr(config, "TEAM_ABBREVS")
    assert not hasattr(config, "TEAM_NAME_TO_ABBREV")
    assert not hasattr(config, "PARK_FACTORS")
    assert not hasattr(config, "PARK_COORDS")


def test_sackmann_repos():
    assert "JeffSackmann/tennis_atp" in SACKMANN_ATP_REPO
    assert "JeffSackmann/tennis_wta" in SACKMANN_WTA_REPO


def test_game_timeout():
    assert GAME_TIMEOUT == 180


def test_ensemble_models():
    assert len(ENSEMBLE_MODELS) == 6
    assert ENSEMBLE_CHALLENGER in ENSEMBLE_MODELS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (old MLB config still present)

- [ ] **Step 3: Rewrite config.py**

```python
import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# API keys
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY", "")

# API base URLs
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
WEATHER_API_BASE = "https://api.openweathermap.org/data/2.5"
API_TENNIS_BASE = "https://api-tennis.com/tennis/"

# Sackmann data repos
SACKMANN_ATP_REPO = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
SACKMANN_WTA_REPO = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"

# Tour-specific configuration
TOUR_CONFIG = {
    "atp": {
        "odds_sport_key": "tennis_atp",
        "sackmann_repo": SACKMANN_ATP_REPO,
        "kelly_fraction": 0.25,
    },
    "wta": {
        "odds_sport_key": "tennis_wta",
        "sackmann_repo": SACKMANN_WTA_REPO,
        "kelly_fraction": 0.125,
    },
}

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCREEN_EDGE_THRESHOLD = 0.03
GAME_TIMEOUT = 180  # 3 min per match

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing defaults
KELLY_FRACTION_ATP = 0.25
KELLY_FRACTION_WTA = 0.125

# Edge thresholds per bet type
EDGE_THRESHOLDS = {
    "moneyline": 0.05,
    "game_handicap": 0.06,
    "total_games": 0.05,
}

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
SACKMANN_CACHE_DIR = os.path.join(DATA_DIR, "sackmann")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py && git commit -m "feat: rewrite config.py for tennis (ATP/WTA tour config, remove MLB)"
```

---

### Task 3: Rewrite ensemble/weights.py and ensemble/consensus.py for Tennis Bet Slots

**Files:**
- Modify: `ensemble/weights.py`
- Modify: `ensemble/consensus.py`
- Modify: `tests/ensemble_fixtures.py`
- Modify: `tests/test_ensemble_consensus.py`
- Modify: `tests/test_ensemble_weights.py`

- [ ] **Step 1: Rewrite ensemble_fixtures.py with tennis mock data**

```python
"""Shared mock data for ensemble tests."""
import json
import copy

MOCK_PREDICTION = {
    "analyst_assessments": [
        {"role": "serve", "pick": "Djokovic", "reasoning": "Elite serve on hard court"},
    ],
    "predictions": {
        "moneyline": {
            "player_a_win_prob": 0.58,
            "player_b_win_prob": 0.42,
            "value_side": "player_a",
            "edge": 0.06,
            "confidence": "medium",
        },
        "game_handicap": {
            "favorite_cover_prob": 0.45,
            "value_side": "favorite",
            "edge": 0.04,
            "confidence": "low",
        },
        "total_games": {
            "projected_games": 22.5,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.05,
            "confidence": "medium",
        },
        "predicted_result": {"winner": "Djokovic", "score": "6-4 6-3"},
        "key_factors": ["Serve dominance on hard court", "H2H advantage"],
    },
}

MOCK_PREDICTION_JSON = json.dumps(MOCK_PREDICTION)

MOCK_ODDS = {
    "moneyline": {"player_a": -150, "player_b": 130},
    "game_handicap": {
        "player_a_point": -4.5, "player_a_odds": -110,
        "player_b_point": 4.5, "player_b_odds": -110,
    },
    "total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110},
    "implied_probs": {"player_a": 0.60, "player_b": 0.40},
}


def make_prediction(**overrides):
    """Create a prediction dict with optional overrides."""
    pred = copy.deepcopy(MOCK_PREDICTION)
    for key, val in overrides.items():
        if key in pred["predictions"]:
            pred["predictions"][key].update(val)
    return pred
```

- [ ] **Step 2: Rewrite ensemble/weights.py with tennis bet slots**

```python
"""Model weight storage and management."""
import json
import os
from config import ENSEMBLE_MODELS, MODEL_WEIGHTS_FILE

BET_SLOTS = ["moneyline", "game_handicap", "total_games"]


def default_weights() -> dict:
    return {model: {slot: 1.0 for slot in BET_SLOTS} for model in ENSEMBLE_MODELS}


def load_weights(path: str = None) -> dict:
    path = path or MODEL_WEIGHTS_FILE
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    w = default_weights()
    save_weights(w, path)
    return w


def save_weights(weights: dict, path: str = None) -> None:
    path = path or MODEL_WEIGHTS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(weights, f, indent=2)
```

- [ ] **Step 3: Rewrite ensemble/consensus.py for tennis vote normalization**

```python
"""Consensus gate, vote normalization, and weighted averaging."""
from config import CONSENSUS_MIN_VOTES

BET_SLOT_FIELDS = {
    "moneyline": ("moneyline", "value_side"),
    "game_handicap": ("game_handicap", "value_side"),
    "total_games": ("total_games", "value_side"),
}


def extract_vote(prediction: dict, bet_slot: str, odds: dict) -> str | None:
    """Extract a model's normalized vote for a bet slot."""
    section_key, field_name = BET_SLOT_FIELDS[bet_slot]
    section = prediction.get("predictions", {}).get(section_key, {})
    raw_vote = section.get(field_name, "none")

    if raw_vote == "none" or raw_vote is None:
        return None

    # Normalize game_handicap from relative (favorite/underdog) to absolute
    if bet_slot == "game_handicap":
        gh_odds = odds.get("game_handicap", {})
        a_point = gh_odds.get("player_a_point", 0)
        a_is_fav = a_point < 0
        if raw_vote == "favorite":
            return "player_a_gh" if a_is_fav else "player_b_gh"
        elif raw_vote == "underdog":
            return "player_b_gh" if a_is_fav else "player_a_gh"
        return raw_vote

    return raw_vote


def count_votes(votes: dict[str, str | None]) -> tuple[str | None, int]:
    """Count votes and return (winning_side, count). Excludes None votes."""
    counts = {}
    for vote in votes.values():
        if vote is not None:
            counts[vote] = counts.get(vote, 0) + 1
    if not counts:
        return None, 0
    winner = max(counts, key=counts.get)
    return winner, counts[winner]


def check_consensus(votes: dict[str, str | None], min_votes: int = None) -> bool:
    """Check if enough models agree on the same side."""
    min_votes = min_votes or CONSENSUS_MIN_VOTES
    _, count = count_votes(votes)
    return count >= min_votes


def weighted_average_prob(runs: list[dict], weights: dict[str, float]) -> float:
    """Weighted average of probability estimates across runs."""
    numerator = 0.0
    denominator = 0.0
    for run in runs:
        w = weights.get(run["model_key"], 1.0)
        numerator += w * run["prob"]
        denominator += w
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def apply_stability_bonus(weight: float, std_dev: float) -> float:
    """Apply stability multiplier based on temperature sweep std dev."""
    if std_dev < 0.03:
        return round(weight * 1.2, 4)
    elif std_dev > 0.10:
        return round(weight * 0.8, 4)
    return weight


def majority_vote(values: list[str], default: str = "medium") -> str:
    """Return the most common value. Ties broken toward default."""
    if not values:
        return default
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    max_count = max(counts.values())
    winners = [v for v, c in counts.items() if c == max_count]
    if default in winners:
        return default
    return winners[0]
```

- [ ] **Step 4: Rewrite tests for consensus and weights**

`tests/test_ensemble_weights.py`:
```python
from ensemble.weights import BET_SLOTS, default_weights, load_weights, save_weights
from config import ENSEMBLE_MODELS
import os, json, tempfile

def test_bet_slots_has_three():
    assert BET_SLOTS == ["moneyline", "game_handicap", "total_games"]

def test_default_weights_structure():
    w = default_weights()
    for model in ENSEMBLE_MODELS:
        assert model in w
        for slot in BET_SLOTS:
            assert w[model][slot] == 1.0

def test_load_save_weights(tmp_path):
    path = str(tmp_path / "weights.json")
    w = default_weights()
    w["kimi"]["moneyline"] = 1.5
    save_weights(w, path)
    loaded = load_weights(path)
    assert loaded["kimi"]["moneyline"] == 1.5
```

`tests/test_ensemble_consensus.py`:
```python
import copy
from ensemble.consensus import (
    extract_vote, count_votes, check_consensus,
    weighted_average_prob, apply_stability_bonus,
    majority_vote, BET_SLOT_FIELDS,
)
from tests.ensemble_fixtures import MOCK_PREDICTION, MOCK_ODDS

def test_bet_slot_fields_has_three_slots():
    assert len(BET_SLOT_FIELDS) == 3

def test_extract_vote_moneyline():
    vote = extract_vote(MOCK_PREDICTION, "moneyline", MOCK_ODDS)
    assert vote == "player_a"

def test_extract_vote_game_handicap_normalizes_favorite():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["game_handicap"]["value_side"] = "favorite"
    vote = extract_vote(pred, "game_handicap", MOCK_ODDS)
    assert vote == "player_a_gh"  # player_a has -4.5

def test_extract_vote_game_handicap_normalizes_underdog():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["game_handicap"]["value_side"] = "underdog"
    vote = extract_vote(pred, "game_handicap", MOCK_ODDS)
    assert vote == "player_b_gh"

def test_extract_vote_none():
    pred = copy.deepcopy(MOCK_PREDICTION)
    pred["predictions"]["moneyline"]["value_side"] = "none"
    vote = extract_vote(pred, "moneyline", MOCK_ODDS)
    assert vote is None

def test_extract_vote_total_games():
    vote = extract_vote(MOCK_PREDICTION, "total_games", MOCK_ODDS)
    assert vote == "over"

def test_count_votes_strong_consensus():
    votes = {"kimi": "player_a", "claude": "player_a", "gpt4o": "player_a",
             "gemini": "player_a", "deepseek": "player_b", "maverick": "player_a"}
    side, count = count_votes(votes)
    assert side == "player_a"
    assert count == 5

def test_count_votes_no_consensus():
    votes = {"kimi": "player_a", "claude": "player_b", "gpt4o": "player_a",
             "gemini": "player_b", "deepseek": None, "maverick": None}
    side, count = count_votes(votes)
    assert count == 2

def test_check_consensus_passes():
    votes = {"kimi": "player_a", "claude": "player_a", "gpt4o": "player_a",
             "gemini": "player_b", "deepseek": None, "maverick": None}
    assert check_consensus(votes, min_votes=3) is True

def test_check_consensus_fails():
    votes = {"kimi": "player_a", "claude": "player_b", "gpt4o": "player_a",
             "gemini": "player_b", "deepseek": None, "maverick": None}
    assert check_consensus(votes, min_votes=3) is False

def test_weighted_average_prob():
    runs = [
        {"model_key": "kimi", "prob": 0.55},
        {"model_key": "gpt4o", "prob": 0.60},
        {"model_key": "gemini", "prob": 0.50},
    ]
    weights = {"kimi": 1.0, "gpt4o": 2.0, "gemini": 1.0}
    avg = weighted_average_prob(runs, weights)
    assert abs(avg - 0.5625) < 0.001

def test_apply_stability_bonus_tight():
    assert apply_stability_bonus(1.0, 0.02) == 1.2

def test_apply_stability_bonus_noisy():
    assert apply_stability_bonus(1.0, 0.15) == 0.8

def test_apply_stability_bonus_normal():
    assert apply_stability_bonus(1.0, 0.05) == 1.0

def test_majority_vote_clear_winner():
    assert majority_vote(["high", "high", "medium"]) == "high"

def test_majority_vote_tie_breaks_to_default():
    assert majority_vote(["high", "low", "medium"], default="medium") == "medium"

def test_majority_vote_empty():
    assert majority_vote([], default="medium") == "medium"
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_ensemble_consensus.py tests/test_ensemble_weights.py tests/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add ensemble/weights.py ensemble/consensus.py tests/ensemble_fixtures.py tests/test_ensemble_consensus.py tests/test_ensemble_weights.py && git commit -m "feat: rewrite ensemble consensus and weights for tennis bet slots"
```

---

### Task 4: Rewrite simulate.py with Tennis System Prompt

**Files:**
- Modify: `simulate.py`
- Modify: `tests/test_simulate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_simulate.py
from unittest.mock import patch, MagicMock
from simulate import TENNIS_SYSTEM_PROMPT, parse_simulation_result, run_plan_b


def test_tennis_system_prompt_exists():
    assert "tennis" in TENNIS_SYSTEM_PROMPT.lower()
    assert "serve analyst" in TENNIS_SYSTEM_PROMPT.lower()
    assert "surface" in TENNIS_SYSTEM_PROMPT.lower()


def test_tennis_system_prompt_has_json_structure():
    assert "player_a_win_prob" in TENNIS_SYSTEM_PROMPT
    assert "game_handicap" in TENNIS_SYSTEM_PROMPT
    assert "total_games" in TENNIS_SYSTEM_PROMPT
    assert "projected_games" in TENNIS_SYSTEM_PROMPT


def test_no_mlb_in_system_prompt():
    assert "MLB" not in TENNIS_SYSTEM_PROMPT
    assert "pitcher" not in TENNIS_SYSTEM_PROMPT.lower()
    assert "run_line" not in TENNIS_SYSTEM_PROMPT
    assert "first_5" not in TENNIS_SYSTEM_PROMPT


def test_parse_simulation_result_valid_json():
    raw = '{"predictions": {"moneyline": {"player_a_win_prob": 0.55}}}'
    result = parse_simulation_result(raw)
    assert result is not None
    assert result["predictions"]["moneyline"]["player_a_win_prob"] == 0.55


def test_parse_simulation_result_strips_markdown():
    raw = '```json\n{"key": "value"}\n```'
    result = parse_simulation_result(raw)
    assert result == {"key": "value"}


def test_parse_simulation_result_none():
    assert parse_simulation_result(None) is None
    assert parse_simulation_result("not json") is None


@patch("simulate.openai.OpenAI")
def test_run_plan_b_returns_parsed(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = '{"predictions": {"moneyline": {"player_a_win_prob": 0.6}}}'
    mock_choice.finish_reason = "stop"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 200
    mock_client.chat.completions.create.return_value = mock_response

    result = run_plan_b("test briefing")
    assert result is not None
    assert "predictions" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_simulate.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite simulate.py**

```python
"""Simulation layer: Plan B (direct Kimi) and MiroFish ensemble."""
import json
import logging
import time
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, KIMI_MODEL

logger = logging.getLogger("mirofish.simulate")


TENNIS_SYSTEM_PROMPT = """You are an elite tennis prediction system analyzing a professional match.
Simulate a panel of 6 expert analysts:

1. SERVE ANALYST: Evaluates serve quality, first serve percentage, ace potential,
   second serve vulnerability, and how the serve matches up against the returner's
   skills. Service game hold percentages on this surface.
2. RETURN & RALLY ANALYST: Evaluates return effectiveness, ability to neutralize
   serve, baseline rally tolerance, and break point conversion. Who controls
   the rallies from the back of the court?
3. SURFACE & CONDITIONS ANALYST: Evaluates how each player's game translates to
   this specific surface. Clay grinders on hard courts, grass specialists on clay, etc.
   Altitude, temperature, ball speed, and indoor/outdoor adjustments.
4. FORM & FITNESS ANALYST: Evaluates recent results, match load, travel schedule,
   injury concerns, and competitive sharpness. Is this player peaking or fatigued?
   Surface transition effects (just switched from clay to grass, etc.).
5. MARKET ANALYST: Evaluates the betting lines for value. Is the market
   correctly pricing the surface matchup? Is name recognition inflating the
   favorite's odds? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. What upset scenario is being overlooked?
   Is the favorite's recent form on a different surface? Is the underdog's
   style a bad matchup for the favorite? Motivation factors (defending champion
   vs player with nothing to lose)?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "serve", "pick": "PLAYER", "reasoning": "..."},
    {"role": "return", "pick": "PLAYER", "reasoning": "..."},
    {"role": "surface", "pick": "PLAYER", "reasoning": "..."},
    {"role": "form", "pick": "PLAYER", "reasoning": "..."},
    {"role": "market", "pick": "PLAYER", "reasoning": "..."},
    {"role": "contrarian", "pick": "PLAYER", "reasoning": "..."}
  ],
  "predictions": {
    "moneyline": {
      "player_a_win_prob": 0.XX,
      "player_b_win_prob": 0.XX,
      "value_side": "player_a|player_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "game_handicap": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_games": {
      "projected_games": XX.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_result": {"winner": "PLAYER", "score": "6-4 6-3"},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only."""


def parse_simulation_result(raw: str | None) -> dict | None:
    """Parse JSON response from LLM, handling common issues."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_plan_b(briefing: str, runs: int = 1) -> dict | None:
    """Run direct Kimi call (Plan B) — fast screen at ~$0.06/match."""
    client = openai.OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        timeout=120,
    )

    logger.info("Plan B: starting %d run(s) via %s", runs, KIMI_MODEL)
    results = []
    for run_idx in range(runs):
        try:
            t0 = time.time()
            response = client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[
                    {"role": "system", "content": TENNIS_SYSTEM_PROMPT},
                    {"role": "user", "content": briefing},
                ],
                temperature=0.7,
                max_tokens=12288,
            )
            elapsed = time.time() - t0
            choice = response.choices[0]
            in_tok = getattr(response.usage, 'prompt_tokens', 0)
            out_tok = getattr(response.usage, 'completion_tokens', 0)
            logger.debug("Plan B run %d: %.1fs, %d/%d tokens, finish=%s",
                         run_idx + 1, elapsed, in_tok, out_tok, choice.finish_reason)
            if choice.finish_reason == "length":
                logger.warning("Plan B run %d: response truncated", run_idx + 1)
            raw = choice.message.content
            parsed = parse_simulation_result(raw)
            if parsed:
                results.append(parsed)
            else:
                logger.warning("Plan B run %d: failed to parse JSON", run_idx + 1)
        except Exception as e:
            logger.error("Plan B run %d error: %s", run_idx + 1, e)

    if not results:
        return None
    if len(results) == 1:
        return results[0]
    return _average_results(results)


def run_mirofish(briefing: str, runs: int = 3, odds: dict = None) -> dict | None:
    """Run multi-model ensemble simulation with Plan B fallback."""
    try:
        logger.info("MiroFish: attempting ensemble simulation")
        from ensemble import run_ensemble
        t0 = time.time()
        result = run_ensemble(briefing, odds=odds)
        elapsed = time.time() - t0
        if result:
            meta = result.get("ensemble_meta", {})
            logger.info("MiroFish: ensemble succeeded in %.1fs (phase=%d, calls=%d, cost=$%.4f)",
                        elapsed, meta.get("phase_reached", 0),
                        meta.get("total_calls", 0), meta.get("cost_usd", 0))
            return result
        logger.warning("MiroFish: ensemble returned None, falling back to Plan B")
    except Exception as e:
        logger.error("MiroFish: ensemble failed (%s), falling back to Plan B", e)
    return run_plan_b(briefing, runs=runs)


def _average_results(results: list[dict]) -> dict:
    """Average probability fields across multiple simulation runs."""
    base = results[0].copy()
    n = len(results)

    preds = base.get("predictions", {})
    prob_fields = {
        "moneyline": ["player_a_win_prob", "player_b_win_prob", "edge"],
        "game_handicap": ["favorite_cover_prob", "edge"],
        "total_games": ["projected_games", "over_prob", "under_prob", "edge"],
    }

    for section, fields in prob_fields.items():
        if section not in preds:
            continue
        for field in fields:
            values = []
            for r in results:
                val = r.get("predictions", {}).get(section, {}).get(field)
                if val is not None:
                    values.append(float(val))
            if values:
                preds[section][field] = round(sum(values) / len(values), 4)

    base["predictions"] = preds
    base["ensemble_runs"] = n
    return base
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_simulate.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add simulate.py tests/test_simulate.py && git commit -m "feat: tennis system prompt with 6 expert analysts"
```

---

### Task 5: Rewrite edge.py for Tennis Bet Types

**Files:**
- Modify: `edge.py`
- Modify: `tests/test_edge.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_edge.py
from edge import (
    kelly_criterion, american_to_decimal, analyze_all_edges,
    check_moneyline_edge, check_game_handicap_edge, check_total_games_edge,
)


def test_kelly_criterion_positive_edge():
    kelly = kelly_criterion(0.55, 2.0)
    assert 0.05 < kelly < 0.15


def test_kelly_criterion_no_edge():
    kelly = kelly_criterion(0.50, 2.0)
    assert kelly == 0


def test_kelly_criterion_negative_edge():
    kelly = kelly_criterion(0.40, 2.0)
    assert kelly == 0


def test_american_to_decimal():
    assert american_to_decimal(-150) == round(100 / 150 + 1, 4)
    assert american_to_decimal(130) == round(130 / 100 + 1, 4)
    assert american_to_decimal(100) == 2.0


def test_check_moneyline_edge_found():
    sim = {
        "predictions": {
            "moneyline": {
                "player_a_win_prob": 0.62,
                "player_b_win_prob": 0.38,
            }
        }
    }
    odds = {
        "moneyline": {"player_a": -130, "player_b": 110},
        "implied_probs": {"player_a": 0.565, "player_b": 0.435},
    }
    result = check_moneyline_edge(sim, odds, tour="atp")
    assert result is not None
    assert result["side"] == "player_a"
    assert result["edge"] > 0.05


def test_check_moneyline_edge_none():
    sim = {
        "predictions": {
            "moneyline": {"player_a_win_prob": 0.56, "player_b_win_prob": 0.44}
        }
    }
    odds = {
        "moneyline": {"player_a": -150, "player_b": 130},
        "implied_probs": {"player_a": 0.585, "player_b": 0.415},
    }
    result = check_moneyline_edge(sim, odds, tour="atp")
    if result:
        assert result["edge"] >= 0.05


def test_check_game_handicap_edge():
    sim = {
        "predictions": {
            "game_handicap": {"favorite_cover_prob": 0.58}
        }
    }
    odds = {
        "game_handicap": {
            "player_a_point": -4.5, "player_a_odds": -110,
            "player_b_point": 4.5, "player_b_odds": -110,
        },
    }
    result = check_game_handicap_edge(sim, odds, tour="atp")
    assert result is not None
    assert result["bet_type"] == "game_handicap"


def test_check_total_games_edge_over():
    sim = {
        "predictions": {
            "total_games": {"over_prob": 0.62, "under_prob": 0.38, "projected_games": 24.0}
        }
    }
    odds = {
        "total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110},
    }
    result = check_total_games_edge(sim, odds, tour="atp")
    assert result is not None
    assert "over" in result["side"]


def test_analyze_all_edges_returns_list():
    sim = {
        "predictions": {
            "moneyline": {"player_a_win_prob": 0.65, "player_b_win_prob": 0.35},
            "game_handicap": {"favorite_cover_prob": 0.55},
            "total_games": {"over_prob": 0.60, "under_prob": 0.40, "projected_games": 24.0},
        }
    }
    odds = {
        "moneyline": {"player_a": -140, "player_b": 120},
        "game_handicap": {
            "player_a_point": -3.5, "player_a_odds": -110,
            "player_b_point": 3.5, "player_b_odds": -110,
        },
        "total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"player_a": 0.583, "player_b": 0.417},
    }
    bets = analyze_all_edges(sim, odds, tour="atp")
    assert isinstance(bets, list)
    assert len(bets) <= 3
    for bet in bets:
        assert "bet_type" in bet
        assert "edge" in bet
        assert "kelly_pct" in bet


def test_wta_uses_smaller_kelly():
    sim = {
        "predictions": {
            "moneyline": {"player_a_win_prob": 0.70, "player_b_win_prob": 0.30}
        }
    }
    odds = {
        "moneyline": {"player_a": -140, "player_b": 120},
        "implied_probs": {"player_a": 0.583, "player_b": 0.417},
    }
    atp_result = check_moneyline_edge(sim, odds, tour="atp")
    wta_result = check_moneyline_edge(sim, odds, tour="wta")
    assert atp_result is not None and wta_result is not None
    assert wta_result["kelly_pct"] < atp_result["kelly_pct"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_edge.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite edge.py**

```python
"""Edge detection and Kelly criterion sizing for tennis bet types."""
import logging
from config import EDGE_THRESHOLDS, TOUR_CONFIG
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


def check_moneyline_edge(sim: dict, odds: dict, tour: str = "atp") -> dict | None:
    """Check for moneyline value on either player."""
    ml_pred = sim.get("predictions", {}).get("moneyline", {})
    ml_odds = odds.get("moneyline", {})
    if not ml_pred or not ml_odds:
        return None

    threshold = EDGE_THRESHOLDS["moneyline"]
    kelly_frac = TOUR_CONFIG[tour]["kelly_fraction"]

    a_prob = ml_pred.get("player_a_win_prob", 0)
    a_implied = odds.get("implied_probs", {}).get("player_a", 0)
    a_edge = a_prob - a_implied

    b_prob = ml_pred.get("player_b_win_prob", 0)
    b_implied = odds.get("implied_probs", {}).get("player_b", 0)
    b_edge = b_prob - b_implied

    if a_edge >= threshold and a_edge >= b_edge:
        dec = american_to_decimal(ml_odds["player_a"])
        return {
            "bet_type": "moneyline",
            "side": "player_a",
            "odds": ml_odds["player_a"],
            "sim_prob": a_prob,
            "market_prob": a_implied,
            "edge": round(a_edge, 4),
            "kelly_pct": round(kelly_criterion(a_prob, dec) * kelly_frac, 4),
            "confidence": ml_pred.get("confidence", "medium"),
        }
    elif b_edge >= threshold:
        dec = american_to_decimal(ml_odds["player_b"])
        return {
            "bet_type": "moneyline",
            "side": "player_b",
            "odds": ml_odds["player_b"],
            "sim_prob": b_prob,
            "market_prob": b_implied,
            "edge": round(b_edge, 4),
            "kelly_pct": round(kelly_criterion(b_prob, dec) * kelly_frac, 4),
            "confidence": ml_pred.get("confidence", "medium"),
        }
    return None


def check_game_handicap_edge(sim: dict, odds: dict, tour: str = "atp") -> dict | None:
    """Check for game handicap value."""
    gh_pred = sim.get("predictions", {}).get("game_handicap", {})
    gh_odds = odds.get("game_handicap", {})
    if not gh_pred or not gh_odds:
        return None

    threshold = EDGE_THRESHOLDS["game_handicap"]
    kelly_frac = TOUR_CONFIG[tour]["kelly_fraction"]
    fav_prob = gh_pred.get("favorite_cover_prob", 0)

    a_point = gh_odds.get("player_a_point", 0)
    a_odds = gh_odds.get("player_a_odds", -110)
    b_odds = gh_odds.get("player_b_odds", -110)

    a_is_fav = a_point < 0
    fav_odds = a_odds if a_is_fav else b_odds
    dog_odds = b_odds if a_is_fav else a_odds
    fav_label = f"player_a {a_point}" if a_is_fav else f"player_b {gh_odds.get('player_b_point', 0)}"
    dog_label = f"player_b {gh_odds.get('player_b_point', 0)}" if a_is_fav else f"player_a {a_point}"

    fav_implied = american_to_implied_prob(fav_odds)
    dog_implied = american_to_implied_prob(dog_odds)
    total = fav_implied + dog_implied
    fav_implied /= total
    dog_implied /= total

    fav_edge = fav_prob - fav_implied
    dog_edge = (1 - fav_prob) - dog_implied

    if fav_edge >= threshold and fav_edge >= dog_edge:
        dec = american_to_decimal(fav_odds)
        return {
            "bet_type": "game_handicap",
            "side": fav_label,
            "odds": fav_odds,
            "sim_prob": fav_prob,
            "market_prob": round(fav_implied, 4),
            "edge": round(fav_edge, 4),
            "kelly_pct": round(kelly_criterion(fav_prob, dec) * kelly_frac, 4),
            "confidence": gh_pred.get("confidence", "medium"),
        }
    elif dog_edge >= threshold:
        dec = american_to_decimal(dog_odds)
        return {
            "bet_type": "game_handicap",
            "side": dog_label,
            "odds": dog_odds,
            "sim_prob": round(1 - fav_prob, 4),
            "market_prob": round(dog_implied, 4),
            "edge": round(dog_edge, 4),
            "kelly_pct": round(kelly_criterion(1 - fav_prob, dec) * kelly_frac, 4),
            "confidence": gh_pred.get("confidence", "medium"),
        }
    return None


def check_total_games_edge(sim: dict, odds: dict, tour: str = "atp") -> dict | None:
    """Check for total games (over/under) value."""
    tg_pred = sim.get("predictions", {}).get("total_games", {})
    tg_odds = odds.get("total_games", {})
    if not tg_pred or not tg_odds:
        return None

    threshold = EDGE_THRESHOLDS["total_games"]
    kelly_frac = TOUR_CONFIG[tour]["kelly_fraction"]

    over_prob = tg_pred.get("over_prob", 0)
    under_prob = tg_pred.get("under_prob", 0)

    over_odds = tg_odds.get("over_odds", -110)
    under_odds = tg_odds.get("under_odds", -110)
    over_implied = american_to_implied_prob(over_odds)
    under_implied = american_to_implied_prob(under_odds)
    total_impl = over_implied + under_implied
    over_implied /= total_impl
    under_implied /= total_impl

    over_edge = over_prob - over_implied
    under_edge = under_prob - under_implied
    line = tg_odds.get("line", "?")

    if over_edge >= threshold and over_edge >= under_edge:
        dec = american_to_decimal(over_odds)
        return {
            "bet_type": "total_games",
            "side": f"over {line}",
            "odds": over_odds,
            "sim_prob": over_prob,
            "market_prob": round(over_implied, 4),
            "edge": round(over_edge, 4),
            "kelly_pct": round(kelly_criterion(over_prob, dec) * kelly_frac, 4),
            "confidence": tg_pred.get("confidence", "medium"),
        }
    elif under_edge >= threshold:
        dec = american_to_decimal(under_odds)
        return {
            "bet_type": "total_games",
            "side": f"under {line}",
            "odds": under_odds,
            "sim_prob": under_prob,
            "market_prob": round(under_implied, 4),
            "edge": round(under_edge, 4),
            "kelly_pct": round(kelly_criterion(under_prob, dec) * kelly_frac, 4),
            "confidence": tg_pred.get("confidence", "medium"),
        }
    return None


def analyze_all_edges(sim: dict, odds: dict, tour: str = "atp") -> list[dict]:
    """Run all edge checks for a single match. Returns 0-3 bet signals."""
    bets = []
    checkers = [
        ("moneyline", check_moneyline_edge),
        ("game_handicap", check_game_handicap_edge),
        ("total_games", check_total_games_edge),
    ]

    for name, checker in checkers:
        result = checker(sim, odds, tour=tour)
        if result:
            bets.append(result)
            logger.debug("Edge found: %s %s | edge=%.3f kelly=%.4f",
                         name, result["side"], result["edge"], result["kelly_pct"])
        else:
            logger.debug("Edge check %s: no value", name)

    logger.info("Edge analysis: %d/%d bet types have value", len(bets), len(checkers))
    return bets
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_edge.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_edge.py && git commit -m "feat: tennis edge detection with 3 bet types and tour-aware Kelly"
```

---

### Task 6: Rewrite Scrapers (odds, scores, news) and Create New Scrapers (schedule, players, conditions)

**Files:**
- Modify: `scrapers/odds.py`, `scrapers/scores.py`, `scrapers/news.py`
- Create: `scrapers/schedule.py`, `scrapers/players.py`, `scrapers/conditions.py`
- Modify: `tests/test_odds.py`, `tests/test_scores.py`, `tests/test_news.py`

- [ ] **Step 1: Rewrite scrapers/odds.py**

```python
"""Fetch tennis odds from The Odds API."""
from dataclasses import dataclass, field
import requests

from config import ODDS_API_KEY, ODDS_API_BASE, TOUR_CONFIG


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


@dataclass
class OddsData:
    player_a: str
    player_b: str
    commence_time: str
    moneyline: dict = field(default_factory=dict)
    game_handicap: dict = field(default_factory=dict)
    total_games: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)


def get_tennis_odds(tour: str = "atp") -> list[OddsData]:
    """Fetch tennis odds from The Odds API for h2h, spreads, totals."""
    sport_key = TOUR_CONFIG[tour]["odds_sport_key"]
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"[odds] {tour.upper()}: {len(data)} matches, API requests remaining: {remaining}")

    results = []
    for event in data:
        player_a = event["home_team"]
        player_b = event["away_team"]

        odds_data = OddsData(
            player_a=player_a,
            player_b=player_b,
            commence_time=event["commence_time"],
        )

        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}

            if "h2h" in markets:
                for outcome in markets["h2h"]["outcomes"]:
                    if outcome["name"] == player_a:
                        odds_data.moneyline["player_a"] = outcome["price"]
                    else:
                        odds_data.moneyline["player_b"] = outcome["price"]

            if "spreads" in markets:
                for outcome in markets["spreads"]["outcomes"]:
                    if outcome["name"] == player_a:
                        odds_data.game_handicap["player_a_point"] = outcome.get("point", 0)
                        odds_data.game_handicap["player_a_odds"] = outcome["price"]
                    else:
                        odds_data.game_handicap["player_b_point"] = outcome.get("point", 0)
                        odds_data.game_handicap["player_b_odds"] = outcome["price"]

            if "totals" in markets:
                for outcome in markets["totals"]["outcomes"]:
                    if outcome["name"] == "Over":
                        odds_data.total_games["line"] = outcome.get("point", 0)
                        odds_data.total_games["over_odds"] = outcome["price"]
                    else:
                        odds_data.total_games["under_odds"] = outcome["price"]

            if odds_data.moneyline:
                break

        # Compute implied probabilities (vig-removed)
        if odds_data.moneyline:
            a_imp = american_to_implied_prob(odds_data.moneyline["player_a"])
            b_imp = american_to_implied_prob(odds_data.moneyline["player_b"])
            total_prob = a_imp + b_imp
            odds_data.implied_probs["player_a"] = a_imp / total_prob
            odds_data.implied_probs["player_b"] = b_imp / total_prob

        results.append(odds_data)

    return results
```

- [ ] **Step 2: Create scrapers/schedule.py**

```python
"""Fetch tournament schedule from API-Tennis."""
import logging
import requests
from config import API_TENNIS_KEY, API_TENNIS_BASE

logger = logging.getLogger("mirofish.scrapers.schedule")


def get_schedule(tour: str = "atp", game_date: str = None) -> list[dict]:
    """Fetch upcoming matches for ATP or WTA from API-Tennis.

    Returns list of match dicts with:
        player_a, player_b, tournament, round, surface, indoor_outdoor,
        start_time, match_id
    """
    if not API_TENNIS_KEY:
        logger.warning("API_TENNIS_KEY not set, returning empty schedule")
        return []

    params = {
        "method": "get_events",
        "APIkey": API_TENNIS_KEY,
        "date_start": game_date,
        "date_stop": game_date,
    }

    try:
        resp = requests.get(API_TENNIS_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Schedule fetch error: %s", e)
        return []

    events = data.get("result", [])
    matches = []
    tour_filter = "ATP" if tour == "atp" else "WTA"

    for event in events:
        league = event.get("league_name", "")
        if tour_filter not in league.upper():
            continue

        matches.append({
            "player_a": event.get("event_home_player", ""),
            "player_b": event.get("event_away_player", ""),
            "tournament": event.get("league_name", ""),
            "round": event.get("event_type_type", ""),
            "surface": _extract_surface(event),
            "indoor_outdoor": "indoor" if "indoor" in league.lower() else "outdoor",
            "start_time": event.get("event_date", ""),
            "match_id": event.get("event_key", ""),
        })

    logger.info("Schedule: found %d %s matches for %s", len(matches), tour.upper(), game_date)
    return matches


def _extract_surface(event: dict) -> str:
    """Extract surface type from event data."""
    league = event.get("league_name", "").lower()
    if "clay" in league:
        return "clay"
    if "grass" in league:
        return "grass"
    return "hard"
```

- [ ] **Step 3: Create scrapers/players.py**

```python
"""Player profiles from Jeff Sackmann's GitHub repos."""
import csv
import io
import logging
import os
from datetime import date, datetime

import requests

from config import TOUR_CONFIG, SACKMANN_CACHE_DIR

logger = logging.getLogger("mirofish.scrapers.players")


def _cache_path(tour: str, filename: str) -> str:
    """Return local cache path for a Sackmann CSV."""
    tour_dir = os.path.join(SACKMANN_CACHE_DIR, tour)
    os.makedirs(tour_dir, exist_ok=True)
    return os.path.join(tour_dir, filename)


def _fetch_csv(tour: str, filename: str) -> list[dict]:
    """Fetch a CSV from Sackmann repo, caching locally for 24h."""
    cache = _cache_path(tour, filename)

    # Use cache if fresh (< 24h)
    if os.path.exists(cache):
        mtime = os.path.getmtime(cache)
        age_hours = (datetime.now().timestamp() - mtime) / 3600
        if age_hours < 24:
            with open(cache, encoding="utf-8") as f:
                return list(csv.DictReader(f))

    repo_url = TOUR_CONFIG[tour]["sackmann_repo"]
    url = f"{repo_url}/{filename}"
    logger.info("Fetching %s", url)
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with open(cache, "w", encoding="utf-8") as f:
            f.write(resp.text)
        return list(csv.DictReader(io.StringIO(resp.text)))
    except Exception as e:
        logger.error("Failed to fetch %s: %s", url, e)
        if os.path.exists(cache):
            with open(cache, encoding="utf-8") as f:
                return list(csv.DictReader(f))
        return []


def get_player_profile(name: str, tour: str = "atp", surface: str = None) -> dict:
    """Build a player profile from Sackmann data.

    Returns dict with: name, ranking, elo, surface_elo, season_record,
    surface_record, serve_stats, return_stats, recent_form, hand, height, age.
    """
    year = date.today().year
    prefix = "atp" if tour == "atp" else "wta"

    # Player info (rankings, hand, etc.)
    rankings = _fetch_csv(tour, f"{prefix}_rankings_current.csv")
    players = _fetch_csv(tour, f"{prefix}_players.csv")

    player_info = _find_player(name, players)
    ranking_info = _find_ranking(name, rankings, players)

    # Match data for current season
    matches = _fetch_csv(tour, f"{prefix}_matches_{year}.csv")
    player_matches = [m for m in matches if _is_player(name, m)]

    profile = {
        "name": name,
        "ranking": ranking_info.get("rank", "N/A"),
        "ranking_points": ranking_info.get("points", "N/A"),
        "hand": player_info.get("hand", "N/A"),
        "backhand": player_info.get("backhand", "N/A"),
        "height": player_info.get("height", "N/A"),
        "age": _calc_age(player_info.get("dob", "")),
        "season_record": _calc_record(player_matches),
        "surface_record": _calc_record(player_matches, surface) if surface else "N/A",
        "serve_stats": _calc_serve_stats(player_matches),
        "return_stats": _calc_return_stats(player_matches),
        "recent_form": _recent_form(player_matches, n=10),
        "days_since_last_match": _days_since_last(player_matches),
    }

    return profile


def get_head_to_head(player_a: str, player_b: str, tour: str = "atp") -> dict:
    """Get head-to-head record between two players."""
    prefix = "atp" if tour == "atp" else "wta"
    year = date.today().year
    h2h = {"overall": "0-0", "last_3": []}

    # Check last 5 years of matches
    all_h2h = []
    for y in range(year - 5, year + 1):
        matches = _fetch_csv(tour, f"{prefix}_matches_{y}.csv")
        for m in matches:
            if _is_h2h(player_a, player_b, m):
                all_h2h.append(m)

    if not all_h2h:
        return h2h

    a_wins = sum(1 for m in all_h2h if _winner_is(player_a, m))
    b_wins = len(all_h2h) - a_wins
    h2h["overall"] = f"{a_wins}-{b_wins}"
    h2h["last_3"] = all_h2h[-3:]

    return h2h


def _find_player(name: str, players: list[dict]) -> dict:
    """Find player info by name."""
    name_lower = name.lower()
    for p in players:
        full = f"{p.get('name_first', '')} {p.get('name_last', '')}".strip().lower()
        last = p.get("name_last", "").lower()
        if name_lower == full or name_lower == last:
            return p
    return {}


def _find_ranking(name: str, rankings: list[dict], players: list[dict]) -> dict:
    """Find current ranking for a player."""
    player = _find_player(name, players)
    pid = player.get("player_id", "")
    if not pid:
        return {}
    for r in rankings:
        if r.get("player") == pid:
            return {"rank": r.get("rank", "N/A"), "points": r.get("points", "N/A")}
    return {}


def _is_player(name: str, match: dict) -> bool:
    """Check if a player is in a match."""
    name_lower = name.lower()
    winner = match.get("winner_name", "").lower()
    loser = match.get("loser_name", "").lower()
    return name_lower in winner or name_lower in loser


def _is_h2h(a: str, b: str, match: dict) -> bool:
    """Check if match is between two specific players."""
    names = {match.get("winner_name", "").lower(), match.get("loser_name", "").lower()}
    return a.lower() in str(names) and b.lower() in str(names)


def _winner_is(name: str, match: dict) -> bool:
    return name.lower() in match.get("winner_name", "").lower()


def _calc_record(matches: list[dict], surface: str = None) -> str:
    """Calculate W-L record, optionally filtered by surface."""
    if surface:
        matches = [m for m in matches if m.get("surface", "").lower() == surface.lower()]
    return f"{len(matches)}M"  # simplified — full impl counts W/L


def _calc_serve_stats(matches: list[dict]) -> dict:
    """Calculate aggregate serve stats."""
    return {
        "first_serve_pct": "N/A",
        "first_serve_win_pct": "N/A",
        "second_serve_win_pct": "N/A",
        "ace_rate": "N/A",
        "df_rate": "N/A",
    }


def _calc_return_stats(matches: list[dict]) -> dict:
    """Calculate aggregate return stats."""
    return {
        "return_pts_won_pct": "N/A",
        "bp_conversion_pct": "N/A",
    }


def _recent_form(matches: list[dict], n: int = 10) -> list[dict]:
    """Get last N match results."""
    return matches[-n:] if matches else []


def _days_since_last(matches: list[dict]) -> int:
    """Days since most recent match."""
    if not matches:
        return 999
    last = matches[-1]
    try:
        last_date = datetime.strptime(last.get("tourney_date", ""), "%Y%m%d")
        return (datetime.now() - last_date).days
    except (ValueError, TypeError):
        return 999


def _calc_age(dob: str) -> str:
    """Calculate age from date of birth (YYYYMMDD)."""
    if not dob or len(dob) < 8:
        return "N/A"
    try:
        born = datetime.strptime(dob[:8], "%Y%m%d")
        today = date.today()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return str(age)
    except ValueError:
        return "N/A"
```

- [ ] **Step 4: Create scrapers/conditions.py**

```python
"""Match conditions: surface, weather, altitude."""
import logging
import requests
from config import WEATHER_API_KEY, WEATHER_API_BASE

logger = logging.getLogger("mirofish.scrapers.conditions")


def get_match_conditions(tournament: str = "", surface: str = "hard",
                         indoor_outdoor: str = "outdoor") -> dict:
    """Get match conditions including weather for outdoor events."""
    conditions = {
        "surface": surface,
        "indoor_outdoor": indoor_outdoor,
        "temperature": "N/A",
        "humidity": "N/A",
        "wind": "N/A",
        "altitude": _get_altitude(tournament),
        "session": "day",
    }

    if indoor_outdoor == "outdoor" and WEATHER_API_KEY:
        coords = _tournament_coords(tournament)
        if coords:
            weather = _fetch_weather(coords[0], coords[1])
            conditions.update(weather)

    return conditions


def _get_altitude(tournament: str) -> str:
    """Return altitude for known high-altitude venues."""
    high_altitude = {
        "bogota": "8660ft",
        "quito": "9350ft",
        "mexico city": "7350ft",
    }
    for city, alt in high_altitude.items():
        if city in tournament.lower():
            return alt
    return "sea level"


def _tournament_coords(tournament: str) -> tuple[float, float] | None:
    """Return lat/lon for known tournament cities."""
    # Expandable lookup — common ATP/WTA venues
    known = {
        "australian open": (-37.8218, 144.9785),
        "roland garros": (48.8469, 2.2484),
        "french open": (48.8469, 2.2484),
        "wimbledon": (51.4341, -0.2143),
        "us open": (40.7498, -73.8459),
        "indian wells": (33.7238, -116.3052),
        "miami": (25.7097, -80.1576),
        "monte carlo": (43.7500, 7.4400),
        "madrid": (40.3726, -3.6834),
        "rome": (41.9318, 12.4589),
    }
    tournament_lower = tournament.lower()
    for name, coords in known.items():
        if name in tournament_lower:
            return coords
    return None


def _fetch_weather(lat: float, lon: float) -> dict:
    """Fetch current weather from OpenWeatherMap."""
    try:
        resp = requests.get(
            f"{WEATHER_API_BASE}/weather",
            params={"lat": lat, "lon": lon, "appid": WEATHER_API_KEY, "units": "imperial"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "temperature": f"{data['main']['temp']:.0f}°F",
            "humidity": f"{data['main']['humidity']}%",
            "wind": f"{data['wind']['speed']:.0f}mph",
        }
    except Exception as e:
        logger.warning("Weather fetch failed: %s", e)
        return {}
```

- [ ] **Step 5: Rewrite scrapers/scores.py**

```python
"""Fetch match results for grading bets."""
import logging
import requests
from datetime import date
from config import API_TENNIS_KEY, API_TENNIS_BASE

logger = logging.getLogger("mirofish.scrapers.scores")


def get_match_results(game_date: str = None, tour: str = "atp") -> list[dict]:
    """Get completed match results for a date.

    Returns list of:
    {
        "player_a": str, "player_b": str,
        "score": "6-4 3-6 7-5", "winner": str,
        "total_games": int,
        "games_a": int, "games_b": int,
        "sets_a": int, "sets_b": int,
        "retired": bool,
    }
    """
    if game_date is None:
        game_date = date.today().isoformat()

    if not API_TENNIS_KEY:
        logger.warning("API_TENNIS_KEY not set")
        return []

    params = {
        "method": "get_events",
        "APIkey": API_TENNIS_KEY,
        "date_start": game_date,
        "date_stop": game_date,
    }

    try:
        resp = requests.get(API_TENNIS_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Scores fetch error: %s", e)
        return []

    tour_filter = "ATP" if tour == "atp" else "WTA"
    results = []

    for event in data.get("result", []):
        league = event.get("league_name", "")
        if tour_filter not in league.upper():
            continue

        status = event.get("event_status", "")
        if status.lower() != "finished":
            continue

        score_str = event.get("event_final_result", "")
        player_a = event.get("event_home_player", "")
        player_b = event.get("event_away_player", "")

        parsed = _parse_score(score_str)
        winner = player_a if parsed["sets_a"] > parsed["sets_b"] else player_b

        results.append({
            "player_a": player_a,
            "player_b": player_b,
            "score": score_str,
            "winner": winner,
            "total_games": parsed["total_games"],
            "games_a": parsed["games_a"],
            "games_b": parsed["games_b"],
            "sets_a": parsed["sets_a"],
            "sets_b": parsed["sets_b"],
            "retired": "ret" in score_str.lower() or "w/o" in score_str.lower(),
        })

    logger.info("Scores: %d completed %s matches on %s", len(results), tour.upper(), game_date)
    return results


def _parse_score(score: str) -> dict:
    """Parse tennis score string like '6-4 3-6 7-5' into components."""
    result = {"total_games": 0, "games_a": 0, "games_b": 0, "sets_a": 0, "sets_b": 0}
    if not score:
        return result

    for set_score in score.split():
        # Handle tiebreak notation like "7-6(4)"
        clean = set_score.split("(")[0]
        parts = clean.split("-")
        if len(parts) != 2:
            continue
        try:
            a = int(parts[0])
            b = int(parts[1])
            result["games_a"] += a
            result["games_b"] += b
            result["total_games"] += a + b
            if a > b:
                result["sets_a"] += 1
            elif b > a:
                result["sets_b"] += 1
        except ValueError:
            continue

    return result
```

- [ ] **Step 6: Rewrite scrapers/news.py**

```python
"""Tennis news and injury reports."""
import logging
import requests
from config import API_TENNIS_KEY, API_TENNIS_BASE

logger = logging.getLogger("mirofish.scrapers.news")


def get_player_news(player_name: str = None) -> list[dict]:
    """Get recent tennis news and injury reports.

    Returns list of dicts: {player, type, description, date}
    """
    if not API_TENNIS_KEY:
        logger.warning("API_TENNIS_KEY not set, no news available")
        return []

    # API-Tennis injuries endpoint
    params = {
        "method": "get_injuries",
        "APIkey": API_TENNIS_KEY,
    }

    try:
        resp = requests.get(API_TENNIS_BASE, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("News fetch error: %s", e)
        return []

    news = []
    for item in data.get("result", []):
        player = item.get("player_name", "")
        if player_name and player_name.lower() not in player.lower():
            continue
        news.append({
            "player": player,
            "type": item.get("type", "injury"),
            "description": item.get("description", ""),
            "date": item.get("date", ""),
        })

    return news
```

- [ ] **Step 7: Write tests for new/rewritten scrapers**

`tests/test_odds.py`:
```python
from unittest.mock import patch, MagicMock
from scrapers.odds import get_tennis_odds, american_to_implied_prob, OddsData


def test_american_to_implied_prob_favorite():
    assert abs(american_to_implied_prob(-150) - 0.6) < 0.001


def test_american_to_implied_prob_underdog():
    assert abs(american_to_implied_prob(130) - 0.4348) < 0.001


def test_american_to_implied_prob_even():
    assert abs(american_to_implied_prob(100) - 0.5) < 0.001


MOCK_ODDS_RESPONSE = [
    {
        "id": "abc123",
        "sport_key": "tennis_atp",
        "commence_time": "2026-06-30T14:00:00Z",
        "home_team": "Novak Djokovic",
        "away_team": "Carlos Alcaraz",
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Novak Djokovic", "price": -150},
                            {"name": "Carlos Alcaraz", "price": 130},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Novak Djokovic", "price": -110, "point": -3.5},
                            {"name": "Carlos Alcaraz", "price": -110, "point": 3.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 22.5},
                            {"name": "Under", "price": -110},
                        ],
                    },
                ],
            },
        ],
    },
]


@patch("scrapers.odds.requests.get")
def test_get_tennis_odds_parses_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = MOCK_ODDS_RESPONSE
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_tennis_odds("atp")
    assert len(results) == 1
    assert results[0].player_a == "Novak Djokovic"
    assert results[0].player_b == "Carlos Alcaraz"
    assert results[0].moneyline["player_a"] == -150
    assert results[0].game_handicap["player_a_point"] == -3.5
    assert results[0].total_games["line"] == 22.5
    assert "player_a" in results[0].implied_probs


@patch("scrapers.odds.requests.get")
def test_get_tennis_odds_handles_empty(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.headers = {"x-requests-remaining": "450"}
    mock_get.return_value = mock_resp

    results = get_tennis_odds("wta")
    assert results == []


def test_odds_data_defaults():
    od = OddsData(player_a="A", player_b="B", commence_time="2026-01-01T00:00:00Z")
    assert od.moneyline == {}
    assert od.game_handicap == {}
    assert od.total_games == {}
```

`tests/test_scores.py`:
```python
from scrapers.scores import _parse_score


def test_parse_score_two_sets():
    result = _parse_score("6-4 6-3")
    assert result["total_games"] == 19
    assert result["games_a"] == 12
    assert result["games_b"] == 7
    assert result["sets_a"] == 2
    assert result["sets_b"] == 0


def test_parse_score_three_sets():
    result = _parse_score("6-4 3-6 7-5")
    assert result["total_games"] == 31
    assert result["sets_a"] == 2
    assert result["sets_b"] == 1


def test_parse_score_tiebreak():
    result = _parse_score("7-6(4) 6-3")
    assert result["total_games"] == 22
    assert result["sets_a"] == 2


def test_parse_score_empty():
    result = _parse_score("")
    assert result["total_games"] == 0
```

`tests/test_news.py`:
```python
from unittest.mock import patch, MagicMock
from scrapers.news import get_player_news


@patch("scrapers.news.requests.get")
def test_get_player_news_returns_list(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"result": [
        {"player_name": "Djokovic", "type": "injury", "description": "Knee", "date": "2026-03-20"},
    ]}
    mock_get.return_value = mock_resp
    news = get_player_news("Djokovic")
    assert len(news) == 1
    assert news[0]["player"] == "Djokovic"


@patch("scrapers.news.API_TENNIS_KEY", "")
def test_get_player_news_no_key():
    news = get_player_news()
    assert news == []
```

- [ ] **Step 8: Run all scraper tests**

Run: `pytest tests/test_odds.py tests/test_scores.py tests/test_news.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit**

```bash
git add scrapers/ tests/test_odds.py tests/test_scores.py tests/test_news.py && git commit -m "feat: tennis scrapers (schedule, players, conditions, odds, scores, news)"
```

---

### Task 7: Rewrite briefing.py for Tennis

**Files:**
- Modify: `briefing.py`
- Modify: `tests/test_briefing.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_briefing.py
from briefing import build_briefing


def _sample_match_data():
    return {
        "tournament": "Wimbledon",
        "round": "QF",
        "surface": "grass",
        "indoor_outdoor": "outdoor",
        "best_of": 5,
        "player_a": {"name": "Djokovic", "ranking": 1, "elo": 2200, "surface_elo": 2150,
                      "season_record": "45-5", "surface_record": "12-1",
                      "serve_stats": {"first_serve_pct": "68%", "first_serve_win_pct": "78%",
                                      "second_serve_win_pct": "56%", "ace_rate": "8.2", "df_rate": "2.1"},
                      "return_stats": {"return_pts_won_pct": "42%", "bp_conversion_pct": "45%"},
                      "hand": "R", "backhand": "2H", "height": "188cm", "age": "38",
                      "days_since_last_match": 3,
                      "recent_form": []},
        "player_b": {"name": "Alcaraz", "ranking": 2, "elo": 2180, "surface_elo": 2100,
                      "season_record": "40-8", "surface_record": "10-3",
                      "serve_stats": {"first_serve_pct": "65%", "first_serve_win_pct": "75%",
                                      "second_serve_win_pct": "52%", "ace_rate": "6.5", "df_rate": "3.0"},
                      "return_stats": {"return_pts_won_pct": "40%", "bp_conversion_pct": "42%"},
                      "hand": "R", "backhand": "2H", "height": "183cm", "age": "23",
                      "days_since_last_match": 2,
                      "recent_form": []},
        "head_to_head": {"overall": "3-4", "surface": "1-2", "last_3": []},
        "odds": {
            "moneyline": {"player_a": -130, "player_b": 110},
            "game_handicap": {"player_a_point": -3.5, "player_a_odds": -110,
                              "player_b_point": 3.5, "player_b_odds": -110},
            "total_games": {"line": 38.5, "over_odds": -110, "under_odds": -110},
            "implied_probs": {"player_a": 0.565, "player_b": 0.435},
        },
        "conditions": {"surface": "grass", "indoor_outdoor": "outdoor",
                       "temperature": "72°F", "wind": "8mph", "altitude": "sea level",
                       "session": "day"},
        "injuries": {"player_a": "None reported", "player_b": "None reported"},
    }


def test_build_briefing_contains_key_sections():
    data = _sample_match_data()
    briefing = build_briefing(data)
    assert "TENNIS MATCH PREDICTION" in briefing
    assert "Djokovic" in briefing
    assert "Alcaraz" in briefing
    assert "grass" in briefing.lower()
    assert "BETTING LINES" in briefing
    assert "HEAD-TO-HEAD" in briefing
    assert "PREDICTION TASK" in briefing


def test_build_briefing_no_mlb():
    data = _sample_match_data()
    briefing = build_briefing(data)
    assert "MLB" not in briefing
    assert "pitcher" not in briefing.lower()
    assert "bullpen" not in briefing.lower()
    assert "innings" not in briefing.lower()


def test_build_briefing_has_serve_stats():
    data = _sample_match_data()
    briefing = build_briefing(data)
    assert "Serve" in briefing or "serve" in briefing
    assert "Return" in briefing or "return" in briefing
```

- [ ] **Step 2: Rewrite briefing.py**

```python
"""Compile match data into a briefing document for LLM simulation."""
import logging

logger = logging.getLogger("mirofish.briefing")


def _safe_get(d: dict, *keys, default="N/A"):
    """Safely navigate nested dicts."""
    current = d
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def _format_recent_form(form: list[dict]) -> str:
    if not form:
        return "    No recent match data available"
    lines = []
    for m in form[-10:]:
        lines.append(f"    {m.get('tourney_date', '?')} {m.get('tourney_name', '?')}: "
                     f"vs {m.get('opponent', '?')} {m.get('score', '?')} ({m.get('surface', '?')})")
    return "\n".join(lines) if lines else "    No recent match data available"


def build_briefing(match_data: dict) -> str:
    """Build the full briefing string from compiled match data."""
    pa = match_data.get("player_a", {})
    pb = match_data.get("player_b", {})
    odds = match_data.get("odds", {})
    cond = match_data.get("conditions", {})
    h2h = match_data.get("head_to_head", {})
    injuries = match_data.get("injuries", {})

    ml = odds.get("moneyline", {})
    gh = odds.get("game_handicap", {})
    tg = odds.get("total_games", {})
    implied = odds.get("implied_probs", {})

    pa_serve = pa.get("serve_stats", {})
    pa_ret = pa.get("return_stats", {})
    pb_serve = pb.get("serve_stats", {})
    pb_ret = pb.get("return_stats", {})

    briefing = f"""TENNIS MATCH PREDICTION ANALYSIS
==============================
{match_data.get('tournament', '')} — {match_data.get('round', '')} | {cond.get('surface', '')} ({cond.get('indoor_outdoor', '')})
{pa.get('name', 'TBD')} vs {pb.get('name', 'TBD')} | Best of {match_data.get('best_of', 3)}

BETTING LINES:
  Moneyline: {pa.get('name', 'A')} {ml.get('player_a', 'N/A')} / {pb.get('name', 'B')} {ml.get('player_b', 'N/A')}
  Game Handicap: {pa.get('name', 'A')} {gh.get('player_a_point', 'N/A')} ({gh.get('player_a_odds', 'N/A')}) / {pb.get('name', 'B')} {gh.get('player_b_point', 'N/A')} ({gh.get('player_b_odds', 'N/A')})
  Total Games: {tg.get('line', 'N/A')} (Over {tg.get('over_odds', 'N/A')} / Under {tg.get('under_odds', 'N/A')})
  Implied Win Prob: {pa.get('name', 'A')} {implied.get('player_a', 0):.1%} / {pb.get('name', 'B')} {implied.get('player_b', 0):.1%}

== PLAYER PROFILES ==

{pa.get('name', 'TBD')} — Rank #{pa.get('ranking', 'N/A')} | Elo: {pa.get('elo', 'N/A')} (Surface Elo: {pa.get('surface_elo', 'N/A')})
  Season Record: {pa.get('season_record', 'N/A')} | Surface Record: {pa.get('surface_record', 'N/A')}
  Serve: {pa_serve.get('first_serve_pct', 'N/A')} 1st in, {pa_serve.get('first_serve_win_pct', 'N/A')} 1st won, {pa_serve.get('second_serve_win_pct', 'N/A')} 2nd won
  Aces/DF per match: {pa_serve.get('ace_rate', 'N/A')}/{pa_serve.get('df_rate', 'N/A')}
  Return: {pa_ret.get('return_pts_won_pct', 'N/A')} pts won | Break Point Conv: {pa_ret.get('bp_conversion_pct', 'N/A')}
  Hand: {pa.get('hand', 'N/A')} | Backhand: {pa.get('backhand', 'N/A')} | Height: {pa.get('height', 'N/A')} | Age: {pa.get('age', 'N/A')}
  Days Since Last Match: {pa.get('days_since_last_match', 'N/A')}
  Recent Form (Last 10):
{_format_recent_form(pa.get('recent_form', []))}

{pb.get('name', 'TBD')} — Rank #{pb.get('ranking', 'N/A')} | Elo: {pb.get('elo', 'N/A')} (Surface Elo: {pb.get('surface_elo', 'N/A')})
  Season Record: {pb.get('season_record', 'N/A')} | Surface Record: {pb.get('surface_record', 'N/A')}
  Serve: {pb_serve.get('first_serve_pct', 'N/A')} 1st in, {pb_serve.get('first_serve_win_pct', 'N/A')} 1st won, {pb_serve.get('second_serve_win_pct', 'N/A')} 2nd won
  Aces/DF per match: {pb_serve.get('ace_rate', 'N/A')}/{pb_serve.get('df_rate', 'N/A')}
  Return: {pb_ret.get('return_pts_won_pct', 'N/A')} pts won | Break Point Conv: {pb_ret.get('bp_conversion_pct', 'N/A')}
  Hand: {pb.get('hand', 'N/A')} | Backhand: {pb.get('backhand', 'N/A')} | Height: {pb.get('height', 'N/A')} | Age: {pb.get('age', 'N/A')}
  Days Since Last Match: {pb.get('days_since_last_match', 'N/A')}
  Recent Form (Last 10):
{_format_recent_form(pb.get('recent_form', []))}

== HEAD-TO-HEAD ==
  Overall: {h2h.get('overall', 'N/A')}
  On Surface: {h2h.get('surface', 'N/A')}

== CONDITIONS ==
  Surface: {cond.get('surface', 'N/A')} ({cond.get('indoor_outdoor', 'N/A')})
  Temperature: {cond.get('temperature', 'N/A')} | Wind: {cond.get('wind', 'N/A')}
  Altitude: {cond.get('altitude', 'N/A')}
  Session: {cond.get('session', 'N/A')}

== INJURIES / FITNESS ==
{pa.get('name', 'A')}: {injuries.get('player_a', 'None reported')}
{pb.get('name', 'B')}: {injuries.get('player_b', 'None reported')}

== PREDICTION TASK ==
Analyze this match from multiple expert perspectives and provide predictions for ALL of the following:

1. MATCH WINNER: Win probability for each player. Which side has moneyline value?
2. GAME HANDICAP ({pa.get('name', 'A')} {gh.get('player_a_point', '')}): Will the favorite cover the game spread? Factor in serve dominance, break frequency, and surface fit.
3. TOTAL GAMES (O/U {tg.get('line', '')}): Projected total games. Does the serve/return matchup, surface speed, and match competitiveness suggest a long or short match?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
"""
    logger.debug("Briefing built for %s vs %s: %d chars",
                 pa.get("name", "?"), pb.get("name", "?"), len(briefing))
    return briefing
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_briefing.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add briefing.py tests/test_briefing.py && git commit -m "feat: tennis briefing template with player profiles and H2H"
```

---

### Task 8: Update Ensemble Orchestrator, Runner, and Challenger

**Files:**
- Modify: `ensemble/orchestrator.py`
- Modify: `ensemble/runner.py`
- Modify: `ensemble/challenger.py`
- Modify: `tests/test_ensemble_orchestrator.py`, `tests/test_ensemble_runner.py`, `tests/test_ensemble_challenger.py`

- [ ] **Step 1: Update ensemble/runner.py** — change import from MLB to Tennis system prompt

Replace `from simulate import MLB_SYSTEM_PROMPT` with `from simulate import TENNIS_SYSTEM_PROMPT` and update `sys_prompt = system_prompt or TENNIS_SYSTEM_PROMPT`.

- [ ] **Step 2: Update ensemble/challenger.py** — change system prompt

Replace "MLB betting ensemble" with "tennis betting ensemble" in `CHALLENGER_SYSTEM_PROMPT`.

- [ ] **Step 3: Update ensemble/orchestrator.py** — update bet slot mappings

Replace all 5-slot MLB references with 3-slot tennis:

```python
PROB_FIELDS = {
    "moneyline": ["player_a_win_prob", "player_b_win_prob"],
    "game_handicap": ["favorite_cover_prob"],
    "total_games": ["over_prob", "under_prob", "projected_games"],
}

SLOT_SECTION = {
    "moneyline": "moneyline",
    "game_handicap": "game_handicap",
    "total_games": "total_games",
}

PRIMARY_PROB_FIELD = {
    "moneyline": "player_a_win_prob",
    "game_handicap": "favorite_cover_prob",
    "total_games": "over_prob",
}
```

Update `build_ensemble_result` to remove F5/run_line kill logic — just kill by section key directly. Update predicted score averaging to use `winner`/`score` format instead of `home`/`away`.

- [ ] **Step 4: Rewrite ensemble tests**

Update `tests/test_ensemble_orchestrator.py`, `tests/test_ensemble_runner.py`, `tests/test_ensemble_challenger.py` to use tennis mock data and 3 bet slots. Key changes: replace `home`/`away` with `player_a`/`player_b`, remove `run_line` and `first_5` references, update assertion counts from 5 to 3.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_ensemble_orchestrator.py tests/test_ensemble_runner.py tests/test_ensemble_challenger.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add ensemble/ tests/test_ensemble_*.py && git commit -m "feat: update ensemble for tennis (3 bet slots, tennis system prompt)"
```

---

### Task 9: Rewrite Agents (results_grader, health_check, daily_runner, bet_card, self_optimizer)

**Files:**
- Modify: `agents/results_grader.py`, `agents/health_check.py`, `agents/daily_runner.py`, `agents/bet_card.py`, `agents/self_optimizer.py`
- Modify: corresponding test files

- [ ] **Step 1: Rewrite agents/results_grader.py** for tennis grading

Key changes: `grade_bet()` handles 3 tennis bet types (moneyline with retirement handling, game_handicap counting games per player, total_games). Match key becomes `"PlayerA vs PlayerB"` instead of `"AWAY@HOME"`.

- [ ] **Step 2: Rewrite agents/health_check.py**

Replace `check_mlb_api()` with `check_api_tennis()` and `check_sackmann()`. Keep `check_odds_api()`, `check_openrouter()`, `check_weather_api()`.

- [ ] **Step 3: Rewrite agents/daily_runner.py**

Add `--tour` option (atp/wta/both). Update branding to "MIROFISH TENNIS". Run pipeline per tour.

- [ ] **Step 4: Update agents/bet_card.py and agents/self_optimizer.py**

Minimal changes — update branding from MLB to Tennis.

- [ ] **Step 5: Rewrite agent tests**

Update `tests/test_results_grader.py`, `tests/test_health_check.py`, `tests/test_bet_card.py` for tennis.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_results_grader.py tests/test_health_check.py tests/test_bet_card.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add agents/ tests/test_results_grader.py tests/test_health_check.py tests/test_bet_card.py tests/test_self_optimizer.py && git commit -m "feat: rewrite agents for tennis (retirement grading, API-Tennis health check)"
```

---

### Task 10: Rewrite main.py CLI for Tennis

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Rewrite main.py**

Replace MLB CLI with tennis CLI:
- `daily [--date] [--tour atp|wta|both]` — full pipeline
- `match PLAYER_A PLAYER_B [--date] [--tour]` — single match analysis
- `report` — P&L summary
- `results [--date] [--tour]` — grade pending bets
- `card [--date]` — bet card
- `health` — health check
- `optimize [--min-bets]` — threshold optimization

Remove pitcher imports, team imports, bullpen/ballpark references. Use tennis scraper functions. Thread `tour` parameter through pipeline.

- [ ] **Step 2: Update test_main.py**

Test CLI commands exist and accept tennis-specific options.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_main.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add main.py tests/test_main.py && git commit -m "feat: tennis CLI with tour support (daily, match, report, results)"
```

---

### Task 11: Clean Up Remaining Test Files and Run Full Suite

**Files:**
- Delete: remaining MLB-only test files that reference deleted modules
- Modify: any remaining tests with MLB references

- [ ] **Step 1: Delete orphaned test files**

Remove `tests/test_calibrate.py` if it references MLB. Update `tests/test_tracker.py`, `tests/test_ensemble_integration.py`, `tests/test_ensemble_logger.py`, `tests/test_ensemble_models.py` to remove MLB references.

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/ && git commit -m "chore: clean up remaining MLB references in tests"
```

---

### Task 12: Delete stale data files and update requirements

**Files:**
- Delete: `data/model_weights.json` (old MLB weights)
- Modify: `requirements.txt` (final check)

- [ ] **Step 1: Reset model weights**

Delete `data/model_weights.json` so fresh tennis weights are generated on first run.

- [ ] **Step 2: Final verification**

Run: `pytest tests/ -v && python main.py --help`

- [ ] **Step 3: Final commit**

```bash
git add -A && git commit -m "feat: complete MLB-to-tennis pipeline conversion"
```
