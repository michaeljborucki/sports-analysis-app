from server.odds.books.coral33.client import Coral33Client


def test_client_records_proxy_url():
    c = Coral33Client("VR11606", "pw",
                     proxy_url="http://u:p@isp.decodo.com:10007")
    assert c.proxy_url == "http://u:p@isp.decodo.com:10007"


def test_client_proxy_url_defaults_to_none():
    c = Coral33Client("VR11606", "pw")
    assert c.proxy_url is None


import asyncio
from unittest.mock import patch
from curl_cffi.requests import AsyncSession


def test_async_session_constructed_with_proxies(monkeypatch):
    captured = {}
    real_init = AsyncSession.__init__

    def spy_init(self, *args, **kwargs):
        captured["proxies"] = kwargs.get("proxies")
        # Construct but don't actually use the session for this test
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "__init__", spy_init)

    c = Coral33Client("VR11606", "pw",
                     proxy_url="http://u:p@isp.decodo.com:10007")
    # Drive the authenticate path far enough to construct a session, but
    # catch the HTTP failure since we have no real server.
    try:
        asyncio.run(c.authenticate())
    except Exception:
        pass
    assert captured["proxies"] == {
        "http": "http://u:p@isp.decodo.com:10007",
        "https": "http://u:p@isp.decodo.com:10007",
    }
