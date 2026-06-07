"""Regression tests for CLV in grade alerts.

Two behaviors:
1. Grade message format includes the CLV column (cents, with sign).
2. The grader's _ensure_clv_for_date triggers a historical backfill ONLY
   when some bets are missing CLV; idempotent + zero cost when fully covered.
"""
from unittest.mock import patch
import pandas as pd
import pytest

from notify.format import _format_grade_line, _GRADE_HEADER_LINE
from agents import results_grader as rg


# ---------------------------------------------------------------------------
# Grade message format
# ---------------------------------------------------------------------------

class TestGradeMessageCLV:
    def test_header_includes_clv_column(self):
        assert "CLV" in _GRADE_HEADER_LINE

    def test_line_renders_positive_clv(self):
        bet = {
            "bet_type": "moneyline", "side": "home", "odds": -150,
            "result": "W", "clv_cents": 5,
        }
        line = _format_grade_line(bet)
        assert "+5" in line

    def test_line_renders_negative_clv(self):
        bet = {
            "bet_type": "total", "side": "over 8.5", "odds": -110,
            "result": "L", "clv_cents": -3,
        }
        line = _format_grade_line(bet)
        assert "-3" in line

    def test_line_renders_zero_clv_with_sign(self):
        bet = {
            "bet_type": "nrfi", "side": "NRFI", "odds": -110,
            "result": "P", "clv_cents": 0,
        }
        line = _format_grade_line(bet)
        # +0 displayed for zero CLV (sign-explicit)
        assert "+0" in line

    def test_missing_clv_renders_double_dash(self):
        bet = {
            "bet_type": "moneyline", "side": "home", "odds": -150,
            "result": "W",  # no clv_cents key
        }
        line = _format_grade_line(bet)
        assert "--" in line

    def test_nan_clv_renders_double_dash(self):
        """When CLV is NaN (CSV-loaded missing value), render as `--`."""
        bet = {
            "bet_type": "total", "side": "over 8.5", "odds": -110,
            "result": "L", "clv_cents": float("nan"),
        }
        line = _format_grade_line(bet)
        assert "--" in line

    def test_string_clv_renders_correctly(self):
        """CSV-loaded values come back as strings — must coerce to int."""
        bet = {
            "bet_type": "moneyline", "side": "home", "odds": -150,
            "result": "W", "clv_cents": "5",
        }
        line = _format_grade_line(bet)
        assert "+5" in line


# ---------------------------------------------------------------------------
# _ensure_clv_for_date — only backfills when there's a gap
# ---------------------------------------------------------------------------

class TestEnsureClvForDate:
    def test_no_op_when_all_bets_have_clv(self, monkeypatch):
        """When every graded bet already has close_odds, no backfill should run."""
        df = pd.DataFrame([
            {"date": "2026-04-19", "game": "BAL@KC", "bet_type": "total",
             "side": "under 9.0", "odds": -113, "sim_prob": 0.6, "edge": 0.12,
             "kelly_pct": 0.04, "result": "W", "profit": 0.88,
             "market_prob": 0.48, "close_odds": -115, "close_prob": 0.535,
             "clv_cents": 2, "clv_pct": 0.01},
        ])
        monkeypatch.setattr(rg, "load_bets", lambda: df)
        # Patch the imported-inside-function reference
        with patch("scrapers.closing_lines.historical_backfill_date") as mock_bf:
            applied = rg._ensure_clv_for_date("2026-04-19")
        mock_bf.assert_not_called()
        assert applied == 0

    def test_no_op_when_no_settled_bets(self, monkeypatch):
        """Pending bets (no result yet) don't trigger backfill."""
        df = pd.DataFrame([
            {"date": "2026-04-20", "game": "BAL@KC", "bet_type": "total",
             "side": "under 9.0", "odds": -113, "sim_prob": 0.6, "edge": 0.12,
             "kelly_pct": 0.04, "result": "", "profit": "",
             "market_prob": 0.48, "close_odds": "", "close_prob": "",
             "clv_cents": "", "clv_pct": ""},
        ])
        monkeypatch.setattr(rg, "load_bets", lambda: df)
        with patch("scrapers.closing_lines.historical_backfill_date") as mock_bf:
            applied = rg._ensure_clv_for_date("2026-04-20")
        mock_bf.assert_not_called()
        assert applied == 0

    def test_runs_backfill_when_clv_missing(self, monkeypatch):
        """Missing CLV → backfill called once for the date."""
        df = pd.DataFrame([
            {"date": "2026-04-19", "game": "BAL@KC", "bet_type": "total",
             "side": "under 9.0", "odds": -113, "sim_prob": 0.6, "edge": 0.12,
             "kelly_pct": 0.04, "result": "W", "profit": 0.88,
             "market_prob": 0.48, "close_odds": "", "close_prob": "",
             "clv_cents": "", "clv_pct": ""},
        ])
        monkeypatch.setattr(rg, "load_bets", lambda: df)
        with patch("scrapers.closing_lines.historical_backfill_date",
                   return_value={"captured_games": 1, "captured_rows": 6,
                                 "snapshot_calls": 1, "event_calls": 1}) as mock_bf, \
             patch("agents.results_grader.update_result") as mock_update:
            applied = rg._ensure_clv_for_date("2026-04-19")
        # Backfill called once for the date
        mock_bf.assert_called_once_with("2026-04-19", include_additional=True)
        # update_result called once (one missing bet)
        assert mock_update.call_count == 1
        assert applied == 1

    def test_backfill_failure_doesnt_crash(self, monkeypatch):
        """If historical_backfill_date raises, we log and return 0 (not crash)."""
        df = pd.DataFrame([
            {"date": "2026-04-19", "game": "BAL@KC", "bet_type": "total",
             "side": "under 9.0", "odds": -113, "sim_prob": 0.6, "edge": 0.12,
             "kelly_pct": 0.04, "result": "W", "profit": 0.88,
             "market_prob": 0.48, "close_odds": "", "close_prob": "",
             "clv_cents": "", "clv_pct": ""},
        ])
        monkeypatch.setattr(rg, "load_bets", lambda: df)
        with patch("scrapers.closing_lines.historical_backfill_date",
                   side_effect=Exception("api down")), \
             patch("agents.results_grader.update_result") as mock_update:
            applied = rg._ensure_clv_for_date("2026-04-19")
        mock_update.assert_not_called()
        assert applied == 0
