"""ODDS_API_FETCHER_ENABLED — the gate that stops THIS repo from
spending Odds API credit while every other fetcher keeps running.

Deliberately narrower than cache_mode: cache_mode=latest silences
coral33 / kalshi / polymarket too, and those are free and must stay up.

Every entry point that can bill the Odds API is covered here:
  * scheduled polling      -> FetcherRegistry.start_all
  * UI "refresh all"       -> FetcherRegistry.refresh_all_now
  * UI per-game refresh    -> FetcherRegistry.refresh_event
  * historical CLV backfill-> POST /api/coral33/accounts/clv-backfill
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.config import Config
from server.odds.fetcher import FetcherRegistry


def _registry(*, enabled: bool, api_key: str = "k") -> FetcherRegistry:
    config = MagicMock()
    config.odds_api_fetcher_enabled = enabled
    config.odds_api_key = api_key
    config.odds_poll_interval = 30
    client = MagicMock()
    client.resolve_sport_keys = AsyncMock(return_value=[])
    return FetcherRegistry(
        config=config,
        sports=[],
        cache=MagicMock(),
        client=client,
        settings_store=MagicMock(),
    )


# ───────────────────────────── config ────────────────────────────────

def test_flag_defaults_to_enabled(monkeypatch):
    """Absent env var = today's behavior. This is the inertness check."""
    monkeypatch.delenv("ODDS_API_FETCHER_ENABLED", raising=False)
    assert Config.from_env().odds_api_fetcher_enabled is True


@pytest.mark.parametrize("raw", ["false", "FALSE", "0", "no", "off", " false "])
def test_falsey_values_disable(monkeypatch, raw):
    monkeypatch.setenv("ODDS_API_FETCHER_ENABLED", raw)
    assert Config.from_env().odds_api_fetcher_enabled is False


@pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", "anything"])
def test_other_values_leave_it_enabled(monkeypatch, raw):
    monkeypatch.setenv("ODDS_API_FETCHER_ENABLED", raw)
    assert Config.from_env().odds_api_fetcher_enabled is True


# ─────────────────────── spend path: start_all ────────────────────────

def test_start_all_refuses_when_disabled():
    reg = _registry(enabled=False)
    reg.all_enabled_tiers = MagicMock(return_value=[("sport", "tier")])
    reg._scheduler = MagicMock()

    assert reg.start_all() == {"status": "disabled_by_env"}
    # Nothing scheduled, nothing marked running — the registry is inert.
    assert reg._scheduler.add_job.call_count == 0
    assert reg._running is False
    # The gate short-circuits BEFORE tier resolution, so no config or
    # market TOML work happens either.
    assert reg.all_enabled_tiers.call_count == 0


def test_start_all_proceeds_past_the_gate_when_enabled():
    """With the flag on, the gate is transparent — start_all falls
    through to its existing checks exactly as before."""
    reg = _registry(enabled=True, api_key="")
    assert reg.start_all() == {"status": "no_api_key"}


# ───────────────────── spend path: refresh_all_now ────────────────────

def test_refresh_all_now_is_a_noop_when_disabled():
    reg = _registry(enabled=False)
    reg.all_enabled_tiers = MagicMock(return_value=[("sport", "tier")])
    reg._tier_runner = MagicMock()

    assert reg.refresh_all_now() == {"status": "disabled_by_env", "triggered": []}
    assert reg._tier_runner.call_count == 0
    assert reg.all_enabled_tiers.call_count == 0


# ────────────────────── spend path: refresh_event ─────────────────────

@pytest.mark.asyncio
async def test_refresh_event_is_a_noop_when_disabled():
    reg = _registry(enabled=False)
    result = await reg.refresh_event("evt_1")
    assert result == {"status": "disabled_by_env", "event_id": "evt_1"}
    # Never looked the event up, never resolved keys, never hit the client.
    assert reg.cache.event_sport_key.call_count == 0
    assert reg.client.resolve_sport_keys.await_count == 0
    # And it did not burn the caller's debounce slot, so re-enabling the
    # flag doesn't leave the UI button dead for 60s.
    assert reg._event_refresh_ts == {}


@pytest.mark.asyncio
async def test_refresh_event_proceeds_past_the_gate_when_enabled():
    reg = _registry(enabled=True)
    reg.cache.event_sport_key = MagicMock(return_value=None)
    result = await reg.refresh_event("evt_1")
    assert result["status"] == "unknown_event"
    assert reg.cache.event_sport_key.call_count == 1


