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

# API base URLs
MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
WEATHER_API_BASE = "https://api.openweathermap.org/data/2.5"

# Shared live-odds feed (the betting-site backend's cache). When
# ODDS_FEED_BASE_URL is set, live odds are pulled from the backend's shared
# database (GET /api/odds/{sport}/raw) instead of hitting The Odds API
# directly, so the agent and the betting site reuse one live-odds source
# rather than each paying for the same games. Leave empty to keep hitting the
# Odds API directly. Any feed failure (backend down, sport not configured)
# transparently falls back to the Odds API; historical odds always use the API.
ODDS_FEED_BASE_URL = os.getenv("ODDS_FEED_BASE_URL", "").strip().rstrip("/")
ODDS_FEED_SPORT = os.getenv("ODDS_FEED_SPORT", "mlb").strip()
ODDS_FEED_TTL_SECONDS = int(os.getenv("ODDS_FEED_TTL_SECONDS", "20"))
# If the backend's odds are older than this (its fetcher stalled, or the cache
# is in snapshot/latest mode), ignore the feed and fall back to the live Odds
# API. Keep it above the backend's poll interval so normal jitter doesn't trip
# it; set to 0 to disable the staleness guard. Default 15 min.
ODDS_FEED_MAX_STALE_SECONDS = int(os.getenv("ODDS_FEED_MAX_STALE_SECONDS", "900"))

# Simulation
KIMI_MODEL = "moonshotai/kimi-k2.5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
SCREEN_EDGE_THRESHOLD = 0.03  # 3% edge to trigger full MiroFish sim
GAME_TIMEOUT = 300  # 5 min max per game (screen or full sim)
PARALLEL_GAMES = 4  # max games processed concurrently (screen + sim)

# Ensemble configuration
ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
# Challenger upgraded 2026-05-07 from claude (Sonnet 4) → claude_opus (Opus 4.7).
# Sonnet stays on panel for diversity; Opus does the dedicated challenger pass.
ENSEMBLE_CHALLENGER = "claude_opus"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50

# Kelly sizing — use quarter-Kelly for safety
KELLY_FRACTION = 0.25

# Edge thresholds per bet type (minimum edge to signal a bet)
EDGE_THRESHOLDS = {
    # ML lowered 0.05 → 0.03 (2026-04-28): the sharpest MLB market with
    # smallest real edges. Pairs with the brief's raised ML confidence cap
    # (80% on lopsided matchups vs 70% elsewhere).
    "moneyline": 0.03,
    # Run line lowered 0.06 → 0.05 (2026-04-28): historical ROI +17.8% on
    # this bet type, lowering the bar lets more legitimate edges through.
    "run_line": 0.05,
    "total": 0.05,
    "first_5_ml": 0.05,
    "first_5_total": 0.05,
    # Phase 1: game-level expansion
    "team_total_home": 0.05,
    "team_total_away": 0.05,
    "first_5_rl": 0.05,
    "nrfi": 0.06,
    "first_1_rl": 0.06,
    "first_3_ml": 0.05,
    "first_3_total": 0.05,
    "first_3_rl": 0.05,
    # Phase 2: player props
    "pitcher_strikeouts": 0.05,
    "pitcher_earned_runs": 0.05,
    "pitcher_outs": 0.05,
    "pitcher_hits_allowed": 0.05,
    "batter_total_bases": 0.05,
    "batter_rbis": 0.05,
    "batter_hits": 0.05,
    "batter_runs_scored": 0.05,
    "batter_hits_runs_rbis": 0.05,
    "batter_strikeouts": 0.05,
}

# Per-bet-type filters applied AFTER edge detection, BEFORE logging.
#
# NOTE (2026-04-24): With the isotonic calibration layer in place, filters that
# were compensating for overconfidence (min_edge, max_edge) are now redundant —
# the calibrator shrinks raw probabilities to empirical win rates per
# (bet_type, side) before edge is computed. We only keep filters that address
# issues calibration cannot fix:
#   - `disabled`: model has no predictive signal on this bet type
#   - `line_in`: market-side skew at specific line values
#
# Supported keys per bet type:
#   disabled: bool        — if True, drop all bets of this type
#   min_edge: float       — drop bets with edge < min_edge
#   max_edge: float       — drop bets with edge >= max_edge
#   side_contains: list   — drop bets unless side string contains one of these
#   line_in: list[float]  — drop bets unless the numeric line in the side is in this list
#   odds_min: int         — drop bets with odds < odds_min
#   odds_max: int         — drop bets with odds > odds_max
# Lower bound for the "Season Totals" Discord summary. Bets before this
# date are excluded from the rolling record because the model architecture
# has gone through enough changes (TTOP, platoon, weather, regression tune)
# that older results no longer describe the system in production. Reset on
# 2026-05-17 after grading the recent fine-tuning window.
SEASON_RECORD_START_DATE = "2026-05-10"


