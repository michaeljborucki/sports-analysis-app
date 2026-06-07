"""Regression tests for the merged ATP+WTA time-sorted slate.

Added 2026-04-24. Before this change, ``main.py daily --tour both`` ran
ATP's entire slate through screen + full-sim before starting WTA. On a
typical slate (~20 matches per tour, ~5 min per full sim) that pushed WTA
processing 60-90 min after ATP, meaning mid-morning WTA matches were often
post-market by the time we got to them.

Fix: merge both tours into a single queue, sort by UTC start time, then
run screening and full-sim in chronological order regardless of tour.
Pre-market alignment is the whole point — there's no point grading a
bet on a match that already started.
"""
from datetime import datetime

from main import _sort_key_by_start_time


def _mk(tour: str, player_a: str, start_time: str, match_id: str = "1") -> dict:
    return {
        "tour": tour, "player_a": player_a, "player_b": "X", "start_time": start_time,
        "match_id": match_id, "player_a_key": "", "player_b_key": "",
    }


def test_sort_key_orders_by_start_time_across_tours():
    matches = [
        _mk("atp", "Later",   "2026-04-24 16:00", "1"),
        _mk("wta", "Earlier", "2026-04-24 09:00", "2"),
        _mk("atp", "Middle",  "2026-04-24 12:00", "3"),
    ]
    matches.sort(key=_sort_key_by_start_time)
    assert [m["player_a"] for m in matches] == ["Earlier", "Middle", "Later"]


def test_sort_key_interleaves_tours_when_times_interleave():
    """Real-world case: morning WTA, mid-day ATP, afternoon WTA should
    interleave, NOT run as 'all ATP then all WTA'."""
    matches = [
        _mk("atp", "ATP-1pm", "2026-04-24 13:00"),
        _mk("wta", "WTA-10am", "2026-04-24 10:00"),
        _mk("atp", "ATP-3pm", "2026-04-24 15:00"),
        _mk("wta", "WTA-2pm", "2026-04-24 14:00"),
        _mk("wta", "WTA-5pm", "2026-04-24 17:00"),
    ]
    matches.sort(key=_sort_key_by_start_time)
    assert [m["player_a"] for m in matches] == [
        "WTA-10am", "ATP-1pm", "WTA-2pm", "ATP-3pm", "WTA-5pm",
    ]


def test_sort_key_pushes_unparseable_start_time_to_end():
    matches = [
        _mk("atp", "Undated", "", "1"),
        _mk("wta", "Dated",   "2026-04-24 14:00", "2"),
        _mk("atp", "Garbage", "not-a-date", "3"),
    ]
    matches.sort(key=_sort_key_by_start_time)
    assert matches[0]["player_a"] == "Dated"
    # Undated + garbage can appear in either order relative to each other,
    # but must come after the dated match.
    assert {matches[1]["player_a"], matches[2]["player_a"]} == {"Undated", "Garbage"}


def test_sort_key_is_stable_for_identical_times():
    """Two matches at the same start time should sort by (tour, match_id)
    deterministically so the same input produces the same order run-to-run."""
    matches = [
        _mk("wta", "Second", "2026-04-24 10:00", "b"),
        _mk("atp", "First",  "2026-04-24 10:00", "a"),
    ]
    matches.sort(key=_sort_key_by_start_time)
    # atp < wta lexicographically, so ATP wins tiebreak
    assert matches[0]["player_a"] == "First"


def test_sort_key_returns_tuple_with_three_components():
    """Defensive: key shape is (datetime, tour_str, match_id_str) so
    comparisons never raise on mixed types."""
    k = _sort_key_by_start_time(_mk("atp", "X", "2026-04-24 10:00", "42"))
    assert isinstance(k, tuple) and len(k) == 3
    assert isinstance(k[0], datetime)
    assert isinstance(k[1], str)
    assert isinstance(k[2], str)


def test_daily_runner_invokes_pipeline_once_for_both_tours():
    """Previous behavior ran ATP then WTA in separate subprocesses. The
    merge-and-sort fix requires a SINGLE subprocess call that handles both
    tours internally — verify daily_runner.main calls run_pipeline once
    when --tour both."""
    import inspect
    from agents import daily_runner
    # daily_runner.main is a click.Command; the actual function is .callback
    src = inspect.getsource(daily_runner.main.callback)
    # The per-tour loop that called run_pipeline for each t in tours is gone.
    # Post-fix, run_pipeline appears at most once in daily_runner.main's body.
    assert src.count("run_pipeline(") == 1, (
        f"Expected run_pipeline to be called once (single merged-slate "
        f"subprocess). Found {src.count('run_pipeline(')} calls — did the "
        f"per-tour loop get reintroduced?"
    )
