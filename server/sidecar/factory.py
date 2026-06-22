"""Singleton SidecarOrchestrator wiring.

Provides ``get_orchestrator()`` — returns a process-wide singleton orchestrator
configured against the running AccountsScraper, a real Coral33Placer factory,
and the live SidecarModeStore. Tests can swap dependencies via
``configure(...)`` (called from ``create_app``) or by patching the module-level
fields directly.

Why a factory module instead of plumbing through ``build_router(deps)``: the
delta-tick scheduler (Phase E5) and the route layer both need the same
orchestrator instance, and the orchestrator owns burned-account / placer-cache
state that must be shared. A module-level singleton is the simplest fit.

Also exposes ``set_orchestrator(orch)`` (legacy E5 helper) — kept for backward
compatibility with the delta-tick tests that may install a fake instance.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from server.sidecar.models import AccountSnapshot
from server.sidecar.mode_store import SidecarModeStore
from server.sidecar.placement import SidecarOrchestrator


logger = logging.getLogger(__name__)


# Module-level wiring set by ``configure(...)`` from ``server.main.create_app``.
# Held as plain globals so tests can patch them with monkeypatch without having
# to thread fixtures through every code path that touches the orchestrator.
_scraper: Any = None
_cache_db_path: Path = Path("server/cache.db")
# Lives next to cache.db (mirrors the existing cache_mode.json pattern at
# server/cache_mode.json). server/main.py overrides this via configure() to
# the same path; the default is here for subprocesses / scripts that import
# the factory without going through create_app.
_mode_config_path: Path = (
    Path(__file__).resolve().parent.parent / "sidecar_mode.json"
)
_orchestrator: SidecarOrchestrator | None = None


def configure(
    scraper: Any,
    cache_db_path: Path | None = None,
    mode_config_path: Path | None = None,
) -> None:
    """Wire dependencies at app startup. Idempotent — repeated calls swap the
    scraper / paths AND invalidate the cached orchestrator so the next
    ``get_orchestrator()`` call rebuilds with the new wiring.
    """
    global _scraper, _cache_db_path, _mode_config_path, _orchestrator
    _scraper = scraper
    if cache_db_path is not None:
        _cache_db_path = Path(cache_db_path)
    if mode_config_path is not None:
        _mode_config_path = Path(mode_config_path)
    _orchestrator = None  # force rebuild on next get


def reset() -> None:
    """Test helper: drop the cached orchestrator + clear configured scraper."""
    global _scraper, _orchestrator
    _scraper = None
    _orchestrator = None


def mode_store() -> SidecarModeStore:
    """Single source of truth for the mode-store path; both the route layer
    and the orchestrator factory must read from the same file."""
    return SidecarModeStore(_mode_config_path)


def cache_db_path() -> Path:
    """Where the audit + active-signals tables live. Exposed so the route
    layer's read-only GET endpoints open the same DB the orchestrator writes
    to."""
    return _cache_db_path


def get_orchestrator() -> SidecarOrchestrator:
    """Return the process-wide orchestrator, building it on first call.

    On startup ``configure(scraper)`` should have been called from
    ``create_app``; if it wasn't (e.g. unit-test imports ``server.main`` and
    the lifespan never ran), the pool provider returns an empty list and the
    placer factory raises if asked to build a placer. The mode gate is still
    honored either way.
    """
    global _orchestrator
    if _orchestrator is not None:
        return _orchestrator

    current_mode = mode_store().get().value
    _orchestrator = SidecarOrchestrator(
        pool_provider=_load_pool,
        placer_factory=_PlacerFactory(),
        mode=current_mode,
        db_path=_cache_db_path,
        refresh_accounts=_refresh_accounts,
    )
    return _orchestrator


def set_orchestrator(orch: SidecarOrchestrator) -> None:
    """Legacy E5 helper — install an externally-built orchestrator. Used by
    delta-tick tests to swap in a fake. Production code should call
    ``configure(...)`` and let ``get_orchestrator()`` build the singleton.
    """
    global _orchestrator
    _orchestrator = orch


def _load_pool() -> list[AccountSnapshot]:
    """Build the splitter's pool snapshot from the latest AccountsScraper
    roll-up. Skips accounts in error state so they don't poison the splitter.
    """
    if _scraper is None:
        return []
    rollup = _scraper.cached()
    out: list[AccountSnapshot] = []
    creds_by_id = {c.customer_id: c for c in _scraper.credentials}
    for snap in rollup.snapshots:
        if snap.error:
            continue
        cred = creds_by_id.get(snap.customer_id)
        if cred is None:
            # Snapshot for an account we no longer have credentials for —
            # skip rather than crash; the next env reload will sync up.
            continue
        out.append(AccountSnapshot(
            credential=cred,
            available_balance=float(snap.available_balance),
            agent_id=snap.agent_id,
            store=snap.store,
            cust_profile=snap.cust_profile,
        ))
    return out


class _PlacerFactory:
    """Builds Coral33Placer instances against the snapshot's credential.

    The orchestrator caches per-account placers; this factory is called once
    per (job_id, customer_id) pair. Each call constructs a fresh Coral33Client
    with the snapshot's proxy_url so the per-account session reuse contract
    in the orchestrator holds.
    """

    def for_account(self, snapshot: AccountSnapshot) -> Any:
        # Lazy imports — keeps the factory module importable in test
        # environments that don't have the coral33 client installed (e.g.
        # the unit tests for the splitter / mode store run in isolation).
        from server.odds.books.coral33.client import Coral33Client
        from server.odds.books.coral33.placement import Coral33Placer

        cred = snapshot.credential
        client = Coral33Client(
            customer_id=cred.customer_id,
            password=cred.password,
            proxy_url=cred.proxy_url,
        )
        agent_id = snapshot.agent_id or ""
        store = snapshot.store or ""
        cust_profile = snapshot.cust_profile or ""
        if not agent_id:
            logger.warning(
                "Coral33Placer for %s built without agent_id — placement "
                "may fail; refresh the AccountsScraper rollup",
                cred.customer_id,
            )
        return Coral33Placer(
            client=client,
            agent_id=agent_id,
            store=store,
            cust_profile=cust_profile,
        )


def _refresh_accounts(customer_ids: set[str]) -> Any:
    """Hook invoked by the orchestrator after a placement loop finishes.

    The existing ``AccountsScraper.trigger_refresh_async`` refreshes the
    entire pool; the orchestrator passes which customer_ids it actually
    touched so a future targeted refresh can use this list.
    """
    if _scraper is None:
        return None
    try:
        return _scraper.trigger_refresh_async()
    except Exception:  # noqa: BLE001
        logger.exception(
            "post-job refresh for %s failed via factory", customer_ids,
        )
        return None
