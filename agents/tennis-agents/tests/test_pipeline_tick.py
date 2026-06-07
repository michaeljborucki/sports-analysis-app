"""Tests for the event-driven pipeline tick + grade tick."""
from datetime import datetime, timedelta, timezone

import pytest


def _match(commence_dt: datetime, pa="A", pb="B", tour="atp") -> dict:
    return {
        "player_a": pa,
        "player_b": pb,
        "tour": tour,
        "start_time": commence_dt.strftime("%Y-%m-%d %H:%M"),
        "commence_iso": commence_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def test_window_includes_match_8h_out():
    from scripts.pipeline_tick import find_dates_in_window

    now = datetime(2026, 4, 21, 3, 0, tzinfo=timezone.utc)
    matches = [_match(now + timedelta(hours=8))]
    dates = find_dates_in_window(matches, now=now, window_start_hours=7, window_end_hours=9)
    assert dates == ["2026-04-21"]


def test_window_excludes_match_5h_out():
    from scripts.pipeline_tick import find_dates_in_window

    now = datetime(2026, 4, 21, 3, 0, tzinfo=timezone.utc)
    matches = [_match(now + timedelta(hours=5))]
    dates = find_dates_in_window(matches, now=now, window_start_hours=7, window_end_hours=9)
    assert dates == []


def test_window_excludes_match_10h_out():
    from scripts.pipeline_tick import find_dates_in_window

    now = datetime(2026, 4, 21, 3, 0, tzinfo=timezone.utc)
    matches = [_match(now + timedelta(hours=10))]
    dates = find_dates_in_window(matches, now=now, window_start_hours=7, window_end_hours=9)
    assert dates == []


def test_window_groups_same_date_matches_dedup():
    from scripts.pipeline_tick import find_dates_in_window

    now = datetime(2026, 4, 21, 3, 0, tzinfo=timezone.utc)
    matches = [
        _match(now + timedelta(hours=7, minutes=30)),
        _match(now + timedelta(hours=8, minutes=15)),
        _match(now + timedelta(hours=9)),  # exactly 9h — inclusive upper bound
    ]
    dates = find_dates_in_window(matches, now=now, window_start_hours=7, window_end_hours=9)
    assert dates == ["2026-04-21"]


def test_dedup_against_runs_log(tmp_path):
    from scripts.pipeline_tick import filter_already_run

    runs_log_path = tmp_path / "pipeline_runs.json"
    runs_log_path.write_text('{"2026-04-21": "2026-04-21T03:00:00Z"}')

    pending = filter_already_run(["2026-04-21", "2026-04-22"], runs_log_path=str(runs_log_path))
    assert pending == ["2026-04-22"]


def test_record_run_writes_log(tmp_path):
    from scripts.pipeline_tick import record_run

    runs_log_path = tmp_path / "pipeline_runs.json"
    record_run("2026-04-21", runs_log_path=str(runs_log_path))
    import json
    data = json.loads(runs_log_path.read_text())
    assert "2026-04-21" in data


def test_grade_date_is_yesterday_local():
    from scripts.grade_tick import compute_grade_date

    now_local = datetime(2026, 4, 21, 4, 0)  # 4 AM local
    assert compute_grade_date(now_local) == "2026-04-20"


def test_grade_tick_rejects_today():
    from scripts.grade_tick import ensure_strictly_past

    now_local = datetime(2026, 4, 21, 4, 0)
    # Grading today should raise.
    with pytest.raises(ValueError):
        ensure_strictly_past("2026-04-21", now_local)
    with pytest.raises(ValueError):
        ensure_strictly_past("2026-04-22", now_local)


def test_grade_tick_accepts_yesterday():
    from scripts.grade_tick import ensure_strictly_past

    now_local = datetime(2026, 4, 21, 4, 0)
    ensure_strictly_past("2026-04-20", now_local)  # should not raise
    ensure_strictly_past("2025-12-31", now_local)
