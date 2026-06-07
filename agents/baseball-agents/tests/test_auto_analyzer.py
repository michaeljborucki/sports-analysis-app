"""Regression tests for agents.auto_analyzer decision logic.

The auto-analyzer must:
1. Launch only when an unanalyzed game is within ANALYZE_LEAD_MINUTES (2h).
2. Skip games that are already analyzed.
3. Skip games whose first pitch is in the past (already started).
4. Emit the shutoff signal when no future unanalyzed games remain today.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from agents import auto_analyzer as aa


def _mk_game(away, home, fp_iso):
    return {"away_team": away, "home_team": home, "game_date": fp_iso,
            "game_pk": hash((away, home, fp_iso)) % 100000}


# ---------------------------------------------------------------------------
# _games_due_for_analysis
# ---------------------------------------------------------------------------

class TestGamesDue:
    def test_due_within_2h(self):
        now = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
        # First pitch in 90 min — within window
        games = [_mk_game("BAL", "KC", "2026-04-21T00:30:00Z")]
        with patch("agents.auto_analyzer.get_probable_starters", return_value=games), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}):
            due = aa._games_due_for_analysis(now_utc=now)
        assert len(due) == 1
        assert due[0]["game_key"] == "BAL@KC"

    def test_skip_too_early(self):
        now = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
        # First pitch in 3h — outside 2h window
        games = [_mk_game("LAD", "COL", "2026-04-21T02:00:00Z")]
        with patch("agents.auto_analyzer.get_probable_starters", return_value=games), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}):
            due = aa._games_due_for_analysis(now_utc=now)
        assert len(due) == 0

    def test_skip_already_started(self):
        now = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
        # First pitch was 30 min ago
        games = [_mk_game("HOU", "CLE", "2026-04-20T22:30:00Z")]
        with patch("agents.auto_analyzer.get_probable_starters", return_value=games), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}):
            due = aa._games_due_for_analysis(now_utc=now)
        assert len(due) == 0

    def test_skip_already_analyzed(self):
        now = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
        games = [_mk_game("BAL", "KC", "2026-04-21T00:30:00Z")]
        analyzed = {"BAL@KC": "flagged"}
        with patch("agents.auto_analyzer.get_probable_starters", return_value=games), \
             patch("agents.auto_analyzer.load_analyzed", return_value=analyzed):
            due = aa._games_due_for_analysis(now_utc=now)
        assert len(due) == 0

    def test_returns_multiple_due_games(self):
        now = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
        games = [
            _mk_game("BAL", "KC", "2026-04-21T00:30:00Z"),    # T+90 — due
            _mk_game("PHI", "CHC", "2026-04-21T00:30:00Z"),   # T+90 — due
            _mk_game("LAD", "COL", "2026-04-21T03:00:00Z"),   # T+240 — too early
        ]
        with patch("agents.auto_analyzer.get_probable_starters", return_value=games), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}):
            due = aa._games_due_for_analysis(now_utc=now)
        assert len(due) == 2
        keys = sorted(g["game_key"] for g in due)
        assert keys == ["BAL@KC", "PHI@CHC"]


# ---------------------------------------------------------------------------
# _has_future_unanalyzed_games  →  drives auto-shutoff decision
# ---------------------------------------------------------------------------

class TestFutureUnanalyzed:
    def test_no_games_at_all(self):
        with patch("agents.auto_analyzer.get_probable_starters", return_value=[]), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}):
            assert aa._has_future_unanalyzed_games() is False

    def test_all_games_analyzed(self):
        now = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
        games = [_mk_game("BAL", "KC", "2026-04-21T00:30:00Z")]
        analyzed = {"BAL@KC": "flagged"}
        with patch("agents.auto_analyzer.get_probable_starters", return_value=games), \
             patch("agents.auto_analyzer.load_analyzed", return_value=analyzed):
            assert aa._has_future_unanalyzed_games(now_utc=now) is False

    def test_unanalyzed_in_future(self):
        now = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
        games = [_mk_game("LAD", "COL", "2026-04-21T03:00:00Z")]
        with patch("agents.auto_analyzer.get_probable_starters", return_value=games), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}):
            # >2h away but still in the future → True (not yet shutoff)
            assert aa._has_future_unanalyzed_games(now_utc=now) is True

    def test_unanalyzed_in_past_doesnt_block_shutoff(self):
        """Edge case: a game started without us catching it. Don't block shutoff."""
        now = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
        games = [_mk_game("X", "Y", "2026-04-20T20:00:00Z")]  # 3h ago
        with patch("agents.auto_analyzer.get_probable_starters", return_value=games), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}):
            assert aa._has_future_unanalyzed_games(now_utc=now) is False

    def test_mixed_past_and_future(self):
        now = datetime(2026, 4, 20, 23, 0, tzinfo=timezone.utc)
        games = [
            _mk_game("BAL", "KC", "2026-04-21T03:00:00Z"),    # future, unanalyzed
            _mk_game("HOU", "CLE", "2026-04-20T20:00:00Z"),  # past, unanalyzed
        ]
        with patch("agents.auto_analyzer.get_probable_starters", return_value=games), \
             patch("agents.auto_analyzer.load_analyzed", return_value={}):
            assert aa._has_future_unanalyzed_games(now_utc=now) is True


# ---------------------------------------------------------------------------
# Pin the lead-minutes constant
# ---------------------------------------------------------------------------

def test_analyze_lead_minutes_pinned():
    """Changing this would shift the entire trigger schedule across all crons."""
    assert aa.ANALYZE_LEAD_MINUTES == 120
