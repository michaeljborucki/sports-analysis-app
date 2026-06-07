"""Regression tests pinning the pre-market-only invariant.

Once play begins, bookmakers roll to live odds and our pre-match probability
edges become meaningless. Logging a bet on an already-started match would
produce garbage CLV the next day. These tests pin the filter so it can't
silently regress.
"""
from datetime import datetime, timedelta, timezone

from main import _match_has_started


def _future(minutes_ahead: int = 60) -> str:
    """Return an ISO-8601 Z-suffixed UTC timestamp N minutes in the future."""
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _past(minutes_ago: int = 30) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ==========================================================================
#  _match_has_started — core filter logic
# ==========================================================================

class TestMatchHasStarted:
    def test_future_match_not_started(self):
        assert _match_has_started({"start_time": _future(60)}) is False

    def test_past_match_already_started(self):
        assert _match_has_started({"start_time": _past(30)}) is True

    def test_right_now_considered_started(self):
        """A match whose commence_time is exactly ``now`` should be treated as
        started — book has almost certainly moved to live."""
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _match_has_started({"start_time": now_iso}) is True

    def test_missing_start_time_does_not_filter(self):
        """No start_time → don't drop the match (schedule scraper is the
        authority on what matches exist; a missing time shouldn't cost
        coverage)."""
        assert _match_has_started({}) is False
        assert _match_has_started({"start_time": ""}) is False

    def test_unparseable_start_time_does_not_filter(self):
        assert _match_has_started({"start_time": "not-a-date"}) is False

    def test_accepts_both_z_and_utc_offset(self):
        """Schedule scrapers may return either format."""
        future_z = _future(60)
        future_offset = future_z.replace("Z", "+00:00")
        assert _match_has_started({"start_time": future_z}) is False
        assert _match_has_started({"start_time": future_offset}) is False

    def test_accepts_injected_now(self):
        """``now_utc`` param lets tests pin behavior deterministically."""
        fixed_now = datetime(2026, 4, 23, 14, 0, 0, tzinfo=timezone.utc)
        # Match at 14:00 with now=14:00 → started
        assert _match_has_started(
            {"start_time": "2026-04-23T14:00:00Z"}, now_utc=fixed_now
        ) is True
        # Match at 15:00 with now=14:00 → not started
        assert _match_has_started(
            {"start_time": "2026-04-23T15:00:00Z"}, now_utc=fixed_now
        ) is False


# ==========================================================================
#  Screener + simulator check for the filter
# ==========================================================================

def test_screener_bails_on_started_match():
    """_screen_one_match must return early with status 'already_started'
    for matches whose commence_time has passed."""
    from main import _screen_one_match

    started_match = {
        "player_a": "A. Player", "player_b": "B. Player",
        "start_time": _past(60),  # started 1h ago
        "surface": "hard", "tournament": "Test", "round": "R1",
        "indoor_outdoor": "outdoor",
    }
    r = _screen_one_match(started_match, odds_list=[], current_tour="atp",
                          game_date_arg="2026-04-23")
    assert r["status"] == "already_started"


def test_simulator_bails_on_started_match():
    """_simulate_one_match must return early with 'already_started' even if
    screening let the match through."""
    from main import _simulate_one_match

    r = _simulate_one_match(
        match_key="A. Player vs B. Player",
        brief="irrelevant — shouldn't be sim'd",
        match_data={"odds": {}},
        bet_date="2026-04-23",
        start_time=_past(30),
        current_tour="atp",
    )
    assert r["status"] == "already_started"
    assert r["bets"] == []


def test_simulator_proceeds_for_future_match(monkeypatch):
    """Future match should NOT be short-circuited by the filter.
    Mocked run_mirofish returns None → sim_failed path, proving the filter
    wasn't what caused the early return."""
    from main import _simulate_one_match

    import simulate
    monkeypatch.setattr(simulate, "run_mirofish", lambda *a, **kw: None)

    r = _simulate_one_match(
        match_key="A. Player vs B. Player",
        brief="test",
        match_data={"odds": {}},
        bet_date="2026-04-23",
        start_time=_future(60),  # 1h in future
        current_tour="atp",
    )
    # Must NOT be already_started; must be sim_failed (from mocked None)
    assert r["status"] == "sim_failed"
