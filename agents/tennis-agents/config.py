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
API_TENNIS_BASE = "https://api.api-tennis.com/tennis/"

# Tour-specific configuration
TOUR_CONFIG = {
    "atp": {
        "odds_sport_key": "tennis_atp",
        "kelly_fraction": 0.25,
    },
    "wta": {
        "odds_sport_key": "tennis_wta",
        "kelly_fraction": 0.125,
    },
}

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCREEN_EDGE_THRESHOLD = 0.05  # Plan B flag threshold. Raised from 0.03 on 2026-04-23: at 0.03
                              # we were flagging ~50% of matches on a busy slate (13 of 26),
                              # many of which produced no bet after the full ensemble reviewed them.
                              # 0.05 cuts marginal flags while preserving the high-conviction ones.
GAME_TIMEOUT = 300  # 5 min per match. Phase 1 alone is ~2 min; Phase 2 expansion on disagreement adds 2-3 min.
                    # The cancel_futures fix in ensemble/orchestrator.py makes this actually enforceable.

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing defaults
KELLY_FRACTION_ATP = 0.25
KELLY_FRACTION_WTA = 0.125

# Edge thresholds per bet type (detection floor — inside each check_*_edge).
# Distinct from BET_FILTERS below: EDGE_THRESHOLDS decides "is this a candidate
# edge at all"; BET_FILTERS decides "is this candidate cleared to log and bet".
#
# 2026-04-23: lowered from 5%/6%/5% to 3%/3%/3% (median aggregation made
# edges 2-3pp smaller than Plan B).
# 2026-04-24: lowered to 2%, then to 1% after observing that even 2% produced
# 0 bets across 4 runs. Explanation from model_predictions.csv analysis: the
# 6 models disagree on DIRECTION (not just magnitude), so the median-of-
# model-medians aggregation correctly lands near 0.5 for most matches → tiny
# aggregate edges. Individual models find big edges (up to 70%+), but on
# different sides per match.
# 1% is experimental. Kelly sizing at 1% edge produces tiny bet sizes
# (~0.2% bankroll), but that's the price of volume needed to accumulate
# CLV data. If this still produces 0-1 bets per slate, the fix needs to be
# an individual-model-conviction fallback, not threshold tuning.
EDGE_THRESHOLDS = {
    "moneyline": 0.01,
    "game_handicap": 0.01,
    "total_games": 0.01,
}

# Pipeline lookahead window. Matches whose start_time is more than this many
# hours away get filtered out before screening — odds drift, lineups change,
# and cached predictions go stale on far-out matches. 8h gets us same-day
# coverage including evening WTA + morning ATP next day, without burning
# ensemble cost on matches that won't tip until tomorrow afternoon.
PIPELINE_LOOKAHEAD_HOURS = 8

# Option B — individual-model-conviction fallback (2026-04-24).
# Primary edge check uses the median-of-model-medians. When models disagree on
# DIRECTION, that median cancels to ~0.5 and produces no bet even when a
# supermajority of models individually see real edge. The fallback fires only
# when primary returns no bet AND:
#   - at least CONVICTION_MIN_MODELS of 6 models agree on the same side
#   - each of those agreeing models sees per-model edge ≥ CONVICTION_MIN_EDGE
# The bet is sized with CONVICTION_KELLY_MULT applied on top of the confidence
# multiplier, because "models agree on direction but not on strength" is weaker
# signal than "ensemble median lands outside the market".
CONVICTION_MIN_MODELS = 4
CONVICTION_MIN_EDGE = 0.03
CONVICTION_KELLY_MULT = 0.5

# Per-bet-type logging gate. Applied AFTER edge detection, BEFORE log_bet().
# Bet types not in this dict pass through unchanged. Supported keys per type:
#   disabled:      True to drop all bets of this type
#   min_edge:      drop bets with edge < this (redundant with EDGE_THRESHOLDS today)
#   max_edge:      drop bets with edge > this (overconfidence guard)
#   side_contains: list of substrings; keep only bets whose side contains one
#   odds_min / odds_max: inclusive American-odds range
#   line_in:       whitelist of numeric lines (totals / handicaps)
#
# 2026-04-20 seed rules are max_edge sanity guards only. Data-driven tuning is
# deferred — see INVESTIGATE_LATER.md item 1.
BET_FILTERS = {
    "moneyline":     {"max_edge": 0.25},
    "game_handicap": {"max_edge": 0.20},
    "total_games":   {"max_edge": 0.18},
}

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
# Local player-data archive. Historical (2020-2024) from Sackmann snapshot,
# 2025+ appended daily by scrapers/sackmann_sync.py via api-tennis.
SACKMANN_LOCAL_DIR = os.path.join(DATA_DIR, "sackmann")
