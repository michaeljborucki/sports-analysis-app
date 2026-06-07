"""Tests for agents.daily_runner."""
from datetime import date

import pandas as pd
import pytest

from agents import daily_runner as dr


@pytest.fixture
def stub_bets_csv(tmp_path, monkeypatch):
    """Point tracker.BETS_CSV at a temp file and return its path."""
    csv = tmp_path / "bets.csv"
    monkeypatch.setattr("tracker.BETS_CSV", str(csv))
    return csv


def _row(date_str, result=""):
    return {
        "date": date_str, "game": "BOS@NYY", "bet_type": "moneyline",
        "side": "home", "odds": -150, "sim_prob": 0.6,
        "market_prob": 0.55, "edge": 0.05, "kelly_pct": 0.02,
        "result": result, "profit": "",
    }


def test_pending_past_dates_empty_csv(stub_bets_csv):
    """No file → no past-pending dates."""
    assert dr._pending_past_dates() == []


def test_pending_past_dates_returns_past_pending_sorted(stub_bets_csv, monkeypatch):
    """Past dates with pending bets are returned in ascending order."""
    monkeypatch.setattr(dr, "_today", lambda: date(2026, 4, 23))
    pd.DataFrame([
        _row("2026-04-03"),            # past, pending
        _row("2026-04-20"),            # past, pending
        _row("2026-04-22", "W"),       # past, already graded → excluded
        _row("2026-04-23"),            # today → excluded (game may not have finished)
    ]).to_csv(stub_bets_csv, index=False)
    assert dr._pending_past_dates() == ["2026-04-03", "2026-04-20"]


def test_pending_past_dates_dedups(stub_bets_csv, monkeypatch):
    """Multiple pending bets on the same date collapse to one entry."""
    monkeypatch.setattr(dr, "_today", lambda: date(2026, 4, 23))
    pd.DataFrame([
        _row("2026-04-20"),
        _row("2026-04-20"),
        _row("2026-04-20"),
    ]).to_csv(stub_bets_csv, index=False)
    assert dr._pending_past_dates() == ["2026-04-20"]


def test_pending_past_dates_excludes_today_and_future(stub_bets_csv, monkeypatch):
    """Same-day and future-dated pending bets must not be swept as past work."""
    monkeypatch.setattr(dr, "_today", lambda: date(2026, 4, 23))
    pd.DataFrame([
        _row("2026-04-23"),   # today
        _row("2026-04-24"),   # future (data entry error, just in case)
    ]).to_csv(stub_bets_csv, index=False)
    assert dr._pending_past_dates() == []
