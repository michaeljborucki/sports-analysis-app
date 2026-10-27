"""Static Polymarket US -> betting-site vocabulary.

Polymarket US (polymarket.us, the CFTC exchange — NOT polymarket.com) tags
every market with a `sportsMarketType`. This module maps those types onto
app market keys. Pure data + tiny lookups; no I/O beyond reading the app's
own market-config tomls once.

Kinds (how `normalizer.py` turns a market's two sides into rows):
  ml          two team sides (teamId on each)            -> h2h-style, point None
  ml3         one Yes/No market per team + one tie market -> 3-way, Yes sides only
  spread      sides "+15.50"/"-15.50" with teamId         -> (team, signed point)
  total       sides Over/Under, no teamId                 -> Over/Under @ line
  team_total  sides Over/Under or Yes/No, teamId = team   -> "<Team> Over|Under" @ line
  nrfi        Yes/No "any run in the 1st inning"          -> nrfi Yes/No
  prop        Yes/No "<Player> N+ <stat>"                  -> "<player> Over|Under" @ N-0.5

Only keys the app knows for the sport are emitted (`known_market_keys`):
the sport's server/config/markets.<sport>.toml tiers, the MarketGroups in
server/sports.py, plus EXTRA_KNOWN_KEYS — keys the Odds API feed in
betting-db (data/odds.db latest_odds, inspected 2026-10-23) already carries
for that sport. bettingdb_source passes those through unfiltered, so they
are live app keys with other books to compare against even though the toml
doesn't list them.
"""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path


BOOK_KEY = "polymarket_us"

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


# ── League -> sport ─────────────────────────────────────────────────────

# Polymarket US league slug (event slug prefix) -> app sport_key. Mirrors
# server/config/polymarket_us.toml [leagues]; the fetcher may override via
# normalize_event(sport_key=...).
LEAGUE_TO_SPORT: dict[str, str] = {
    "nba": "nba",
    "wnba": "wnba",
    "nfl": "nfl",
    "cfb": "ncaaf",
    "nhl": "nhl",
    "mlb": "mlb",
    "epl": "soccer",
    "mls": "soccer",
    "lal": "soccer", "laliga": "soccer",
    "sea": "soccer", "seriea": "soccer",
    "bun": "soccer", "bundesliga": "soccer",
    "fl1": "soccer", "ligue1": "soccer",
    "ucl": "soccer",
    "uel": "soccer",
    "mex": "soccer", "ligamx": "soccer",
    "bra": "soccer",
    "jap": "soccer", "jleague": "soccer",
}

# Soccer league slug -> (league_key, league_title). league_key is the Odds
# API sport key, exactly what normalize_odds_response / bettingdb_source put
# on soccer rows (the web groups soccer games by it). Titles are the Odds
# API sport_title strings. Only epl / mls are fixture-verified slugs.
SOCCER_LEAGUES: dict[str, tuple[str, str]] = {
    "epl": ("soccer_epl", "EPL"),
    "mls": ("soccer_usa_mls", "MLS"),
    "lal": ("soccer_spain_la_liga", "La Liga - Spain"),
    "laliga": ("soccer_spain_la_liga", "La Liga - Spain"),
    "sea": ("soccer_italy_serie_a", "Serie A - Italy"),
    "seriea": ("soccer_italy_serie_a", "Serie A - Italy"),
    "bun": ("soccer_germany_bundesliga", "Bundesliga - Germany"),
    "bundesliga": ("soccer_germany_bundesliga", "Bundesliga - Germany"),
    "fl1": ("soccer_france_ligue_one", "Ligue 1 - France"),
    "ligue1": ("soccer_france_ligue_one", "Ligue 1 - France"),
    "ucl": ("soccer_uefa_champs_league", "UEFA Champions League"),
    "uel": ("soccer_uefa_europa_league", "UEFA Europa League"),
    "mex": ("soccer_mexico_ligamx", "Liga MX"),
    "ligamx": ("soccer_mexico_ligamx", "Liga MX"),
    "bra": ("soccer_brazil_campeonato", "Brazil Série A"),
    "jap": ("soccer_japan_j_league", "J League"),
    "jleague": ("soccer_japan_j_league", "J League"),
}


