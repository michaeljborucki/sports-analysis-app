from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any

from curl_cffi.requests import AsyncSession


logger = logging.getLogger(__name__)

BASE_URL = "https://coral33.com/cloud/api"
TIMEOUT = 20.0
OFFICE = "LEOOFFICE"
DOMAIN = "coral33.com"

# customerID is space-padded to 10 chars on the hot path. The server's SQL
# column is CHAR(10); unpadded values are rejected on some endpoints.
_CUSTOMER_ID_WIDTH = 10

# Refresh the JWT this many seconds before its `exp` claim. Coral's tokens
# live ~21 min, so 60s of headroom is plenty while avoiding unnecessary
# re-auths.
_JWT_REFRESH_MARGIN_S = 60


class Coral33APIError(Exception):
    pass


class Coral33AuthError(Coral33APIError):
    pass


def _browser_headers() -> dict[str, str]:
    """Match the real browser's header set. Cloudflare-fronted endpoints on
    coral33 inspect these (plus TLS fingerprint via curl_cffi's
    impersonate='chrome')."""
    return {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "origin": "https://coral33.com",
        "referer": "https://coral33.com/sports.html",
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-requested-with": "XMLHttpRequest",
    }


def _decode_jwt_exp(jwt: str) -> int | None:
    """Parse the `exp` (unix seconds) claim out of a JWT without verifying
    signature. We trust the server's token for our own scheduling; if this
    fails we fall back to ~20 min."""
    try:
        payload_b64 = jwt.split(".")[1]
        pad = 4 - (len(payload_b64) % 4)
        if pad < 4:
            payload_b64 += "=" * pad
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = claims.get("exp")
        return int(exp) if exp else None
    except Exception:
        return None


