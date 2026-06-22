import json
import asyncio
import pytest
from unittest.mock import patch
from server.odds.books.coral33.client import Coral33Client


@pytest.mark.asyncio
async def test_post_json_sends_application_json_body(monkeypatch):
    """post_json must serialize the body as JSON, not form-encoded, and
    set content-type accordingly. Captures the request via a mock and
    asserts the captured body equals the input dict."""
    captured = {}

    async def fake_post(self, url, data=None, headers=None, json=None, **kw):
        captured["data"] = data
        captured["json"] = json
        captured["headers"] = headers
        # Return a fake response object
        class R:
            status_code = 200
            text = '{"INFO": {"MaxPicks": 10}}'
            def json(self):
                return {"INFO": {"MaxPicks": 10}}
        return R()

    from curl_cffi.requests import AsyncSession
    monkeypatch.setattr(AsyncSession, "post", fake_post)

    c = Coral33Client("VR12509", "pw")
    # Pre-set a token to skip auth
    c._token = "FAKE_JWT"
    c._token_exp = 9999999999

    nested_body = {
        "customerID": "VR12509   ",
        "list": [{"gameNum": 619136397, "wagerType": "P"}],
        "operation": "checkWagerLineMulti",
        "RRO": 0,
    }
    result = await c.post_json("checkWagerLineMulti", nested_body)
    assert result == {"INFO": {"MaxPicks": 10}}
    # Content-type must indicate JSON
    assert "application/json" in captured["headers"]["content-type"].lower()
    # Body must round-trip as the SAME nested dict (no _stringify)
    sent = captured["json"] or json.loads(captured["data"])
    assert sent == nested_body
    assert isinstance(sent["list"], list)
    assert isinstance(sent["list"][0], dict)