# ── Game-line types ─────────────────────────────────────────────────────

_BASKETBALL_PERIODS = {
    "first_half": "_h1", "second_half": "_h2",
    "first_quarter": "_q1", "second_quarter": "_q2",
    "third_quarter": "_q3", "fourth_quarter": "_q4",
}
_HOCKEY_PERIODS = {
    "first_period": "_p1", "second_period": "_p2", "third_period": "_p3",
}

# sportsMarketType -> (kind, period suffix)
GAME_TYPES: dict[str, tuple[str, str]] = {
    # basketball (nba / wnba)
    "basketball_team_full_game_winner": ("ml", ""),
    "basketball_team_full_game_spread": ("spread", ""),
    "basketball_team_full_game_total": ("total", ""),
    "basketball_team_total_points": ("team_total", ""),
    "basketball_team_total_points_first_half": ("team_total", "_h1"),
    "basketball_team_total_points_second_half": ("team_total", "_h2"),
    "basketball_team_total_points_first_quarter": ("team_total", "_q1"),
    "basketball_team_total_points_second_quarter": ("team_total", "_q2"),
    "basketball_team_total_points_third_quarter": ("team_total", "_q3"),
    "basketball_team_total_points_fourth_quarter": ("team_total", "_q4"),
    # football (nfl / ncaaf). NOTE the naming trap: football_team_full_game_total
    # is the GAME total (no teamId), football_team_{first,second}_half_total are
    # TEAM totals (teamId set), football_game_*_total are game period totals.
    "football_team_full_game_winner": ("ml", ""),
    "football_team_full_game_spread": ("spread", ""),
    "football_team_full_game_total": ("total", ""),
    "football_team_points_full_game_total": ("team_total", ""),
    "football_team_first_half_total": ("team_total", "_h1"),
    "football_team_second_half_total": ("team_total", "_h2"),
    "football_game_first_half_total": ("total", "_h1"),
    "football_game_second_half_total": ("total", "_h2"),
    "football_game_first_quarter_total": ("total", "_q1"),
    "football_game_second_quarter_total": ("total", "_q2"),
    "football_game_third_quarter_total": ("total", "_q3"),
    "football_game_fourth_quarter_total": ("total", "_q4"),
    # hockey (nhl)
    "hockey_team_full_game_winner": ("ml", ""),
    "hockey_team_full_game_spread": ("spread", ""),
    "hockey_team_full_game_total": ("total", ""),
    # Regulation result (tie market = "tied after regulation") — the app's
    # NHL `h2h_3_way` is exactly the regulation-time 3-way.
    "hockey_team_regulation_winner": ("ml3", ""),
    "hockey_team_total_goals": ("team_total", ""),
    # baseball (mlb)
    "baseball_team_full_game_winner": ("ml", ""),
    "baseball_team_full_game_spread": ("spread", ""),
    "baseball_team_full_game_total": ("total", ""),
    "baseball_team_total_runs": ("team_total", ""),
    "baseball_team_first_five_spread": ("spread", "_1st_5_innings"),
    "baseball_team_first_five_total": ("total", "_1st_5_innings"),
    # Polymarket F5 "winner" loses on a tie (separate tie market) -> 3-way,
    # NOT the Odds API 2-way h2h_1st_5_innings (tie = push).
    "baseball_team_first_five_winner": ("ml3", "_1st_5_innings"),
    "baseball_team_inning1_total": ("total", "_1st_1_innings"),
    "baseball_team_inning1_winner": ("ml3", "_1st_1_innings"),
    "baseball_team_first_inning_run": ("nrfi", ""),
    # soccer
    "soccer_team_full_time_winner": ("ml3", ""),
    "soccer_team_full_game_spread": ("spread", ""),
    "soccer_team_full_game_total": ("total", ""),
    "soccer_team_total_goals": ("team_total", ""),
    "soccer_team_total_goals_first_half": ("team_total", "_h1"),
}
for _name, _sfx in _BASKETBALL_PERIODS.items():
    GAME_TYPES[f"basketball_team_{_name}_winner"] = ("ml3", _sfx)
    GAME_TYPES[f"basketball_team_{_name}_spread"] = ("spread", _sfx)
    GAME_TYPES[f"basketball_team_{_name}_total"] = ("total", _sfx)
    GAME_TYPES[f"football_team_{_name}_winner"] = ("ml3", _sfx)
    GAME_TYPES[f"football_team_{_name}_spread"] = ("spread", _sfx)
