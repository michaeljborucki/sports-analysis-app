"""Regression tests for the per-day ensemble simulation cache.

Added 2026-04-24 after observing ~$5.69 of duplicate ensemble spend across
3 daily-runner invocations on the same slate. Each ensemble call is
~$0.20-0.30 in OpenRouter cost (Phase 1 + Phase 2 + challenger), so
running ``daily`` three times on a 15-match slate burns ~$10-15 of
duplicate spend.

The cache stores the ensemble's prediction dict per ``(date, match_key)``.
Edge analysis still runs against LIVE odds every time — only the
expensive ensemble probability estimates are reused.

If a test fails because the cache is misbehaving, suspect one of:
  - A code path that bypasses get_cached_sim before run_mirofish
  - save_cached_sim being called with an unsuccessful (None) result
  - Cache file format drift
"""
import json
import os
from unittest.mock import patch, MagicMock

import pytest


# ---- Module-level cache helpers ----


def test_cache_miss_returns_none(tmp_path, monkeypatch):
    import sim_cache
    monkeypatch.setattr(sim_cache, "CACHE_DIR", str(tmp_path / "sim_cache"))
    assert sim_cache.get_cached_sim("2026-04-24", "X vs Y") is None


def test_cache_hit_round_trip(tmp_path, monkeypatch):
    import sim_cache
    monkeypatch.setattr(sim_cache, "CACHE_DIR", str(tmp_path / "sim_cache"))
    payload = {
        "predictions": {"moneyline": {"player_a_win_prob": 0.6}},
        "ensemble_runs": 1,
    }
    sim_cache.save_cached_sim("2026-04-24", "Rublev vs Kopriva", payload)
    got = sim_cache.get_cached_sim("2026-04-24", "Rublev vs Kopriva")
    assert got == payload


def test_cache_isolates_by_date(tmp_path, monkeypatch):
    """Same match_key on different dates must not collide — handles
    rematches in a tournament across days."""
    import sim_cache
    monkeypatch.setattr(sim_cache, "CACHE_DIR", str(tmp_path / "sim_cache"))
    sim_cache.save_cached_sim("2026-04-24", "A vs B", {"day": 24})
    sim_cache.save_cached_sim("2026-04-25", "A vs B", {"day": 25})
    assert sim_cache.get_cached_sim("2026-04-24", "A vs B") == {"day": 24}
    assert sim_cache.get_cached_sim("2026-04-25", "A vs B") == {"day": 25}


def test_cache_save_does_not_overwrite_other_matches(tmp_path, monkeypatch):
    """Saving match B on a date with existing match A must preserve A."""
    import sim_cache
    monkeypatch.setattr(sim_cache, "CACHE_DIR", str(tmp_path / "sim_cache"))
    sim_cache.save_cached_sim("2026-04-24", "A vs B", {"r": "AB"})
    sim_cache.save_cached_sim("2026-04-24", "C vs D", {"r": "CD"})
    assert sim_cache.get_cached_sim("2026-04-24", "A vs B") == {"r": "AB"}
    assert sim_cache.get_cached_sim("2026-04-24", "C vs D") == {"r": "CD"}


def test_cache_save_overwrites_same_match(tmp_path, monkeypatch):
    """Re-running with --force-resim should overwrite the cached entry."""
    import sim_cache
    monkeypatch.setattr(sim_cache, "CACHE_DIR", str(tmp_path / "sim_cache"))
    sim_cache.save_cached_sim("2026-04-24", "A vs B", {"v": 1})
    sim_cache.save_cached_sim("2026-04-24", "A vs B", {"v": 2})
    assert sim_cache.get_cached_sim("2026-04-24", "A vs B") == {"v": 2}


def test_cache_ignores_falsy_results(tmp_path, monkeypatch):
    """An ensemble that returned None or {} should NOT poison the cache —
    next run gets a fresh shot, not a cached failure."""
    import sim_cache
    monkeypatch.setattr(sim_cache, "CACHE_DIR", str(tmp_path / "sim_cache"))
    sim_cache.save_cached_sim("2026-04-24", "A vs B", None)
    sim_cache.save_cached_sim("2026-04-24", "A vs B", {})
    assert sim_cache.get_cached_sim("2026-04-24", "A vs B") is None


def test_cache_handles_corrupt_json_gracefully(tmp_path, monkeypatch, caplog):
    import sim_cache
    monkeypatch.setattr(sim_cache, "CACHE_DIR", str(tmp_path / "sim_cache"))
    os.makedirs(sim_cache.CACHE_DIR, exist_ok=True)
    with open(os.path.join(sim_cache.CACHE_DIR, "2026-04-24.json"), "w") as f:
        f.write("not-valid-json{")
    # Must not raise; returns None and logs a warning.
    assert sim_cache.get_cached_sim("2026-04-24", "X") is None


def test_clear_cache_specific_date(tmp_path, monkeypatch):
    import sim_cache
    monkeypatch.setattr(sim_cache, "CACHE_DIR", str(tmp_path / "sim_cache"))
    sim_cache.save_cached_sim("2026-04-24", "A vs B", {"x": 1})
    sim_cache.save_cached_sim("2026-04-25", "A vs B", {"x": 2})
    removed = sim_cache.clear_cache("2026-04-24")
    assert removed == 1
    assert sim_cache.get_cached_sim("2026-04-24", "A vs B") is None
    assert sim_cache.get_cached_sim("2026-04-25", "A vs B") == {"x": 2}


