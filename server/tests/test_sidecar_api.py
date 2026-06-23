"""FastAPI route tests for the sidecar surface.

Covers all six endpoints introduced in Task F1 + the active-signals endpoint
from H5 Step 1:

  POST /api/sidecar/place              place a job (202)
  GET  /api/sidecar/runs               recent placements
  GET  /api/sidecar/runs/{job_id}      single-job placements (404 when empty)
  GET  /api/sidecar/mode                read mode
  POST /api/sidecar/mode               flip mode
  GET  /api/sidecar/active-signals     pre-game armed signals

Tests build the app via ``create_app`` (rather than importing the module-level
``app``) so each test gets a clean tmp_path-scoped sidecar_mode.json and
cache.db. The Coral33 placement client is never reached — the orchestrator's
placer factory is swapped for a fake via ``factory.configure(...)``.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from server.odds.cache import init_schema_on_path
from server.sidecar import active_signals as active_signals_mod
from server.sidecar import factory as sidecar_factory
from server.sidecar.mode_store import SidecarMode, SidecarModeStore
from server.sidecar.models import AccountSnapshot, LegSpec
from server.sidecar.placement import SidecarOrchestrator
from server.sidecar.settings import KellyFraction


@pytest.fixture
def isolated_paths(tmp_path: Path, monkeypatch):
    """Point the factory at a tmp-scoped cache.db + sidecar_mode.json so each
    test starts from a clean slate. Also stubs ``resolve_ev_row_to_leg`` so
    the place route has a deterministic mapping from id -> LegSpec.
    """
    cache_db = tmp_path / "cache.db"
    init_schema_on_path(cache_db)
    mode_path = tmp_path / "sidecar_mode.json"

    # Build a tiny fake AccountsScraper-like surface. The factory only reads
    # ``.cached()`` and ``.credentials``; ``trigger_refresh_async`` is the
    # refresh hook (returns immediately).
    from server.odds.books.coral33.accounts import (
        AccountCredential,
        AccountSnapshot as ScraperAccountSnapshot,
        AccountsRollup,
    )

    cred = AccountCredential(
        customer_id="VR_TEST", password="pw",
        proxy_url=None, max_parlay_stake=100,
    )
    snap = ScraperAccountSnapshot(
        customer_id="VR_TEST",
        label="Test",
        fetched_at="2026-06-21T00:00:00+00:00",
        available_balance=500.0,
        agent_id="AGENT_TEST",
        store="01",
        cust_profile="   ",
    )
    fake_scraper = MagicMock()
    fake_scraper.credentials = [cred]
    fake_scraper.cached.return_value = AccountsRollup(
        snapshots=[snap], refreshed_at=None, refreshing=False,
    )
    fake_scraper.trigger_refresh_async.return_value = {"status": "triggered"}

    sidecar_factory.configure(
        scraper=fake_scraper,
        cache_db_path=cache_db,
        mode_config_path=mode_path,
    )

    # Stub the resolver so test ids map to a known LegSpec; "nonexistent"
    # explicitly resolves to None so the 404 path is exercised.
    def fake_resolve(ev_row_id: str):
        if ev_row_id == "nonexistent":
            return None
        leg = LegSpec(
            sport_type="Soccer              ",
            sport_sub_type="WORLD CUP   ",
            period="Game",
            line_type="M",
            game_num=619136397,
            chosen_team_id="New Zealand",
            rot_num=225390,
            price_american=475,
            price_decimal=5.75,
            price_numerator=19,
            price_denominator=4,
            game_datetime="2099-06-21 19:00:01.000",
            description="Soccer #225390 New Zealand +475 - For Game ",
        )
        return leg, 0.02  # 2% full Kelly

    monkeypatch.setattr(
        "server.api.sidecar.resolve_ev_row_to_leg", fake_resolve,
    )

    # Stub the placer factory so no real Coral33 client / HTTP call is
    # attempted from the background task. Returns a coroutine-aware fake
    # that emits a "dry_run"-shaped result.
    class _FakeResult:
        def __init__(self) -> None:
            self.ticket_number = None
            self.dry_run = True
            self.accepted_payload = None
            self.would_be_payload = {"stub": True}
            self.decimal_payout = 1.0
            self.expected_win = 0.0

    class _FakePlacer:
        async def place_open_parlay(self, ev_leg, stake_dollars, live):
            return _FakeResult()

    class _FakePlacerFactory:
        def for_account(self, snapshot):
            return _FakePlacer()

    # The orchestrator builds on first ``get_orchestrator()`` call; swap its
    # placer factory by patching the module's _PlacerFactory class.
    monkeypatch.setattr(
        sidecar_factory, "_PlacerFactory", _FakePlacerFactory,
    )

    yield {
        "cache_db": cache_db,
        "mode_path": mode_path,
        "fake_scraper": fake_scraper,
    }

    # Clean up the cached orchestrator so the next test rebuilds against
    # its own tmp_path. Without this the singleton survives across tests.
    sidecar_factory.reset()


@pytest.fixture
def app(isolated_paths, monkeypatch):
    """Build a fresh FastAPI app per test, with all heavy dependencies stubbed
    out. We don't use the TestClient context-manager form (which runs the
    full lifespan) because the lifespan starts schedulers + fetchers we
    don't need for these route tests."""
    monkeypatch.setenv("ODDS_API_KEY", "")
    from server.main import create_app
    application = create_app()
    # ``create_app`` re-runs ``factory.configure`` against the production
    # paths; re-pin our test paths so they win.
    sidecar_factory.configure(
        scraper=isolated_paths["fake_scraper"],
        cache_db_path=isolated_paths["cache_db"],
        mode_config_path=isolated_paths["mode_path"],
    )
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