for _name, _sfx in _HOCKEY_PERIODS.items():
    GAME_TYPES[f"hockey_team_{_name}_winner"] = ("ml3", _sfx)
    GAME_TYPES[f"hockey_team_{_name}_spread"] = ("spread", _sfx)
    GAME_TYPES[f"hockey_team_{_name}_total"] = ("total", _sfx)
for _name, _sfx in (("first_half", "_h1"), ("second_half", "_h2")):
    GAME_TYPES[f"soccer_team_{_name}_winner"] = ("ml3", _sfx)
    GAME_TYPES[f"soccer_team_{_name}_spread"] = ("spread", _sfx)
    GAME_TYPES[f"soccer_team_{_name}_total"] = ("total", _sfx)


# ── Player props ────────────────────────────────────────────────────────
# Yes/No "at least N" milestones -> Odds API O/U base key at N-0.5.
# rows_to_games merges `<base>_alternate` into `<base>` anyway, so the base
# key is used for every rung.

_BASKETBALL_PROPS = {
    "basketball_player_points": "player_points",
    "basketball_player_rebounds": "player_rebounds",
    "basketball_player_assists": "player_assists",
    "basketball_player_threes": "player_threes",
    "basketball_player_blocks": "player_blocks",
    "basketball_player_steals": "player_steals",
    "basketball_player_turnovers": "player_turnovers",
    "basketball_player_points_rebounds_assists": "player_points_rebounds_assists",
    "basketball_player_points_rebounds": "player_points_rebounds",
    "basketball_player_points_assists": "player_points_assists",
    "basketball_player_rebounds_assists": "player_rebounds_assists",
    "basketball_player_blocks_steals": "player_blocks_steals",
}
_FOOTBALL_PROPS = {
    "football_player_passing_yards": "player_pass_yds",
    "football_player_passing_touchdowns": "player_pass_tds",
    "football_player_passing_attempts": "player_pass_attempts",
    "football_player_passing_completions": "player_pass_completions",
    "football_player_interceptions_thrown": "player_pass_interceptions",
    "football_player_rushing_yards": "player_rush_yds",
    "football_player_receiving_yards": "player_reception_yds",
    "football_player_receptions": "player_receptions",
    "football_player_longest_reception": "player_reception_longest",
    "football_player_longest_completion": "player_pass_longest_completion",
    "football_player_kicking_points": "player_kicking_points",
}
_HOCKEY_PROPS = {
    "hockey_player_points": "player_points",
    "hockey_player_assists": "player_assists",
    "hockey_player_goals": "player_goals",
    "hockey_player_shots_on_goal": "player_shots_on_goal",
    "hockey_player_saves": "player_total_saves",
    "hockey_player_blocked_shots": "player_blocked_shots",
    "hockey_player_power_play_points": "player_power_play_points",
}
PROP_TYPES: dict[str, dict[str, str]] = {
    "nba": _BASKETBALL_PROPS,
    "wnba": _BASKETBALL_PROPS,
    "nfl": _FOOTBALL_PROPS,
    "ncaaf": _FOOTBALL_PROPS,
    "nhl": _HOCKEY_PROPS,
    # mlb / soccer: no Polymarket US prop type has been seen and mapped yet.
}


