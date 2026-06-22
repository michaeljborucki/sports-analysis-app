import asyncio
import json

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