BET_FILTERS: dict[str, dict] = {
    # first_3_* re-disabled 2026-05-19 after one graded slate.
    # 2026-05-18 results:
    #   first_3_rl    3-11 (21.4%, -22.1% ROI on 14 picks)
    #   first_3_total 2-4  (33.3%, -42.0% ROI on 6 picks)
    #   first_3_ml    not picked in the day's sample.
    # Model over-predicts early scoring on home favorites. The picks averaged
    # +250 odds (need ~29% to break even) but only 21% hit. Re-disable while
    # we investigate the root cause (likely an ensemble-level bias on first-3
    # PA rates vs full-game distributions).
    "first_3_rl":    {"disabled": True},
    "first_3_total": {"disabled": True},
    "first_3_ml":    {"disabled": True},

    # Other filters cleared 2026-05-17 — operator preference is to see every
    # bet-type result against the latest model params (TTOP, platoon,
    # PITCHER_REGRESS_BF=50) and fix underlying issues instead of blanket-
    # hiding them. The filter mechanism stays in place; reintroduce
    # entries here when a specific bet type / line bucket needs scoping.
}

# All 30 MLB team abbreviations
TEAM_ABBREVS = [
    "ARI", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE",
    "COL", "DET", "HOU", "KC", "LAA", "LAD", "MIA", "MIL",
    "MIN", "NYM", "NYY", "OAK", "PHI", "PIT", "SD", "SF",
    "SEA", "STL", "TB", "TEX", "TOR", "WSH",
]

# Team full name to abbreviation mapping
TEAM_NAME_TO_ABBREV = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS",
    "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET",
    "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL",
    "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK", "Athletics": "OAK",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT",
    "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB", "Texas Rangers": "TEX",
    "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

# Park factors: keyed by team abbreviation
# runs/hr are multipliers vs league average (1.00 = neutral).
#
# Recalibrated 2026-04-21 against Baseball Savant + public consensus:
# observed systemic under-bias in total predictions was driven in part by
# pitcher-park factors set too low (esp. SF 0.85, MIA/OAK/SEA/SD all 0.90,
# all below public consensus of ~0.93-0.96) and hitter-park factors too
# high (CIN 1.15, PHI 1.10). See docs/superpowers/plans/2026-04-21-
# totals-recalibration.md for methodology.
PARK_FACTORS = {
    "ARI": {"name": "Chase Field", "runs": 1.05, "hr": 1.05, "roof": "retractable"},
    "ATL": {"name": "Truist Park", "runs": 1.00, "hr": 1.05, "roof": "open"},
    "BAL": {"name": "Camden Yards", "runs": 1.05, "hr": 1.10, "roof": "open"},
    "BOS": {"name": "Fenway Park", "runs": 1.08, "hr": 0.95, "roof": "open"},
    "CHC": {"name": "Wrigley Field", "runs": 1.05, "hr": 1.05, "roof": "open"},
    "CWS": {"name": "Guaranteed Rate Field", "runs": 1.05, "hr": 1.10, "roof": "open"},
    "CIN": {"name": "Great American Ball Park", "runs": 1.08, "hr": 1.18, "roof": "open"},
    "CLE": {"name": "Progressive Field", "runs": 0.96, "hr": 0.95, "roof": "open"},
    "COL": {"name": "Coors Field", "runs": 1.30, "hr": 1.25, "roof": "open"},
    "DET": {"name": "Comerica Park", "runs": 0.96, "hr": 0.92, "roof": "open"},
    "HOU": {"name": "Minute Maid Park", "runs": 1.05, "hr": 1.10, "roof": "retractable"},
    "KC": {"name": "Kauffman Stadium", "runs": 1.01, "hr": 0.95, "roof": "open"},
    "LAA": {"name": "Angel Stadium", "runs": 0.97, "hr": 1.00, "roof": "open"},
    "LAD": {"name": "Dodger Stadium", "runs": 0.98, "hr": 0.97, "roof": "open"},
    "MIA": {"name": "loanDepot Park", "runs": 0.95, "hr": 0.90, "roof": "retractable"},
    "MIL": {"name": "American Family Field", "runs": 1.05, "hr": 1.10, "roof": "retractable"},
    "MIN": {"name": "Target Field", "runs": 1.00, "hr": 1.00, "roof": "open"},
    "NYM": {"name": "Citi Field", "runs": 0.96, "hr": 0.95, "roof": "open"},
    "NYY": {"name": "Yankee Stadium", "runs": 1.03, "hr": 1.12, "roof": "open"},
    "OAK": {"name": "Oakland Coliseum", "runs": 0.95, "hr": 0.90, "roof": "open"},
    "PHI": {"name": "Citizens Bank Park", "runs": 1.06, "hr": 1.10, "roof": "open"},
    "PIT": {"name": "PNC Park", "runs": 0.96, "hr": 0.92, "roof": "open"},
    "SD": {"name": "Petco Park", "runs": 0.95, "hr": 0.93, "roof": "open"},
    "SF": {"name": "Oracle Park", "runs": 0.93, "hr": 0.88, "roof": "open"},
    "SEA": {"name": "T-Mobile Park", "runs": 0.95, "hr": 0.92, "roof": "retractable"},
    "STL": {"name": "Busch Stadium", "runs": 0.97, "hr": 0.95, "roof": "open"},
    "TB": {"name": "Tropicana Field", "runs": 0.97, "hr": 0.95, "roof": "dome"},
    "TEX": {"name": "Globe Life Field", "runs": 1.02, "hr": 1.05, "roof": "retractable"},
    "TOR": {"name": "Rogers Centre", "runs": 1.03, "hr": 1.08, "roof": "retractable"},
    "WSH": {"name": "Nationals Park", "runs": 1.00, "hr": 1.05, "roof": "open"},
}

