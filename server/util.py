"""Small shared utilities."""
from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """Tiny request-level memoizer.

    Used by scan endpoints to collapse bursts of simultaneous SWR requests
    (the Edges page fires arb + low-hold + ev + free-bet together every
    poll) into one underlying scan. Each entry expires after `ttl_seconds`.

    Not LRU — we GC eagerly on `set` once the store grows past
    `gc_threshold`. Keys must be hashable; callers compose them as tuples
    of all inputs that affect the response (including `cache.path` so
    cache-mode flips invalidate too).
    """

    def __init__(self, ttl_seconds: float = 20.0, gc_threshold: int = 64) -> None:
        self._ttl = ttl_seconds
        self._gc_threshold = gc_threshold
        self._store: dict[tuple, tuple[float, Any]] = {}

    def get(self, key: tuple) -> Any | None:
        hit = self._store.get(key)
        if hit is None:
            return None
        ts, val = hit
        if time.time() - ts >= self._ttl:
            return None
        return val

    def set(self, key: tuple, value: Any) -> None:
        self._store[key] = (time.time(), value)
        if len(self._store) > self._gc_threshold:
            now = time.time()
            self._store = {
                k: v for k, v in self._store.items() if now - v[0] < self._ttl
            }
