"""Fetch match results for grading bets."""
import logging
import requests
from datetime import date
from config import API_TENNIS_KEY, API_TENNIS_BASE

logger = logging.getLogger("mirofish.scrapers.scores")


def get_match_results(game_date: str = None, tour: str = "atp") -> list[dict]:
    if game_date is None:
        game_date = date.today().isoformat()
    if not API_TENNIS_KEY:
        logger.warning("API_TENNIS_KEY not set")
        return []
    params = {"method": "get_fixtures", "APIkey": API_TENNIS_KEY, "date_start": game_date, "date_stop": game_date}
    try:
        resp = requests.get(API_TENNIS_BASE, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Scores fetch error: %s", e)
        return []

    tour_filter = tour.lower()
    results = []
    events = data.get("result", [])
    if not isinstance(events, list):
        events = []
    for event in events:
        event_type = event.get("event_type_type", "").lower()
        if tour_filter not in event_type or "doubles" in event_type:
            continue
        status = event.get("event_status", "")
        if status.lower() != "finished":
            continue
        score_str = event.get("event_final_result", "")
        player_a = event.get("event_first_player", "")
        player_b = event.get("event_second_player", "")
        sets_a, sets_b = _parse_sets_summary(score_str)
        games_a, games_b = _parse_games_from_pbp(event.get("pointbypoint") or [])

        winner_tag = event.get("event_winner", "")
        if winner_tag == "First Player":
            winner = player_a
        elif winner_tag == "Second Player":
            winner = player_b
        else:
            winner = player_a if sets_a > sets_b else player_b

        results.append({
            "player_a": player_a, "player_b": player_b,
            "score": score_str, "winner": winner,
            "total_games": games_a + games_b,
            "games_a": games_a, "games_b": games_b,
            "sets_a": sets_a, "sets_b": sets_b,
            "retired": "ret" in score_str.lower() or "w/o" in score_str.lower(),
        })
    logger.info("Scores: %d completed %s matches on %s", len(results), tour.upper(), game_date)
    return results


def _parse_sets_summary(score: str) -> tuple[int, int]:
    """Parse api-tennis ``event_final_result`` sets summary like ``"2 - 1"``."""
    if not score:
        return 0, 0
    parts = score.replace(" ", "").split("-")
    if len(parts) != 2:
        return 0, 0
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0


def _parse_games_from_pbp(pbp: list[dict]) -> tuple[int, int]:
    """Walk ``pointbypoint`` entries to total games won per player.

    Each entry's ``score`` is the running game count within its set after that
    game finishes, so the last entry per ``set_number`` holds the final set
    score. Summing those gives match game totals.
    """
    last_per_set: dict[str, str] = {}
    order: list[str] = []
    for game in pbp:
        set_key = game.get("set_number", "")
        if not set_key:
            continue
        if set_key not in last_per_set:
            order.append(set_key)
        last_per_set[set_key] = game.get("score", "")

    games_a = 0
    games_b = 0
    for set_key in order:
        final = last_per_set[set_key].replace(" ", "").split("-")
        if len(final) != 2:
            continue
        try:
            games_a += int(final[0])
            games_b += int(final[1])
        except ValueError:
            continue
    return games_a, games_b
