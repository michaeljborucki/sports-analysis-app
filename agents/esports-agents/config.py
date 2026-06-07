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
ODDSPAPI_API_KEY = os.getenv("ODDSPAPI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# API base URLs
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDSPAPI_BASE = "https://api.oddspapi.com/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
SCREEN_EDGE_THRESHOLD = 0.03  # 3% edge to trigger full MiroFish sim
GAME_TIMEOUT = 180  # 3 min max per game (screen or full sim)

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing — use quarter-Kelly for safety
KELLY_FRACTION = 0.25

# Esports configuration
SUPPORTED_GAMES = ["cs2", "lol"]
MAX_TIER = 2

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
