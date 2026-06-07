"""Regression tests for agents.analyzed_games state tracker.

The pipeline marks each screened game in this CSV; the auto-analyzer reads
it to skip already-processed work. Schema and round-trip behavior must stay
consistent or the pipeline will redo work (cost) or skip needed work (gap).
"""
import pytest

from agents import analyzed_games as ag


@pytest.fixture
def tmp_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "analyzed_games.csv"
    monkeypatch.setattr(ag, "_CSV", str(csv_path))
    return csv_path


# ---------------------------------------------------------------------------
# Round-trip: mark + load
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_empty_returns_empty_dict(self, tmp_csv):
        assert ag.load_analyzed("2026-04-20") == {}

    def test_single_mark_loads(self, tmp_csv):
        ag.mark_analyzed("2026-04-20", "BAL@KC", "flagged")
        result = ag.load_analyzed("2026-04-20")
        assert result == {"BAL@KC": "flagged"}

    def test_multiple_marks_load(self, tmp_csv):
        ag.mark_analyzed("2026-04-20", "BAL@KC", "flagged")
        ag.mark_analyzed("2026-04-20", "PHI@CHC", "no_edge")
        ag.mark_analyzed("2026-04-20", "DET@BOS", "no_odds")
        result = ag.load_analyzed("2026-04-20")
        assert result == {"BAL@KC": "flagged", "PHI@CHC": "no_edge", "DET@BOS": "no_odds"}

    def test_date_isolation(self, tmp_csv):
        ag.mark_analyzed("2026-04-20", "BAL@KC", "flagged")
        ag.mark_analyzed("2026-04-21", "ATL@WSH", "flagged")
        assert ag.load_analyzed("2026-04-20") == {"BAL@KC": "flagged"}
        assert ag.load_analyzed("2026-04-21") == {"ATL@WSH": "flagged"}

    def test_unknown_date_returns_empty(self, tmp_csv):
        ag.mark_analyzed("2026-04-20", "BAL@KC", "flagged")
        assert ag.load_analyzed("2026-04-21") == {}


# ---------------------------------------------------------------------------
# Latest-status semantics
# ---------------------------------------------------------------------------

class TestLatestStatus:
    def test_re_marking_keeps_latest(self, tmp_csv):
        """If a game is marked twice (e.g. pipeline re-run on the same day),
        the latest status wins on load. Earlier status is still in CSV history."""
        ag.mark_analyzed("2026-04-20", "BAL@KC", "no_odds")
        ag.mark_analyzed("2026-04-20", "BAL@KC", "flagged")
        assert ag.load_analyzed("2026-04-20") == {"BAL@KC": "flagged"}


# ---------------------------------------------------------------------------
# Schema contract
# ---------------------------------------------------------------------------

def test_columns_pinned():
    """If columns drift, the auto-analyzer's load_analyzed will silently break."""
    assert ag._COLUMNS == ["date", "game", "status", "analyzed_at"]


def test_status_enum_documented():
    """The AnalyzedStatus type alias documents the status values used today.
    Pipeline.py emits these — adding a new status without updating downstream
    consumers will silently break filtering.
    """
    expected_statuses = {"flagged", "no_edge", "no_odds", "screen_error", "screen_timeout"}
    # Mark each one to confirm the function accepts them
    for s in expected_statuses:
        ag.mark_analyzed("2026-01-01", f"X@Y_{s}", s)