class Coral33Client:
    """Async HTTP client for coral33.com's form-encoded JSON API.

    Auth model (reverse-engineered from Copy-as-cURL):
      - POST /System/authenticateCustomer with (customerID, password, …)
        returns `{code: "<JWT>"}`. The JWT encodes user + expiry.
      - Every subsequent /cloud/api/* call requires `Authorization: Bearer
        <JWT>` and must carry the full set of browser headers (accept,
        origin, referer, sec-ch-ua*, etc.). Cloudflare gates the path at
        the edge — without the Bearer header we get openresty 401.
      - curl_cffi with `impersonate='chrome'` is required so the TLS/JA4
        fingerprint matches Chrome; Python's default TLS stack is
        fingerprinted by Cloudflare and rejected at handshake.

    The client refreshes the JWT ~60s before its `exp` claim. On 401 we
    force a re-auth + retry once.
    """

    def __init__(self, customer_id: str, password: str):
        if not customer_id or not password:
            raise Coral33AuthError("coral33 credentials missing")
        self.customer_id = customer_id.strip()
        self.password = password
        self._token: str | None = None
        self._token_exp: int | None = None   # unix seconds
        self._lock = asyncio.Lock()

    @property
    def is_authenticated(self) -> bool:
        return self._token is not None and not self._token_expired()

    def _token_expired(self) -> bool:
        if self._token_exp is None:
            # If we couldn't parse exp, assume it's expired after ~15 min —
            # safer than hoarding a dead token.
            return True
        return time.time() >= (self._token_exp - _JWT_REFRESH_MARGIN_S)

    def _padded_customer_id(self) -> str:
        cid = self.customer_id
        return cid + " " * max(0, _CUSTOMER_ID_WIDTH - len(cid))

    async def authenticate(self) -> None:
        """Hit /System/authenticateCustomer, store JWT + exp."""
        body = {
            "customerID": self.customer_id,
            "state": "true",
            "password": self.password,
            "multiaccount": "1",
            "response_type": "code",
            "client_id": self.customer_id,
            "domain": DOMAIN,
            "redirect_uri": DOMAIN,
            "operation": "authenticateCustomer",
            "RRO": "1",
        }
        headers = {
            **_browser_headers(),
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        async with AsyncSession(impersonate="chrome", timeout=TIMEOUT) as http:
            resp = await http.post(
                f"{BASE_URL}/System/authenticateCustomer",
                data=body,
                headers=headers,
            )
            if resp.status_code != 200:
                raise Coral33AuthError(
                    f"auth failed {resp.status_code}: {resp.text[:300]}"
                )
            try:
                data = resp.json()
            except Exception as e:
                raise Coral33AuthError(
                    f"auth non-JSON body: {resp.text[:200]}"
                ) from e
            jwt = data.get("code") or data.get("token")
            if not jwt or not isinstance(jwt, str):
                raise Coral33AuthError(
                    f"auth response missing JWT: {str(data)[:200]}"
                )
            self._token = jwt
            self._token_exp = _decode_jwt_exp(jwt)
            logger.info(
                "coral33: authenticated as %s (JWT exp=%s)",
                self.customer_id,
                self._token_exp,
            )

    async def post_form(
        self, operation: str, params: dict[str, Any] | None = None
    ) -> dict:
        """POST {operation} with standard body + Bearer token header. Ensures
        a non-expired JWT before firing. Retries once on 401."""
        async with self._lock:
            if not self._token or self._token_expired():
                await self.authenticate()
        try:
            return await self._raw_post(operation, params or {})
        except Coral33AuthError:
            async with self._lock:
                await self.authenticate()
            return await self._raw_post(operation, params or {})

    async def _raw_post(
        self, operation: str, params: dict[str, Any]
    ) -> dict:
        body: dict[str, Any] = {
            "customerID": self._padded_customer_id(),
            "operation": operation,
            "office": OFFICE,
            "agentSite": "0",
            **{k: _stringify(v) for k, v in params.items()},
        }
        headers = {
            **_browser_headers(),
            "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
            "authorization": f"Bearer {self._token}",
        }
        async with AsyncSession(impersonate="chrome", timeout=TIMEOUT) as http:
            resp = await http.post(
                f"{BASE_URL}/{_operation_path(operation)}",
                data=body,
                headers=headers,
            )
            if resp.status_code == 401:
                self._token = None
                self._token_exp = None
                raise Coral33AuthError(
                    f"{operation}: 401 — token rejected"
                )
            if resp.status_code != 200:
                raise Coral33APIError(
                    f"{operation} {resp.status_code}: {resp.text[:300]}"
                )
            try:
                return resp.json()
            except Exception as e:
                raise Coral33APIError(
                    f"{operation} non-JSON body: {resp.text[:300]}"
                ) from e

    # ---------- Convenience endpoints ----------

    async def get_sports_leagues(self) -> list[dict]:
        """List every sport/league the account can access. Discovery only."""
        data = await self.post_form("Get_SportsLeagues", {
            "wagerType": "Straight",
            "placeLateFlag": "false",
        })
        return data.get("Leagues") or data.get("SportsLeagues") or []

    async def get_league_lines(
        self,
        sport_type: str,
        sport_sub_type: str,
        period: str = "Game",
    ) -> dict:
        """Fetch odds for a (sportType, sportSubType, period) tuple. Returns
        the raw response; caller inspects CaptchaRequired + Lines."""
        params = {
            "sportType": sport_type,
            "sportSubType": sport_sub_type,
            "period": period,
            "hourFilter": "0",
            "propDescription": "Game",
            "wagerType": "Straight",
            "keyword": "",
            "correlationID": "",
            "periodNumber": "0",
            "grouping": "",
            "periods": "0",
            "rotOrder": "0",
            "placeLateFlag": "false",
            "RRO": "1",
        }
        return await self.post_form("Get_LeagueLines2", params)


def _stringify(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _operation_path(operation: str) -> str:
    return _OP_PATHS.get(operation, f"System/{operation}")


_OP_PATHS = {
    "Get_SportsLeagues":    "League/Get_SportsLeagues",
    "Get_LeagueLines2":     "Lines/Get_LeagueLines2",
    "getAccountInfo":       "Customer/getAccountInfo",
    "getCommunicationMessages": "Customer/getCommunicationMessages",
    "putPreference":        "Customer/putPreference",
    "Pending":              "Report/Pending",
    "authenticateCustomer": "System/authenticateCustomer",
}
