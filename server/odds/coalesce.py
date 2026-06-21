"""Request coalescing + memoization helper for scanner endpoints.

The cache-version TTLCache memo (see server/util.py + the scanner
endpoints in server/api/) catches the *second-arrival* case: B
arrives after A returns, B hits memo. It does NOT catch the
*simultaneous* case: A and B both start before either completes →
both independently scan the cache.

`memoized_coalesced(memo, key, fn)` plugs that gap:

  1. Fast path — if `memo` has `key`, return immediately.
  2. Coalesce — if a task is already in-flight for this key, await
     THAT task instead of starting a new one. Second/third/N-th
     callers all share the first caller's work.
  3. Spawn — no memo hit, no in-flight task: create a task running
     `fn()`, register it as in-flight, return its result. On task
     completion the result populates the memo and the in-flight
     slot clears.

Cancellation safety. Awaiters use `asyncio.shield`, so an HTTP
request being dropped mid-await does NOT abort the underlying work.
Other awaiters and the memo population still complete normally.
This also means a single-caller scenario where the caller cancels
still warms the memo for the next request — wasted CPU only on the
network side, not on the compute.

Exception semantics. If `fn` raises, the same exception propagates
to every awaiter. The in-flight slot clears regardless of outcome,
and the memo is NOT populated on failure — so the next request
retries cleanly instead of caching an error.

Thread / concurrency model. FastAPI runs handlers in a single
asyncio event loop; `dict` mutations on `_inflight` are atomic
under the GIL with no other thread / coroutine able to interleave
between `key in _inflight` and `_inflight[key] = task`. No lock
needed.

Key collision across endpoints. Each endpoint's `memo` is local to
its `build_router()` closure (separate TTLCache instance). The
`_inflight` registry is process-global, but the cache_key tuples
include endpoint-specific discriminators (e.g. `"arb"`, `"ev"`,
`"low_hold"`) so keys from different endpoints don't collide. Only
same-key concurrent calls share work.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar


T = TypeVar("T")


# Process-global in-flight registry. Maps cache_key → Task running
# the computation. Inserted on first request for a key, removed on
# task completion (via the done-callback below).
_inflight: dict[tuple, "asyncio.Task[Any]"] = {}


async def memoized_coalesced(
    memo: Any,
    key: tuple,
    fn: Callable[[], Awaitable[T]],
) -> T:
    """Combined memo + coalesce wrapper.

    Args:
        memo: object with `get(key) -> value | None` and
              `set(key, value)` — `server.util.TTLCache` fits.
        key:  hashable tuple identifying this computation. Should
              include cache.version + every parameter that affects
              the result, so different inputs don't collide.
        fn:   no-arg async callable that returns the computed value.

    Returns:
        The computed value (from memo, from in-flight task, or
        from a fresh `fn()` invocation depending on which path
        was taken).
    """
    # Path 1 — memo hit. Skip everything else.
    hit = memo.get(key)
    if hit is not None:
        return hit

    # Path 2 — coalesce. Another caller is already computing this
    # exact key; join their task. `asyncio.shield` ensures THIS
    # awaiter's cancellation (e.g. HTTP request dropped) doesn't
    # propagate into the shared task — it keeps running for the
    # other awaiters.
    existing = _inflight.get(key)
    if existing is not None:
        return await asyncio.shield(existing)

    # Path 3 — fresh start. Spawn a task, register it, hook the
    # post-completion cleanup, then await like everyone else.
    task: asyncio.Task[T] = asyncio.create_task(fn())
    _inflight[key] = task

    def _on_done(t: "asyncio.Task[T]") -> None:
        # Always clear the slot so a future request after this one
        # finishes can start fresh.
        _inflight.pop(key, None)
        # Only populate the memo on clean success. Cancellations
        # and exceptions skip memo set, so the next request gets a
        # fresh attempt rather than a cached failure.
        if t.cancelled():
            return
        if t.exception() is not None:
            return
        memo.set(key, t.result())

    task.add_done_callback(_on_done)
    return await asyncio.shield(task)
