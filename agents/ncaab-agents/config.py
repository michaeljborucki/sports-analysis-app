import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Logging configuration — set LOG_LEVEL env var to DEBUG for verbose output
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# API keys
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
CBBDATA_API_KEY = os.getenv("CBBDATA_API_KEY", "")

# API base URLs
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ESPN_CBB_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
TORVIK_BASE = "https://barttorvik.com"
CBBDATA_BASE = "https://www.cbbdata.com/api"

# Odds API sport key
ODDS_SPORT_KEY = "basketball_ncaab"

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCREEN_EDGE_THRESHOLD = 0.03  # 3% edge to trigger full MiroFish sim
GAME_TIMEOUT = 300  # 5 min max per game (screen or full sim)

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick", "stat_anchor"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing — use quarter-Kelly for safety
KELLY_FRACTION = 0.25

# Maximum American odds for moneyline bets — blocks phantom edges on heavy underdogs
MAX_ML_ODDS = 200

# Edge thresholds per bet type (minimum edge to signal a bet)
EDGE_THRESHOLDS = {
    "moneyline": 0.10,
    "spread": 0.05,
    "total": 0.12,
    "first_half_ml": 0.07,
    "first_half_spread": 0.07,
    "first_half_total": 0.12,
}

# Sport slot registry — canonical list of bet types this pipeline supports
BET_SLOTS = ["moneyline", "spread", "total", "first_half_ml", "first_half_spread", "first_half_total"]

# Home-court advantage (points)
HOME_COURT_ADVANTAGE = 3.5

# Conference tiers
POWER_CONFERENCES = ["SEC", "B10", "B12", "ACC", "BE"]
MID_MAJOR_CONFERENCES = ["A10", "MWC", "WCC", "MVC", "Amer", "CUSA", "SB", "MAC"]

# All 32 Division I conferences
ALL_CONFERENCES = [
    "SEC", "B10", "B12", "ACC", "BE",          # Power conferences
    "A10", "MWC", "WCC", "MVC", "Amer",        # Mid-majors
    "CUSA", "SB", "MAC",                        # Mid-majors (cont.)
    "SC", "BSky", "BSth", "CAA", "Horz",       # One-bid leagues
    "Ivy", "MAAC", "MEAC", "NEC", "OVC",
    "Pat", "SLC", "Sum", "SWAC", "WAC",
    "WCar", "AE", "ASun", "BW",
]

# Season date boundaries
SEASON_START_MONTH = 11
SEASON_END_MONTH = 4

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
PREDICTIONS_CSV = os.path.join(DATA_DIR, "predictions.csv")
