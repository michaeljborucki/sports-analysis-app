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
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "")
CRICKET_API_KEY = os.getenv("CRICKET_API_KEY", "")

# API base URLs
CRICKET_API_BASE = "https://api.cricapi.com/v1"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
WEATHER_API_BASE = "https://api.openweathermap.org/data/2.5"

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCREEN_EDGE_THRESHOLD = 0.03  # 3% edge to trigger full MiroFish sim
GAME_TIMEOUT = 300  # 5 min max per game (screen or full sim)

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing — use eighth-Kelly for T20 volatility
KELLY_FRACTION = 0.125

# Bet type configuration — engines, multipliers, thresholds
BET_TYPES = {
    # Tier 1 — Core Markets (6% threshold)
    "moneyline": {
        "engine": "direct",
        "threshold": 0.06,
        "tier": 1,
    },
    "match_total_runs": {
        "engine": "linear",
        "std_dev": 60,
        "multiplier": 0.008,
        "threshold": 0.06,
        "tier": 1,
    },
    "team_total_runs": {
        "engine": "linear",
        "std_dev": 30,
        "multiplier": 0.017,
        "threshold": 0.06,
        "tier": 1,
    },
    "spread": {
        "engine": "linear",
        "std_dev": 20,
        "multiplier": 0.025,
        "threshold": 0.06,
        "tier": 1,
    },
    "team_total_chase": {
        "engine": "bimodal_chase",
        "threshold": 0.06,
        "tier": 1,
    },
    # Tier 2 — Player Props (5% threshold)
    "player_runs": {
        "engine": "exponential",
        "threshold": 0.05,
        "tier": 2,
    },
    "player_wickets": {
        "engine": "poisson",
        "overdispersion": 1.20,  # Variance/mean ratio for T20 bowling wickets
        "threshold": 0.05,
        "tier": 2,
    },
    "player_boundaries": {
        "engine": "poisson",
        "overdispersion": 1.25,  # Correlation with runs creates extra variance
        "threshold": 0.05,
        "tier": 2,
    },
    "player_sixes": {
        "engine": "poisson",
        "overdispersion": 1.35,  # Venue/matchup creates high extra variance
        "threshold": 0.05,
        "tier": 2,
    },
    # Tier 3 — Phase & Specialty (4% threshold)
    "powerplay_runs": {
        "engine": "linear",
        "std_dev": 16,
        "multiplier": 0.031,
        "threshold": 0.04,
        "tier": 3,
    },
    "match_total_sixes": {
        "engine": "linear",
        "std_dev": 6,
        "multiplier": 0.083,
        "threshold": 0.04,
        "tier": 3,
    },
    "match_total_fours": {
        "engine": "linear",
        "std_dev": 6,
        "multiplier": 0.083,
        "threshold": 0.04,
        "tier": 3,
    },
    "first_over_runs": {
        "engine": "linear",
        "std_dev": 4,
        "multiplier": 0.125,
        "threshold": 0.04,
        "tier": 3,
    },
    "fall_of_first_wicket": {
        "engine": "exponential",
        "threshold": 0.04,
        "tier": 3,
    },
    # Tier 4 — Bowling Props (5% threshold)
    "runs_conceded": {
        "engine": "linear",
        "std_dev": 11,
        "multiplier": 0.045,
        "threshold": 0.05,
        "tier": 4,
    },
    "dot_balls": {
        "engine": "linear",
        "std_dev": 3.5,
        "multiplier": 0.143,
        "threshold": 0.05,
        "tier": 4,
    },
}

ACTIVE_TIERS = [1, 2, 3, 4]

# Maps LLM prediction keys to BET_TYPES keys (where they differ)
PREDICTION_KEY_MAP = {"total_runs": "match_total_runs"}

# Legacy aliases for backward compatibility during migration
EDGE_THRESHOLDS = {k: v["threshold"] for k, v in BET_TYPES.items()}
EDGE_THRESHOLDS["total_runs"] = EDGE_THRESHOLDS["match_total_runs"]  # old key alias
BET_SLOTS = list(BET_TYPES.keys())