# ── Deliberately unmapped types and why (shown to the user) ─────────────

_NO_KEY = "no app market key with matching semantics"
UNMAPPED_REASONS: dict[str, str] = {
    "basketball_game_overtime": _NO_KEY + " (overtime yes/no)",
    "basketball_game_race_to_points": "betting-db has team_to_10/20_points_first but the app config doesn't; Polymarket posts one Yes/No per team",
    "basketball_game_winning_margin": _NO_KEY + " (winning-margin bands)",
    "football_game_double_result": _NO_KEY + " (halftime/full-time double result)",
    "football_game_exact_margin": _NO_KEY + " (margin bands)",
    "football_game_first_score": _NO_KEY + " (first team to score)",
    "football_game_first_touchdown": _NO_KEY + " (first team TD)",
    "football_game_overtime": _NO_KEY,
    "football_game_race_to_points": _NO_KEY,
    "football_game_safety": _NO_KEY,
    "football_game_tie": _NO_KEY,
    "football_game_total_touchdowns": _NO_KEY + " (game TD count)",
    "football_game_total_pass_touchdowns": _NO_KEY,
    "football_game_total_rush_touchdowns": _NO_KEY,
    "football_game_total_defensive_special_teams_touchdowns": _NO_KEY,
    "football_game_total_two_point_conversions": _NO_KEY,
    "football_game_total_fourth_down_conversions": _NO_KEY,
    "football_player_fantasy_points_ppr": _NO_KEY,
    "football_player_first_touchdown": "app has no first-TD-scorer key (Odds API player_1st_td not configured)",
    "football_player_team_first_touchdown": _NO_KEY,
    "football_player_touchdowns": "anytime-TD (player_anytime_td) not in app config",
    "football_player_most_passing_yards": _NO_KEY,
    "football_player_rushing_attempts": "player_rush_attempts not in app config / betting-db",
    "football_player_scrimmage_yards": "player_rush_reception_yds not in app config / betting-db",
    "football_team_total_defensive_special_teams_touchdowns": _NO_KEY,
    "football_team_total_field_goals_made": _NO_KEY,
    "football_team_total_first_downs": _NO_KEY,
    "football_team_total_offensive_yards": _NO_KEY,
    "football_team_total_pass_touchdowns": _NO_KEY,
    "football_team_total_pass_yards": _NO_KEY,
    "football_team_total_receptions": _NO_KEY,
    "football_team_total_rush_touchdowns": _NO_KEY,
    "football_team_total_rush_yards": _NO_KEY,
    "football_team_total_touchdowns": _NO_KEY,
    "hockey_game_first_team_to_score": _NO_KEY,
    "hockey_game_overtime": _NO_KEY,
    "hockey_game_shootout": _NO_KEY,
    "hockey_team_saves": "team saves; app only has per-goalie player_total_saves",
    "baseball_game_extra_innings": _NO_KEY,
    "soccer_game_btts": _NO_KEY + " (BTTS not in app config)",
    "soccer_game_first_half_btts": _NO_KEY,
    "soccer_game_second_half_btts": _NO_KEY,
    "soccer_game_exact_score": _NO_KEY,
    "soccer_game_first_half_exact_score": _NO_KEY,
    "soccer_game_first_team_to_score": _NO_KEY,
    "soccer_game_first_half_first_team_to_score": _NO_KEY,
    "soccer_game_second_half_first_team_to_score": _NO_KEY,
    "soccer_game_total_corners": _NO_KEY,
    "soccer_player_goals": "app has no soccer player-prop keys",
}
for _q in ("first", "second", "third", "fourth"):
    UNMAPPED_REASONS[f"football_game_{_q}_quarter_both_teams_score_points"] = _NO_KEY
for _n in range(2, 10):
    UNMAPPED_REASONS[f"baseball_team_inning{_n}_total"] = "single inning N; app only has first-N-innings keys"
    UNMAPPED_REASONS[f"baseball_team_inning{_n}_winner"] = "single inning N; app only has first-N-innings keys"


