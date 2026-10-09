"""GZip on the real app: large JSON is compressed, the SSE stream is not.

Starlette's GZipMiddleware buffers/compresses whatever it wraps unless the
response's content type is excluded — `text/event-stream` is, by default
(starlette.middleware.gzip.DEFAULT_EXCLUDED_CONTENT_TYPES). These tests pin
both halves against the app `create_app()` actually builds.
"""
from __future__ import annotations

import asyncio
import gzip

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ODDS_API_KEY", "")  # disables fetcher

    import server.config as config_mod
    import server.user_settings as us_mod

    original_from_env = config_mod.Config.from_env

    def patched_from_env():
        c = original_from_env()
        c.cache_db = tmp_path / "cache.db"
        return c

    monkeypatch.setattr(config_mod.Config, "from_env", staticmethod(patched_from_env))
    monkeypatch.setattr(us_mod, "SETTINGS_PATH", tmp_path / "user_settings.json")

    from server.main import create_app
    return create_app()


def test_large_json_is_gzipped_when_accepted(app):
    with TestClient(app) as c:
        plain = c.get("/api/sports", headers={"Accept-Encoding": "identity"})
        zipped = c.get("/api/sports", headers={"Accept-Encoding": "gzip"})

    assert plain.status_code == zipped.status_code == 200
    assert len(plain.content) > 1024, "need a payload above minimum_size"
    assert "content-encoding" not in plain.headers
    assert zipped.headers["content-encoding"] == "gzip"
    assert zipped.headers["vary"].lower().find("accept-encoding") >= 0
    # httpx transparently decodes; the decoded body is unchanged.
    assert zipped.content == plain.content
    assert zipped.json() == plain.json()


def test_small_json_is_not_gzipped(app):
    with TestClient(app) as c:
        r = c.get("/api/cache-mode", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert len(r.content) < 1024
    assert "content-encoding" not in r.headers


def test_sse_stream_is_not_gzipped_or_buffered(app):
    """Drive /api/stream/odds through the full middleware stack at the ASGI
    level: the first event must arrive as plain text, immediately, with no
    Content-Encoding — then disconnect."""

    async def run() -> tuple[dict, bytes]:
        disconnect = asyncio.Event()
        sent: list[dict] = []
        got_body = asyncio.Event()

        request_delivered = False

        async def receive():
            nonlocal request_delivered
            if not request_delivered:
                request_delivered = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                got_body.set()

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": "/api/stream/odds",
            "raw_path": b"/api/stream/odds", "root_path": "", "query_string": b"",
            "headers": [(b"host", b"testserver"), (b"accept-encoding", b"gzip")],
            "client": ("127.0.0.1", 1234), "server": ("testserver", 80),
        }
        task = asyncio.create_task(app(scope, receive, send))
        try:
            await asyncio.wait_for(got_body.wait(), timeout=5)
        finally:
            disconnect.set()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        start = next(m for m in sent if m["type"] == "http.response.start")
        body = next(
            m["body"] for m in sent
            if m["type"] == "http.response.body" and m.get("body")
        )
        return start, body

    start, first_chunk = asyncio.run(run())
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert headers["content-type"].startswith("text/event-stream")
    assert "content-encoding" not in headers
    assert first_chunk.startswith(b"event: connected")
    with pytest.raises(gzip.BadGzipFile):
        gzip.decompress(first_chunk)
