import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from cache import ensemble_cache as ec


@pytest.fixture
def tmp_cache_dir(tmp_path, monkeypatch):
    cdir = tmp_path / "ensemble_cache"
    cdir.mkdir()
    monkeypatch.setattr(ec, "CACHE_DIR", str(cdir))
    return cdir


def _lineup(home_batters, away_batters, home_sp, away_sp):
    return {
        "home": home_batters,
        "away": away_batters,
        "home_pitcher": home_sp,
        "away_pitcher": away_sp,
    }


def test_hash_is_order_independent():
    a = _lineup([1, 2, 3, 4, 5, 6, 7, 8, 9],
                [11, 12, 13, 14, 15, 16, 17, 18, 19], 100, 200)
    b = _lineup([9, 8, 7, 6, 5, 4, 3, 2, 1],
                [19, 18, 17, 16, 15, 14, 13, 12, 11], 100, 200)
    assert ec.compute_starters_hash(a) == ec.compute_starters_hash(b)


def test_hash_changes_when_starter_changes():
    a = _lineup([1, 2, 3, 4, 5, 6, 7, 8, 9],
                [11, 12, 13, 14, 15, 16, 17, 18, 19], 100, 200)
    swap_batter = _lineup([1, 2, 3, 4, 5, 6, 7, 8, 99],
                          [11, 12, 13, 14, 15, 16, 17, 18, 19], 100, 200)
    swap_sp = _lineup([1, 2, 3, 4, 5, 6, 7, 8, 9],
                      [11, 12, 13, 14, 15, 16, 17, 18, 19], 100, 999)
    assert ec.compute_starters_hash(a) != ec.compute_starters_hash(swap_batter)
    assert ec.compute_starters_hash(a) != ec.compute_starters_hash(swap_sp)


def test_hash_returns_empty_when_lineup_incomplete():
    assert ec.compute_starters_hash({}) == ""
    assert ec.compute_starters_hash({"home": [1], "away": []}) == ""
    assert ec.compute_starters_hash(None) == ""


def test_set_and_get_screening(tmp_cache_dir):
    h = ec.compute_starters_hash(
        _lineup([1, 2, 3, 4, 5, 6, 7, 8, 9],
                [11, 12, 13, 14, 15, 16, 17, 18, 19], 100, 200)
    )
    payload = {"predictions": {"moneyline": {"home_win_prob": 0.6}}}
    ec.set_cache_entry(12345, h, "2026-04-14", "screening", payload)

    entry = ec.get_cache_entry(12345, h, "2026-04-14")
    assert entry is not None
    assert entry["screening"] == payload
    assert "ensemble" not in entry


def test_screening_and_ensemble_coexist(tmp_cache_dir):
    h = ec.compute_starters_hash(
        _lineup([1, 2, 3, 4, 5, 6, 7, 8, 9],
                [11, 12, 13, 14, 15, 16, 17, 18, 19], 100, 200)
    )
    s = {"a": 1}
    e = {"b": 2}
    ec.set_cache_entry(99, h, "2026-04-14", "screening", s)
    ec.set_cache_entry(99, h, "2026-04-14", "ensemble", e)
    entry = ec.get_cache_entry(99, h, "2026-04-14")
    assert entry["screening"] == s
    assert entry["ensemble"] == e


def test_cache_miss_returns_none(tmp_cache_dir):
    assert ec.get_cache_entry(1, "abc123", "2026-04-14") is None


def test_invalid_kind_rejected(tmp_cache_dir):
    with pytest.raises(ValueError):
        ec.set_cache_entry(1, "abc", "2026-04-14", "bogus", {"x": 1})


def test_rotation_deletes_old_files(tmp_cache_dir):
    today = datetime.now(timezone.utc).date()
    old = today - timedelta(days=45)
    fresh = today - timedelta(days=5)

    (tmp_cache_dir / f"{old.isoformat()}.json").write_text("{}")
    (tmp_cache_dir / f"{fresh.isoformat()}.json").write_text("{}")
    (tmp_cache_dir / "not-a-date.json").write_text("{}")

    deleted = ec.rotate_old_cache(keep_days=30)
    assert deleted == 1
    assert not (tmp_cache_dir / f"{old.isoformat()}.json").exists()
    assert (tmp_cache_dir / f"{fresh.isoformat()}.json").exists()
    assert (tmp_cache_dir / "not-a-date.json").exists()


def test_corrupted_cache_treated_as_empty(tmp_cache_dir):
    bad = tmp_cache_dir / "2026-04-14.json"
    bad.write_text("{not valid json}")
    assert ec.get_cache_entry(1, "abc", "2026-04-14") is None
