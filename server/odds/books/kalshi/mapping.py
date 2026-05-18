from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


# Kalshi series_ticker → (our sport_key, our market_key). Only h2h ("game
# winner") for Phase 1; Phase 2 will add spread / total / team_total /
# period / NRFI / F5 series tickers (all carry their own series prefixes
# like KXMLBSPREAD, KXMLBTOTAL, etc.).
SERIES_TO_SPORT_MARKET: dict[str, tuple[str, str]] = {
    "KXMLBGAME":  ("mlb",  "h2h"),
    "KXNBAGAME":  ("nba",  "h2h"),
    "KXNHLGAME":  ("nhl",  "h2h"),
    "KXWNBAGAME": ("wnba", "h2h"),
}


# Kalshi market-ticker team-code suffix → canonical (Odds API) team name.
# Codes are standard ESPN-style abbreviations, scoped per-sport because the
# same 3-letter code can mean different teams across leagues (e.g. "LAA" is
# only MLB but conflicts are easier to audit when each sport's table is
# self-contained).
#
# Codes can be 2-4 chars (MLB has SD/KC/TB/SF/AZ; WNBA has CONN). The
# ticker suffix is whatever's after the LAST dash, so length is irrelevant
# to lookup — we just match the literal string.
#
# Probed live 2026-05-12:
#   MLB (30 codes), NBA (4 codes visible: CLE/NYK/OKC/SAS),
#   NHL (2 codes visible: COL/VGK), WNBA (6 codes visible).
# Tables below carry FULL standard rosters so off-season / pre-playoff
# markets normalize without re-probes.
TEAM_CODE_TO_CANONICAL: dict[str, dict[str, str]] = {
    "mlb": {
        # AL East
        "BAL": "Baltimore Orioles",
        "BOS": "Boston Red Sox",
        "NYY": "New York Yankees",
        "TB":  "Tampa Bay Rays",
        "TOR": "Toronto Blue Jays",
        # AL Central
        "CWS": "Chicago White Sox",
        "CLE": "Cleveland Guardians",
        "DET": "Detroit Tigers",
        "KC":  "Kansas City Royals",
        "MIN": "Minnesota Twins",
        # AL West
        "HOU": "Houston Astros",
        "LAA": "Los Angeles Angels",
        "ATH": "Athletics",
        "SEA": "Seattle Mariners",
        "TEX": "Texas Rangers",
        # NL East
        "ATL": "Atlanta Braves",
        "MIA": "Miami Marlins",
        "NYM": "New York Mets",
        "PHI": "Philadelphia Phillies",
        "WSH": "Washington Nationals",
        # NL Central
        "CHC": "Chicago Cubs",
        "CIN": "Cincinnati Reds",
        "MIL": "Milwaukee Brewers",
        "PIT": "Pittsburgh Pirates",
        "STL": "St Louis Cardinals",
        # NL West
        "AZ":  "Arizona Diamondbacks",
        "COL": "Colorado Rockies",
        "LAD": "Los Angeles Dodgers",
        "SD":  "San Diego Padres",
        "SF":  "San Francisco Giants",
    },
    "nba": {
        # Atlantic
        "BOS": "Boston Celtics",
        "BKN": "Brooklyn Nets",
        "NYK": "New York Knicks",
        "PHI": "Philadelphia 76ers",
        "TOR": "Toronto Raptors",
        # Central
        "CHI": "Chicago Bulls",
        "CLE": "Cleveland Cavaliers",
        "DET": "Detroit Pistons",
        "IND": "Indiana Pacers",
        "MIL": "Milwaukee Bucks",
        # Southeast
        "ATL": "Atlanta Hawks",
        "CHA": "Charlotte Hornets",
        "MIA": "Miami Heat",
        "ORL": "Orlando Magic",
        "WAS": "Washington Wizards",
        # Northwest
        "DEN": "Denver Nuggets",
        "MIN": "Minnesota Timberwolves",
        "OKC": "Oklahoma City Thunder",
        "POR": "Portland Trail Blazers",
        "UTA": "Utah Jazz",
        # Pacific
        "GSW": "Golden State Warriors",
        "LAC": "Los Angeles Clippers",
        "LAL": "Los Angeles Lakers",
        "PHX": "Phoenix Suns",
        "SAC": "Sacramento Kings",
        # Southwest
        "DAL": "Dallas Mavericks",
        "HOU": "Houston Rockets",
        "MEM": "Memphis Grizzlies",
        "NOP": "New Orleans Pelicans",
        "SAS": "San Antonio Spurs",
    },
    "nhl": {
        # Eastern - Atlantic
        "BOS": "Boston Bruins",
        "BUF": "Buffalo Sabres",
        "DET": "Detroit Red Wings",
        "FLA": "Florida Panthers",
        "MTL": "Montréal Canadiens",
        "OTT": "Ottawa Senators",
        "TBL": "Tampa Bay Lightning",
        "TOR": "Toronto Maple Leafs",
        # Eastern - Metropolitan
        "CAR": "Carolina Hurricanes",
        "CBJ": "Columbus Blue Jackets",
        "NJD": "New Jersey Devils",
        "NYI": "New York Islanders",
        "NYR": "New York Rangers",
        "PHI": "Philadelphia Flyers",
        "PIT": "Pittsburgh Penguins",
        "WSH": "Washington Capitals",
        # Western - Central
        "CHI": "Chicago Blackhawks",
        "COL": "Colorado Avalanche",
        "DAL": "Dallas Stars",
        "MIN": "Minnesota Wild",
        "NSH": "Nashville Predators",
        "STL": "St Louis Blues",
        "UTA": "Utah Mammoth",
        "WPG": "Winnipeg Jets",
        # Western - Pacific
        "ANA": "Anaheim Ducks",
        "CGY": "Calgary Flames",
        "EDM": "Edmonton Oilers",
        "LAK": "Los Angeles Kings",
        "SJS": "San Jose Sharks",
        "SEA": "Seattle Kraken",
        "VAN": "Vancouver Canucks",
        "VGK": "Vegas Golden Knights",
    },
    "wnba": {
        # Eastern Conference
        "ATL":  "Atlanta Dream",
        "CHI":  "Chicago Sky",
        "CONN": "Connecticut Sun",   # 4-char Kalshi code
        "IND":  "Indiana Fever",
        "NYL":  "New York Liberty",
        "WSH":  "Washington Mystics",
        "TOR":  "Toronto Tempo",
        # Western Conference
        "DAL":  "Dallas Wings",
        "GV":   "Golden State Valkyries",
        "LVA":  "Las Vegas Aces",
        "LA":   "Los Angeles Sparks",
        "MIN":  "Minnesota Lynx",
        "PHX":  "Phoenix Mercury",
        "PDX":  "Portland Fire",
        "SEA":  "Seattle Storm",
    },
}


