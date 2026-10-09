"""/api/cache-mode row counts: stale-while-revalidate.

`_inspect_db` runs COUNT(*) over the large cache files (1-1.7s). Once a
value is known, an expired memo must be served immediately while ONE
background thread recomputes it. The snapshot file (`track_changes=True`)
still recomputes inline as soon as its size/mtime changes, so a fresh
capture reports its real row count at once.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

import server.api.cache_mode as cm


@pytest.fixture(autouse=True)
def _clean_memo():
    cm._inspect_memo.clear()
    cm._inspect_refreshing.clear()
    yield
    cm._inspect_memo.clear()
    cm._inspect_refreshing.clear()


class _SlowCounter:
    """Stands in for `_inspect_db_uncached`: returns `value`, optionally
    blocking until released, and counts calls."""

    def __init__(self, value: int) -> None:
        self.value = value
        self.calls = 0
        self.release = threading.Event()
        self.release.set()
        self.done = threading.Event()

    def __call__(self, path: Path):
        self.calls += 1
        self.release.wait(5)
        self.done.set()
        return self.value, f"newest-{self.value}"


def _expire(path: Path) -> None:
    ts, stamp, result = cm._inspect_memo[path]
    cm._inspect_memo[path] = (ts - cm._INSPECT_TTL_S - 1, stamp, result)


def test_first_call_computes_inline(monkeypatch, tmp_path):
    counter = _SlowCounter(10)
    monkeypatch.setattr(cm, "_inspect_db_uncached", counter)
    assert cm._inspect_db(tmp_path / "cache.db") == (10, "newest-10")
    assert counter.calls == 1
    # Fresh memo: no recompute.
    assert cm._inspect_db(tmp_path / "cache.db") == (10, "newest-10")
    assert counter.calls == 1


def test_expired_memo_returns_last_value_and_refreshes_in_background(
    monkeypatch, tmp_path,
):
    path = tmp_path / "cache.db"
    counter = _SlowCounter(10)
    monkeypatch.setattr(cm, "_inspect_db_uncached", counter)
    cm._inspect_db(path)
    _expire(path)

    counter.value = 20
    counter.release.clear()   # the background COUNT(*) is "slow"
    counter.done.clear()
    started = time.perf_counter()
    assert cm._inspect_db(path) == (10, "newest-10")      # stale, instant
    assert cm._inspect_db(path) == (10, "newest-10")      # still in flight
    assert time.perf_counter() - started < 0.5
    assert path in cm._inspect_refreshing

    counter.release.set()
    assert counter.done.wait(5)
    deadline = time.time() + 5
    while path in cm._inspect_refreshing and time.time() < deadline:
        time.sleep(0.01)
    # Exactly one background recompute for the two stale reads.
    assert counter.calls == 2
    assert cm._inspect_db(path) == (20, "newest-20")
    assert counter.calls == 2


def test_track_changes_recomputes_inline_when_file_changes(monkeypatch, tmp_path):
    path = tmp_path / "cache.snapshot.db"
    path.write_bytes(b"a")
    counter = _SlowCounter(5)
    monkeypatch.setattr(cm, "_inspect_db_uncached", counter)
    assert cm._inspect_db(path, track_changes=True) == (5, "newest-5")

    # A fresh capture rewrites the file: the very next read is exact.
    counter.value = 7
    path.write_bytes(b"bb")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert cm._inspect_db(path, track_changes=True) == (7, "newest-7")
    assert counter.calls == 2
    assert not cm._inspect_refreshing


def test_background_refresh_failure_keeps_last_value(monkeypatch, tmp_path):
    path = tmp_path / "cache.db"
    monkeypatch.setattr(cm, "_inspect_db_uncached", lambda p: (3, "x"))
    cm._inspect_db(path)
    _expire(path)

    done = threading.Event()

    def boom(p):
        done.set()
        raise RuntimeError("disk gone")

    monkeypatch.setattr(cm, "_inspect_db_uncached", boom)
    assert cm._inspect_db(path) == (3, "x")
    assert done.wait(5)
    deadline = time.time() + 5
    while path in cm._inspect_refreshing and time.time() < deadline:
        time.sleep(0.01)
    assert path not in cm._inspect_refreshing
    assert cm._inspect_memo[path][2] == (3, "x")
