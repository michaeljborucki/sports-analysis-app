"""Static Novig → betting-site vocabulary.

Novig (https://docs.novig.com) is a peer-to-peer exchange. Its catalog names
leagues and market types in its own canonical vocabulary; this module maps
them onto our app sport keys and onto *families* of Odds API market keys.

A family is the set of Odds API keys one Novig market type can land under
(main + alternate). The normalizer never decides main-vs-alternate itself:
it copies the market_key of the Novig row betting-db already holds for the
same (event, line, player/team) — see `normalizer.build_sibling_index`.
That keeps every direct row in exactly the PK slot the Odds API copy uses,
so the direct quote overrides it instead of duplicating it.
"""
from __future__ import annotations


BOOK_KEY = "novig"
# Virtual book: the price you would POST (see server/odds/venues.py).
MAKER_BOOK_KEY = "novig_maker"

# Novig league → app sport key. Leagues not listed are skipped (PGA, futures-
# only leagues, …). Soccer competitions fall through to SPORT_TO_APP.
LEAGUE_TO_SPORT: dict[str, str] = {
    "NFL": "nfl",
    "NCAAF": "ncaaf",
    "MLB": "mlb",
    "NBA": "nba",
    "WNBA": "wnba",
    "NHL": "nhl",
    "ATP": "tennis",
    "WTA": "tennis",
    "UFC": "ufc",
    "KBO": "asian_baseball",
    "NPB": "asian_baseball",
}
SPORT_TO_APP: dict[str, str] = {"SOCCER": "soccer"}

# Novig leagues per app sport — the catalog listing is filtered to these so
# a disabled sport costs no requests.
SPORT_TO_LEAGUES: dict[str, tuple[str, ...]] = {}
for _league, _sport in LEAGUE_TO_SPORT.items():
    SPORT_TO_LEAGUES.setdefault(_sport, ())
    SPORT_TO_LEAGUES[_sport] += (_league,)


# Game-line families. Kind drives how outcomes are oriented:
#   ml     — two team/player outcomes, home = market description
#   spread — "<TEAM> ±x" outcomes, home = the outcome whose line == strike
#   total  — "Over x" / "Under x"
#   team_total — "Over x" / "Under x", team named in the description
GAME_FAMILIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "MONEY":      ("ml",         ("h2h",)),
    "MONEY_1H":   ("ml",         ("h2h_h1",)),
    "SPREAD":     ("spread",     ("spreads", "alternate_spreads")),
    "SPREAD_1H":  ("spread",     ("spreads_h1", "alternate_spreads_h1")),
    "TOTAL":      ("total",      ("totals", "alternate_totals")),
    "TOTAL_1H":   ("total",      ("totals_h1", "alternate_totals_h1")),
    "TEAM_TOTAL": ("team_total", ("team_totals", "alternate_team_totals")),
}

# MLB's "1H" markets are first-five-innings markets.
MLB_PERIOD_OVERRIDES: dict[str, tuple[str, ...]] = {
    "MONEY_1H":  ("h2h_1st_5_innings",),
    "SPREAD_1H": ("spreads_1st_5_innings", "alternate_spreads_1st_5_innings"),
    "TOTAL_1H":  ("totals_1st_5_innings", "alternate_totals_1st_5_innings"),
}

# Player-prop types: Novig type → Odds API base key, per app sport. The
# family is the base key plus its `_alternate` variant. Types whose Odds API
# encoding differs (Yes/No scorer markets, double-doubles as Yes/No) are
# deliberately absent — they never find a sibling, so nothing is written.
_FOOTBALL_PROPS = {
    "RECEIVING_YARDS": "player_reception_yds",
    "RUSHING_YARDS": "player_rush_yds",
    "RECEPTIONS": "player_receptions",
    "PASSING_YARDS": "player_pass_yds",
    "PASSING_TOUCHDOWNS": "player_pass_tds",
    "PASSING_ATTEMPTS": "player_pass_attempts",
    "PASSING_COMPLETIONS": "player_pass_completions",
    "INTERCEPTIONS_THROWN": "player_pass_interceptions",
    "LONGEST_RECEPTION": "player_reception_longest",
    "LONGEST_COMPLETION": "player_pass_longest_completion",
    "LONGEST_RUSH": "player_rush_longest",
    "RUSHING_ATTEMPTS": "player_rush_attempts",
    "RUSHING_AND_RECEIVING_YARDS": "player_rush_reception_yds",
    "PASSING_AND_RUSHING_YARDS": "player_pass_rush_yds",
    "KICKING_POINTS": "player_kicking_points",
    "FIELD_GOALS_MADE": "player_field_goals",
    "TACKLES_ASSISTS": "player_tackles_assists",
}
_BASKETBALL_PROPS = {
    "POINTS": "player_points",
    "REBOUNDS": "player_rebounds",
    "ASSISTS": "player_assists",
    "THREE_POINTERS_MADE": "player_threes",
    "POINTS_REBOUNDS_ASSISTS": "player_points_rebounds_assists",
    "REBOUNDS_ASSISTS": "player_rebounds_assists",
}
PROP_TYPES: dict[str, dict[str, str]] = {
    "nfl": _FOOTBALL_PROPS,
    "ncaaf": _FOOTBALL_PROPS,
    "nba": _BASKETBALL_PROPS,
    "wnba": _BASKETBALL_PROPS,
    "mlb": {
        "HITS": "batter_hits",
        "HOME_RUNS": "batter_home_runs",
        "RBIS": "batter_rbis",
        "HITS_RUNS_RBIS": "batter_hits_runs_rbis",
        "TOTAL_BASES": "batter_total_bases",
        "BATTING_STRIKEOUTS": "batter_strikeouts",
        "STOLEN_BASES": "batter_stolen_bases",
        "RUNS": "batter_runs_scored",
        "BATTING_WALKS": "batter_walks",
        "PITCHER_STRIKEOUTS": "pitcher_strikeouts",
        "HITS_ALLOWED": "pitcher_hits_allowed",
        "EARNED_RUNS": "pitcher_earned_runs",
        "PITCHER_OUTS": "pitcher_outs",
        "WALKS": "pitcher_walks",
    },
    "nhl": {
        "PLAYER_GOALS": "player_goals",
        "SHOTS_ON_GOAL": "player_shots_on_goal",
        "POINTS": "player_points",
        "ASSISTS": "player_assists",
        "SAVES": "player_total_saves",
    },
}


def app_sport(event: dict) -> str | None:
    """App sport key for a Novig event, or None when we don't cover it."""
    league = event.get("league") or ""
    if league in LEAGUE_TO_SPORT:
        return LEAGUE_TO_SPORT[league]
    return SPORT_TO_APP.get(event.get("sport") or "")


def family_for(sport: str, market_type: str) -> tuple[str, tuple[str, ...]] | None:
    """(kind, candidate Odds API market keys) for a Novig market type, or
    None when the type isn't mapped for this sport."""
    if sport == "mlb" and market_type in MLB_PERIOD_OVERRIDES:
        kind = GAME_FAMILIES[market_type][0]
        return kind, MLB_PERIOD_OVERRIDES[market_type]
    if market_type in GAME_FAMILIES:
        return GAME_FAMILIES[market_type]
    base = PROP_TYPES.get(sport, {}).get(market_type)
    if base:
        return "prop", (base, f"{base}_alternate")
    return None


def family_id(market_key: str) -> str:
    """Collapse an Odds API market key to its family id: main and alternate
    variants share one id so a sibling lookup finds either."""
    if market_key.startswith("alternate_"):
        market_key = market_key[len("alternate_"):]
    return market_key.removesuffix("_alternate")
