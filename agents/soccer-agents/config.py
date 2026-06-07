import logging
import os
from dotenv import load_dotenv

load_dotenv()

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
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")

# API base URLs
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
WEATHER_API_BASE = "https://api.openweathermap.org/data/2.5"
ESPN_API_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCREEN_EDGE_THRESHOLD = 0.03
GAME_TIMEOUT = 180

# Number of matches to screen/simulate concurrently. Each thread is one
# ThreadPoolExecutor worker; the ensemble itself also fans out to 6 LLM models
# per match, so total concurrency = PARALLEL_GAMES * 6 OpenRouter calls in
# flight at once. Raise cautiously — OpenRouter rate limits are per-key.
PARALLEL_GAMES = 5

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing — eighth-Kelly for soccer (low scoring = high variance)
KELLY_FRACTION = 0.125

# Bet types for soccer
BET_SLOTS = ["asian_handicap", "total", "btts"]

# Edge thresholds per bet type
EDGE_THRESHOLDS = {
    "asian_handicap": 0.05,
    "total": 0.05,
    "btts": 0.06,
}

# Supported leagues and their Odds API sport keys
SUPPORTED_LEAGUES = {
    "MLS": "soccer_usa_mls",
    "Eredivisie": "soccer_netherlands_eredivisie",
    "Serie A": "soccer_italy_serie_a",
    "Bundesliga": "soccer_germany_bundesliga",
    "La Liga": "soccer_spain_la_liga",
    "EPL": "soccer_epl",
    "Ligue 1": "soccer_france_ligue_one",
}

ACTIVE_LEAGUES = ["MLS", "Eredivisie", "Serie A", "EPL"]

HOME_ADVANTAGE_BY_LEAGUE = {
    "MLS": 0.08,
    "Eredivisie": 0.10,
    "Serie A": 0.12,
    "EPL": 0.08,
    "Bundesliga": 0.10,
    "La Liga": 0.10,
    "Ligue 1": 0.10,
}

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
