import asyncio
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, PublicFormat

from server.odds.books.polymarket_us import fetcher as fmod
from server.odds.books.polymarket_us import ws_client
from server.odds.books.polymarket_us.normalizer import NormalizedEvent


NOW = datetime.now(timezone.utc)
CONFIG = Path(__file__).parent.parent / "config" / "polymarket_us.toml"


def _secret_b64(seed_plus_pub: bool = True) -> tuple[str, Ed25519PrivateKey]:
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    raw = seed + pub if seed_plus_pub else seed
    return base64.b64encode(raw).decode().rstrip("="), key


def test_handshake_signs_only_the_market_data_path():
    secret, key = _secret_b64()
    signing = ws_client.load_signing_key(secret)       # padding stripped, 64-byte form
    h = ws_client.handshake_headers("kid-1", signing, now_ms=1700000000000)
    assert h["X-PM-Access-Key"] == "kid-1"
    assert h["X-PM-Timestamp"] == "1700000000000"
    key.public_key().verify(
        base64.b64decode(h["X-PM-Signature"]),
        b"1700000000000GET/v1/ws/markets",
    )


def test_bad_secret_disables_ws_but_not_rest():
    f = fmod.PolymarketUSFetcher(cache=None, config_path=CONFIG, key_id="k", secret_key="!!notbase64")
    assert f._ws is None
    assert "bad credentials" in f.ws_disabled_reason
    g = fmod.PolymarketUSFetcher(cache=None, config_path=CONFIG)
    assert g._ws is None and "not set" in g.ws_disabled_reason


def _row(slug, long, outcome, point=None, commence=None, event="evt1"):
    return {
        "event_id": event, "sport_key": "nba", "home_team": "H", "away_team": "A",
        "commence_time": commence or (NOW + timedelta(hours=3)),
        "bookmaker_key": "polymarket_us", "market_key": "h2h",
        "outcome_name": outcome, "outcome_point": point, "price_american": 100,
        "fetched_at": NOW, "max_stake_dollars": None, "wager_type": None,
        "_market_slug": slug, "_long": long, "_fee": 0.0695,
    }


def _book(bid, ask, bid_qty="10", ask_qty="250"):
    return {
        "marketSlug": "m1", "state": "MARKET_STATE_OPEN",
        "bids": [{"px": {"value": bid}, "qty": bid_qty}] if bid else [],
        "offers": [{"px": {"value": ask}, "qty": ask_qty}] if ask else [],
    }


def test_ws_update_batches_book_prices_and_skips_unchanged():
    f = fmod.PolymarketUSFetcher(cache=None, config_path=CONFIG)
    f._templates = {"m1": [_row("m1", True, "A"), _row("m1", False, "H")]}
    f._on_market_data(_book("0.40", "0.45"))
    assert len(f._pending_upserts) == 2
    by_name = {r["outcome_name"]: r for r in f._pending_upserts.values()}
    assert by_name["A"]["max_stake_dollars"] == pytest.approx(0.45 * 250)
    assert by_name["H"]["max_stake_dollars"] == pytest.approx(0.60 * 10)   # 1 - bid
    assert by_name["A"]["price_american"] > 0 and by_name["H"]["price_american"] < 0
    f._pending_upserts.clear()
    f._on_market_data(_book("0.40", "0.45"))
    assert f._pending_upserts == {}                                      # unchanged


def test_ws_unbuyable_side_is_deleted_once_and_started_games_ignored():
    f = fmod.PolymarketUSFetcher(cache=None, config_path=CONFIG)
    f._templates = {"m1": [_row("m1", True, "A"),
                           _row("m1", False, "H", commence=NOW - timedelta(minutes=1))]}
    f._on_market_data(_book("0.40", None))          # no offers: long can't be bought
    assert len(f._pending_deletes) == 1 and f._pending_upserts == {}
    f._pending_deletes.clear()
    f._on_market_data(_book("0.40", None))
    assert f._pending_deletes == set()                # not re-queued
    f._on_market_data({**_book("0.40", "0.45"), "state": "MARKET_STATE_SUSPENDED"})
    assert f._pending_upserts == {}                   # suspended == unbuyable


class FakeCache:
    def __init__(self):
        self.upserts, self.deletes = [], []

    async def purge_live_rows_for_book_async(self, book, now):
        return 0

    async def distinct_events_async(self, sport_key=None):
        return []

    async def upsert_async(self, rows):
        self.upserts.append(list(rows))

    async def delete_rows_async(self, keys):
        self.deletes.append(list(keys))


class FakeClient:
    def __init__(self, listing):
        self.listing, self.fetched = listing, []
        self.requests = self.errors = 0

    async def list_league_events(self, league):
        return self.listing

    async def get_event(self, slug):
        self.fetched.append(slug)
        return {"slug": slug}


def _fake_normalize(rows_by_slug):
    def normalize_event(event, league, fetched_at, match, sport_key=None):
        rows = rows_by_slug.get(event["slug"], [])
        return NormalizedEvent(rows=rows, unmapped=__import__("collections").Counter({"x_type": 1}),
                               event_id="evt1" if rows else None)
    return normalize_event


