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
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
ODDS_SPORT_KEY = "basketball_nba"
ODDS_EVENT_ENDPOINT = f"https://api.the-odds-api.com/v4/sports/{ODDS_SPORT_KEY}/events"
ODDS_EVENT_MARKETS = (
    "h2h_h2,spreads_h2,totals_h2,"
    "h2h_q1,spreads_q1,totals_q1,"
    "totals_q2,totals_q3,totals_q4,"
    "team_totals,"
    "alternate_spreads,alternate_totals,"
    "player_points,player_rebounds,player_assists,player_threes,player_points_rebounds_assists"
)

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCREEN_EDGE_THRESHOLD = 0.03
GAME_TIMEOUT = 300

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
PROP_ENSEMBLE_MODELS = ["kimi", "gemini", "maverick"]
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing
KELLY_FRACTION = 0.25

# Edge thresholds per bet type
EDGE_THRESHOLDS = {
    "moneyline": 0.05, "spread": 0.06, "total": 0.05,
    "first_half_ml": 0.05, "first_half_total": 0.05, "first_half_spread": 0.05,
    "q1_ml": 0.04, "q1_spread": 0.05, "q1_total": 0.04,
    "q2_total": 0.05, "q3_total": 0.05, "q4_total": 0.05,
    "team_total_home": 0.04, "team_total_away": 0.04,
    "player_points": 0.04, "player_rebounds": 0.04, "player_assists": 0.04,
    "player_threes": 0.04, "player_pra": 0.04,
}

ODDS_EVENT_ENDPOINT = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/events"
ODDS_EVENT_MARKETS = (
    "h2h_h1,spreads_h1,totals_h1,"
    "h2h_h2,spreads_h2,totals_h2,"
    "h2h_q1,spreads_q1,totals_q1,"
    "totals_q2,totals_q3,totals_q4,"
    "team_totals,"
    "alternate_spreads,alternate_totals,"
    "player_points,player_rebounds,player_assists,"
    "player_threes,player_points_rebounds_assists"
)

PROP_ENSEMBLE_MODELS = ["kimi", "gpt4o", "deepseek"]
MAX_CONCURRENT_GAMES = 6
MAX_CONCURRENT_API_CALLS = 5
Q3_SCORING_SHARE = 0.52
Q4_SCORING_SHARE = 0.48

GAME_BET_SLOTS = [
    "moneyline", "spread", "total",
    "first_half_ml", "first_half_total", "first_half_spread",
    "q1_ml", "q1_spread", "q1_total",
    "q2_total", "q3_total", "q4_total",
    "team_total_home", "team_total_away",
]
DERIVED_SLOTS = {"q2_total", "q3_total", "q4_total"}
PROP_BET_SLOTS = [
    "player_points", "player_rebounds", "player_assists",
    "player_threes", "player_pra",
]

# Home court advantage (approximate points)
HOME_COURT_ADVANTAGE = 3.0

# All 30 NBA team abbreviations
TEAM_ABBREVS = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN",
    "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM", "MIA",
    "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX",
    "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]

# Team full name to abbreviation mapping (covers Odds API + nba_api names)
TEAM_NAME_TO_ABBREV = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS",
    "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GSW",
    "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "LA Clippers": "LAC",
    "Los Angeles Lakers": "LAL", "LA Lakers": "LAL",
    "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK",
    "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL",
    "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC",
    "San Antonio Spurs": "SAS", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def nba_season(game_date: str) -> str:
    """Convert date string to NBA season format.

    nba_api expects seasons like '2025-26'.
    NBA season starts in October, so dates Oct-Dec belong to the current year's season,
    and dates Jan-Sep belong to the previous year's season.

    Example: '2026-03-22' -> '2025-26', '2025-10-15' -> '2025-26'
    """
    year = int(game_date[:4])
    month = int(game_date[5:7])
    if month >= 10:
        return f"{year}-{str(year + 1)[-2:]}"
    return f"{year - 1}-{str(year)[-2:]}"


# Quarter scoring share for H2 split (Q3 typically scores more than Q4)
Q3_SCORING_SHARE = 0.52
Q4_SCORING_SHARE = 0.48

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