def test_clear_cache_all_dates(tmp_path, monkeypatch):
    import sim_cache
    monkeypatch.setattr(sim_cache, "CACHE_DIR", str(tmp_path / "sim_cache"))
    sim_cache.save_cached_sim("2026-04-24", "A vs B", {"x": 1})
    sim_cache.save_cached_sim("2026-04-25", "C vs D", {"x": 2})
    removed = sim_cache.clear_cache()
    assert removed == 2


# ---- Integration: _simulate_one_match uses the cache ----


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Point sim_cache.CACHE_DIR at a tmp dir for the duration of a test."""
    import sim_cache
    monkeypatch.setattr(sim_cache, "CACHE_DIR", str(tmp_path / "sim_cache"))
    yield


def _stub_match_data():
    return {
        "odds": {
            "moneyline": {"player_a": -140, "player_b": 120},
            "game_handicap": {"player_a_point": -3.5, "player_a_odds": -110,
                              "player_b_point": 3.5, "player_b_odds": -110},
            "total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110},
            "implied_probs": {"player_a": 0.583, "player_b": 0.417},
        }
    }


def test_simulate_one_match_skips_ensemble_on_cache_hit(isolated_cache):
    """With a cached entry present, _simulate_one_match must NOT call
    run_mirofish — that's the whole point of the cache."""
    import sim_cache
    from main import _simulate_one_match

    cached_result = {
        "predictions": {
            "moneyline": {"player_a_win_prob": 0.65, "player_b_win_prob": 0.35,
                          "confidence": "medium"},
        }
    }
    sim_cache.save_cached_sim("2099-04-24", "X vs Y", cached_result)

    fake_run_mirofish = MagicMock()
    with patch("simulate.run_mirofish", fake_run_mirofish):
        r = _simulate_one_match(
            "X vs Y", "<brief>", _stub_match_data(),
            "2099-04-24", "2099-04-24 11:00", "atp",
        )

    fake_run_mirofish.assert_not_called(), \
        "run_mirofish must be skipped when sim cache has an entry"
    assert r["status"] in ("logged", "cached_no_bets")
    if r["status"] == "logged":
        assert r["from_cache"] is True


def test_simulate_one_match_calls_ensemble_on_cache_miss(isolated_cache):
    from main import _simulate_one_match

    sim_result = {
        "predictions": {
            "moneyline": {"player_a_win_prob": 0.65, "player_b_win_prob": 0.35,
                          "confidence": "medium"},
        }
    }
    fake = MagicMock(return_value=sim_result)
    with patch("simulate.run_mirofish", fake):
        r = _simulate_one_match(
            "X vs Y", "<brief>", _stub_match_data(),
            "2099-04-24", "2099-04-24 11:00", "atp",
        )

    fake.assert_called_once()
    if r["status"] == "logged":
        assert r["from_cache"] is False


def test_simulate_one_match_writes_cache_after_successful_sim(isolated_cache):
    from main import _simulate_one_match
    import sim_cache

    sim_result = {
        "predictions": {
            "moneyline": {"player_a_win_prob": 0.65, "player_b_win_prob": 0.35,
                          "confidence": "medium"},
        }
    }
    with patch("simulate.run_mirofish", MagicMock(return_value=sim_result)):
        _simulate_one_match(
            "X vs Y", "<brief>", _stub_match_data(),
            "2099-04-24", "2099-04-24 11:00", "atp",
        )

    cached = sim_cache.get_cached_sim("2099-04-24", "X vs Y")
    assert cached is not None
    assert cached["predictions"]["moneyline"]["player_a_win_prob"] == 0.65


def test_simulate_one_match_force_resim_bypasses_cache(isolated_cache):
    """force_resim=True must call run_mirofish even when cache has an entry."""
    import sim_cache
    from main import _simulate_one_match

    sim_cache.save_cached_sim("2099-04-24", "X vs Y", {"predictions": {}})

    new_result = {
        "predictions": {
            "moneyline": {"player_a_win_prob": 0.7, "player_b_win_prob": 0.3,
                          "confidence": "medium"},
        }
    }
    fake = MagicMock(return_value=new_result)
    with patch("simulate.run_mirofish", fake):
        _simulate_one_match(
            "X vs Y", "<brief>", _stub_match_data(),
            "2099-04-24", "2099-04-24 11:00", "atp",
            force_resim=True,
        )

    fake.assert_called_once(), "force_resim=True must bypass the cache"
    # Cache should also be updated to the new result
    cached = sim_cache.get_cached_sim("2099-04-24", "X vs Y")
    assert cached["predictions"]["moneyline"]["player_a_win_prob"] == 0.7


def test_simulate_one_match_does_not_cache_failed_sim(isolated_cache):
    """If run_mirofish returns None (sim_failed), the cache must NOT store
    a poison entry — next run gets another shot."""
    import sim_cache
    from main import _simulate_one_match

    with patch("simulate.run_mirofish", MagicMock(return_value=None)):
        r = _simulate_one_match(
            "X vs Y", "<brief>", _stub_match_data(),
            "2099-04-24", "2099-04-24 11:00", "atp",
        )

    assert r["status"] == "sim_failed"
    assert sim_cache.get_cached_sim("2099-04-24", "X vs Y") is None
