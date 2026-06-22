"""Sidecar API surface — place auto-bets, read audit log, toggle mode.

Endpoints:

  POST /api/sidecar/place             Enqueue a placement job. Returns 202
                                       with {job_id, plan_preview} so the UI
                                       can render the split preview while the
                                       BackgroundTask fires. 503 when mode is
                                       'off'; 404 when ev_row_id no longer
                                       resolves; 422 on a bad kelly_fraction.
  GET  /api/sidecar/runs?limit=N      Recent placements across all jobs,
                                       newest first. Source-of-truth for the
                                       /sidecar dashboard's RunLog.
  GET  /api/sidecar/runs/{job_id}     All placements for a single job,
                                       oldest-first (rendered as a 1/N..N/N
                                       receipt sequence in the modal).
  GET  /api/sidecar/mode              Current mode ({'mode': 'off'|...}).
  POST /api/sidecar/mode              Flip mode; returns the new mode.
  GET  /api/sidecar/active-signals    Currently-armed signals (pre-game) for
                                       the dashboard's ActiveSignalsPanel.

All long-running work happens in a BackgroundTask owned by the orchestrator;
this router only validates input, resolves the ev_row_id, computes the plan
preview synchronously, and hands off.
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from server.sidecar import factory
from server.sidecar.audit import fetch_job, fetch_placements
from server.sidecar.mode_store import SidecarMode
from server.sidecar.models import SidecarPlaceRequest
from server.sidecar.resolve import resolve_ev_row_to_leg
from server.sidecar.settings import (
    KellyFraction,
    get_bankroll,
    get_default_kelly,
    kelly_to_pct,
)
from server.sidecar.splitter import plan_splits


logger = logging.getLogger(__name__)


class PlaceBody(BaseModel):
    ev_row_id: str = Field(..., min_length=1)
    kelly_fraction: str  # 'full' | 'half' | 'quarter'


class PlaceResponse(BaseModel):
    job_id: str
    plan_preview: dict | None = None


class ModeResponse(BaseModel):
    mode: str


class ModeBody(BaseModel):
    mode: str  # 'off' | 'dry-run' | 'live'


class SidecarSettingsResponse(BaseModel):
    """Bankroll + default Kelly used by the sidecar dashboard.

    These are stored as opaque extra keys in user_settings.json (the
    UserSettings dataclass deliberately ignores them — see Task B3), so we
    expose them via a small dedicated endpoint rather than the general
    /api/settings response. The /sidecar SignalFeed reads this to display
    the Kelly-derived dollar stake on each row + AutoPlace button label.
    """

    bankroll: int
    default_kelly: str  # 'full' | 'half' | 'quarter'


def _audit_conn() -> sqlite3.Connection:
    """Fresh connection per call, properly closed via context manager.

    Read-only GET routes open their own connection so they don't contend with
    the orchestrator's writes (sqlite handles this fine with WAL, and even
    without WAL the readers just retry).
    """
    return sqlite3.connect(str(factory.cache_db_path()))


def build_router() -> APIRouter:
    """Construct the sidecar router.

    The router has no constructor-time dependencies — it reads its scraper +
    cache path lazily through ``server.sidecar.factory`` so the singleton
    orchestrator stays consistent between the route layer and the delta-tick
    scheduler.
    """
    router = APIRouter(prefix="/api/sidecar", tags=["sidecar"])

    @router.post("/place", status_code=202, response_model=PlaceResponse)
    async def post_place(
        body: PlaceBody, background_tasks: BackgroundTasks,
    ) -> PlaceResponse:
        # 1) Hard off-gate first — refuse before resolving the leg or building
        #    the orchestrator. Keeps the off-mode path cheap and avoids
        #    needlessly hitting the EV scanner.
        mode = factory.mode_store().get()
        if mode is SidecarMode.OFF:
            raise HTTPException(
                status_code=503, detail="sidecar mode is off",
            )

        # 2) Validate kelly_fraction up-front — Pydantic accepts any string,
        #    but the enum will raise on a bogus value. Turn that into a 422
        #    rather than a 500.
        try:
            fraction = KellyFraction(body.kelly_fraction)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"invalid kelly_fraction: {body.kelly_fraction}",
            ) from exc

        # 3) Resolve the ev_row_id back to a LegSpec via the live EV scan.
        #    None means the row aged out (line moved off best price, event
        #    went off the board, etc.). 404 surfaces cleanly to the UI.
        resolved = resolve_ev_row_to_leg(body.ev_row_id)
        if resolved is None:
            raise HTTPException(
                status_code=404,
                detail=f"ev_row_id not found: {body.ev_row_id}",
            )
        ev_leg, kelly_full_pct = resolved

        bankroll = get_bankroll()
        orchestrator = factory.get_orchestrator()
        # Keep orchestrator mode in lockstep with the persisted file. The
        # singleton is built once per process, so without this re-read a
        # POST /mode flip wouldn't take effect until the next restart.
        orchestrator.mode = mode.value

        req = SidecarPlaceRequest(
            ev_row_id=body.ev_row_id,
            ev_leg=ev_leg,
            kelly_full_pct=kelly_full_pct,
            kelly_fraction=fraction,
            bankroll=bankroll,
        )

        # 4) Pre-compute the plan preview SYNCHRONOUSLY so the UI's confirm
        #    modal can render the split breakdown immediately. The
        #    background task re-runs plan_splits against a fresh pool
        #    snapshot when it actually fires; the preview is best-effort.
        try:
            target = int(round(kelly_to_pct(fraction, kelly_full_pct) * bankroll))
            pool = orchestrator.pool_provider()
            plan = plan_splits(target, pool)
            plan_preview: dict[str, Any] = {
                "target": plan.target,
                "status": plan.status,
                "filled": plan.filled,
                "unfilled": plan.unfilled,
                "assignments": [
                    {
                        "customer_id": a.account.customer_id,
                        "amount": a.amount,
                    }
                    for a in plan.assignments
                ],
            }
        except Exception:  # noqa: BLE001
            # Preview is non-critical; the orchestrator will still try to
            # place. Log + return an empty preview rather than 500-ing.
            logger.exception(
                "plan_preview build failed for ev_row_id=%s", body.ev_row_id,
            )
            plan_preview = None

        # 5) Hand off to the orchestrator. The route returns 202 immediately;
        #    SSE delivers progress events keyed on the returned job_id.
        job_id = uuid.uuid4().hex
        background_tasks.add_task(orchestrator.handle_place, req, job_id)
        return PlaceResponse(job_id=job_id, plan_preview=plan_preview)

    @router.get("/runs")
    def get_runs(limit: int = 100) -> list[dict]:
        """Recent placements across all jobs, newest-first.

        The dashboard's RunLog calls this once on mount and re-polls on
        ``sidecar_placement`` SSE invalidations.
        """
        conn = _audit_conn()
        try:
            return [r.__dict__ for r in fetch_placements(conn, limit=limit)]
        finally:
            conn.close()

    @router.get("/runs/{job_id}")
    def get_run(job_id: str) -> list[dict]:
        """All placements for one job, oldest-first. 404 if the job_id has
        no rows (either it's still pending or never existed)."""
        conn = _audit_conn()
        try:
            rows = fetch_job(conn, job_id)
            if not rows:
                raise HTTPException(
                    status_code=404, detail=f"job not found: {job_id}",
                )
            return [r.__dict__ for r in rows]
        finally:
            conn.close()

    @router.get("/mode", response_model=ModeResponse)
    def get_mode() -> ModeResponse:
        return ModeResponse(mode=factory.mode_store().get().value)

    @router.post("/mode", response_model=ModeResponse)
    def post_mode(body: ModeBody) -> ModeResponse:
        store = factory.mode_store()
        try:
            new_mode = SidecarMode(body.mode)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"invalid mode: {body.mode}",
            ) from exc
        store.set(new_mode)
        # Mirror the new mode onto the live orchestrator instance if it's
        # already been built. Without this the cached singleton would keep
        # serving the boot-time mode until process restart.
        try:
            factory.get_orchestrator().mode = new_mode.value
        except Exception:  # noqa: BLE001
            logger.exception("failed to propagate new mode to orchestrator")
        return ModeResponse(mode=new_mode.value)

    @router.get("/settings", response_model=SidecarSettingsResponse)
    def get_sidecar_settings() -> SidecarSettingsResponse:
        """Return the sidecar-specific user settings (bankroll + default
        Kelly fraction). The /sidecar SignalFeed reads this to render the
        Kelly-derived dollar stake on each row and the AutoPlace button
        label without opening the confirm modal.
        """
        return SidecarSettingsResponse(
            bankroll=get_bankroll(),
            default_kelly=get_default_kelly().value,
        )

    @router.get("/active-signals")
    def get_active_signals() -> list[dict]:
        """List active (pre-game) signals being tracked by the delta-tick
        loop. Sourced from sidecar_active_signals. Empty when nothing is
        armed.
        """
        # Lazy import — the active_signals module is part of the same
        # package, but importing at module load creates a circular hint
        # path through resolve.py in some test orderings.
        from server.sidecar import active_signals

        conn = _audit_conn()
        try:
            signals = active_signals.list_active(conn)
            return [s.__dict__ for s in signals]
        finally:
            conn.close()

    return router
