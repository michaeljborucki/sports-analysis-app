from pathlib import Path
from unittest.mock import MagicMock

from server.odds.books.coral33.fetcher import Coral33Fetcher


def test_fetcher_uses_configured_lines_proxy(monkeypatch, tmp_path):
    monkeypatch.setenv("CORAL33_PROXY_URL", "http://proxy.example:10001")
    fetcher = Coral33Fetcher("customer", "password", MagicMock(path=tmp_path / "cache.sqlite"), Path("unused"))
    assert fetcher.client._proxies() == {
        "http": "http://proxy.example:10001",
        "https": "http://proxy.example:10001",
    }
