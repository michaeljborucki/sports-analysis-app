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
"""
from __future__ import annotations

import json

from fastapi import Response
from pydantic import BaseModel


def model_json_bytes(model: BaseModel) -> bytes:
    """Bytes identical to what FastAPI would send for `model` returned from
    a route declared with `response_model=type(model)`."""
    return json.dumps(
        model.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        allow_nan=False,
        indent=None,
        separators=(",", ":"),
    ).encode("utf-8")


def json_bytes_response(body: bytes) -> Response:
    """Wrap pre-rendered JSON bytes. Returning a `Response` makes FastAPI
    skip response_model validation/serialization (the declared
    `response_model=` still documents the shape in OpenAPI)."""
    return Response(content=body, media_type="application/json")
