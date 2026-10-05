import pytest

from server.odds.books.coral33.client import Coral33Client


@pytest.mark.asyncio
@pytest.mark.parametrize("period,number", [
    ("Game", "0"), ("1st Half", "1"),
    ("1st Quarter", "3"), ("2nd Quarter", "4"),
    ("3rd Quarter", "5"), ("4th Quarter", "6"),
])
async def test_football_request_uses_matching_period_number(monkeypatch, period, number):
    captured = {}

    async def capture_post_form(operation, params):
        captured["operation"] = operation
        captured["params"] = params
        return {"Lines": []}

    client = Coral33Client("customer", "password")
    monkeypatch.setattr(client, "post_form", capture_post_form)

    await client.get_league_lines(
        "FOOTBALL", "NFL", period=period, wager_type="Straight"
    )

    assert captured["operation"] == "Get_LeagueLines2"
    assert captured["params"]["periodNumber"] == number