# --------------------------------------------------------------------------
# /mode
# --------------------------------------------------------------------------

def test_get_mode_default_is_off(client):
    r = client.get("/api/sidecar/mode")
    assert r.status_code == 200
    assert r.json() == {"mode": "off"}


def test_post_mode_cycles_through_all_three(client):
    for mode in ("dry-run", "live", "off"):
        r = client.post("/api/sidecar/mode", json={"mode": mode})
        assert r.status_code == 200
        assert r.json() == {"mode": mode}
        # Re-read to confirm persistence
        assert client.get("/api/sidecar/mode").json() == {"mode": mode}


def test_post_mode_rejects_bogus_mode(client):
    r = client.post("/api/sidecar/mode", json={"mode": "wild"})
    assert r.status_code == 422


# --------------------------------------------------------------------------
# /place
# --------------------------------------------------------------------------

def test_place_returns_503_when_mode_is_off(client):
    # Default mode is off (no prior set on this fresh tmp_path)
    r = client.post("/api/sidecar/place", json={
        "ev_row_id": "rid-X", "kelly_fraction": "half",
    })
    assert r.status_code == 503
    assert "off" in r.json()["detail"]


def test_post_place_returns_job_id(client):
    # Flip to dry-run so the off-gate doesn't fire
    client.post("/api/sidecar/mode", json={"mode": "dry-run"})

    r = client.post("/api/sidecar/place", json={
        "ev_row_id": "619136397|h2h|new_zealand",
        "kelly_fraction": "half",
    })
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body
    assert len(body["job_id"]) == 32  # uuid4 hex
    # Plan preview is computed synchronously; status will be
    # 'below_minimum' (Kelly target $100 * 0.02 * 0.5 = $1) — the route
    # still returns 202 because the orchestrator handles the refusal.
    assert body["plan_preview"] is not None
    assert "status" in body["plan_preview"]


def test_post_place_validates_ev_row_id_exists(client):
    client.post("/api/sidecar/mode", json={"mode": "dry-run"})
    r = client.post("/api/sidecar/place", json={
        "ev_row_id": "nonexistent",
        "kelly_fraction": "half",
    })
    assert r.status_code == 404
    assert "nonexistent" in r.json()["detail"]


def test_post_place_validates_kelly_fraction(client):
    client.post("/api/sidecar/mode", json={"mode": "dry-run"})
    r = client.post("/api/sidecar/place", json={
        "ev_row_id": "619136397|h2h|new_zealand",
        "kelly_fraction": "wild",
    })
    assert r.status_code == 422


