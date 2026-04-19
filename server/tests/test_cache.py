from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.odds.cache import OddsCache


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "cache.db")
    c.init()
    return c


def test_upsert_and_read_single_row(cache: OddsCache):
    now = datetime.now(timezone.utc)
    cache.upsert([
        {
            "event_id": "evt_1",
            "home_team": "Yankees", "away_team": "Red Sox",
            "commence_time": now,
            "bookmaker_key": "draftkings",
            "market_key": "h2h",
            "outcome_name": "Yankees",
            "outcome_point": None,
            "price_american": -138,
            "fetched_at": now,
        }
    ])
    rows = cache.all_current()
    assert len(rows) == 1
    assert rows[0]["price_american"] == -138


def test_upsert_overwrites_same_key(cache: OddsCache):
    now = datetime.now(timezone.utc)
    base = {
        "event_id": "evt_1",
        "home_team": "Yankees", "away_team": "Red Sox",
        "commence_time": now,
        "bookmaker_key": "draftkings",
        "market_key": "h2h",
        "outcome_name": "Yankees",
        "outcome_point": None,
        "fetched_at": now,
    }
    cache.upsert([{**base, "price_american": -138}])
    cache.upsert([{**base, "price_american": -140}])
    rows = cache.all_current()
    assert len(rows) == 1
    assert rows[0]["price_american"] == -140


def test_status_upsert(cache: OddsCache):
    now = datetime.now(timezone.utc)
    cache.set_status(last_fetch_at=now, requests_remaining=500)
    status = cache.get_status()
    assert status is not None
    assert status["requests_remaining"] == 500
