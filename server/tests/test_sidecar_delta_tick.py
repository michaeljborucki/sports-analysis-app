"""Task E5 — 60s autonomous Kelly-delta re-fire scheduler.

Mocks `get_orchestrator` and `resolve_ev_row_to_leg` directly at the
`server.sidecar.delta_tick` module so the tick logic runs in isolation
without a real orchestrator/cache wiring."""
from __future__ import annotations

import asyncio  # noqa: F401  (kept for parity with the plan; mocks are sync)
import sqlite3
import time

import pytest

from server.odds.cache import init_schema_on_path
from server.sidecar import active_signals
from server.sidecar.delta_tick import run_delta_tick
from server.sidecar.models import LegSpec
from server.sidecar.settings import KellyFraction


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "cache.db"
    init_schema_on_path(path)
    return path


def _arm(db_path, ev_row_id, total_placed, commence_in_seconds=3600):
    conn = sqlite3.connect(db_path)
    try:
        active_signals.arm_signal(
            conn, ev_row_id, KellyFraction.HALF, 10000,
            int(time.time()) + commence_in_seconds,
        )
        active_signals.update_total_placed(conn, ev_row_id, total_placed)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_tick_fires_delta_when_kelly_grew(db, monkeypatch):
    """Active signal at total_placed=$100, current Kelly target=$200.
    Delta = $100, above $30 floor → fire a placement job for $100."""
    _arm(db, "rid-grew", total_placed=100)

    fired = []

    async def fake_handle_place(req, job_id):
        fired.append((req.ev_row_id, req.kelly_full_pct))
        return job_id

    leg = LegSpec(sport_type="X", sport_sub_type="Y", period="Game",
                  line_type="M", game_num=1, chosen_team_id="T",
                  rot_num=1, price_american=100, price_decimal=2.0,
                  price_numerator=1, price_denominator=1)
    monkeypatch.setattr(
        "server.sidecar.delta_tick.resolve_ev_row_to_leg",
        # kelly_full_pct is a PERCENTAGE (e.g., 4.0 means 4%).
        # _arm uses HALF by default → 4% × half × $10k = $200 target.
        # Signal already has $100 placed → delta $100 ≥ $30 floor → fires.
        lambda rid: (leg, 4.0),
    )
    # ``staticmethod`` so attribute lookup on the dynamic class doesn't
    # bind the function and prepend `self` to the call args.
    monkeypatch.setattr(
        "server.sidecar.delta_tick.get_orchestrator",
        lambda: type("O", (), {"handle_place": staticmethod(fake_handle_place),
                               "mode": "live"})(),
    )

    await run_delta_tick(db_path=db)
    assert len(fired) == 1
    assert fired[0][0] == "rid-grew"


@pytest.mark.asyncio
async def test_tick_skips_when_delta_below_floor(db, monkeypatch):
    """total_placed=$100, target=$110 → delta $10 < $30, do not fire."""
    _arm(db, "rid-tiny", total_placed=100)

    fired = []

    async def fake_handle_place(req, job_id):
        fired.append(req.ev_row_id)
        return job_id

    leg = LegSpec(sport_type="X", sport_sub_type="Y", period="Game",
                  line_type="M", game_num=1, chosen_team_id="T",
                  rot_num=1, price_american=100, price_decimal=2.0,
                  price_numerator=1, price_denominator=1)
    monkeypatch.setattr(
        "server.sidecar.delta_tick.resolve_ev_row_to_leg",
        # 2.2% × half × $10k = $110 target; signal already has $100 →
        # delta $10 < $30 floor → does NOT fire.
        lambda rid: (leg, 2.2),
    )
    monkeypatch.setattr(
        "server.sidecar.delta_tick.get_orchestrator",
        lambda: type("O", (), {"handle_place": staticmethod(fake_handle_place),
                               "mode": "live"})(),
    )
    await run_delta_tick(db_path=db)
    assert fired == []


@pytest.mark.asyncio
async def test_tick_skips_when_row_no_longer_in_ev_scanner(db, monkeypatch):
    _arm(db, "rid-gone", total_placed=100)
    monkeypatch.setattr(
        "server.sidecar.delta_tick.resolve_ev_row_to_leg",
        lambda rid: None,
    )
    fired = []
    monkeypatch.setattr(
        "server.sidecar.delta_tick.get_orchestrator",
        lambda: type("O", (), {
            "handle_place": lambda req, job_id: (
                fired.append(req.ev_row_id) or job_id
            ),
            "mode": "live",
        })(),
    )
    await run_delta_tick(db_path=db)
    assert fired == []


@pytest.mark.asyncio
async def test_tick_bails_in_off_mode(db, monkeypatch):
    """When sidecar_mode is 'off', the tick exits without scanning."""
    _arm(db, "rid-off", total_placed=100)
    monkeypatch.setattr(
        "server.sidecar.delta_tick.resolve_ev_row_to_leg",
        lambda rid: pytest.fail("should not have called resolve in off mode"),
    )
    monkeypatch.setattr(
        "server.sidecar.delta_tick.get_orchestrator",
        lambda: type("O", (), {"mode": "off",
                               "handle_place": None})(),
    )
    await run_delta_tick(db_path=db)
    # Pass if no failure was raised


@pytest.mark.asyncio
async def test_tick_skips_past_commence_time(db, monkeypatch):
    """Signals whose game has started are filtered by list_active."""
    _arm(db, "rid-live", total_placed=100, commence_in_seconds=-60)
    monkeypatch.setattr(
        "server.sidecar.delta_tick.resolve_ev_row_to_leg",
        lambda rid: pytest.fail("should not have called resolve"),
    )
    monkeypatch.setattr(
        "server.sidecar.delta_tick.get_orchestrator",
        lambda: type("O", (), {"handle_place": None, "mode": "live"})(),
    )
    await run_delta_tick(db_path=db)