# T20 cricket leagues and team abbreviations
LEAGUES = {
    "ipl": {
        "name": "Indian Premier League",
        "teams": ["CSK", "MI", "RCB", "KKR", "DC", "PBKS", "RR", "SRH", "GT", "LSG"],
        "odds_key": "cricket_ipl",
        "season": "Mar-May",
        "team_names": {
            "Chennai Super Kings": "CSK", "Mumbai Indians": "MI",
            "Royal Challengers Bengaluru": "RCB", "Kolkata Knight Riders": "KKR",
            "Delhi Capitals": "DC", "Punjab Kings": "PBKS",
            "Rajasthan Royals": "RR", "Sunrisers Hyderabad": "SRH",
            "Gujarat Titans": "GT", "Lucknow Super Giants": "LSG",
        },
    },
    "bbl": {
        "name": "Big Bash League",
        "teams": ["ADS", "BBH", "HBH", "MLS", "MRS", "PST", "SSX", "SST"],
        "odds_key": "cricket_big_bash_league",
        "season": "Dec-Jan",
        "team_names": {
            "Adelaide Strikers": "ADS", "Brisbane Heat": "BBH",
            "Hobart Hurricanes": "HBH", "Melbourne Stars": "MLS",
            "Melbourne Renegades": "MRS", "Perth Scorchers": "PST",
            "Sydney Sixers": "SSX", "Sydney Thunder": "SST",
        },
    },
    "cpl": {
        "name": "Caribbean Premier League",
        "teams": ["TKR", "GAW", "BT", "SNP", "SLK", "JAM"],
        "odds_key": "cricket_caribbean_premier_league",
        "season": "Aug-Sep",
        "team_names": {
            "Trinbago Knight Riders": "TKR", "Guyana Amazon Warriors": "GAW",
            "Barbados Tridents": "BT", "St Kitts and Nevis Patriots": "SNP",
            "Saint Lucia Kings": "SLK", "Jamaica Tallawahs": "JAM",
        },
    },
    "psl": {
        "name": "Pakistan Super League",
        "teams": ["IU", "KK", "LQ", "MS", "PZ", "QG"],
        "odds_key": "cricket_psl",
        "season": "Feb-Mar",
        "team_names": {
            "Islamabad United": "IU", "Karachi Kings": "KK",
            "Lahore Qalandars": "LQ", "Multan Sultans": "MS",
            "Peshawar Zalmi": "PZ", "Quetta Gladiators": "QG",
        },
    },
    "hundred": {
        "name": "The Hundred",
        "teams": ["BPH", "LNS", "MO", "NOS", "OI", "SB", "TF", "WF"],
        "odds_key": "cricket_the_hundred",
        "season": "Jul-Aug",
        "team_names": {
            "Birmingham Phoenix": "BPH", "London Spirit": "LNS",
            "Manchester Originals": "MO", "Northern Superchargers": "NOS",
            "Oval Invincibles": "OI", "Southern Brave": "SB",
            "Trent Rockets": "TF", "Welsh Fire": "WF",
        },
    },
    "sa20": {
        "name": "SA20",
        "teams": ["DSG", "JBG", "MI-CT", "PR", "SEC", "SUN"],
        "odds_key": "cricket_sa20",
        "season": "Jan-Feb",
        "team_names": {
            "Durban Super Giants": "DSG", "Joburg Super Kings": "JBG",
            "MI Cape Town": "MI-CT", "Paarl Royals": "PR",
            "Sunrisers Eastern Cape": "SEC", "Pretoria Capitals": "SUN",
        },
    },
    "bpl": {
        "name": "Bangladesh Premier League",
        "teams": ["CV", "CK", "DB", "FBD", "KT", "RR", "SYS"],
        "odds_key": "cricket_bpl",
        "season": "Jan-Feb",
        "team_names": {
            "Comilla Victorians": "CV", "Chittagong Kings": "CK",
            "Dhaka Dominators": "DB", "Fortune Barishal": "FBD",
            "Khulna Tigers": "KT", "Rangpur Riders": "RR",
            "Sylhet Strikers": "SYS",
        },
    },
    "ilt20": {
        "name": "International League T20",
        "teams": ["ADK", "DBC", "DES", "GUL", "MIE", "SHJ"],
        "odds_key": "cricket_ilt20",
        "season": "Jan-Feb",
        "team_names": {
            "Abu Dhabi Knight Riders": "ADK", "Dubai Capitals": "DBC",
            "Desert Vipers": "DES", "Gulf Giants": "GUL",
            "MI Emirates": "MIE", "Sharjah Warriors": "SHJ",
        },
    },
}