# ───────────────── startup: no ODDS_API_KEY, flag off ─────────────────

@pytest.fixture
def app_env(monkeypatch, tmp_path):
    """Mirrors test_api.py's app fixture, minus the API key."""
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    monkeypatch.setenv("BET_CARD_DIR", str(Path(__file__).parent / "fixtures"))
    monkeypatch.setenv(
        "BETS_CSV",
        str(Path(__file__).parent / "fixtures" / "bets_example.csv"),
    )

    import server.config as config_mod
    import server.user_settings as us_mod

    original_from_env = config_mod.Config.from_env

    def patched_from_env():
        c = original_from_env()
        c.cache_db = tmp_path / "cache.db"
        return c

    monkeypatch.setattr(config_mod.Config, "from_env", staticmethod(patched_from_env))
    monkeypatch.setattr(us_mod, "SETTINGS_PATH", tmp_path / "user_settings.json")
    # The lifespan only starts ANY fetcher in cache_mode=live; without
    # this the startup assertions below would pass vacuously.
    (tmp_path / "cache_mode.json").write_text('{"mode": "live"}')
    return monkeypatch


def test_app_starts_with_no_api_key_and_fetcher_disabled(app_env):
    """Mike will eventually delete ODDS_API_KEY entirely. Startup must not
    depend on it once the fetcher is off."""
    app_env.setenv("ODDS_API_FETCHER_ENABLED", "false")

    from fastapi.testclient import TestClient
    from server.main import create_app

    # Stub every fetcher's start_all so the lifespan exercises startup
    # without spinning up real pollers / websockets in a test.
    _spy_startups(app_env)

    app = create_app()
    with TestClient(app) as c:            # runs the full lifespan
        assert c.get("/api/health").status_code == 200


def _spy_startups(monkeypatch):
    """Record which fetchers the lifespan starts, without starting any."""
    import server.main as main_mod

    started: list[str] = []
    for label, cls in (
        ("odds_api", main_mod.FetcherRegistry),
        ("kalshi", main_mod.KalshiFetcher),
        ("polymarket", main_mod.PolymarketFetcher),
        ("coral33", main_mod.Coral33Fetcher),
    ):
        def spy(self, _label=label):
            started.append(_label)
            return {"status": "spied"}
        monkeypatch.setattr(cls, "start_all", spy)
    return started


def test_disabled_flag_stops_only_the_odds_api_fetcher(app_env):
    """Blast radius: in cache_mode=live the gate must suppress the Odds
    API fetcher and NOTHING else. The free direct-book fetchers keep
    running — that is the whole reason this is not cache_mode=latest."""
    app_env.setenv("ODDS_API_FETCHER_ENABLED", "false")

    import server.main as main_mod
    from fastapi.testclient import TestClient

    started = _spy_startups(app_env)
    with TestClient(main_mod.create_app()):
        pass

    assert "odds_api" not in started
    assert "kalshi" in started
    assert "polymarket" in started


def test_enabled_flag_starts_the_odds_api_fetcher(app_env):
    """The contrast case — proves the assertion above is not vacuous."""
    app_env.setenv("ODDS_API_FETCHER_ENABLED", "true")
    app_env.setenv("ODDS_API_KEY", "test-key")

    import server.main as main_mod
    from fastapi.testclient import TestClient

    started = _spy_startups(app_env)
    with TestClient(main_mod.create_app()):
        pass

    assert "odds_api" in started
    assert "kalshi" in started


# ──────────── spend path: historical CLV backfill endpoint ────────────

@pytest.mark.asyncio
async def test_clv_backfill_endpoint_refuses_when_disabled(monkeypatch):
    """`POST /api/coral33/accounts/clv-backfill` walks the Odds API's
    HISTORICAL endpoints, which cost more per request than the live ones
    — and dry_run=True still spends on event discovery. It must refuse
    with the fetcher gated off."""
    monkeypatch.setenv("ODDS_API_FETCHER_ENABLED", "false")

    from server.api.coral33_accounts import build_router

    scraper = MagicMock()
    scraper.get_wager_log = AsyncMock(return_value={})
    router = build_router(scraper, cache=MagicMock(), odds_client=MagicMock())

    route = next(
        r for r in router.routes
        if getattr(r, "path", "") == "/api/coral33/accounts/clv-backfill"
    )
    result = await route.endpoint(dry_run=False)

    assert result["status"] == "disabled_by_env"
    # Never even read the wager log, let alone hit the historical API.
    assert scraper.get_wager_log.await_count == 0
