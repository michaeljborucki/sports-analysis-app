"""Serialize-once helpers for the memoized scanner endpoints.

The scanner endpoints used to memoize pydantic response models. FastAPI
then re-validated and re-serialized that (multi-MB) model on every request
— memo hits included — on the event loop: ~60-130ms per hit for the 4MB
/api/profit_boost payload. Now the threadpool compute renders the JSON
bytes once and the memo stores bytes, so a hit is a dict lookup.

`model_json_bytes` reproduces FastAPI's `response_model` path exactly:
FastAPI dumps the model with `mode="json", by_alias=True`, and Starlette's
`JSONResponse.render` then runs `json.dumps` with the arguments below.
Pydantic's own `model_dump_json()` is faster but NOT byte-identical (it
writes 1e-05 as 0.00001), so it is deliberately not used here.

Compression: the body is also gzipped once, in the same threadpool call
(zlib releases the GIL), and memoized with it. The response picks the gzip
copy when the client sends Accept-Encoding: gzip — no per-request or
on-event-loop compression. Bodies are unchanged after decoding.
"""
from __future__ import annotations

import gzip
import json

from fastapi import Response
from pydantic import BaseModel

# Below this, gzip isn't worth a header. Level 1: ~6-8x on this JSON at
# a fraction of level 9's CPU.
GZIP_MIN_BYTES = 1024
GZIP_LEVEL = 1


class JsonBytes(bytes):
    """Rendered JSON plus its pre-compressed gzip copy (None if tiny)."""

    gz: bytes | None = None


def _accepts_gzip(scope) -> bool:
    for name, value in scope.get("headers") or ():
        if name == b"accept-encoding":
            return b"gzip" in value.lower()
    return False


class _JsonBytesResponse(Response):
    media_type = "application/json"

    def __init__(self, body: bytes):
        super().__init__(content=body)
        self._gz = getattr(body, "gz", None)

    async def __call__(self, scope, receive, send) -> None:
        if self._gz is not None and _accepts_gzip(scope):
            self.body = self._gz
            self.headers["content-encoding"] = "gzip"
            self.headers["content-length"] = str(len(self._gz))
            self.headers["vary"] = "Accept-Encoding"
        await super().__call__(scope, receive, send)


def model_json_bytes(model: BaseModel) -> bytes:
    """Bytes identical to what FastAPI would send for `model` returned from
    a route declared with `response_model=type(model)`. Carries `.gz`."""
    out = JsonBytes(json.dumps(
        model.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        allow_nan=False,
        indent=None,
        separators=(",", ":"),
    ).encode("utf-8"))
    if len(out) >= GZIP_MIN_BYTES:
        out.gz = gzip.compress(out, compresslevel=GZIP_LEVEL, mtime=0)
    return out


def json_bytes_response(body: bytes) -> Response:
    """Wrap pre-rendered JSON bytes. Returning a `Response` makes FastAPI
    skip response_model validation/serialization (the declared
    `response_model=` still documents the shape in OpenAPI)."""
    return _JsonBytesResponse(body)