@dataclass
class KalshiSportConfig:
    """One sport block in kalshi.toml. Phase 1 only uses `series_main`; the
    other slots are stubbed so Phase 2 can extend without re-shaping the
    config schema."""
    sport_key: str
    series_main: list[str] = field(default_factory=list)
    series_spread: list[str] = field(default_factory=list)
    series_total: list[str] = field(default_factory=list)
    series_team_total: list[str] = field(default_factory=list)
    series_period: list[str] = field(default_factory=list)
    series_rfi: list[str] = field(default_factory=list)


@dataclass
class KalshiConfig:
    sports: dict[str, KalshiSportConfig]              # keyed by sport_key
    team_aliases: dict[str, dict[str, str]]           # {sport_key: {norm: canon}}


def load_kalshi_config(path: Path) -> KalshiConfig:
    """Load server/config/kalshi.toml. Missing sections default to empty —
    we want the fetcher to start cleanly even on a half-configured deploy."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    sports: dict[str, KalshiSportConfig] = {}
    for key, cfg in (raw.get("sports") or {}).items():
        sports[key] = KalshiSportConfig(
            sport_key=key,
            series_main=list(cfg.get("series_main") or []),
            series_spread=list(cfg.get("series_spread") or []),
            series_total=list(cfg.get("series_total") or []),
            series_team_total=list(cfg.get("series_team_total") or []),
            series_period=list(cfg.get("series_period") or []),
            series_rfi=list(cfg.get("series_rfi") or []),
        )
    aliases_raw = raw.get("team_aliases") or {}
    team_aliases: dict[str, dict[str, str]] = {}
    for sport, table in aliases_raw.items():
        team_aliases[sport] = {k: v for k, v in table.items()}
    return KalshiConfig(sports=sports, team_aliases=team_aliases)