# Flattened team name/abbreviation mapping across all leagues
TEAM_NAME_TO_ABBREV = {}
for league_cfg in LEAGUES.values():
    TEAM_NAME_TO_ABBREV.update(league_cfg["team_names"])

# Venue coordinates for weather lookups (major T20 venues)
VENUE_COORDS = {
    # IPL venues
    "Wankhede Stadium": (18.9389, 72.8258),
    "M. A. Chidambaram Stadium": (13.0627, 80.2792),
    "Eden Gardens": (22.5646, 88.3433),
    "M. Chinnaswamy Stadium": (12.9788, 77.5996),
    "Arun Jaitley Stadium": (28.6377, 77.2433),
    "Rajiv Gandhi Intl Cricket Stadium": (17.4065, 78.5507),
    "Sawai Mansingh Stadium": (26.8933, 75.8064),
    "Punjab Cricket Association Stadium": (30.6928, 76.7370),
    "Narendra Modi Stadium": (23.0916, 72.5970),
    "Ekana Cricket Stadium": (26.9467, 80.9462),
    # BBL venues
    "Adelaide Oval": (-34.9156, 138.5962),
    "The Gabba": (-27.4858, 153.0381),
    "Bellerive Oval": (-42.8776, 147.3737),
    "Melbourne Cricket Ground": (-37.8200, 144.9834),
    "Marvel Stadium": (-37.8165, 144.9475),
    "Perth Stadium": (-31.9512, 115.8891),
    "Sydney Cricket Ground": (-33.8916, 151.2247),
    "Sydney Showground Stadium": (-33.8448, 151.0674),
    # CPL venues
    "Queen's Park Oval": (10.6741, -61.5153),
    "Providence Stadium": (6.8074, -58.1539),
    "Kensington Oval": (13.1050, -59.6250),
    "Warner Park": (17.3000, -62.7167),
    "Daren Sammy Cricket Ground": (14.0680, -60.9479),
    "Sabina Park": (18.0056, -76.7464),
    # PSL venues
    "National Stadium Karachi": (24.8922, 67.0653),
    "Gaddafi Stadium": (31.5135, 74.3399),
    "Multan Cricket Stadium": (30.1984, 71.4542),
    "Rawalpindi Cricket Stadium": (33.5981, 73.0562),
    "Arbab Niaz Stadium": (34.0123, 71.5785),
    # The Hundred venues
    "Edgbaston": (52.4556, -1.9025),
    "Lord's": (51.5294, -0.1727),
    "Old Trafford": (53.4569, -2.2873),
    "Headingley": (53.8178, -1.5822),
    "The Oval": (51.4838, -0.1147),
    "The Ageas Bowl": (50.9242, -1.3213),
    "Trent Bridge": (52.9369, -1.1322),
    "Sophia Gardens": (51.4750, -3.1819),
    # SA20 venues
    "Kingsmead": (-29.8560, 31.0275),
    "The Wanderers": (-26.1335, 28.0605),
    "Newlands": (-33.9273, 18.4575),
    "Boland Park": (-33.7525, 18.9659),
    "St George's Park": (-33.9638, 25.6006),
    "SuperSport Park": (-25.7500, 28.2050),
}

# Cricsheet data directory
CRICSHEET_DATA_DIR = "data/cricsheet"

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
