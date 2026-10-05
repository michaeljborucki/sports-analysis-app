from __future__ import annotations

import asyncio
import threading
import time

import pytest
from fastapi import HTTPException

from server.odds import scanner_runtime


@pytest.fixture(autouse=True)
def _reset_runtime():
    scanner_runtime._reset_for_tests()
    yield
    scanner_runtime._reset_for_tests()


async def test_blocking_compute_runs_off_event_loop_thread():
    event_loop_thread = threading.get_ident()

    result_thread = await scanner_runtime.run_scanner(
        "thread-check", threading.get_ident,
    )

    assert result_thread != event_loop_thread


async def test_different_scanners_share_one_capacity_slot():
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def compute() -> str:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        with state_lock:
            active -= 1
        return "ok"

    results = await asyncio.gather(
        scanner_runtime.run_scanner("arb", compute),
        scanner_runtime.run_scanner("low-hold", compute),
    )

    assert results == ["ok", "ok"]
    assert maximum_active == 1


async def test_capacity_timeout_is_retryable_503(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking() -> None:
        started.set()
        release.wait(timeout=1)

    first = asyncio.create_task(scanner_runtime.run_scanner("first", blocking))
    await asyncio.to_thread(started.wait, 1)
    monkeypatch.setattr(scanner_runtime, "SCANNER_WAIT_TIMEOUT_S", 0.01)

    with pytest.raises(HTTPException) as exc:
        await scanner_runtime.run_scanner("second", lambda: None)

    assert exc.value.status_code == 503
    assert "retry" in str(exc.value.detail).lower()
    release.set()
    await first


async def test_scanner_run_logs_elapsed_time(caplog):
    caplog.set_level("INFO", logger="server.odds.scanner_runtime")

    await scanner_runtime.run_scanner("timed", lambda: 42)

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith("scanner complete name=timed")
        and "compute_ms=" in message
        and "wait_ms=" in message
        for message in messages
    )
