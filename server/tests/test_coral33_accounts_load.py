import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.odds.books.coral33.accounts import (
    AccountCredential,
    AccountSnapshot,
    AccountsRollup,
    AccountsScraper,
    HistoryPoint,
    load_account_credentials,
)


def test_load_credentials_parses_proxy_and_cap(monkeypatch):
    monkeypatch.setenv("CORAL33_ACCOUNTS", json.dumps([
        {"customer_id": "VR11606", "password": "stanley1",
         "label": "Ryan Stanley",
         "proxy_url": "http://u:p@isp.decodo.com:10007",
         "max_parlay_stake": 150},
        {"customer_id": "VR11601", "password": "dixon1",
         "label": "Jimmy Dixon"},
    ]))
    creds = load_account_credentials()
    assert len(creds) == 2
    stanley, dixon = creds
    assert stanley.proxy_url == "http://u:p@isp.decodo.com:10007"
    assert stanley.max_parlay_stake == 150
    assert dixon.proxy_url is None
    assert dixon.max_parlay_stake == 100   # default


def test_accounts_scraper_passes_proxy_to_client(monkeypatch):
    """The per-account scrape must construct each Coral33Client with the
    credential's proxy_url so each account's traffic egresses through its
    own residential IP.

    The real per-account scrape lives in the module-level ``fetch_account``
    coroutine — ``AccountsScraper.refresh`` fans out across credentials
    via ``asyncio.gather(*(fetch_account(c) for c in creds))``. We spy on
    ``Coral33Client.__init__`` and short-circuit ``authenticate`` so the
    test never touches the network.
    """
    monkeypatch.setenv("CORAL33_ACCOUNTS", json.dumps([
        {"customer_id": "VR11606", "password": "p",
         "proxy_url": "http://u:p@isp.decodo.com:10007"},
    ]))
    from server.odds.books.coral33 import accounts as accts

    captured: list[dict] = []
    real_init = accts.Coral33Client.__init__

    def spy_init(self, customer_id, password, proxy_url=None):
        captured.append({"cust": customer_id, "proxy": proxy_url})
        real_init(self, customer_id, password, proxy_url=proxy_url)

    monkeypatch.setattr(accts.Coral33Client, "__init__", spy_init)

    # Short-circuit the network call — we only care that the client was
    # constructed with the proxy. authenticate() raising Coral33AuthError
    # is the existing, well-tested failure path inside fetch_account and
    # results in a snapshot with snap.error set rather than an exception.
    async def boom(self):
        raise accts.Coral33AuthError("test short-circuit")

    monkeypatch.setattr(accts.Coral33Client, "authenticate", boom)

    scraper = accts.AccountsScraper()
    snap = asyncio.run(accts.fetch_account(scraper.credentials[0]))

    assert snap.error and snap.error.startswith("auth:")
    assert captured, "Coral33Client was never constructed"
    assert captured[0]["cust"] == "VR11606"
    assert captured[0]["proxy"] == "http://u:p@isp.decodo.com:10007"


def test_fetch_account_turns_transport_timeout_into_snapshot_error(monkeypatch):
    """A proxy timeout must fail only its account, not the whole refresh."""
    from curl_cffi.requests.exceptions import Timeout
    from server.odds.books.coral33 import accounts as accts

    async def timeout(self):
        raise Timeout("proxy connection timed out")

    monkeypatch.setattr(accts.Coral33Client, "authenticate", timeout)

    snapshot = asyncio.run(accts.fetch_account(AccountCredential(
        customer_id="VR1",
        password="pw",
        label="Primary",
        proxy_url="http://u:p@isp.decodo.com:10001",
    )))

    assert snapshot.customer_id == "VR1"
    assert snapshot.error == "auth: proxy connection timed out"


def test_fetch_account_isolates_transport_timeout_after_auth(monkeypatch):
    """A later proxy timeout must also remain local to its account."""
    from curl_cffi.requests.exceptions import Timeout
    from server.odds.books.coral33 import accounts as accts

    monkeypatch.setattr(
        accts.Coral33Client, "authenticate", AsyncMock(return_value=None),
    )

    async def timeout(self, operation, params=None):
        raise Timeout("proxy connection timed out")

    monkeypatch.setattr(accts.Coral33Client, "post_form", timeout)

    snapshot = asyncio.run(accts.fetch_account(AccountCredential(
        customer_id="VR2",
        password="pw",
        label="Secondary",
        proxy_url="http://u:p@isp.decodo.com:10002",
    )))

    assert snapshot.customer_id == "VR2"
    assert snapshot.error == "getAccountInfo: proxy connection timed out"


