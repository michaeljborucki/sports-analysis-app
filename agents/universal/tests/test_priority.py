"""Tests for the universal priority-alerts rule."""
import threading
import time

from universal.priority import run_priority_pipeline, sort_by_first_pitch


def _game(key, fp):
    return {"key": key, "game_date": fp}


# ---------- sort_by_first_pitch ----------

def test_sort_orders_soonest_first():
    games = [
        _game("late", "2026-06-07T23:05:00Z"),
        _game("early", "2026-06-07T17:05:00Z"),
        _game("mid", "2026-06-07T20:05:00Z"),
    ]
    keys = [g["key"] for g in sort_by_first_pitch(games)]
    assert keys == ["early", "mid", "late"]


def test_sort_places_missing_and_unparseable_times_last():
    games = [
        _game("no_time", None),
        _game("known", "2026-06-07T17:05:00Z"),
        _game("garbage", "not-a-timestamp"),
    ]
    keys = [g["key"] for g in sort_by_first_pitch(games)]
    assert keys[0] == "known"
    assert set(keys[1:]) == {"no_time", "garbage"}


def test_sort_is_stable_for_unknown_times():
    games = [_game("a", None), _game("b", None), _game("c", None)]
    assert [g["key"] for g in sort_by_first_pitch(games)] == ["a", "b", "c"]


def test_sort_honors_custom_time_field():
    games = [_game("late", None), _game("early", None)]
    games[0]["fp"] = "2026-06-07T23:00:00Z"
    games[1]["fp"] = "2026-06-07T18:00:00Z"
    keys = [g["key"] for g in sort_by_first_pitch(games, time_field="fp")]
    assert keys == ["early", "late"]


# ---------- run_priority_pipeline ----------

def _key(g):
    return g["key"]


def test_processes_in_soonest_first_order_single_worker():
    games = [
        _game("late", "2026-06-07T23:00:00Z"),
        _game("early", "2026-06-07T17:00:00Z"),
        _game("mid", "2026-06-07T20:00:00Z"),
    ]
    order = []

    def process(game):
        order.append(game["key"])
        return {"bets": []}

    run_priority_pipeline(games, process, get_game_key=_key, max_workers=1)
    assert order == ["early", "mid", "late"]


def test_alerts_fire_only_for_games_with_bets():
    games = [_game("a", "2026-06-07T17:00:00Z"), _game("b", "2026-06-07T18:00:00Z")]

    def process(game):
        return {"bets": [1, 2]} if game["key"] == "a" else {"bets": []}

    alerted = []
    summary = run_priority_pipeline(
        games, process, get_game_key=_key,
        send_alert=lambda gk, result: alerted.append(gk),
        max_workers=1,
    )
    assert alerted == ["a"]
    assert summary == {"processed": 2, "alerted": 1, "errors": 0, "total_bets": 2}


def test_alert_fires_immediately_not_after_whole_slate():
    """The early game's alert must land before the slow late game finishes."""
    slow_started = threading.Event()
    alert_times = {}
    finish_times = {}

    def process(game):
        if game["key"] == "fast":
            return {"bets": ["x"]}
        # slow game blocks until released
        slow_started.set()
        time.sleep(0.5)
        finish_times["slow"] = time.perf_counter()
        return {"bets": []}

    def alert(gk, result):
        alert_times[gk] = time.perf_counter()

    # Two workers so fast and slow run concurrently; fast finishes ~instantly.
    run_priority_pipeline(
        [_game("slow", "2026-06-07T17:00:00Z"), _game("fast", "2026-06-07T18:00:00Z")],
        process, get_game_key=_key, send_alert=alert, max_workers=2,
    )
    assert "fast" in alert_times
    assert slow_started.is_set()
    # The fast alert fired before the slow game finished — i.e. we did not wait
    # for the full slate before alerting.
    assert alert_times["fast"] < finish_times["slow"]


def test_one_failing_game_does_not_sink_the_slate():
    games = [_game("boom", "2026-06-07T17:00:00Z"), _game("ok", "2026-06-07T18:00:00Z")]
    errors = []

    def process(game):
        if game["key"] == "boom":
            raise RuntimeError("kaboom")
        return {"bets": ["b"]}

    alerted = []
    summary = run_priority_pipeline(
        games, process, get_game_key=_key,
        send_alert=lambda gk, r: alerted.append(gk),
        on_error=lambda g, exc: errors.append((g["key"], str(exc))),
        max_workers=1,
    )
    assert alerted == ["ok"]
    assert errors == [("boom", "kaboom")]
    assert summary["processed"] == 1
    assert summary["errors"] == 1
    assert summary["total_bets"] == 1


def test_alert_failure_does_not_abort_processing():
    games = [_game("a", "2026-06-07T17:00:00Z"), _game("b", "2026-06-07T18:00:00Z")]

    def process(game):
        return {"bets": ["x"]}

    def boom_alert(gk, result):
        raise RuntimeError("discord down")

    summary = run_priority_pipeline(
        games, process, get_game_key=_key, send_alert=boom_alert, max_workers=1,
    )
    # Both games still processed; alert failures are swallowed (not counted).
    assert summary["processed"] == 2
    assert summary["alerted"] == 0
    assert summary["total_bets"] == 2


def test_on_complete_called_for_every_returning_game():
    games = [_game("a", "2026-06-07T17:00:00Z"), _game("b", "2026-06-07T18:00:00Z")]
    completed = []
    run_priority_pipeline(
        games, lambda g: {"bets": []}, get_game_key=_key,
        on_complete=lambda g, r: completed.append(g["key"]), max_workers=1,
    )
    assert sorted(completed) == ["a", "b"]


def test_empty_slate_returns_zeroed_summary():
    summary = run_priority_pipeline([], lambda g: {"bets": []}, get_game_key=_key)
    assert summary == {"processed": 0, "alerted": 0, "errors": 0, "total_bets": 0}


def test_custom_get_bets_extractor():
    games = [_game("a", "2026-06-07T17:00:00Z")]
    alerted = []
    run_priority_pipeline(
        games, lambda g: ["raw", "bets"], get_game_key=_key,
        get_bets=lambda result: result,  # result IS the bets list
        send_alert=lambda gk, r: alerted.append(gk), max_workers=1,
    )
    assert alerted == ["a"]
