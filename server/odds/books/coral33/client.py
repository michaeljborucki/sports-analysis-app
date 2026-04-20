from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx


logger = logging.getLogger(__name__)

BASE_URL = "https://coral33.com/cloud/api"
TIMEOUT = 20.0
OFFICE = "LEOOFFICE"
DOMAIN = "coral33.com"

# Width customerID is padded to in all non-auth operations. The real site always
# sends a space-padded 10-char customerID (e.g. "VR12509   "). Empirically the
# server tolerates the unpadded form for /authenticate but some endpoints reject
# unpadded on the hot path.
_CUSTOMER_ID_WIDTH = 10

# Operations that require a JWT in the body. Everything else (odds endpoints,
# league discovery) is scoped by customerID alone.
_TOKEN_REQUIRED_OPS = {
    "getAccountInfo",
    "getCommunicationMessages",
    "Pending",
    "putPreference",
}


class Coral33APIError(Exception):
    pass


class Coral33AuthError(Coral33APIError):
    pass


class Coral33Client:
    """Async HTTP client for coral33.com's form-encoded JSON API.

    Auth model: POST /System/authenticateCustomer returns a JWT. Every
    subsequent call includes (customerID, token, operation, office, agentSite=0)
    in a form-encoded body. On 401 or auth-invalid response we re-authenticate
    once and retry. Token is held in-memory — no persistence.
    """

    def __init__(self, customer_id: str, password: str):
        if not customer_id or not password:
            raise Coral33AuthError("coral33 credentials missing")
        self.customer_id = customer_id.strip()
        self.password = password
        self._token: str | None = None
        self._lock = asyncio.Lock()

    @property
    def is_authenticated(self) -> bool:
        return self._token is not None

    def _padded_customer_id(self) -> str:
        """Pad customerID to _CUSTOMER_ID_WIDTH with trailing spaces — matches
        what the real browser client sends and what the server's SQL column
        expects for non-auth ops."""
        cid = self.customer_id
        return cid + " " * max(0, _CUSTOMER_ID_WIDTH - len(cid))

    async def authenticate(self) -> None:
        """Hit /System/authenticateCustomer and cache the JWT. Called lazily
        on first use and on retry after auth failure."""
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
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            resp = await http.post(
                f"{BASE_URL}/System/authenticateCustomer", data=body
            )
            if resp.status_code != 200:
                raise Coral33AuthError(
                    f"auth failed {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json()
            token = _extract_token(data)
            if not token:
                raise Coral33AuthError(
                    f"auth response missing token: {str(data)[:300]}"
                )
            self._token = token
            logger.info("coral33: authenticated as %s", self.customer_id)

    async def post_form(
        self, operation: str, params: dict[str, Any] | None = None
    ) -> dict:
        """POST {operation} with a form body. Authenticates lazily on first
        call that requires a token. Retries once on auth failure."""
        needs_token = operation in _TOKEN_REQUIRED_OPS
        if needs_token:
            async with self._lock:
                if not self._token:
                    await self.authenticate()
        try:
            return await self._raw_post(operation, params or {}, needs_token)
        except Coral33AuthError:
            if not needs_token:
                raise
            async with self._lock:
                await self.authenticate()
            return await self._raw_post(operation, params or {}, needs_token)

    async def _raw_post(
        self,
        operation: str,
        params: dict[str, Any],
        include_token: bool,
    ) -> dict:
        body: dict[str, Any] = {
            "customerID": self._padded_customer_id(),
            "operation": operation,
            "office": OFFICE,
            "agentSite": "0",
            **{k: _stringify(v) for k, v in params.items()},
        }
        if include_token:
            body["token"] = self._token or ""
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            resp = await http.post(f"{BASE_URL}/{_operation_path(operation)}", data=body)
            if resp.status_code == 401:
                self._token = None
                raise Coral33AuthError("401 — token invalid")
            if resp.status_code != 200:
                raise Coral33APIError(
                    f"{operation} {resp.status_code}: {resp.text[:300]}"
                )
            try:
                data = resp.json()
            except Exception as e:
                raise Coral33APIError(
                    f"{operation} non-JSON body: {resp.text[:300]}"
                ) from e
        # Some responses signal auth-invalid with a 200 body — treat as auth error
        if isinstance(data, dict) and _looks_like_auth_failure(data):
            self._token = None
            raise Coral33AuthError(f"{operation} auth rejected: {str(data)[:200]}")
        return data

    # ---------- Convenience endpoints ----------

    async def get_sports_leagues(self) -> list[dict]:
        """List every sport/league the account can access. Discovery only —
        not called on the hot path."""
        data = await self.post_form("Get_SportsLeagues")
        return data.get("Leagues") or data.get("SportsLeagues") or []

    async def get_league_lines(
        self,
        sport_type: str,
        sport_sub_type: str,
        period: str = "Game",
    ) -> dict:
        """Fetch odds for a (sportType, sportSubType, period) tuple. Returns
        the full response dict so the caller can inspect CaptchaRequired."""
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


def _extract_token(data: Any) -> str | None:
    """coral33 wraps the JWT in different keys across responses. Check the
    common ones in order."""
    if not isinstance(data, dict):
        return None
    for key in ("token", "Token", "access_token", "jwt", "JWT", "code"):
        v = data.get(key)
        if isinstance(v, str) and v:
            return v
    # Nested shape: {"data": {"token": "..."}}
    inner = data.get("data")
    if isinstance(inner, dict):
        return _extract_token(inner)
    return None


def _operation_path(operation: str) -> str:
    """Map an operation name to its URL sub-path. coral33 nests ops under
    a domain segment like /Lines/ or /League/. We keep this table small —
    only operations we actually call."""
    return _OP_PATHS.get(operation, f"System/{operation}")


_OP_PATHS = {
    "Get_SportsLeagues":       "League/Get_SportsLeagues",
    "Get_LeagueLines2":        "Lines/Get_LeagueLines2",
    "getAccountInfo":          "Customer/getAccountInfo",
    "Pending":                 "Report/Pending",
    "authenticateCustomer":    "System/authenticateCustomer",
}


def _looks_like_auth_failure(data: dict) -> bool:
    """Heuristic: some endpoints return 200 with an error body instead of 401."""
    code = data.get("ErrorCode") or data.get("errorCode") or data.get("code")
    msg = data.get("ErrorMessage") or data.get("errorMessage") or data.get("message") or ""
    if isinstance(msg, str) and any(
        t in msg.lower() for t in ("token", "unauthoriz", "auth", "session")
    ):
        return True
    if isinstance(code, (int, str)) and str(code) in ("401", "403"):
        return True
    return False