def test_account_snapshot_carries_placement_context(monkeypatch):
    """After a scrape, AccountSnapshot exposes the per-customer placement
    context fields the Coral33Placer needs (agent_id, store, cust_profile)
    alongside the existing balance fields."""
    from server.odds.books.coral33 import accounts as accts

    cred = accts.AccountCredential(
        customer_id="VR11606", password="p", label="Stanley",
        proxy_url="http://u:p@h:1", max_parlay_stake=150,
    )

    # Mock Coral33Client.post_form to return a getAccountInfo response that
    # includes the placement-context fields the HAR confirms are present.
    # Real key is "accountInfo" (camelCase) per the HAR fixture.
    fake_account_info = {
        "accountInfo": {
            "CurrentBalance": 50000,        # cents → $500
            "AvailableBalance": 480.0,
            "PendingWagerBalance": 2000,    # cents → $20
            "FreePlayBalance": 0,
            "CreditLimit": 1000.0,
            "WagerLimit": 200.0,
            "AgentID": "TYSONR",
            "Store": "wiseguys",
            "CustProfile": ".                   ",
        }
    }

    async def fake_post_form(self, op, params=None):
        if op == "getAccountInfo":
            return fake_account_info
        if op == "Pending":
            return {"Pending": []}
        raise AssertionError(f"unscripted op in test: {op}")

    monkeypatch.setattr(accts.Coral33Client, "post_form", fake_post_form)
    # Skip the real authenticate (no network).
    monkeypatch.setattr(accts.Coral33Client, "authenticate",
                        AsyncMock(return_value=None))

    # The real per-account fetch is the module-level fetch_account coroutine
    # (A3 confirmed there's no `_scrape_one` method on AccountsScraper).
    snap = asyncio.run(accts.fetch_account(cred))

    assert snap.error is None, f"unexpected scrape error: {snap.error}"
    assert snap.customer_id == "VR11606"
    assert snap.agent_id == "TYSONR"
    assert snap.store == "wiseguys"
    assert snap.cust_profile == ".                   "
    assert snap.available_balance == 480.0


def test_trigger_refresh_async_coalesces_concurrent_taps(monkeypatch):
    """Rapid 5x POST to /api/coral33/accounts/refresh must spawn ONE
    scrape; the other 4 return ``already_running`` without queueing on
    the lock and re-pulling every account."""
    monkeypatch.setenv("CORAL33_ACCOUNTS", json.dumps([
        {"customer_id": "VR1", "password": "p"},
    ]))

    scrape_count = 0

    async def slow_fetch(cred):
        nonlocal scrape_count
        scrape_count += 1
        # Yield so the next trigger_refresh_async sees _refreshing=True.
        await asyncio.sleep(0.05)
        from server.odds.books.coral33.accounts import AccountSnapshot
        return AccountSnapshot(
            customer_id=cred.customer_id, label=cred.customer_id,
            fetched_at="2026-01-01T00:00:00+00:00",
        )

    from server.odds.books.coral33 import accounts as accts
    monkeypatch.setattr(accts, "fetch_account", slow_fetch)

    async def run():
        scraper = AccountsScraper()
        results = [scraper.trigger_refresh_async() for _ in range(5)]
        # Let the spawned task run to completion.
        await asyncio.sleep(0.2)
        return results

    results = asyncio.run(run())
    # Exactly one "triggered", four "already_running".
    statuses = sorted(r["status"] for r in results)
    assert statuses == ["already_running"] * 4 + ["triggered"]
    # And the actual scrape ran exactly once.
    assert scrape_count == 1


