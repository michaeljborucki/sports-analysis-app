"""coral33 line-time zone detection: the server zone moved Denver -> Eastern
(~2026-10-24) and orphaned every strict-window sport until it was voted from
the data."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from server.odds.books.coral33 import normalizer as nz


@pytest.fixture(autouse=True)
def _reset_zone():
    saved = (nz._CORAL_TZ_NAME, nz._CORAL_TZ)
    yield
    nz._CORAL_TZ_NAME, nz._CORAL_TZ = saved


def _events(*utc_starts):
    return [{"event_id": f"e{i}", "commence_time": s} for i, s in enumerate(utc_starts)]


# 2026-10-25 NFL: 1:00 PM ET = 17:00Z, 4:05 PM ET = 20:05Z, 4:25 PM ET = 20:25Z,
# 9:30 AM ET London game = 13:30Z, 8:20 PM ET SNF = 00:20Z (+1 day).
CACHE = _events("2026-10-25T17:00:00+00:00", "2026-10-25T20:05:00+00:00",
                "2026-10-25T20:25:00+00:00", "2026-10-25T13:30:00+00:00",
                "2026-10-26T00:20:00Z")
ET_LINES = [{"GameDateTime": t} for t in (
    "2026-10-25 13:00:01.000", "2026-10-25 13:00:01.000", "2026-10-25 16:05:01.000",
    "2026-10-25 16:25:01.000", "2026-10-25 09:30:01.000", "2026-10-25 20:20:01.000",
)]


def test_eastern_lines_switch_the_zone_and_parse_onto_cache_times():
    assert nz._CORAL_TZ_NAME == "America/Denver"
    assert nz._parse_coral_datetime("2026-10-25 13:00:01.000") == datetime(
        2026, 10, 25, 19, 0, 1, tzinfo=timezone.utc)          # the 2h-off bug
    assert nz.observe_coral_timezone(ET_LINES, CACHE) == "America/New_York"
    assert nz._parse_coral_datetime("2026-10-25 13:00:01.000") == datetime(
        2026, 10, 25, 17, 0, 1, tzinfo=timezone.utc)


def test_denver_lines_keep_denver():
    lines = [{"GameDateTime": datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
              .astimezone(ZoneInfo("America/Denver")).strftime("%Y-%m-%d %H:%M:01.000")}
             for e in CACHE]
    assert nz.observe_coral_timezone(lines, CACHE) == "America/Denver"


def test_too_few_hits_do_not_switch():
    assert nz.observe_coral_timezone(ET_LINES[:2], CACHE) == "America/Denver"   # 1 distinct hit


def test_no_lines_or_no_events_is_a_no_op():
    assert nz.observe_coral_timezone([], CACHE) == "America/Denver"
    assert nz.observe_coral_timezone(ET_LINES, []) == "America/Denver"
    assert nz.observe_coral_timezone([{"GameDateTime": "junk"}], CACHE) == "America/Denver"


def test_switches_back_when_the_data_does():
    nz.observe_coral_timezone(ET_LINES, CACHE)
    lines = [{"GameDateTime": datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
              .astimezone(ZoneInfo("America/Denver")).strftime("%Y-%m-%d %H:%M:01.000")}
             for e in CACHE]
    assert nz.observe_coral_timezone(lines, CACHE) == "America/Denver"


def test_wide_window_sports_do_not_vote():
    """Soccer (180-min window) times are unreliable — never flip the zone."""
    assert nz.observe_coral_timezone(ET_LINES, CACHE, window_minutes=180) == "America/Denver"
    assert nz.observe_coral_timezone(ET_LINES, CACHE, window_minutes=30) == "America/New_York"


def test_production_default_is_the_users_local_zone():
    import importlib
    from server import config
    assert config.LOCAL_TZ_NAME == "America/New_York"      # LOCAL_TZ unset in tests
    fresh = importlib.reload(nz)
    try:
        assert fresh._CORAL_TZ_NAME == config.LOCAL_TZ_NAME
    finally:
        importlib.reload(nz)
