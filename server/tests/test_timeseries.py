from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.odds.cache import OddsCache


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "cache.db")
    c.init()
    return c


def _row(**over):
    now = datetime.now(timezone.utc)
    base = {
        "event_id": "evt_1",
        "sport_key": "mlb",
        "home_team": "Yankees", "away_team": "Red Sox",
        "commence_time": now + timedelta(hours=2),
        "bookmaker_key": "pinnacle",
        "market_key": "h2h",
        "outcome_name": "Yankees",
        "outcome_point": None,
        "price_american": -138,
        "fetched_at": now,
    }
    base.update(over)
    return base


def test_history_records_first_observation(cache: OddsCache):
    cache.upsert([_row()])
    hist = cache.history_for_event("evt_1")
    assert len(hist) == 1
    assert hist[0]["price_american"] == -138


def test_history_dedupes_unchanged_price(cache: OddsCache):
    t0 = datetime.now(timezone.utc)
    cache.upsert([_row(fetched_at=t0, price_american=-138)])
    cache.upsert([_row(fetched_at=t0 + timedelta(minutes=5), price_american=-138)])
    hist = cache.history_for_event("evt_1")
    # Same price re-observed → no new point.
    assert len(hist) == 1


def test_history_appends_on_change(cache: OddsCache):
    t0 = datetime.now(timezone.utc)
    cache.upsert([_row(fetched_at=t0, price_american=-138)])
    cache.upsert([_row(fetched_at=t0 + timedelta(minutes=5), price_american=-145)])
    cache.upsert([_row(fetched_at=t0 + timedelta(minutes=10), price_american=-145)])
    cache.upsert([_row(fetched_at=t0 + timedelta(minutes=15), price_american=-150)])
    prices = [h["price_american"] for h in cache.history_for_event("evt_1")]
    # -138 → -145 (recorded) → -145 (skipped) → -150 (recorded)
    assert prices == [-138, -145, -150]


def test_history_tracks_books_independently(cache: OddsCache):
    t0 = datetime.now(timezone.utc)
    cache.upsert([_row(bookmaker_key="pinnacle", price_american=-138)])
    cache.upsert([_row(bookmaker_key="draftkings", price_american=-140)])
    hist = cache.history_for_event("evt_1")
    books = {h["bookmaker_key"] for h in hist}
    assert books == {"pinnacle", "draftkings"}


def test_history_distinguishes_points(cache: OddsCache):
    # Two spread ladders at different points are independent series.
    cache.upsert([_row(market_key="spreads", outcome_name="Yankees",
                       outcome_point=-1.5, price_american=120)])
    cache.upsert([_row(market_key="spreads", outcome_name="Yankees",
                       outcome_point=-1.5, price_american=120)])  # dup
    cache.upsert([_row(market_key="spreads", outcome_name="Yankees",
                       outcome_point=1.5, price_american=-160)])
    hist = cache.history_for_event("evt_1")
    assert len(hist) == 2


def test_props_excluded(cache: OddsCache):
    cache.upsert([_row(market_key="batter_hits", outcome_name="Aaron Judge Over",
                       outcome_point=1.5, price_american=110)])
    cache.upsert([_row(market_key="player_points", outcome_name="LeBron James Over",
                       outcome_point=25.5, price_american=-115)])
    assert cache.history_for_event("evt_1") == []


def test_alternate_ladders_excluded(cache: OddsCache):
    cache.upsert([_row(market_key="alternate_spreads", outcome_name="Yankees",
                       outcome_point=-3.5, price_american=160)])
    assert cache.history_for_event("evt_1") == []


def test_period_variant_recorded(cache: OddsCache):
    # h2h_h1 / totals_1st_5_innings collapse to core bases via _base_market.
    cache.upsert([_row(market_key="h2h_h1", price_american=-120)])
    cache.upsert([_row(market_key="totals_1st_5_innings", outcome_name="Over",
                       outcome_point=4.5, price_american=-105)])
    keys = {h["market_key"] for h in cache.history_for_event("evt_1")}
    assert keys == {"h2h_h1", "totals_1st_5_innings"}


def test_market_key_filter(cache: OddsCache):
    cache.upsert([_row(market_key="h2h", price_american=-138)])
    cache.upsert([_row(market_key="spreads", outcome_point=-1.5, price_american=120)])
    assert len(cache.history_for_event("evt_1", market_key="h2h")) == 1


def test_events_with_history_summary(cache: OddsCache):
    cache.upsert([_row(price_american=-138)])
    cache.upsert([_row(fetched_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                       price_american=-150)])
    events = cache.events_with_history(sport_key="mlb")
    assert len(events) == 1
    assert events[0]["event_id"] == "evt_1"
    assert events[0]["point_count"] == 2
    assert events[0]["home_team"] == "Yankees"


def test_purge_old_history(cache: OddsCache):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=120)
    cache.upsert([_row(event_id="old_evt", commence_time=old,
                       fetched_at=old, price_american=-110)])
    cache.upsert([_row(event_id="new_evt", price_american=-110)])
    removed = cache.purge_old_history(now, days=90)
    assert removed == 1
    assert cache.history_for_event("old_evt") == []
    assert len(cache.history_for_event("new_evt")) == 1