# ── App market-key universe ─────────────────────────────────────────────

# Keys the betting-db Odds API feed carries for the sport (2026-10-23) that
# the toml / sports.py don't list. Restricted to families this book posts.
EXTRA_KNOWN_KEYS: dict[str, frozenset[str]] = {
    "nfl": frozenset({
        "h2h_q1", "h2h_q2", "h2h_q3", "h2h_q4",
        "spreads_q1", "spreads_q2", "spreads_q3", "spreads_q4",
        "alternate_spreads_q1", "alternate_spreads_q2", "alternate_spreads_q3", "alternate_spreads_q4",
        "totals_q1", "totals_q2", "totals_q3", "totals_q4",
        "alternate_totals_q1", "alternate_totals_q2", "alternate_totals_q3", "alternate_totals_q4",
        "alternate_spreads_h1", "alternate_totals_h1", "team_totals_h1",
    }),
    "ncaaf": frozenset({"team_totals", "alternate_team_totals", "team_totals_h1"}),
    "soccer": frozenset({"team_totals"}),
}


@lru_cache(maxsize=None)
def known_market_keys(sport_key: str) -> frozenset[str]:
    """Every market key the app knows for `sport_key`."""
    from ....sports import SPORTS

    keys: set[str] = set(EXTRA_KNOWN_KEYS.get(sport_key, ()))
    sport = SPORTS.get(sport_key)
    if sport is not None:
        for g in sport.market_groups:
            keys.add(g.main_key)
            if g.alt_key:
                keys.add(g.alt_key)
        path = _CONFIG_DIR / sport.markets_config
        try:
            raw = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            raw = {}
        for section in raw.values():
            if isinstance(section, dict):
                keys.update(str(m) for m in section.get("markets", []) or [])
    return frozenset(keys)


def main_key(kind: str, suffix: str, sport_key: str) -> str | None:
    """Main app market key for a (kind, period) — None for prop kinds."""
    if kind == "ml":
        return f"h2h{suffix}"
    if kind == "ml3":
        # Soccer's full-time 3-way lives under plain `h2h` (with "Draw"),
        # matching coral33 / Odds API / polymarket intl.
        if sport_key == "soccer" and suffix == "":
            return "h2h"
        return f"h2h_3_way{suffix}"
    if kind == "spread":
        return f"spreads{suffix}"
    if kind == "total":
        return f"totals{suffix}"
    if kind == "team_total":
        return f"team_totals{suffix}"
    if kind == "nrfi":
        return "nrfi"
    return None


def alt_key(kind: str, suffix: str, sport_key: str) -> str | None:
    """Alternate-line key when the app knows one for this sport, else None
    (callers then use the main key for every line)."""
    base = {"spread": "spreads", "total": "totals", "team_total": "team_totals"}.get(kind)
    if base is None:
        return None
    key = f"alternate_{base}{suffix}"
    return key if key in known_market_keys(sport_key) else None


def classify(sport_key: str, market_type: str) -> tuple[str, str, str] | tuple[None, str, str]:
    """(kind, suffix_or_base_key, main_market_key) for a mapped type, or
    (None, reason, "") when this type yields nothing for the sport."""
    prop = PROP_TYPES.get(sport_key, {}).get(market_type)
    if prop:
        if prop not in known_market_keys(sport_key):
            return None, f"{prop} not an app key for {sport_key}", ""
        return "prop", prop, prop
    spec = GAME_TYPES.get(market_type)
    if spec is None:
        return None, UNMAPPED_REASONS.get(market_type, "unknown sportsMarketType (not in mapping)"), ""
    kind, suffix = spec
    mk = main_key(kind, suffix, sport_key)
    if mk is None or mk not in known_market_keys(sport_key):
        return None, f"{mk} not an app key for {sport_key}", ""
    return kind, suffix, mk
