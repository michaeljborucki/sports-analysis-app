import asyncio
import json
from unittest.mock import AsyncMock

from server.odds.books.coral33.accounts import load_account_credentials


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