def test_history_appends_snapshot_dates_missing_from_weekly_figures():
    """A stale weekly report must not truncate the chart before newer
    locally captured balance dates."""
    from server.api.coral33_accounts import build_router

    class FakeScraper:
        credentials = [AccountCredential("VR1", "pw", "Primary")]

        async def get_history(self, weeks_back=12, force=False):
            return {
                "VR1": [HistoryPoint(
                    date="2026-08-17", won=0, lost=0, net=5, balance=100,
                )]
            }

        async def get_wager_log(self, force=False):
            return {}

        def cached(self):
            return AccountsRollup(
                snapshots=[AccountSnapshot(
                    customer_id="VR1", label="Primary",
                    fetched_at="2026-08-19T22:00:00+00:00",
                    current_balance=120, pending_wager_balance=20,
                )],
                refreshed_at="2026-08-19T22:00:00+00:00",
            )

    class FakeCache:
        def latest_balance_snapshot_per_date(self, customer_id):
            assert customer_id == "VR1"
            return {
                "2026-08-18": {
                    "local_date": "2026-08-18",
                    "current_balance": 110,
                    "pending": 5,
                },
                "2026-08-19": {
                    "local_date": "2026-08-19",
                    "current_balance": 120,
                    "pending": 20,
                },
            }

    app = FastAPI()
    app.include_router(build_router(FakeScraper(), cache=FakeCache()))

    response = TestClient(app).get("/api/coral33/accounts/history?weeks=12")
    assert response.status_code == 200
    points = response.json()["accounts"][0]["points"]
    assert [p["date"] for p in points] == [
        "2026-08-17", "2026-08-18", "2026-08-19",
    ]
    assert [p["balance"] for p in points] == [100, 110, 120]
    assert [p["net"] for p in points] == [5, 10, 10]
    assert [p["pending"] for p in points] == [0, 5, 20]


def test_refresh_labels_snapshot_with_denver_calendar_date(monkeypatch):
    """An evening Mountain-time refresh must not be stored as tomorrow
    merely because UTC has crossed midnight."""
    from server.odds.books.coral33 import accounts as accts

    monkeypatch.setenv("CORAL33_ACCOUNTS", json.dumps([
        {"customer_id": "VR1", "password": "pw"},
    ]))

    async def fake_fetch(cred):
        return AccountSnapshot(
            customer_id=cred.customer_id,
            label=cred.customer_id,
            fetched_at="2026-08-20T02:30:00+00:00",
            current_balance=100,
        )

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 20, 2, 30, tzinfo=timezone.utc)

    class RecordingCache:
        rows = None

        def upsert_balance_snapshots(self, rows):
            self.rows = rows
            return len(rows)

    cache = RecordingCache()
    monkeypatch.setattr(accts, "fetch_account", fake_fetch)
    monkeypatch.setattr(accts, "datetime", FixedDateTime)

    asyncio.run(AccountsScraper(cache=cache).refresh())

    assert cache.rows is not None
    assert cache.rows[0]["local_date"] == "2026-08-19"


def test_history_keeps_successful_weeks_when_one_transport_call_fails(
    monkeypatch,
):
    """A proxy/DNS failure for one week must not abort the account's entire
    history response and make the chart disappear."""
    from curl_cffi.requests.exceptions import ProxyError
    from server.odds.books.coral33 import accounts as accts

    cred = AccountCredential("VR1", "pw", "Primary")

    async def fake_post_form(self, operation, params=None):
        if operation == "getAccountInfo":
            return {"accountInfo": {"AgentID": "TYSONR"}}
        if operation == "getDailyFiguresByCustomer":
            if params["week"] == "0":
                raise ProxyError("Could not resolve proxy")
            return {"INFO": {
                "BOW": "2026-08-04 00:00:00.000",
                "PreviousBalance": 100,
                "day1": 1,
                "day2": 2,
                "day3": 3,
                "day4": 4,
                "day5": 5,
                "day6": 6,
                "day7": 7,
            }}
        raise AssertionError(f"unexpected operation: {operation}")

    monkeypatch.setattr(
        accts.Coral33Client, "authenticate", AsyncMock(return_value=None),
    )
    monkeypatch.setattr(accts.Coral33Client, "post_form", fake_post_form)

    points = asyncio.run(accts.fetch_account_history(cred, weeks_back=2))

    assert len(points) == 7
    assert points[0].date == "2026-08-04"
    assert points[-1].balance == 128


