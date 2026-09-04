from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

import httpx

from ..odds.cache import OddsCache
from .context_cache import SystemContextCache
from .models import EvaluationGame
from .team_names import (
    TeamIndex,
    competitor_id,
    index_from_competitors,
    normalize as team_normalize,
)


Enricher = Callable[
    [list[EvaluationGame], date],
    Awaitable[tuple[dict[str, dict], list[str]]],
]


def _parse_dt(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _main_point(rows: list[dict], market_key: str) -> float | None:
    points = [float(row["outcome_point"]) for row in rows if row["market_key"] == market_key]
    return Counter(points).most_common(1)[0][0] if points else None


# The one book these signals can actually be placed at. Systems rows quote
# Coral33 and nothing else: a price from a book the user has no account at
# is not a price, and showing the market-best number invites betting a line
# that is not on offer.
PLACEMENT_BOOK = "coral33"


def _outcome_rows(
    rows: list[dict], market: str, outcome: str, point: float | None = None
) -> list[dict]:
    return [
        row for row in rows
        if row["market_key"] == market and row["outcome_name"] == outcome
        and (point is None or abs(float(row["outcome_point"]) - point) < .001)
    ]


def _best_price(rows: list[dict], market: str, outcome: str, point: float | None = None) -> tuple[int | None, str | None]:
    """Market-best price. Feeds the RULES, which gate on market consensus."""
    candidates = _outcome_rows(rows, market, outcome, point)
    if not candidates:
        return None, None
    best = max(candidates, key=lambda row: int(row["price_american"]))
    return int(best["price_american"]), best["bookmaker_key"]


def _placement_price(
    rows: list[dict], market: str, outcome: str, point: float | None = None
) -> int | None:
    """Coral33's price, or None when Coral33 is not offering this selection.

    Feeds the DISPLAY only. Returning None rather than falling back keeps an
    unplaceable price off the page entirely.
    """
    candidates = [
        row for row in _outcome_rows(rows, market, outcome, point)
        if row["bookmaker_key"] == PLACEMENT_BOOK
    ]
    if not candidates:
        return None
    return int(max(candidates, key=lambda row: int(row["price_american"]))["price_american"])


def _base_game(rows: list[dict]) -> EvaluationGame:
    first = rows[0]
    spread_point = _main_point(rows, "spreads")
    total = _main_point(rows, "totals")
    context: dict = {
        "day_of_week": _parse_dt(first["commence_time"]).strftime("%A"),
        "month": _parse_dt(first["commence_time"]).month,
        "total": total,
    }
    for side, team in (("home", first["home_team"]), ("away", first["away_team"])):
        price, book = _best_price(rows, "h2h", team)
        context[f"{side}_moneyline"] = price
        context[f"{side}_moneyline_book"] = book
        context[f"{side}_moneyline_placement"] = _placement_price(rows, "h2h", team)
        if spread_point is not None:
            side_points = [float(r["outcome_point"]) for r in rows if r["market_key"] == "spreads" and r["outcome_name"] == team]
            side_point = Counter(side_points).most_common(1)[0][0] if side_points else None
            context[f"{side}_spread"] = side_point
            spread_price, spread_book = _best_price(rows, "spreads", team, side_point)
            context[f"{side}_spread_price"] = spread_price
            context[f"{side}_spread_book"] = spread_book
            context[f"{side}_spread_placement"] = _placement_price(
                rows, "spreads", team, side_point
            )
        else:
            context[f"{side}_spread"] = None
            context[f"{side}_spread_price"] = None
            context[f"{side}_spread_book"] = None
            context[f"{side}_spread_placement"] = None
    for direction, outcome in (("over", "Over"), ("under", "Under")):
        total_price, total_book = _best_price(rows, "totals", outcome, total)
        context[f"total_{direction}_price"] = total_price
        context[f"total_{direction}_book"] = total_book
        context[f"total_{direction}_placement"] = _placement_price(
            rows, "totals", outcome, total
        )
    fetched = max(_parse_dt(row["fetched_at"]) for row in rows)
    return EvaluationGame(
        event_id=first["event_id"], sport=first["sport_key"],
        home_team=first["home_team"], away_team=first["away_team"],
        commence_time=_parse_dt(first["commence_time"]), data_timestamp=fetched,
        context=context,
    )


async def build_evaluation_games(
    cache: OddsCache,
    requested_date: date,
    timezone_name: str,
    now: datetime,
    *,
    enrich: Enricher | None = None,
    include_after: bool = False,
    source_rows: tuple[dict, ...] | None = None,
) -> tuple[list[EvaluationGame], list[str]]:
    zone = ZoneInfo(timezone_name)
    grouped: dict[str, list[dict]] = defaultdict(list)
    rows = list(source_rows) if source_rows is not None else [
        row
        for sport in ("mlb", "ncaaf", "nfl")
        for row in cache.all_current_markets(
            sport, ("h2h", "spreads", "totals")
        )
    ]
    for row in rows:
        commence = _parse_dt(row["commence_time"])
        local_date = commence.astimezone(zone).date()
        date_matches = local_date >= requested_date if include_after else local_date == requested_date
        if commence > now and date_matches:
            grouped[row["event_id"]].append(row)
    games = [_base_game(rows) for rows in grouped.values()]
    warnings: list[str] = []
    try:
        if enrich is None:
            additions, provider_warnings = await current_context_enricher(
                games, requested_date, context_cache=SystemContextCache(cache.path)
            )
        else:
            additions, provider_warnings = await enrich(games, requested_date)
        warnings.extend(provider_warnings)
        for game in games:
            game.context.update(additions.get(game.event_id, {}))
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        warnings.append(f"Context provider unavailable for {requested_date}: {detail}" if include_after else f"Context provider unavailable: {detail}")
    return sorted(games, key=lambda game: game.commence_time), warnings


# ESPN files a game under its US EASTERN date. A UTC date silently walks a
# night game onto the following day — an 8pm ET kickoff is already tomorrow
# in UTC — so once the afternoon games start and drop off the slate, every
# remaining game asks ESPN for the WRONG day, matches nothing, and takes the
# venue-less directory fallback. That put the three weather systems back on
# "unable to evaluate" every evening.
_ESPN_ZONE = ZoneInfo("America/New_York")


def scoreboard_date_key(games: list[EvaluationGame], fallback_date: date) -> str:
    """Return one ESPN date or an inclusive range covering a combined slate."""
    if not games:
        return fallback_date.strftime("%Y%m%d")
    dates = sorted({
        game.commence_time.astimezone(_ESPN_ZONE).date() for game in games
    })
    first, last = dates[0].strftime("%Y%m%d"), dates[-1].strftime("%Y%m%d")
    return first if first == last else f"{first}-{last}"


_MLB_CACHE: dict[str, tuple[float, tuple[dict[str, dict], list[str]]]] = {}
_FOOTBALL_CACHE: dict[str, tuple[float, tuple[dict[str, dict], list[str]]]] = {}


def _norm(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", ascii_name.lower())


def _college_norm(name: str) -> str:
    """Deprecated shim — use `TeamIndex.resolve`. Retained for the MLB path."""
    return team_normalize(name)


_P4_CONFERENCES = {1, 4, 5, 8}  # ACC, Big 12, Big Ten, SEC
_G5_CONFERENCES = {12, 15, 17, 37, 151}  # CUSA, MAC, MWC, Sun Belt, AAC
_FBS_CONFERENCES = _P4_CONFERENCES | _G5_CONFERENCES | {9, 18}


def football_scoreboard_context(
    games: list[EvaluationGame], payload: dict
) -> dict[str, dict]:
    """Match odds events to ESPN schedule events and return confirmed metadata."""
    week = payload.get("week", {}).get("number")
    index, events = _scoreboard_index(payload)

    additions: dict[str, dict] = {}
    for game in games:
        matched = _match_event(game, index, events)
        if not matched:
            continue
        event, sides = matched
        competition = (event.get("competitions") or [{}])[0]
        conference_ids = {
            side: int(sides[side]["team"]["conferenceId"])
            for side in ("home", "away")
            if sides[side]["team"].get("conferenceId") is not None
        }
        is_fbs = len(conference_ids) == 2 and all(
            conference_id in _FBS_CONFERENCES
            for conference_id in conference_ids.values()
        )
        context: dict = {
            "is_fbs_game": is_fbs,
            "week": event.get("week", {}).get("number") or week,
        }
        if event.get("id"):
            context["espn_event_id"] = event["id"]
        if competition.get("venue"):
            context["venue"] = competition["venue"]
        for side in ("home", "away"):
            conference_id = conference_ids.get(side)
            context[f"{side}_conference_class"] = (
                "p4" if conference_id in _P4_CONFERENCES
                else "g5" if conference_id in _G5_CONFERENCES
                else None
            )
        additions[game.event_id] = context
    return additions


def college_games_played_context(
    games: list[EvaluationGame], payload: dict,
) -> dict[str, dict]:
    """Count each team's completed current-season games before kickoff."""
    index = TeamIndex()
    completed: list[tuple[datetime, set[str]]] = []
    for event in payload.get("events", []):
        competitors = [
            competitor
            for competition in event.get("competitions", [])
            for competitor in competition.get("competitors", [])
        ]
        index_from_competitors(competitors, index)
        if event.get("status", {}).get("type", {}).get("completed") is not True:
            continue
        event_date = event.get("date")
        if not event_date:
            continue
        team_ids = {
            resolved
            for competitor in competitors
            if (resolved := competitor_id(competitor.get("team") or {})) is not None
        }
        completed.append((_parse_dt(event_date), team_ids))

    additions: dict[str, dict] = {}
    for game in games:
        # A team absent from the index has played nothing: the history feed
        # spans the whole season to date, so "not found" means zero games,
        # not an unresolved name.
        additions[game.event_id] = {
            f"{side}_games_played": sum(
                team_id is not None
                and team_id in team_ids
                and played_at < game.commence_time
                for played_at, team_ids in completed
            )
            for side, team_id in (
                ("home", index.resolve(game.home_team)),
                ("away", index.resolve(game.away_team)),
            )
        }
    return additions


def _scoreboard_index(
    payload: dict,
) -> tuple[TeamIndex, dict[tuple[str, str], tuple[dict, dict]]]:
    """Index a scoreboard by ESPN team id, plus every alias each team answers to.

    Keying events on team *ids* rather than on a normalized display-name pair
    means the fuzzy part of matching happens once, in `TeamIndex`, instead of
    demanding that both team names spell out identically.
    """
    index = TeamIndex()
    events: dict[tuple[str, str], tuple[dict, dict]] = {}
    for event in payload.get("events", []):
        competition = (event.get("competitions") or [{}])[0]
        sides = {
            item.get("homeAway"): item
            for item in competition.get("competitors", [])
        }
        if "home" not in sides or "away" not in sides:
            continue
        index_from_competitors(sides.values(), index)
        home_id = competitor_id(sides["home"].get("team") or {})
        away_id = competitor_id(sides["away"].get("team") or {})
        if home_id is None or away_id is None:
            continue
        events[(home_id, away_id)] = (event, sides)
    return index, events


def _match_event(
    game: EvaluationGame,
    index: TeamIndex,
    events: dict[tuple[str, str], tuple[dict, dict]],
) -> tuple[dict, dict] | None:
    home_id = index.resolve(game.home_team)
    away_id = index.resolve(game.away_team)
    if home_id is None or away_id is None:
        return None
    return events.get((home_id, away_id))


def nfl_scoreboard_context(
    games: list[EvaluationGame],
    payload: dict,
    division_by_team_id: dict[int, str],
    prior_playoff_team_ids: set[int],
) -> dict[str, dict]:
    index, events = _scoreboard_index(payload)
    additions: dict[str, dict] = {}
    season_types = {1: "preseason", 2: "regular", 3: "postseason"}
    for game in games:
        matched = _match_event(game, index, events)
        if not matched:
            continue
        event, sides = matched
        home_id = int(sides["home"]["team"]["id"])
        away_id = int(sides["away"]["team"]["id"])
        season_type_id = event.get("season", {}).get("type")
        week = event.get("week", {}).get("number") or payload.get("week", {}).get("number")
        home_division = division_by_team_id.get(home_id)
        away_division = division_by_team_id.get(away_id)
        additions[game.event_id] = {
            "season_type": season_types.get(season_type_id),
            "week": week,
            "is_divisional": bool(home_division and home_division == away_division),
            "away_made_playoffs_previous_season": away_id in prior_playoff_team_ids,
            "home_espn_team_id": home_id,
            "away_espn_team_id": away_id,
        }
    return additions


def _directory_index(directory: dict[str, int]) -> TeamIndex:
    """Index ESPN's team directory, which offers display names only.

    The last word of "Nicholls Colonels" is the mascot, and pass C of the
    resolver needs it to tell "Nicholls State Colonels" (the same school)
    from "Houston Baptist Huskies" (not Houston).
    """
    index = TeamIndex()
    for name, team_id in directory.items():
        school, _, mascot = name.rpartition(" ")
        # Register the school half on its own as well, so a feed name that
        # pads it out ("Nicholls State Colonels" over ESPN's "Nicholls
        # Colonels") still has a prefix to latch onto. The mascot check keeps
        # that from over-reaching onto a genuinely different school.
        index.add(str(team_id), int(team_id), name, school or None,
                  mascot=mascot or None)
    return index


def college_team_directory_context(
    games: list[EvaluationGame],
    directory: dict[str, int],
    details: dict[int, dict],
    *,
    week: int | None,
) -> dict[str, dict]:
    index = _directory_index(directory)
    additions: dict[str, dict] = {}
    for game in games:
        home_id = index.resolve(game.home_team)
        away_id = index.resolve(game.away_team)
        home = details.get(home_id if home_id is not None else -1, {})
        away = details.get(away_id if away_id is not None else -1, {})
        if not home or not away:
            continue
        is_fbs = home.get("parent_group_id") == 80 and away.get("parent_group_id") == 80
        additions[game.event_id] = {
            "is_fbs_game": is_fbs,
            "week": week,
            "home_conference_class": (
                "p4" if home.get("conference_id") in _P4_CONFERENCES
                else "g5" if home.get("conference_id") in _G5_CONFERENCES else None
            ),
            "away_conference_class": (
                "p4" if away.get("conference_id") in _P4_CONFERENCES
                else "g5" if away.get("conference_id") in _G5_CONFERENCES else None
            ),
        }
    return additions


def select_kickoff_weather(hourly: dict, kickoff: datetime) -> dict[str, float]:
    """Nearest hour to kickoff that actually carries both readings.

    Open-Meteo returns nulls at the edge of its forecast range. Taking the
    nearest hour blindly and calling float() on a null raised straight out
    of the enricher, blanking the context for EVERY football game rather
    than the one game with a thin forecast.
    """
    times = [
        datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        for value in hourly.get("time", [])
    ]
    temperatures = hourly.get("temperature_2m", [])
    winds = hourly.get("wind_speed_10m", [])
    usable = [
        index for index in range(len(times))
        if index < len(temperatures) and index < len(winds)
        and temperatures[index] is not None and winds[index] is not None
    ]
    if not usable:
        return {}
    index = min(usable, key=lambda idx: abs((times[idx] - kickoff).total_seconds()))
    return {
        "temperature_f": float(temperatures[index]),
        "sustained_wind_mph": float(winds[index]),
    }


def weather_forecast_available(forecast_date: date, today: date) -> bool:
    """Open-Meteo only serves forecasts roughly sixteen days ahead.

    The window is anchored on TODAY, not on the requested slate date: asking
    for `upcoming` shifts the requested date forward two days, and measuring
    from there overshot the provider's range and 400'd.
    """
    return forecast_date <= today + timedelta(days=15)


# ESPN venue addresses carry two-letter state codes; Open-Meteo's `admin1`
# carries the full name. Comparing them directly never matched, so every
# lookup silently fell through to the most prominent city of that name
# anywhere in the country — Missouri's stadium was resolving to Columbia,
# SOUTH CAROLINA, and Delaware's to Newark, NEW JERSEY. Wind and temperature
# rules bet on those numbers, so the join has to be exact.
_US_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida",
    "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
    "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}


def select_geocode_result(results: list[dict], city: str, state: str | None) -> dict:
    """Pick the one geocoder hit that is actually this venue's city.

    Returns {} rather than a guess when the state is known and nothing in it
    matched: no weather is a visible gap, wrong weather is a silent bad bet.
    """
    candidates = [item for item in results if item.get("latitude") is not None]
    wanted_state = _US_STATE_NAMES.get((state or "").strip().upper())
    if wanted_state:
        candidates = [item for item in candidates if item.get("admin1") == wanted_state]
    elif state:
        # An unrecognized (non-US) state code: refuse rather than guess.
        return {}
    if not candidates:
        return {}
    city_key = _norm(city)
    best = max(
        candidates,
        key=lambda item: (
            _norm(item.get("name") or "") == city_key,
            item.get("population") or 0,
        ),
    )
    return {"latitude": best["latitude"], "longitude": best["longitude"]}


async def football_schedule_enricher(
    games: list[EvaluationGame], requested_date: date,
    *, context_cache: SystemContextCache | None = None,
) -> tuple[dict[str, dict], list[str]]:
    football_games = [game for game in games if game.sport in ("ncaaf", "nfl")]
    if not football_games:
        return {}, []
    additions: dict[str, dict] = {}
    warnings: list[str] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        for sport, path in (("ncaaf", "college-football"), ("nfl", "nfl")):
            sport_games = [game for game in football_games if game.sport == sport]
            if not sport_games:
                continue
            date_key = scoreboard_date_key(sport_games, requested_date)
            async def load_scoreboard(path: str = path) -> dict:
                response = await client.get(
                    f"https://site.api.espn.com/apis/site/v2/sports/football/{path}/scoreboard",
                    params={"dates": date_key, "limit": 300},
                )
                response.raise_for_status()
                return response.json()

            if context_cache:
                cached = await context_cache.get_or_refresh(
                    "espn", f"{sport}:scoreboard:{date_key}", requested_date,
                    timedelta(minutes=15), load_scoreboard,
                )
                payload = cached.payload
                if cached.warning:
                    warnings.append(cached.warning)
            else:
                try:
                    payload = await load_scoreboard()
                except Exception as exc:
                    detail = str(exc).strip() or type(exc).__name__
                    warnings.append(f"{sport.upper()} schedule context unavailable: {detail}")
                    continue

            if sport == "ncaaf":
                cfb_additions = football_scoreboard_context(sport_games, payload)
                unmatched = [game for game in sport_games if game.event_id not in cfb_additions]
                if unmatched:
                    fallback, fallback_warnings = await _college_directory_fallback(
                        unmatched, payload.get("week", {}).get("number"),
                        requested_date, client, context_cache,
                    )
                    cfb_additions.update(fallback)
                    warnings.extend(fallback_warnings)
                    still_unmatched = [
                        f"{game.away_team} @ {game.home_team}"
                        for game in unmatched
                        if game.event_id not in cfb_additions
                    ]
                    if still_unmatched:
                        # Name it. An unmatched game silently blanks every
                        # context field it needs, so it must never be invisible.
                        warnings.append(
                            "No ESPN schedule match for "
                            + "; ".join(sorted(still_unmatched))
                        )

                last_game_date = max(
                    game.commence_time.date() for game in sport_games
                )
                history_date_key = (
                    f"{requested_date.year}0801-"
                    f"{last_game_date.strftime('%Y%m%d')}"
                )

                async def load_cfb_history() -> dict:
                    response = await client.get(
                        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
                        params={"dates": history_date_key, "limit": 1000},
                    )
                    response.raise_for_status()
                    return response.json()

                history_cache_key = (
                    f"ncaaf:season-results:{requested_date.year}:"
                    f"{last_game_date.strftime('%Y%m%d')}"
                )
                if context_cache:
                    cached_history = await context_cache.get_or_refresh(
                        "espn", history_cache_key, requested_date,
                        timedelta(minutes=15), load_cfb_history,
                    )
                    history_payload = cached_history.payload
                    if cached_history.warning:
                        warnings.append(cached_history.warning)
                else:
                    history_payload = await load_cfb_history()

                games_played = college_games_played_context(
                    sport_games, history_payload
                )
                for event_id, values in games_played.items():
                    cfb_additions.setdefault(event_id, {}).update(values)
                additions.update(cfb_additions)
                weather_values, weather_warnings = await _football_weather_context(
                    sport_games, cfb_additions, requested_date, client, context_cache
                )
                for event_id, values in weather_values.items():
                    additions.setdefault(event_id, {}).update(values)
                warnings.extend(weather_warnings)
            else:
                nfl_values, nfl_warnings = await _nfl_context(
                    sport_games, payload, requested_date, client, context_cache
                )
                additions.update(nfl_values)
                warnings.extend(nfl_warnings)
    return additions, warnings


async def _college_directory_fallback(
    games: list[EvaluationGame],
    week: int | None,
    requested_date: date,
    client: httpx.AsyncClient,
    context_cache: SystemContextCache | None,
) -> tuple[dict[str, dict], list[str]]:
    warnings: list[str] = []

    async def load_directory() -> dict:
        response = await client.get(
            "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams",
            params={"limit": 1000},
        )
        response.raise_for_status()
        teams = {
            team["team"]["displayName"]: int(team["team"]["id"])
            for sport in response.json().get("sports", [])
            for league in sport.get("leagues", [])
            for team in league.get("teams", [])
        }
        return {"teams": teams}

    if context_cache:
        cached_directory = await context_cache.get_or_refresh(
            "espn", f"ncaaf:team-directory:{requested_date.year}",
            date(requested_date.year, 1, 1), timedelta(days=7), load_directory,
        )
        if cached_directory.warning:
            warnings.append(cached_directory.warning)
        directory = cached_directory.payload.get("teams", {})
    else:
        directory = (await load_directory()).get("teams", {})
    index = _directory_index(directory)
    ids = {
        resolved
        for game in games
        for name in (game.home_team, game.away_team)
        if (resolved := index.resolve(name)) is not None
    }

    async def load_detail(team_id: int) -> tuple[int, dict]:
        async def loader() -> dict:
            response = await client.get(
                f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_id}"
            )
            response.raise_for_status()
            team = response.json().get("team", {})
            groups = team.get("groups", {})
            return {
                "conference_id": int(groups["id"]) if groups.get("id") else None,
                "parent_group_id": int(groups.get("parent", {}).get("id")) if groups.get("parent", {}).get("id") else None,
            }
        if context_cache:
            cached = await context_cache.get_or_refresh(
                "espn", f"ncaaf:team:{team_id}", date(requested_date.year, 1, 1),
                timedelta(days=7), loader,
            )
            if cached.warning:
                warnings.append(cached.warning)
            return team_id, cached.payload
        return team_id, await loader()

    details = dict(await asyncio.gather(*[load_detail(team_id) for team_id in ids]))
    return college_team_directory_context(games, directory, details, week=week), warnings


async def _football_weather_context(
    games: list[EvaluationGame],
    base_context: dict[str, dict],
    requested_date: date,
    client: httpx.AsyncClient,
    context_cache: SystemContextCache | None,
    today: date | None = None,
) -> tuple[dict[str, dict], list[str]]:
    additions: dict[str, dict] = {}
    warnings: list[str] = []
    today = today or datetime.now(timezone.utc).date()
    for game in games:
        forecast_date = game.commence_time.astimezone(timezone.utc).date()
        if not weather_forecast_available(forecast_date, today):
            continue
        venue = base_context.get(game.event_id, {}).get("venue") or {}
        if venue.get("indoor") is True:
            additions[game.event_id] = {"weather_applicable": False}
            continue
        address = venue.get("address") or {}
        city, state = address.get("city"), address.get("state")
        if not city:
            continue
        venue_key = str(venue.get("id") or f"{city}:{state or ''}")

        async def load_geocode(city: str = city, state: str | None = state) -> dict:
            response = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                # count=100: common city names (Columbia, Columbus, Buffalo)
                # push the right state past a 10-result page.
                params={"name": city, "count": 100, "language": "en", "countryCode": "US"},
            )
            response.raise_for_status()
            return select_geocode_result(response.json().get("results", []), city, state)

        if context_cache:
            coordinates = await context_cache.get_or_refresh(
                "open_meteo", f"geocode:{venue_key}", date(2000, 1, 1),
                timedelta(days=3650), load_geocode,
            )
            if coordinates.warning:
                warnings.append(coordinates.warning)
            coordinate_payload = coordinates.payload
        else:
            coordinate_payload = await load_geocode()
        if not coordinate_payload:
            warnings.append(
                f"No weather: could not place {city}, {state or '??'} "
                f"({game.away_team} @ {game.home_team})"
            )
            continue
        latitude = coordinate_payload["latitude"]
        longitude = coordinate_payload["longitude"]

        async def load_forecast() -> dict:
            response = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude, "longitude": longitude,
                    "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m",
                    "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
                    "timezone": "UTC", "start_date": forecast_date.isoformat(),
                    "end_date": forecast_date.isoformat(),
                },
            )
            response.raise_for_status()
            return response.json()

        if context_cache:
            forecast = await context_cache.get_or_refresh(
                "open_meteo", f"forecast:{venue_key}", forecast_date,
                timedelta(minutes=15), load_forecast,
            )
            if forecast.warning:
                warnings.append(forecast.warning)
            forecast_payload = forecast.payload
        else:
            forecast_payload = await load_forecast()
        try:
            weather = select_kickoff_weather(
                forecast_payload.get("hourly", {}), game.commence_time
            )
        except Exception as exc:
            # Per-game, deliberately: a malformed forecast for one stadium
            # is a gap in one game, never a blackout across the slate.
            detail = str(exc).strip() or type(exc).__name__
            warnings.append(
                f"No weather for {game.away_team} @ {game.home_team}: {detail}"
            )
            continue
        if weather:
            additions[game.event_id] = {"weather_applicable": True, **weather}
    return additions, warnings


