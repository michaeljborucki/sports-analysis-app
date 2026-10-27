from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.debug_memory import build_router
from server.odds.normalize import _coerce_dt


def _client(snapshot=None, novig_stream=None, kalshi_stats=None):
    cache = SimpleNamespace(_writer=ThreadPoolExecutor(max_workers=1))
    service = SimpleNamespace(current=snapshot, age_seconds=3.0, overlays_published=7)
    kalshi = SimpleNamespace(debug_stats=kalshi_stats or (lambda: {"ingestor": None}))
    poly = SimpleNamespace(debug_stats=lambda: {"ingestor": {"templates_assets": 2}})
    novig = SimpleNamespace(_stream=novig_stream)
    app = FastAPI()
    app.include_router(build_router(cache, service, kalshi, poly, novig))
    return TestClient(app)


def test_reports_counters_without_snapshot():
    body = _client().get("/api/debug/memory").json()
    assert body["snapshot"] == {"built": False}
    assert body["cache_writer_queue"] == 0
    assert body["polymarket"] == {"ingestor": {"templates_assets": 2}}
    assert body["novig_stream"] is None
    assert body["process"].get("footprint_mb", 1) > 0


def test_snapshot_and_novig_counts():
    snap = SimpleNamespace(
        generation=4, rows=(1, 2, 3), games=(1,), system_rows=(), derived={"a": 1},
    )
    stream = SimpleNamespace(
        state={"m1": {}, "m2": {}}, _live={"m1"}, _subscribed={"e1"}, reconnects=5,
    )
    body = _client(snapshot=snap, novig_stream=stream).get("/api/debug/memory").json()
    assert body["snapshot"]["rows"] == 3
    assert body["snapshot"]["overlays_published"] == 7
    assert body["novig_stream"] == {
        "state_markets": 2, "live_markets": 1, "subscribed_events": 1, "reconnects": 5,
    }


def test_broken_probe_is_isolated():
    def boom():
        raise RuntimeError("nope")
    body = _client(kalshi_stats=boom).get("/api/debug/memory").json()
    assert body["kalshi"] == {"error": "RuntimeError: nope"}
    assert body["polymarket"]["ingestor"]["templates_assets"] == 2


def test_timestamp_parse_is_shared_and_equal():
    a = _coerce_dt("2026-10-23T22:31:39Z")
    b = _coerce_dt("2026-10-23T22:31:39Z")
    assert a is b
    assert a.isoformat() == "2026-10-23T22:31:39+00:00"
