"""Bounded execution for CPU/SQLite-heavy odds scanners."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import TypeVar

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool


T = TypeVar("T")
logger = logging.getLogger(__name__)

SCANNER_WAIT_TIMEOUT_S = 30.0
_capacity = asyncio.Semaphore(1)


async def run_scanner(name: str, compute: Callable[[], T]) -> T:
    """Run one blocking scanner computation without blocking the API loop."""
    waiting_started = time.perf_counter()
    try:
        await asyncio.wait_for(
            _capacity.acquire(), timeout=SCANNER_WAIT_TIMEOUT_S,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"{name} scanner is busy; retry shortly",
            headers={"Retry-After": "2"},
        ) from exc
    try:
        acquired = time.perf_counter()
        result = await run_in_threadpool(compute)
        completed = time.perf_counter()
        logger.info(
            "scanner complete name=%s wait_ms=%.1f compute_ms=%.1f total_ms=%.1f",
            name,
            (acquired - waiting_started) * 1000,
            (completed - acquired) * 1000,
            (completed - waiting_started) * 1000,
        )
        return result
    finally:
        _capacity.release()


def _reset_for_tests() -> None:
    global _capacity
    _capacity = asyncio.Semaphore(1)
