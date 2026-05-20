"""Polymarket sport/team mapping + config loader.

Slug team codes (the `<a>` and `<b>` segments of `nba-sas-okc-2026-05-20`)
follow standard ESPN-style abbreviations. We hold a per-sport
`TEAM_CODE_TO_CANONICAL` map that translates each code to the canonical
Odds API team name (the same canonical strings Kalshi/Coral33 use, so
joins across books work without per-book aliases).

Codes verified live 2026-05-12 (per the spec author's probes). One
deviation from Kalshi convention worth flagging:
  - NHL Vegas Golden Knights: Polymarket uses `las`, Kalshi uses `vgk`.
    Both keys → "Vegas Golden Knights".

The map is the primary path; the optional `team_aliases` config table
provides a per-sport hook for short-form display names if a future slug
ever drops the code-only convention.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


# Slug team-code → canonical (Odds API) team name, scoped per sport.
#
# Same canonical strings as `KALSHI.TEAM_CODE_TO_CANONICAL` (intentional —
# the cache joins on these names across books). Codes are LOWERCASE here
# (Polymarket slugs are lowercase), unlike Kalshi's uppercase ticker
# suffixes.
#
# Audit: every Phase 1 sport here lists ALL 30 teams (NBA/MLB) or 32
# (NHL) so off-season / pre-playoff games normalize without re-probes.
# Reactively add team-name drift to `team_aliases` in polymarket.toml.
TEAM_CODE_TO_CANONICAL: dict[str, dict[str, str]] = {
    "mlb": {
        # AL East
        "bal": "Baltimore Orioles",
        "bos": "Boston Red Sox",
        "nyy": "New York Yankees",
        "tb":  "Tampa Bay Rays",
        "tor": "Toronto Blue Jays",
        # AL Central
        "cws": "Chicago White Sox",
        "cle": "Cleveland Guardians",
        "det": "Detroit Tigers",
        "kc":  "Kansas City Royals",
        "min": "Minnesota Twins",
        # AL West
        "hou": "Houston Astros",
        "laa": "Los Angeles Angels",
        "ath": "Athletics",
        "sea": "Seattle Mariners",
        "tex": "Texas Rangers",
        # NL East
        "atl": "Atlanta Braves",
        "mia": "Miami Marlins",
        "nym": "New York Mets",
        "phi": "Philadelphia Phillies",
        "wsh": "Washington Nationals",
        # NL Central
        "chc": "Chicago Cubs",
        "cin": "Cincinnati Reds",
        "mil": "Milwaukee Brewers",
        "pit": "Pittsburgh Pirates",
        "stl": "St Louis Cardinals",
        # NL West
        "az":  "Arizona Diamondbacks",
        "col": "Colorado Rockies",
        "lad": "Los Angeles Dodgers",
        "sd":  "San Diego Padres",
        "sf":  "San Francisco Giants",
    },
    "nba": {
        # Atlantic
        "bos": "Boston Celtics",
        "bkn": "Brooklyn Nets",
        "nyk": "New York Knicks",
        "phi": "Philadelphia 76ers",
        "tor": "Toronto Raptors",
        # Central
        "chi": "Chicago Bulls",
        "cle": "Cleveland Cavaliers",
        "det": "Detroit Pistons",
        "ind": "Indiana Pacers",
        "mil": "Milwaukee Bucks",
        # Southeast
        "atl": "Atlanta Hawks",
        "cha": "Charlotte Hornets",
        "mia": "Miami Heat",
        "orl": "Orlando Magic",
        "was": "Washington Wizards",
        # Northwest
        "den": "Denver Nuggets",
        "min": "Minnesota Timberwolves",
        "okc": "Oklahoma City Thunder",
        "por": "Portland Trail Blazers",
        "uta": "Utah Jazz",
        # Pacific
        "gsw": "Golden State Warriors",
        "lac": "Los Angeles Clippers",
        "lal": "Los Angeles Lakers",
        "phx": "Phoenix Suns",
        "sac": "Sacramento Kings",
        # Southwest
        "dal": "Dallas Mavericks",
        "hou": "Houston Rockets",
        "mem": "Memphis Grizzlies",
        "nop": "New Orleans Pelicans",
        "sas": "San Antonio Spurs",
    },
    "nhl": {
        # Eastern - Atlantic
        "bos": "Boston Bruins",
        "buf": "Buffalo Sabres",
        "det": "Detroit Red Wings",
        "fla": "Florida Panthers",
        "mtl": "Montréal Canadiens",
        "ott": "Ottawa Senators",
        "tbl": "Tampa Bay Lightning",
        "tor": "Toronto Maple Leafs",
        # Eastern - Metropolitan
        "car": "Carolina Hurricanes",
        "cbj": "Columbus Blue Jackets",
        "njd": "New Jersey Devils",
        "nyi": "New York Islanders",
        "nyr": "New York Rangers",
        "phi": "Philadelphia Flyers",
        "pit": "Pittsburgh Penguins",
        "wsh": "Washington Capitals",
        # Western - Central
        "chi": "Chicago Blackhawks",
        "col": "Colorado Avalanche",
        "dal": "Dallas Stars",
        "min": "Minnesota Wild",
        "nsh": "Nashville Predators",
        "stl": "St Louis Blues",
        "uta": "Utah Mammoth",
        "wpg": "Winnipeg Jets",
        # Western - Pacific
        "ana": "Anaheim Ducks",
        "cgy": "Calgary Flames",
        "edm": "Edmonton Oilers",
        "lak": "Los Angeles Kings",
        "sjs": "San Jose Sharks",
        "sea": "Seattle Kraken",
        "van": "Vancouver Canucks",
        # NB: Polymarket uses `las` for Vegas Golden Knights (Kalshi uses
        # `vgk`). Both map to the same canonical Odds API name so the
        # cache stays consistent across books.
        "las": "Vegas Golden Knights",
        # Keep `vgk` as an alias too — some Polymarket markets might use
        # the more conventional abbreviation if seeding changes.
        "vgk": "Vegas Golden Knights",
        # Arizona Coyotes legacy code (in case any historical or
        # forgotten slug surfaces). Maps to the same franchise that
        # moved → Utah Mammoth in 2024.
        "ari": "Utah Mammoth",
    },
}


@dataclass
class PolymarketSportConfig:
    """One sport block in polymarket.toml.

    Phase 1: only `slug_prefix` matters (e.g. "nba" → matches slugs
    starting with `nba-`). Phase 2 will add `tag_slug` for tag-based
    discovery and per-market-type filter knobs.
    """
    sport_key: str
    slug_prefix: str


@dataclass
class PolymarketConfig:
    sports: dict[str, PolymarketSportConfig]    # keyed by our sport_key
    team_aliases: dict[str, dict[str, str]]     # {sport_key: {norm_form: canon}}


def load_polymarket_config(path: Path) -> PolymarketConfig:
    """Load `server/config/polymarket.toml`. Missing sections default to
    empty so the fetcher starts cleanly even on a half-configured deploy."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    sports: dict[str, PolymarketSportConfig] = {}
    for key, cfg in (raw.get("sports") or {}).items():
        sports[key] = PolymarketSportConfig(
            sport_key=key,
            slug_prefix=str(cfg.get("slug_prefix") or key),
        )
    aliases_raw = raw.get("team_aliases") or {}
    team_aliases: dict[str, dict[str, str]] = {}
    for sport, table in aliases_raw.items():
        team_aliases[sport] = {k: v for k, v in (table or {}).items()}
    return PolymarketConfig(sports=sports, team_aliases=team_aliases)