def test_history_does_not_include_tomorrow_after_utc_midnight(monkeypatch):
    """At 8:30 PM Denver time, a Coral weekly row for the next UTC date
    must not appear on the chart yet."""
    from server.odds.books.coral33 import accounts as accts

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 20, 2, 30, tzinfo=timezone.utc)

    async def fake_post_form(self, operation, params=None):
        if operation == "getAccountInfo":
            return {"accountInfo": {"AgentID": "TYSONR"}}
        return {"INFO": {
            "BOW": "2026-08-18 00:00:00.000",
            "PreviousBalance": 100,
            "day1": 1,
            "day2": 2,
            "day3": 3,
            "day4": 0,
            "day5": 0,
            "day6": 0,
            "day7": 0,
        }}

    monkeypatch.setattr(accts, "datetime", FixedDateTime)
    monkeypatch.setattr(
        accts.Coral33Client, "authenticate", AsyncMock(return_value=None),
    )
    monkeypatch.setattr(accts.Coral33Client, "post_form", fake_post_form)

    points = asyncio.run(accts.fetch_account_history(
        AccountCredential("VR1", "pw"), weeks_back=1,
    ))

    assert [p.date for p in points] == ["2026-08-18", "2026-08-19"]


def test_fetch_account_history_isolates_transport_error_at_auth(monkeypatch):
    """A proxy/DNS failure during auth must fail only its account.

    Regression: `fetch_account_history` caught only Coral33AuthError /
    Coral33APIError, so a curl_cffi ProxyError escaped and — because
    `get_history` gathers with return_exceptions=False — took the whole
    /api/coral33/accounts/history response down with a 500. The snapshot
    path (fetch_account) already catches RequestException; history must too.
    """
    from curl_cffi.requests.exceptions import ProxyError
    from server.odds.books.coral33 import accounts as accts

    async def boom(self):
        raise ProxyError("Could not resolve proxy: isp.decodo.com")

    monkeypatch.setattr(accts.Coral33Client, "authenticate", boom)

    points = asyncio.run(accts.fetch_account_history(AccountCredential(
        customer_id="VR3",
        password="pw",
        label="Tertiary",
        proxy_url="http://u:p@isp.decodo.com:10003",
    ), 4))

    assert points == []


def test_fetch_account_history_isolates_transport_error_at_agent_lookup(
    monkeypatch,
):
    """The getAccountInfo agent lookup must also swallow transport errors."""
    from curl_cffi.requests.exceptions import ProxyError
    from server.odds.books.coral33 import accounts as accts

    monkeypatch.setattr(
        accts.Coral33Client, "authenticate", AsyncMock(return_value=None),
    )

    async def boom(self, operation, params=None):
        raise ProxyError("Could not resolve proxy: isp.decodo.com")

    monkeypatch.setattr(accts.Coral33Client, "post_form", boom)

    points = asyncio.run(accts.fetch_account_history(AccountCredential(
        customer_id="VR4",
        password="pw",
        label="Quaternary",
        proxy_url="http://u:p@isp.decodo.com:10004",
    ), 4))

    assert points == []


def test_get_history_survives_one_account_transport_error(monkeypatch):
    """One account's proxy blip must not 500 the whole history rollup."""
    import json as _json
    from curl_cffi.requests.exceptions import ProxyError
    from server.odds.books.coral33 import accounts as accts

    monkeypatch.setenv("CORAL33_ACCOUNTS", _json.dumps([
        {"customer_id": "GOOD", "password": "p",
         "proxy_url": "http://u:p@isp.decodo.com:10001"},
        {"customer_id": "BAD", "password": "p",
         "proxy_url": "http://u:p@isp.decodo.com:10002"},
    ]))

    async def fake_fetch(cred, weeks_back):
        if cred.customer_id == "BAD":
            raise ProxyError("Could not resolve proxy: isp.decodo.com")
        return [HistoryPoint(
            date="2026-09-18", won=0.0, lost=0.0, net=0.0,
            balance=100.0, pending=0.0,
        )]

    monkeypatch.setattr(accts, "fetch_account_history", fake_fetch)

    scraper = accts.AccountsScraper()
    history = asyncio.run(scraper.get_history(weeks_back=4))

    # The healthy account still reports; the broken one degrades to empty.
    assert history.get("GOOD"), "healthy account lost its history"
    assert history.get("BAD") == []
