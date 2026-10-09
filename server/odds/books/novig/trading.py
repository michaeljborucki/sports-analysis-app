"""Novig trading client — places and cancels REAL-MONEY orders.

Used only by the auto-maker process (`server.automaker.novig_maker`). The
API server must never import this module: its Novig client is read-only and
loads the `trading::read` key, while this one loads the `trading` key of the
`trading` subaccount.

Key location comes from ~/.config/novig/trading.json:
    {"key_id": "<trading key uuid>", "pem": "~/.config/novig/novig-trading.pem"}
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .client import BASE_URL, canonical_query

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("~/.config/novig/trading.json").expanduser()


class NovigTradeError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(f"HTTP {status} {code}: {message}")
        self.status, self.code = status, code


class NovigTrader:
    def __init__(self, config_path: Path = CONFIG_PATH):
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        cfg = json.loads(config_path.read_text())
        self.key_id: str = cfg["key_id"]
        self._key = load_pem_private_key(
            Path(cfg["pem"]).expanduser().read_bytes(), None,
        )
        self._http = httpx.AsyncClient(
            base_url=BASE_URL, timeout=httpx.Timeout(15.0, connect=10.0),
            headers={"Accept": "application/json"},
        )

    def _headers(self, method: str, path: str, query: str, body: bytes) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        canon = "\n".join(
            ["NOVIG-V3", ts, method, path, query, hashlib.sha256(body).hexdigest()]
        )
        h = {
            "Novig-Key-Id": self.key_id,
            "Novig-Timestamp": ts,
            "Novig-Signature": base64.b64encode(self._key.sign(canon.encode())).decode(),
        }
        if body:
            h["Content-Type"] = "application/json"
        return h

    async def _call(self, method: str, path: str, params: dict | None = None,
                    body: Any = None) -> Any:
        query = canonical_query(params)
        raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
        url = f"{path}?{query}" if query else path
        r = await self._http.request(
            method, url, content=raw or None,
            headers=self._headers(method, path, query, raw),
        )
        if r.status_code >= 400:
            try:
                err = r.json()
                code, msg = err.get("code", ""), err.get("message", r.text[:200])
            except Exception:
                code, msg = "", r.text[:200]
            raise NovigTradeError(r.status_code, code, msg)
        return r.json() if r.content else None

    # ───────────────────────── reads ─────────────────────────

    async def balance(self) -> float:
        d = await self._call("GET", f"/v3/account/subaccounts/{self.key_id}/balance")
        return float(d["balance"])

    async def open_orders(self) -> list[dict]:
        d = await self._call("GET", "/v3/account/orders")
        return list(d.get("open") or [])

    async def positions(self) -> list[dict]:
        """Open positions: [{marketId, outcomeId, qty, cost}]. Novig redeems
        matched pairs, so each market nets to one side."""
        d = await self._call("GET", "/v3/portfolio/positions")
        return list(d or [])

    async def fills_since(self, after_ms: int) -> list[dict]:
        d = await self._call("GET", "/v3/portfolio/fills",
                             {"startsAfter": after_ms, "limit": 500})
        return list(d.get("items") or [])

    # ───────────────────────── orders ─────────────────────────

    async def place_post_only(self, outcome_id: str, price: float, qty: int,
                              ttl_ms: int) -> dict:
        """A post-only resting bid: refused rather than ever taking."""
        return await self._call("POST", "/v3/orders", body={
            "outcomeId": outcome_id,
            "price": f"{price:.3f}",
            "qty": int(qty),
            "tif": "PO",
            "ttl": int(ttl_ms),
            "clientId": str(uuid.uuid4()),
        })

    async def cancel(self, order_id: str) -> None:
        await self._call("DELETE", f"/v3/orders/{order_id}")

    async def cancel_all(self) -> int:
        d = await self._call("DELETE", "/v3/orders")
        return int((d or {}).get("canceled") or 0)

    async def aclose(self) -> None:
        await self._http.aclose()