async def _nfl_context(
    games: list[EvaluationGame],
    scoreboard: dict,
    requested_date: date,
    client: httpx.AsyncClient,
    context_cache: SystemContextCache | None,
) -> tuple[dict[str, dict], list[str]]:
    warnings: list[str] = []
    teams: dict[int, str] = {}
    for event in scoreboard.get("events", []):
        competition = (event.get("competitions") or [{}])[0]
        for competitor in competition.get("competitors", []):
            team = competitor.get("team", {})
            if team.get("id"):
                teams[int(team["id"])] = team.get("abbreviation") or team["id"]

    async def team_division(team_id: int, abbreviation: str) -> tuple[int, str | None]:
        async def load_team() -> dict:
            response = await client.get(
                f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{abbreviation.lower()}"
            )
            response.raise_for_status()
            return response.json()
        if context_cache:
            cached = await context_cache.get_or_refresh(
                "espn", f"nfl:team:{team_id}", date(requested_date.year, 1, 1),
                timedelta(days=7), load_team,
            )
            if cached.warning:
                warnings.append(cached.warning)
            payload = cached.payload
        else:
            payload = await load_team()
        group_id = payload.get("team", {}).get("groups", {}).get("id")
        return team_id, str(group_id) if group_id is not None else None

    division_pairs = await asyncio.gather(*[
        team_division(team_id, abbreviation) for team_id, abbreviation in teams.items()
    ])
    division_by_team = dict(division_pairs)

    previous_season = requested_date.year - 1
    async def load_playoffs() -> dict:
        response = await client.get(
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
            params={
                "dates": f"{requested_date.year}0101-{requested_date.year}0220",
                "limit": 100,
            },
        )
        response.raise_for_status()
        ids = {
            int(competitor["team"]["id"])
            for event in response.json().get("events", [])
            if event.get("season", {}).get("year") == previous_season
            and event.get("season", {}).get("type") == 3
            for competition in event.get("competitions", [])
            for competitor in competition.get("competitors", [])
        }
        return {"team_ids": sorted(ids)}

    if context_cache:
        playoffs = await context_cache.get_or_refresh(
            "espn", f"nfl:playoffs:{previous_season}", date(previous_season, 1, 1),
            timedelta(days=3650), load_playoffs,
        )
        if playoffs.warning:
            warnings.append(playoffs.warning)
        playoff_payload = playoffs.payload
    else:
        playoff_payload = await load_playoffs()
    playoff_ids = {int(value) for value in playoff_payload.get("team_ids", [])}
    additions = nfl_scoreboard_context(games, scoreboard, division_by_team, playoff_ids)

    if games:
        async def load_harbaugh() -> dict:
            url = "https://www.giants.com/team/coaches-roster/john-harbaugh"
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            if "John Harbaugh" not in response.text:
                return {}
            return {"coach_name": "John Harbaugh", "source_url": url}
        if context_cache:
            coach = await context_cache.get_or_refresh(
                "nfl_official", "coach:new-york-giants", requested_date,
                timedelta(hours=24), load_harbaugh,
            )
            if coach.warning:
                warnings.append(coach.warning)
            coach_payload = coach.payload
        else:
            coach_payload = await load_harbaugh()
        if coach_payload.get("coach_name"):
            for game in games:
                additions.setdefault(game.event_id, {}).update({
                    "home_coach": (
                        coach_payload["coach_name"]
                        if game.home_team == "New York Giants" else "Other head coach"
                    ),
                    "away_coach": (
                        coach_payload["coach_name"]
                        if game.away_team == "New York Giants" else "Other head coach"
                    ),
                })
    return additions, warnings


