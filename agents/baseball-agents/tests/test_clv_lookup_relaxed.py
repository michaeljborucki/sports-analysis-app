"""Regression tests for find_closing_line: line-relaxed lookup + props.

Three behaviors to pin:
1. Exact-line match wins when present.
2. Line-relaxed fallback picks the closest available line on a mismatch.
3. Player-name disambiguation for prop lookups.
"""
import pandas as pd
import pytest

from scrapers import closing_lines as cl


@pytest.fixture
def populated_csv(tmp_path, monkeypatch):
    """A small in-memory closing_lines.csv with mainlines + props."""
    csv_path = tmp_path / "closing_lines.csv"
    rows = [
        # Mainlines for NYY@BOS on 2026-04-15
        {"date": "2026-04-15", "game": "NYY@BOS", "market": "moneyline",
         "side": "home", "line": "", "close_odds": -150,
         "close_prob_devig": 0.6, "captured_at": "2026-04-15T22:55:00Z",
         "player_name": ""},
        {"date": "2026-04-15", "game": "NYY@BOS", "market": "total",
         "side": "over", "line": "8.5", "close_odds": -110,
         "close_prob_devig": 0.524, "captured_at": "2026-04-15T22:55:00Z",
         "player_name": ""},
        {"date": "2026-04-15", "game": "NYY@BOS", "market": "total",
         "side": "under", "line": "8.5", "close_odds": -110,
         "close_prob_devig": 0.476, "captured_at": "2026-04-15T22:55:00Z",
         "player_name": ""},
        # Total at a different line — for line-relaxed fallback
        {"date": "2026-04-15", "game": "NYY@BOS", "market": "total",
         "side": "over", "line": "9.0", "close_odds": -105,
         "close_prob_devig": 0.512, "captured_at": "2026-04-15T22:55:00Z",
         "player_name": ""},
        # Prop with player_name
        {"date": "2026-04-15", "game": "NYY@BOS", "market": "batter_hits",
         "side": "over", "line": "0.5", "close_odds": -200,
         "close_prob_devig": 0.667, "captured_at": "2026-04-15T22:55:00Z",
         "player_name": "Aaron Judge"},
        {"date": "2026-04-15", "game": "NYY@BOS", "market": "batter_hits",
         "side": "over", "line": "0.5", "close_odds": -150,
         "close_prob_devig": 0.6, "captured_at": "2026-04-15T22:55:00Z",
         "player_name": "Mike Trout"},
        # Two captures for the same key — latest should win
        {"date": "2026-04-15", "game": "NYY@BOS", "market": "moneyline",
         "side": "home", "line": "", "close_odds": -160,
         "close_prob_devig": 0.615, "captured_at": "2026-04-15T22:30:00Z",
         "player_name": ""},
    ]
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    monkeypatch.setattr(cl, "CLOSING_LINES_CSV", str(csv_path))
    return csv_path


# ---------------------------------------------------------------------------
# Mainline lookups
# ---------------------------------------------------------------------------

class TestExactLineMatch:
    def test_total_over_exact(self, populated_csv):
        result = cl.find_closing_line("2026-04-15", "NYY@BOS", "total", "over", line=8.5)
        assert result is not None
        assert result["close_odds"] == -110
        assert float(result["line"]) == 8.5

    def test_moneyline_no_line(self, populated_csv):
        result = cl.find_closing_line("2026-04-15", "NYY@BOS", "moneyline", "home")
        assert result is not None
        assert result["close_odds"] == -150  # latest by captured_at

    def test_no_match_returns_none(self, populated_csv):
        result = cl.find_closing_line("2026-04-15", "NYY@BOS", "moneyline", "away")
        assert result is None

    def test_wrong_game_returns_none(self, populated_csv):
        result = cl.find_closing_line("2026-04-15", "BOS@NYY", "moneyline", "home")
        assert result is None

    def test_wrong_date_returns_none(self, populated_csv):
        result = cl.find_closing_line("2026-04-16", "NYY@BOS", "moneyline", "home")
        assert result is None


# ---------------------------------------------------------------------------
# Line-relaxed fallback (the bug we want to never re-introduce)
# ---------------------------------------------------------------------------

class TestLineRelaxedFallback:
    def test_no_exact_line_picks_closest(self, populated_csv):
        """We bet over 9.5; CSV has 8.5 and 9.0 → relaxed should pick 9.0 (closer)."""
        result = cl.find_closing_line("2026-04-15", "NYY@BOS", "total", "over", line=9.5)
        assert result is not None
        assert float(result["line"]) == 9.0, "should pick closest available line"
        assert result["close_odds"] == -105

    def test_relaxed_picks_lower_when_closer(self, populated_csv):
        """We bet over 8.0; CSV has 8.5 and 9.0 → relaxed should pick 8.5."""
        result = cl.find_closing_line("2026-04-15", "NYY@BOS", "total", "over", line=8.0)
        assert result is not None
        assert float(result["line"]) == 8.5


# ---------------------------------------------------------------------------
# Prop lookups (player_name disambiguation)
# ---------------------------------------------------------------------------

class TestPropLookup:
    def test_finds_correct_player(self, populated_csv):
        result = cl.find_closing_line("2026-04-15", "NYY@BOS", "batter_hits",
                                      "over", line=0.5, player_name="Aaron Judge")
        assert result is not None
        assert result["close_odds"] == -200

    def test_finds_other_player(self, populated_csv):
        result = cl.find_closing_line("2026-04-15", "NYY@BOS", "batter_hits",
                                      "over", line=0.5, player_name="Mike Trout")
        assert result is not None
        assert result["close_odds"] == -150

    def test_unknown_player_returns_none(self, populated_csv):
        result = cl.find_closing_line("2026-04-15", "NYY@BOS", "batter_hits",
                                      "over", line=0.5, player_name="Unknown Player")
        assert result is None

    def test_missing_player_name_doesnt_match_prop(self, populated_csv):
        """A mainline-style call (no player_name) must not match a prop row."""
        result = cl.find_closing_line("2026-04-15", "NYY@BOS", "batter_hits",
                                      "over", line=0.5)
        assert result is None