# Removed 2026-05-04: TOTAL_UNDER_BIAS_CORRECTION = 0.06
# Originally added 2026-04-21 to shift `total` probabilities UNDER → OVER
# after a 107-bet sample showed systemic under-bias. After the MC tune
# (advance-prob recalibration) and per-side isotonic calibration shipped,
# the +0.06 constant was no longer flipping side calls (still ~92% unders
# post-correction) and created double-correction risk with the calibrator.
# Bias is now handled at the MC + calibration layers, not post-LLM.
#
# Removed 2026-05-04: TEAM_TOTAL_HOME_OVER_BIAS_CORRECTION = 0.06
# Same reasoning — the home-only correction was producing 100% LOCK
# home-under picks at hitters' parks (Coors, etc.) by stacking on already-
# low MC distributions. Park effects influence both teams equally; any
# future correction must be symmetric, not home-only.

# Ballpark coordinates for weather lookups
PARK_COORDS = {
    "ARI": (33.4455, -112.0667), "ATL": (33.8907, -84.4677),
    "BAL": (39.2838, -76.6218), "BOS": (42.3467, -71.0972),
    "CHC": (41.9484, -87.6553), "CWS": (41.8299, -87.6338),
    "CIN": (39.0974, -84.5082), "CLE": (41.4962, -81.6852),
    "COL": (39.7559, -104.9942), "DET": (42.3390, -83.0485),
    "HOU": (29.7573, -95.3555), "KC": (39.0517, -94.4803),
    "LAA": (33.8003, -117.8827), "LAD": (34.0739, -118.2400),
    "MIA": (25.7781, -80.2196), "MIL": (43.0280, -87.9712),
    "MIN": (44.9818, -93.2775), "NYM": (40.7571, -73.8458),
    "NYY": (40.8296, -73.9262), "OAK": (37.7516, -122.2005),
    "PHI": (39.9061, -75.1665), "PIT": (40.4469, -80.0057),
    "SD": (32.7076, -117.1570), "SF": (37.7786, -122.3893),
    "SEA": (47.5914, -122.3325), "STL": (38.6226, -90.1928),
    "TB": (27.7682, -82.6534), "TEX": (32.7512, -97.0832),
    "TOR": (43.6414, -79.3894), "WSH": (38.8730, -77.0074),
}

# Data directory
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
BETS_CSV = os.path.join(DATA_DIR, "bets.csv")
MODEL_WEIGHTS_FILE = os.path.join(DATA_DIR, "model_weights.json")
MODEL_PREDICTIONS_CSV = os.path.join(DATA_DIR, "model_predictions.csv")