async def current_context_enricher(
    games: list[EvaluationGame], requested_date: date,
    *, context_cache: SystemContextCache | None = None,
) -> tuple[dict[str, dict], list[str]]:
    """Load each free context source independently so one outage is not global."""
    additions: dict[str, dict] = {}
    warnings: list[str] = []
    for label, provider in (
        ("MLB", mlb_stats_enricher),
        ("football", football_schedule_enricher),
    ):
        try:
            values, provider_warnings = await provider(
                games, requested_date, context_cache=context_cache
            )
            additions.update(values)
            warnings.extend(provider_warnings)
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            warnings.append(f"{label} context unavailable: {detail}")
    return additions, warnings


def resolve_mlb_team_record(
    team_name: str,
    team_ids_by_name: dict[str, int],
    records_by_id: dict[int, dict],
) -> dict:
    team_id = team_ids_by_name.get(_norm(team_name))
    return records_by_id.get(team_id, {}) if team_id is not None else {}


def was_swept_in_previous_home_series(history: list[dict]) -> bool | None:
    """Return sweep status for the most recent completed series in history."""
    if not history:
        return None
    latest = history[-1]
    if not latest.get("was_home"):
        return False
    opponent = latest.get("opponent")
    series: list[dict] = []
    for item in reversed(history):
        if item.get("opponent") != opponent or not item.get("was_home"):
            break
        series.append(item)
    expected = latest.get("series_length")
    numbers = {item.get("series_game_number") for item in series}
    if not expected or expected < 2 or numbers != set(range(1, expected + 1)):
        return None
    return all(not item.get("won") for item in series)