# --------------------------------------------------------------------------
# /runs
# --------------------------------------------------------------------------

def test_get_runs_returns_recent_jobs(client, isolated_paths):
    # Empty cache -> empty list
    r = client.get("/api/sidecar/runs?limit=20")
    assert r.status_code == 200
    assert r.json() == []

    # Seed a row directly via audit to keep this test independent of the
    # /place background task's timing.
    from server.sidecar.audit import AuditRow, insert_placement
    conn = sqlite3.connect(str(isolated_paths["cache_db"]))
    try:
        insert_placement(conn, AuditRow(
            placement_id="p1", job_id="j1", created_at=int(time.time()),
            ev_row_id="rid", ev_leg="{}", parlay_name="10 team",
            kelly_fraction="half", target_stake=100.0, stake=100.0,
            mode="dry-run", picked_account="VR_TEST", result="dry_run",
            ticket_number=None, accepted_payload=None, error_message=None,
        ))
    finally:
        conn.close()

    r = client.get("/api/sidecar/runs?limit=20")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["job_id"] == "j1"
    assert rows[0]["result"] == "dry_run"


def test_get_run_by_job_id_404_when_missing(client):
    r = client.get("/api/sidecar/runs/missing-job-id")
    assert r.status_code == 404


def test_get_run_by_job_id_returns_rows(client, isolated_paths):
    from server.sidecar.audit import AuditRow, insert_placement
    conn = sqlite3.connect(str(isolated_paths["cache_db"]))
    try:
        for amount in (100, 30):
            insert_placement(conn, AuditRow(
                placement_id=f"p_{amount}", job_id="job_xyz",
                created_at=int(time.time()),
                ev_row_id="rid", ev_leg="{}", parlay_name="10 team",
                kelly_fraction="half", target_stake=130.0, stake=float(amount),
                mode="dry-run", picked_account="VR_TEST", result="dry_run",
                ticket_number=None, accepted_payload=None, error_message=None,
            ))
    finally:
        conn.close()

    r = client.get("/api/sidecar/runs/job_xyz")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert sum(row["stake"] for row in rows) == 130.0


# --------------------------------------------------------------------------
# /settings
# --------------------------------------------------------------------------

def test_get_sidecar_settings_defaults(client, tmp_path, monkeypatch):
    """With no overrides set, /api/sidecar/settings returns the documented
    defaults: $10,000 bankroll, half-Kelly. Point the settings module at an
    empty tmp file so we don't depend on the developer's local
    user_settings.json having (or not having) sidecar_* keys."""
    empty_settings = tmp_path / "empty_user_settings.json"
    empty_settings.write_text("{}")
    monkeypatch.setattr(
        "server.sidecar.settings._settings_path",
        lambda: empty_settings,
    )

    r = client.get("/api/sidecar/settings")
    assert r.status_code == 200
    assert r.json() == {"bankroll": 10000, "default_kelly": "half"}


# --------------------------------------------------------------------------
# /active-signals
# --------------------------------------------------------------------------

def test_active_signals_empty_by_default(client):
    r = client.get("/api/sidecar/active-signals")
    assert r.status_code == 200
    assert r.json() == {"signals": []}


def test_active_signals_returns_armed_signal(client, isolated_paths):
    conn = sqlite3.connect(str(isolated_paths["cache_db"]))
    try:
        active_signals_mod.arm_signal(
            conn,
            ev_row_id="619136397|h2h|new_zealand",
            kelly_fraction=KellyFraction.HALF,
            bankroll_at_arm=10000,
            # Far-future so the list_active() filter doesn't drop it
            commence_time=int(time.time()) + 86400,
            armed_customer_id="VR11605",
        )
    finally:
        conn.close()

    r = client.get("/api/sidecar/active-signals")
    assert r.status_code == 200
    payload = r.json()
    signals = payload["signals"]
    assert len(signals) == 1
    assert signals[0]["ev_row_id"] == "619136397|h2h|new_zealand"
    assert signals[0]["kelly_fraction"] == "half"
    assert signals[0]["bankroll_at_arm"] == 10000
    # Account-first signals carry the pinned customer_id.
    assert signals[0]["armed_customer_id"] == "VR11605"
