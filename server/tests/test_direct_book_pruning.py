"""Kalshi / Polymarket direct-book registration pruning.

The WS ingestors used to accumulate every market ticker / asset_id ever
seen, so the Kalshi orderbook poller kept polling finished games for days
and the Polymarket WS subscription (capped at 5000, insertion order) filled
up with stale assets and stopped subscribing new games. Each REST cycle now
REPLACES its own scope's registrations — (sport, series) for Kalshi, sport
for Polymarket — and started games are unregistered alongside the existing
live-row purge.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.odds.books.kalshi.ws_ingest import KalshiTickerIngestor
from server.odds.books.polymarket.ws_ingest import PolymarketIngestor
from server.odds.cache import OddsCache


FUTURE = datetime.now(timezone.utc) + timedelta(days=1)
PAST = datetime.now(timezone.utc) - timedelta(hours=3)


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _k_row(ticker: str, outcome: str = "BOS", commence=FUTURE, side="yes") -> dict:
    return {
        "_market_ticker": ticker, "_ws_side": side,
        "event_id": f"ev-{ticker}", "sport_key": "basketball_nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": commence,
        "bookmaker_key": "kalshi",
        "market_key": "h2h", "outcome_name": outcome, "outcome_point": None,
        "price_american": -150, "fetched_at": datetime.now(timezone.utc),
    }


def _p_row(asset: str, commence=FUTURE) -> dict:
    return {
        "_asset_id": asset, "_ws_side": "yes",
        "event_id": f"ev-{asset}", "sport_key": "basketball_nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": commence,
        "bookmaker_key": "polymarket",
        "market_key": "h2h", "outcome_name": "BOS", "outcome_point": None,
        "price_american": -150, "fetched_at": datetime.now(timezone.utc),
    }


# ───────────────────────────── Kalshi ingestor ─────────────────────────────


def test_kalshi_ticker_set_shrinks_when_market_disappears(cache):
    ing = KalshiTickerIngestor(cache)
    scope = ("basketball_nba", "KXNBAGAME")
    ing.replace_scope(scope, [_k_row("T1"), _k_row("T2"), _k_row("T3")])
    ing.last_ws_update["T1"] = time.time()
    assert sorted(ing.registered_tickers()) == ["T1", "T2", "T3"]

    ing.replace_scope(scope, [_k_row("T2"), _k_row("T3"), _k_row("T4")])
    assert sorted(ing.registered_tickers()) == ["T2", "T3", "T4"]
    assert "T1" not in ing.last_ws_update
    assert ing.stats()["templates_tickers"] == 3
    assert ing.registered_markets == 3


def test_kalshi_empty_listing_releases_scope(cache):
    ing = KalshiTickerIngestor(cache)
    scope = ("basketball_nba", "KXNBAGAME")
    ing.replace_scope(scope, [_k_row("T1")])
    ing.replace_scope(scope, [])
    assert ing.registered_tickers() == []
    assert ing.stats()["scopes"] == 0


def test_kalshi_other_series_and_sport_survive(cache):
    ing = KalshiTickerIngestor(cache)
    ing.replace_scope(("basketball_nba", "KXNBAGAME"), [_k_row("NBA-ML")])
    ing.replace_scope(("basketball_nba", "KXNBASPREAD"), [_k_row("NBA-SP")])
    ing.replace_scope(("icehockey_nhl", "KXNHLGAME"), [_k_row("NHL-ML")])

    # NBA moneyline series' listing changes — only that scope is touched.
    ing.replace_scope(("basketball_nba", "KXNBAGAME"), [_k_row("NBA-ML2")])
    assert sorted(ing.registered_tickers()) == ["NBA-ML2", "NBA-SP", "NHL-ML"]


def test_kalshi_ticker_shared_by_two_scopes_kept_until_both_release(cache):
    ing = KalshiTickerIngestor(cache)
    ing.replace_scope(("a", "S"), [_k_row("SHARED")])
    ing.replace_scope(("b", "S"), [_k_row("SHARED")])
    ing.replace_scope(("a", "S"), [])
    assert ing.registered_tickers() == ["SHARED"]
    ing.replace_scope(("b", "S"), [])
    assert ing.registered_tickers() == []


def test_kalshi_replace_refreshes_outcomes_on_surviving_ticker(cache):
    ing = KalshiTickerIngestor(cache)
    scope = ("basketball_nba", "KXNBATOTAL")
    ing.replace_scope(scope, [_k_row("T", "Over"), _k_row("T", "Under", side="no")])
    ing.replace_scope(scope, [_k_row("T", "Over")])
    assert [t["outcome_name"] for t, _ in ing._templates["T"]] == ["Over"]


def test_kalshi_prune_started_matches_live_purge(cache):
    ing = KalshiTickerIngestor(cache)
    scope = ("basketball_nba", "KXNBAGAME")
    ing.replace_scope(scope, [
        _k_row("OLD", commence=PAST),
        _k_row("OLD_ISO", commence=PAST.isoformat()),
        _k_row("NEW", commence=FUTURE),
        _k_row("UNKNOWN", commence="not-a-date"),
    ])
    ing.last_ws_update["OLD"] = time.time()
    dropped = ing.prune_started(datetime.now(timezone.utc))
    assert dropped == 2
    assert sorted(ing.registered_tickers()) == ["NEW", "UNKNOWN"]
    assert "OLD" not in ing.last_ws_update
    # A started ticker that's still listed next cycle doesn't confuse scope
    # bookkeeping: releasing the scope empties everything.
    ing.replace_scope(scope, [])
    assert ing.registered_tickers() == []


def test_kalshi_ws_tick_for_pruned_ticker_is_ignored(cache):
    ing = KalshiTickerIngestor(cache)
    scope = ("basketball_nba", "KXNBAGAME")
    ing.replace_scope(scope, [_k_row("GONE")])
    ing.replace_scope(scope, [])
    n = ing.process_ticker({"msg": {"market_ticker": "GONE", "yes_ask_dollars": "0.55"}})
    assert n == 0
    assert "GONE" not in ing.last_ws_update


# ───────────────────────────── Kalshi fetcher cycle ────────────────────────


def test_kalshi_fetcher_cycle_replaces_per_series_and_keeps_failed_series(cache, monkeypatch):
    from server.odds.books.kalshi import fetcher as kf

    f = kf.KalshiFetcher(cache=cache, config_path=Path("/nonexistent.toml"))
    f._ingestor = KalshiTickerIngestor(cache)
    sport_cfg = SimpleNamespace(
        series_main=["SER-A"], series_spread=["SER-B"], series_total=[],
        series_team_total=[], series_period=[], series_rfi=[], series_f5_winner=[],
    )
    f._config = SimpleNamespace(sports={"basketball_nba": sport_cfg}, team_aliases={})
    monkeypatch.setattr(kf, "_INTER_SERIES_GAP_S", 0)
    monkeypatch.setattr(f, "_matcher", lambda events=None: None)
    monkeypatch.setattr(f, "_smart_match_event", lambda matcher: None)

    listings: dict[str, list | None] = {
        "SER-A": [{"ticker": "A1"}, {"ticker": "A2"}],
        "SER-B": [{"ticker": "B1"}],
    }

    async def fake_list(series_ticker, sport_key):
        return listings[series_ticker]

    def fake_normalize(markets, *, series_ticker, fetched_at, match_event):
        return [_k_row(m["ticker"]) for m in markets]

    monkeypatch.setattr(f, "_safe_list_markets", fake_list)
    monkeypatch.setattr(kf, "normalize_markets", fake_normalize)

    asyncio.run(f._run_sport_cycle("basketball_nba"))
    assert sorted(f.registered_tickers()) == ["A1", "A2", "B1"]

    # A2 settles off the listing; SER-B's fetch fails this cycle (None) —
    # its registrations must survive rather than be wiped.
    listings["SER-A"] = [{"ticker": "A1"}]
    listings["SER-B"] = None
    asyncio.run(f._run_sport_cycle("basketball_nba"))
    assert sorted(f.registered_tickers()) == ["A1", "B1"]

    dbg = f.debug_stats()
    assert dbg["ingestor"]["templates_tickers"] == 2
    assert "ws" in dbg


# ───────────────────────────── Polymarket ──────────────────────────────────


def test_polymarket_asset_set_shrinks_and_other_sport_survives(cache):
    ing = PolymarketIngestor(cache)
    ing.replace_scope("basketball_nba", [_p_row("n1"), _p_row("n2")])
    ing.replace_scope("icehockey_nhl", [_p_row("h1")])
    ing.replace_scope("basketball_nba", [_p_row("n2"), _p_row("n3")])
    assert sorted(ing.asset_ids()) == ["h1", "n2", "n3"]
    assert ing.registered_assets == 3
    assert ing.stats()["templates_assets"] == 3


def test_polymarket_prune_started(cache):
    ing = PolymarketIngestor(cache)
    ing.replace_scope("basketball_nba", [
        _p_row("old", commence=PAST), _p_row("new", commence=FUTURE),
    ])
    assert ing.prune_started(datetime.now(timezone.utc)) == 1
    assert ing.asset_ids() == ["new"]


def test_polymarket_new_assets_subscribed_after_many_stale(cache):
    """6000 stale assets from finished games used to fill the 5000-asset
    subscribe cap (insertion order), so a newly-posted game never got
    subscribed. With per-sport replacement the stale ones are released."""
    from server.odds.books.polymarket import ws_client as wsc

    ing = PolymarketIngestor(cache)
    stale = [_p_row(f"stale{i}") for i in range(6000)]
    ing.replace_scope("basketball_nba", stale)
    ing.replace_scope("basketball_nba", [_p_row("fresh1"), _p_row("fresh2")])

    client = wsc.PolymarketWSClient(get_asset_ids=ing.asset_ids)
    sent: list[dict] = []

    class FakeWS:
        async def send(self, data):
            import json
            sent.append(json.loads(data))

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def close(self):
            pass

    class FakeConnect:
        async def __aenter__(self):
            return FakeWS()

        async def __aexit__(self, *a):
            return False

    async def run():
        orig = wsc.websockets.connect
        wsc.websockets.connect = lambda *a, **k: FakeConnect()
        try:
            async for _ in client._connect_and_stream():
                pass
        finally:
            wsc.websockets.connect = orig

    asyncio.run(run())
    assert sorted(sent[0]["assets_ids"]) == ["fresh1", "fresh2"]


def test_polymarket_ws_client_resubscribes_when_new_assets_registered(cache):
    from server.odds.books.polymarket import ws_client as wsc

    ing = PolymarketIngestor(cache)
    ing.replace_scope("basketball_nba", [_p_row("a1")])
    client = wsc.PolymarketWSClient(get_asset_ids=ing.asset_ids)
    # Simulate a live connection subscribed to the current set.
    client._subscribed = set(ing.asset_ids())
    client.connected_at = time.time() - 120
    assert client.needs_resubscribe() is False

    # Removal alone doesn't force a reconnect (stale msgs are just dropped).
    ing.replace_scope("basketball_nba", [])
    assert client.needs_resubscribe() is False

    ing.replace_scope("basketball_nba", [_p_row("a2")])
    assert client.needs_resubscribe() is True

    # Debounced: a just-opened connection isn't recycled.
    client.connected_at = time.time()
    assert client.needs_resubscribe() is False
    # Not connected → nothing to recycle.
    client.connected_at = None
    assert client.needs_resubscribe() is False


def test_polymarket_fetcher_cycle_replaces_sport_scope(cache, monkeypatch):
    from server.odds.books.polymarket import fetcher as pf

    f = pf.PolymarketFetcher(cache=cache, config_path=Path("/nonexistent.toml"))
    f._config = SimpleNamespace(
        sports={
            "basketball_nba": SimpleNamespace(slug_prefixes=["nba"]),
            "icehockey_nhl": SimpleNamespace(slug_prefixes=["nhl"]),
        },
        team_aliases={},
    )
    monkeypatch.setattr(f, "_matcher", lambda events=None: None)
    current = {"events": [{"id": 1}], "basketball_nba": ["n1", "n2"], "icehockey_nhl": ["h1"]}

    async def fake_events():
        return current["events"]

    def fake_normalize(events, *, sport_key, slug_prefixes, fetched_at, match_event):
        return [_p_row(a) for a in current[sport_key]]

    monkeypatch.setattr(f, "_fetch_gamma_events", fake_events)
    monkeypatch.setattr(pf, "normalize_events", fake_normalize)

    asyncio.run(f._run_sport_cycle("basketball_nba"))
    asyncio.run(f._run_sport_cycle("icehockey_nhl"))
    assert sorted(f._ingestor.asset_ids()) == ["h1", "n1", "n2"]

    current["basketball_nba"] = ["n2"]
    asyncio.run(f._run_sport_cycle("basketball_nba"))
    assert sorted(f._ingestor.asset_ids()) == ["h1", "n2"]

    # Empty Gamma response = glitch → registrations kept.
    current["events"] = []
    current["basketball_nba"] = []
    asyncio.run(f._run_sport_cycle("basketball_nba"))
    assert sorted(f._ingestor.asset_ids()) == ["h1", "n2"]

    dbg = f.debug_stats()
    assert dbg["ingestor"]["templates_assets"] == 2
    assert "subscribed_assets" in dbg["ws_client"]
