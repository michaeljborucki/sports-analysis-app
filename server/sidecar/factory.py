"""Lazy accessor for the shared SidecarOrchestrator instance.

E5 ships a thin lazy-init helper so the delta-tick scheduler has
something to call; Task F1 will replace this with the proper
factory wired against the live account pool, placer factory, and
mode-store-backed mode resolution.

Tests do not exercise this helper — they ``monkeypatch.setattr`` on
``server.sidecar.delta_tick.get_orchestrator`` directly, which means
this module only runs in production at app startup."""
from __future__ import annotations

from typing import Optional

from server.sidecar.placement import SidecarOrchestrator


_orchestrator: Optional[SidecarOrchestrator] = None


def get_orchestrator() -> SidecarOrchestrator:
    """Return the process-wide SidecarOrchestrator.

    TODO(F1): wire this against the real pool/placer/mode_store. Until
    then we raise if anyone outside of tests tries to use it — the only
    in-process caller is the delta-tick scheduler, and tests patch this
    symbol on the delta_tick module before the tick runs.
    """
    global _orchestrator
    if _orchestrator is None:
        raise RuntimeError(
            "SidecarOrchestrator not initialized — set_orchestrator() "
            "must run during app startup before the delta tick fires."
        )
    return _orchestrator


def set_orchestrator(orch: SidecarOrchestrator) -> None:
    """Install the orchestrator at app startup. Idempotent."""
    global _orchestrator
    _orchestrator = orch
