"""Unit tests for the request-coalescing helper.

Exercises every code path in `server/odds/coalesce.py`:
  - memo-hit fast path
  - in-flight join (the actual coalescing)
  - fresh spawn → memo population on success
  - exception propagation to all awaiters
  - exception does NOT poison the memo
  - cancellation of one awaiter doesn't abort the shared task
"""
from __future__ import annotations

import asyncio

import pytest

from server.odds import coalesce
from server.odds.coalesce import memoized_coalesced


class _Memo:
    """Minimal stand-in for server.util.TTLCache — just a dict with
    `get(key) -> value | None` and `set(key, value)`."""

    def __init__(self) -> None:
        self.store: dict[tuple, object] = {}
        self.set_calls = 0

    def get(self, key: tuple):
        return self.store.get(key)

    def set(self, key: tuple, value) -> None:
        self.set_calls += 1
        self.store[key] = value


@pytest.fixture(autouse=True)
def _reset_inflight():
    """Coalesce keeps a process-global registry; clear between tests so
    cases don't leak into each other."""
    coalesce._inflight.clear()
    yield
    coalesce._inflight.clear()


@pytest.mark.asyncio
async def test_memo_hit_skips_fn():
    """If memo already has the key, fn must NOT be called."""
    memo = _Memo()
    memo.set(("k",), "cached")
    memo.set_calls = 0  # reset after the seed
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return "fresh"

    result = await memoized_coalesced(memo, ("k",), fn)
    assert result == "cached"
    assert calls == 0
    assert memo.set_calls == 0


@pytest.mark.asyncio
async def test_simultaneous_calls_share_one_fn_run():
    """Two coroutines awaiting the same key concurrently must trigger
    fn exactly ONCE — that's the whole point of coalescing."""
    memo = _Memo()
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        # Yield so the second caller has a chance to land in the in-flight
        # branch before we return.
        await asyncio.sleep(0.05)
        return "result"

    results = await asyncio.gather(
        memoized_coalesced(memo, ("k",), fn),
        memoized_coalesced(memo, ("k",), fn),
        memoized_coalesced(memo, ("k",), fn),
    )
    assert results == ["result", "result", "result"]
    assert calls == 1
    # Memo populated exactly once (in the done-callback).
    assert memo.set_calls == 1
    assert memo.store[("k",)] == "result"


@pytest.mark.asyncio
async def test_different_keys_run_independently():
    """Concurrent calls with different keys should NOT coalesce — they're
    independent computations."""
    memo = _Memo()
    calls = 0

    async def make_fn(value):
        async def fn():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return value
        return fn

    fn_a = await make_fn("a")
    fn_b = await make_fn("b")
    fn_c = await make_fn("c")
    results = await asyncio.gather(
        memoized_coalesced(memo, ("a",), fn_a),
        memoized_coalesced(memo, ("b",), fn_b),
        memoized_coalesced(memo, ("c",), fn_c),
    )
    assert calls == 3
    assert sorted(results) == ["a", "b", "c"]
    # All three populated the memo independently.
    assert memo.store == {("a",): "a", ("b",): "b", ("c",): "c"}


@pytest.mark.asyncio
async def test_exception_propagates_to_all_awaiters():
    """If fn raises, every awaiter sees the same exception. The memo
    must NOT be populated with the failure."""
    memo = _Memo()

    class Boom(Exception):
        pass

    async def fn():
        await asyncio.sleep(0.01)
        raise Boom("nope")

    async def safe_call():
        try:
            await memoized_coalesced(memo, ("k",), fn)
        except Boom as e:
            return str(e)

    results = await asyncio.gather(safe_call(), safe_call(), safe_call())
    assert results == ["nope", "nope", "nope"]
    # Failure must NOT be cached.
    assert memo.set_calls == 0
    assert ("k",) not in memo.store


@pytest.mark.asyncio
async def test_exception_does_not_block_future_calls():
    """After a failure, the next call with the same key should run fn
    again rather than coalescing onto the dead task."""
    memo = _Memo()
    calls = 0

    async def fn_fail():
        nonlocal calls
        calls += 1
        raise RuntimeError("first")

    async def fn_ok():
        nonlocal calls
        calls += 1
        return "ok"

    with pytest.raises(RuntimeError):
        await memoized_coalesced(memo, ("k",), fn_fail)

    # Inflight slot should be clear — the next call sees no existing task.
    assert ("k",) not in coalesce._inflight
    result = await memoized_coalesced(memo, ("k",), fn_ok)
    assert result == "ok"
    assert calls == 2


@pytest.mark.asyncio
async def test_cancelled_awaiter_does_not_abort_shared_task():
    """If awaiter A cancels mid-await, awaiter B (and the memo
    population) must still complete normally — asyncio.shield isolates
    the consumers from each other."""
    memo = _Memo()
    fn_done = asyncio.Event()
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        # Long enough that we can cancel the first awaiter mid-flight.
        await asyncio.sleep(0.05)
        fn_done.set()
        return "result"

    # Start awaiter A and B; cancel A almost immediately.
    task_a = asyncio.create_task(memoized_coalesced(memo, ("k",), fn))
    await asyncio.sleep(0)  # let A register the in-flight task
    task_b = asyncio.create_task(memoized_coalesced(memo, ("k",), fn))
    await asyncio.sleep(0.005)
    task_a.cancel()

    # B should still complete with the value.
    result_b = await task_b
    assert result_b == "result"
    assert calls == 1
    # The underlying task ran to completion despite A's cancellation.
    assert fn_done.is_set()
    # Memo got populated from the shared task.
    assert memo.store[("k",)] == "result"

    # A's task raised CancelledError when awaited.
    with pytest.raises(asyncio.CancelledError):
        await task_a


@pytest.mark.asyncio
async def test_inflight_cleared_after_completion():
    """The done-callback must clear the slot so a subsequent request
    starts a fresh task instead of awaiting a finished one."""
    memo = _Memo()

    async def fn():
        return "v"

    await memoized_coalesced(memo, ("k",), fn)
    # Run any pending callbacks.
    await asyncio.sleep(0)
    assert ("k",) not in coalesce._inflight


@pytest.mark.asyncio
async def test_serial_calls_use_memo_not_inflight():
    """After the first call completes and populates the memo, the
    second call should be a memo hit (NOT a fresh fn invocation, NOT
    an in-flight join)."""
    memo = _Memo()
    calls = 0

    async def fn():
        nonlocal calls
        calls += 1
        return "v"

    await memoized_coalesced(memo, ("k",), fn)
    await asyncio.sleep(0)
    await memoized_coalesced(memo, ("k",), fn)

    assert calls == 1
    assert memo.set_calls == 1