async def mlb_stats_enricher(
    games: list[EvaluationGame], requested_date: date,
    *, context_cache: SystemContextCache | None = None,
) -> tuple[dict[str, dict], list[str]]:
    mlb_games = [game for game in games if game.sport == "mlb"]
    if not mlb_games:
        return {}, []
    start = requested_date - timedelta(days=35)
    params = {
        "sportId": "1", "startDate": start.isoformat(),
        "endDate": requested_date.isoformat(), "hydrate": "team,linescore",
    }
    warnings: list[str] = []
    async with httpx.AsyncClient(timeout=15.0) as client:
        async def load_schedule() -> dict:
            response = await client.get("https://statsapi.mlb.com/api/v1/schedule", params=params)
            response.raise_for_status()
            return response.json()

        async def load_standings() -> dict:
            response = await client.get("https://statsapi.mlb.com/api/v1/standings", params={"leagueId": "103,104", "season": requested_date.year, "date": requested_date.isoformat(), "standingsTypes": "regularSeason"})
            response.raise_for_status()
            return response.json()

        async def load_calendar() -> dict:
            response = await client.get("https://statsapi.mlb.com/api/v1/schedule", params={"sportId": "1", "season": requested_date.year, "gameTypes": "A"})
            response.raise_for_status()
            return response.json()

        if context_cache:
            schedule_cached, standings_cached, calendar_cached = await asyncio.gather(
                context_cache.get_or_refresh("mlb_stats", f"schedule:{start}:{requested_date}", requested_date, timedelta(minutes=5), load_schedule),
                context_cache.get_or_refresh("mlb_stats", f"standings:{requested_date.year}", requested_date, timedelta(minutes=15), load_standings),
                context_cache.get_or_refresh("mlb_stats", f"all_star:{requested_date.year}", date(requested_date.year, 1, 1), timedelta(days=7), load_calendar),
            )
            schedule_payload = schedule_cached.payload
            standings_payload = standings_cached.payload
            calendar_payload = calendar_cached.payload
            warnings.extend(item.warning for item in (schedule_cached, standings_cached, calendar_cached) if item.warning)
        else:
            schedule_payload, standings_payload, calendar_payload = await asyncio.gather(
                load_schedule(), load_standings(), load_calendar()
            )
    schedule_games = [game for day in schedule_payload.get("dates", []) for game in day.get("games", [])]
    team_records: dict[int, dict] = {}
    for record_group in standings_payload.get("records", []):
        division_id = record_group.get("division", {}).get("id")
        for team_record in record_group.get("teamRecords", []):
            wins = int(team_record.get("wins", 0)); losses = int(team_record.get("losses", 0))
            team_records[int(team_record["team"]["id"])] = {
                "win_pct": wins / (wins + losses) if wins + losses else None,
                "division_id": division_id,
            }

    histories: dict[str, list[dict]] = defaultdict(list)
    team_ids_by_name: dict[str, int] = {}
    for sg in schedule_games:
        for side in ("home", "away"):
            team = sg["teams"][side]["team"]
            team_ids_by_name[_norm(team["name"])] = int(team["id"])
        if sg.get("status", {}).get("abstractGameState") != "Final":
            continue
        for side in ("home", "away"):
            entry = sg["teams"][side]
            opponent = "away" if side == "home" else "home"
            histories[_norm(entry["team"]["name"])].append({
                "date": sg.get("officialDate"), "was_home": side == "home",
                "won": bool(entry.get("isWinner")), "runs": int(entry.get("score", 0)),
                "opponent_runs": int(sg["teams"][opponent].get("score", 0)),
                "opponent": _norm(sg["teams"][opponent]["team"]["name"]),
                "series_game_number": sg.get("seriesGameNumber"),
                "series_length": sg.get("gamesInSeries"),
            })
    for history in histories.values():
        history.sort(key=lambda item: item["date"])

    additions: dict[str, dict] = {}
    for game in mlb_games:
        home_key, away_key = _norm(game.home_team), _norm(game.away_team)
        home_rec = resolve_mlb_team_record(game.home_team, team_ids_by_name, team_records)
        away_rec = resolve_mlb_team_record(game.away_team, team_ids_by_name, team_records)
        all_star_dates = [
            day.get("date") for day in calendar_payload.get("dates", [])
            if day.get("games")
        ]
        all_star_date = max(all_star_dates) if all_star_dates else None
        context: dict = {
            "home_win_pct": home_rec.get("win_pct"), "away_win_pct": away_rec.get("win_pct"),
            "is_divisional": bool(home_rec.get("division_id") and home_rec.get("division_id") == away_rec.get("division_id")),
            "after_all_star_break": requested_date.isoformat() > all_star_date if all_star_date else None,
        }
        for side, key in (("home", home_key), ("away", away_key)):
            history = histories.get(key, [])
            previous = history[-1] if history else None
            context[f"{side}_previous_runs_scored"] = previous["runs"] if previous else None
            context[f"{side}_previous_run_margin"] = previous["runs"] - previous["opponent_runs"] if previous else None
            context[f"{side}_won_previous_game"] = previous["won"] if previous else None
            context[f"{side}_previous_game_was_home"] = previous["was_home"] if previous else None
            streak = 0
            if previous:
                wanted = previous["won"]
                for item in reversed(history):
                    if item["won"] != wanted: break
                    streak += 1
            context[f"{side}_winning_streak"] = streak if previous and previous["won"] else 0
            context[f"{side}_losing_streak"] = streak if previous and not previous["won"] else 0
        current = next((sg for sg in schedule_games if _norm(sg["teams"]["home"]["team"]["name"]) == home_key and _norm(sg["teams"]["away"]["team"]["name"]) == away_key and sg.get("officialDate") == requested_date.isoformat()), None)
        if current:
            number = current.get("seriesGameNumber")
            length = current.get("gamesInSeries")
            context["series_game_number"] = number
            context["series_length"] = length
            for side, key, opponent in (("home", home_key, away_key), ("away", away_key, home_key)):
                prior_series = [item for item in histories.get(key, []) if item["opponent"] == opponent]
                context[f"{side}_series_losses"] = sum(not item["won"] for item in prior_series[-max((number or 1) - 1, 0):]) if number and number > 1 else 0
        else:
            context["series_game_number"] = context["series_length"] = None
        context["home_first_game_back"] = context.get("home_previous_game_was_home") is False
        context["away_was_swept_home"] = was_swept_in_previous_home_series(
            histories.get(away_key, [])
        )
        additions[game.event_id] = context
    return additions, warnings
