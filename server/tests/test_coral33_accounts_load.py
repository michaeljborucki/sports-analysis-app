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