def test_cycle_filters_games_upserts_and_drops_delisted(monkeypatch):
    cache = FakeCache()
    f = fmod.PolymarketUSFetcher(cache=cache, config_path=CONFIG)
    soon, later = (NOW + timedelta(hours=2)).isoformat(), (NOW + timedelta(days=9)).isoformat()
    f.client = FakeClient([
        {"slug": "g1", "startTime": soon},
        {"slug": "g2", "startTime": (NOW - timedelta(minutes=5)).isoformat()},  # started
        {"slug": "g3", "startTime": soon, "live": True},
        {"slug": "g4", "startTime": later},                                      # past horizon
    ])
    rows = {"g1": [_row("m1", True, "A"), _row("m2", True, "B")]}
    monkeypatch.setattr(fmod, "normalize_event", _fake_normalize(rows))
    asyncio.run(f._run_league_cycle("nba"))
    assert f.client.fetched == ["g1"]
    assert len(cache.upserts[0]) == 2
    assert f.registered_slugs() == {"m1", "m2"}
    assert f.status["unmapped_market_types"]["nba"] == {"x_type": 1}

    # Next full fetch: m2 delisted -> its row deleted, template gone.
    rows["g1"] = [_row("m1", True, "A")]
    asyncio.run(f._run_league_cycle("nba", force=True))
    assert cache.deletes and cache.deletes[-1] == [fmod._pk(_row("m2", True, "B"))]
    assert f.registered_slugs() == {"m1"}

    # Empty listing = API glitch: keep what we have.
    f.client.listing = []
    asyncio.run(f._run_league_cycle("nba"))
    assert f.registered_slugs() == {"m1"}

    # Game no longer listed (started / removed): its rows are deleted.
    f.client.listing = [{"slug": "g9", "startTime": soon}]
    asyncio.run(f._run_league_cycle("nba"))
    assert f.registered_slugs() == set()
    assert fmod._pk(_row("m1", True, "A")) in cache.deletes[-1]


def test_full_refresh_is_throttled_when_not_forced(monkeypatch):
    cache = FakeCache()
    f = fmod.PolymarketUSFetcher(cache=cache, config_path=CONFIG)
    f.client = FakeClient([{"slug": "g1", "startTime": (NOW + timedelta(hours=2)).isoformat()}])
    monkeypatch.setattr(fmod, "normalize_event", _fake_normalize({"g1": [_row("m1", True, "A")]}))
    asyncio.run(f._run_league_cycle("nba"))
    asyncio.run(f._run_league_cycle("nba"))
    assert f.client.fetched == ["g1"]            # second cycle within refresh age


def test_fuzzy_matcher_resolves_cfb_name_variants_only_when_unambiguous():
    t = NOW + timedelta(hours=5)
    events = [
        {"event_id": "e1", "home_team": "Arizona State Sun Devils", "away_team": "Kansas State Wildcats", "commence_time": t},
        {"event_id": "e2", "home_team": "Miami Hurricanes", "away_team": "Pittsburgh Panthers", "commence_time": t},
        {"event_id": "e3", "home_team": "Troy Trojans", "away_team": "UL Monroe Warhawks", "commence_time": t},
        {"event_id": "e4", "home_team": "Kentucky Wildcats", "away_team": "Georgia Bulldogs", "commence_time": t},
    ]
    m = fmod.fuzzy_matcher(events)
    assert m("ncaaf", "K-State Wildcats", "Arizona State Sun Devils", t)["event_id"] == "e1"
    assert m("ncaaf", "Pittsburgh Panthers", "Miami (FL) Hurricanes", t)["event_id"] == "e2"
    assert m("ncaaf", "Louisiana-Monroe Warhawks", "Troy Trojans", t)["event_id"] == "e3"
    assert m("ncaaf", "K-State Wildcats", "Georgia Bulldogs", t) is None        # mascot only isn't enough
    assert m("ncaaf", "K-State Wildcats", "Arizona State Sun Devils", t + timedelta(hours=3)) is None


def test_ws_pool_shards_slugs_sticky_and_caps_connections():
    secret, _ = _secret_b64()
    slugs = {f"m{i:05d}" for i in range(2500)}
    pool = ws_client.PolymarketUSWSPool("k", secret, get_slugs=lambda: slugs,
                                        on_market_data=lambda m: None, max_connections=2)
    pool._rebalance()
    assert [len(s) for s in pool._shard_slugs] == [1000, 1000]
    assert pool.unstreamed == 500
    slugs -= {f"m{i:05d}" for i in range(10)}            # 10 finished on shard 0
    pool._rebalance()
    assert pool.unstreamed == 490 and len(pool._shard_slugs[0]) == 1000   # overflow fills it

    pool._max = 3
    pool._rebalance()
    assert pool.unstreamed == 0 and len(pool._shard_slugs[2]) == 490
    first = dict(pool._assign)
    slugs -= {f"m{i:05d}" for i in range(10, 20)}
    slugs |= {"new1"}
    pool._rebalance()
    assert pool._assign["new1"] == 0                     # freed room reused
    assert all(pool._assign[s] == k for s, k in first.items() if s in pool._assign)
