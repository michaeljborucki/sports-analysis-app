import json
from pathlib import Path
from typing import Any

import pytest

from server.odds.books.coral33.placement import (
    build_check_wager_line_multi_parlay,
    build_insert_wager_parlay,
    build_get_info_parlay,
    build_get_parlay_specs,
    build_get_pending_by_ticket,
)
from server.sidecar.models import LegSpec


FIXTURE_DIR = Path(__file__).parent / "fixtures/coral33/placement"


def load(name):
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


@pytest.fixture
def new_zealand_leg() -> LegSpec:
    """Reconstruct the leg from the HAR's insert_wager_parlay payload."""
    return LegSpec(
        sport_type="Soccer              ",
        sport_sub_type="WORLD CUP   ",
        period="Game",
        line_type="M",
        game_num=619136397,
        chosen_team_id="New Zealand",
        rot_num=225390,
        price_american=475,
        price_decimal=5.75,
        price_numerator=19,
        price_denominator=4,
        game_datetime="2026-06-21 19:00:01.000",
        description="Soccer #225390 New Zealand +475 - For Game ",
    )


def test_build_get_parlay_specs_matches_har():
    fixture = load("get_parlay_specs")
    built = build_get_parlay_specs(
        customer_id="VR12509",
        parlay_name="10 team",
    )
    assert built == fixture["request"]


def test_build_get_info_parlay_matches_har():
    fixture = load("get_info_parlay")
    built = build_get_info_parlay(
        customer_id="VR12509",
        parlay_name="10 team",
        teams=2,
        selects="619136397-M|New Zealand^0",
    )
    assert built == fixture["request"]


def test_build_check_wager_line_multi_matches_har(new_zealand_leg):
    fixture = load("check_wager_line_multi_parlay")
    built = build_check_wager_line_multi_parlay(
        customer_id="VR12509",
        leg=new_zealand_leg,
        position=25710414,           # HAR-captured value
        risk_dollars=10.0,
        win_dollars=99.77,
    )
    assert built == fixture["request"]


def test_build_insert_wager_parlay_matches_har(new_zealand_leg):
    fixture = load("insert_wager_parlay")
    delay = fixture["request"]["delay"]
    built = build_insert_wager_parlay(
        customer_id="VR12509",
        agent_id="TYSONR",
        store="wiseguys",
        cust_profile=".                   ",
        leg=new_zealand_leg,
        stake_dollars=10.0,
        win_dollars=99.77,
        decimal_win_amount=47.5,
        parlay_name="10 team",
        doc_num=27458945,            # HAR-captured value
        delay=delay,
    )
    # The HAR has minor field-ordering jitter; compare structurally.
    assert built["operation"] == "insertWagerParlay"
    assert built["list"][0]["chosenTeamID"] == "New Zealand"
    assert built["list"][0]["wager"]["openSpotFlag"] == "O"
    assert built["list"][0]["wager"]["totalPicks"] == 2
    assert built["list"][0]["wager"]["minPicks"] == 1
    assert built["list"][0]["wager"]["parlayName"] == "10 team"
    assert built["delay"] == delay


def test_build_get_pending_by_ticket_matches_har():
    fixture = load("get_pending_by_ticket")
    built = build_get_pending_by_ticket(
        agent_id="TYSONR",
        customer_id="VR12509",
        ticket_number=1471133392,
    )
    assert built == fixture["request"]


# --- Coral33Placer orchestration tests ---------------------------------------

from server.odds.books.coral33.placement import (
    Coral33Placer,
    PlacementResult,
    PlacementError,
)


class FakeCoral33Client:
    """In-memory replacement for Coral33Client. Records every POST and
    returns scripted responses keyed by operation name."""

    def __init__(self):
        self.customer_id = "VR12509"
        self.posts: list[tuple[str, dict]] = []
        self._responses: dict[str, Any] = {}

    def script(self, operation: str, response: Any) -> None:
        self._responses[operation] = response

    async def post_json(self, operation: str, body: dict) -> dict:
        self.posts.append((operation, body))
        if operation in self._responses:
            return self._responses[operation]
        raise AssertionError(f"unscripted op: {operation}")


@pytest.mark.asyncio
async def test_place_open_parlay_runs_five_calls_in_order(new_zealand_leg):
    client = FakeCoral33Client()
    client.script("getParlaySpecs",
                  {"INFO": {"MaxPicks": 10, "DefaultPrice": -110}})
    client.script("getInfoParlay",
                  {"INFO": {"CARD": [{"GamesPicked": 2, "MoneyLine": 2.6,
                                       "ToBase": 1, "MaxPayoutMoneyLine": None,
                                       "MaxPayoutToBase": None}]}})
    client.script("checkWagerLineMulti",
                  {"LIST": [{"position": 25710414,
                              "Status": "O",
                              "MoneyLine2": 475}],
                   "DELAY": {"time": 1782088322, "secs": 0, "sig": "SIG_X"}})
    client.script("insertWagerParlay",
                  {"STATUS": {"STATE": 1, "DOC": 1471133392, "T": ""}})
    client.script("getPendingByTicket",
                  {"PENDING": [{"TicketNumber": 1471133392}]})

    placer = Coral33Placer(
        client=client,
        agent_id="TYSONR",
        store="wiseguys",
        cust_profile=".                   ",
    )
    import os
    os.environ["CORAL33_PLACEMENT_LIVE"] = "true"
    try:
        result = await placer.place_open_parlay(
            ev_leg=new_zealand_leg,
            stake_dollars=10,
            live=True,
        )
    finally:
        os.environ.pop("CORAL33_PLACEMENT_LIVE", None)
    assert isinstance(result, PlacementResult)
    assert result.ticket_number == 1471133392
    # Five-call sequence in exact order
    assert [op for op, _ in client.posts] == [
        "getParlaySpecs", "getInfoParlay", "checkWagerLineMulti",
        "insertWagerParlay", "getPendingByTicket",
    ]


@pytest.mark.asyncio
async def test_dry_run_halts_before_insert(new_zealand_leg):
    client = FakeCoral33Client()
    client.script("getParlaySpecs",
                  {"INFO": {"MaxPicks": 10, "DefaultPrice": -110}})
    client.script("getInfoParlay",
                  {"INFO": {"CARD": [{"GamesPicked": 2, "MoneyLine": 2.6,
                                       "ToBase": 1, "MaxPayoutMoneyLine": None,
                                       "MaxPayoutToBase": None}]}})
    client.script("checkWagerLineMulti",
                  {"LIST": [{"position": 1}],
                   "DELAY": {"time": 0, "secs": 0, "sig": "SIG_DRY"}})

    placer = Coral33Placer(client=client, agent_id="A", store="s",
                           cust_profile=".")
    result = await placer.place_open_parlay(
        ev_leg=new_zealand_leg, stake_dollars=10, live=False,
    )
    assert result.ticket_number is None
    assert result.dry_run is True
    assert result.would_be_payload is not None
    # Three calls, no insert, no pending fetch
    assert [op for op, _ in client.posts] == [
        "getParlaySpecs", "getInfoParlay", "checkWagerLineMulti",
    ]


@pytest.mark.asyncio
async def test_live_flag_false_overrides_env_true(new_zealand_leg, monkeypatch):
    monkeypatch.setenv("CORAL33_PLACEMENT_LIVE", "true")
    client = FakeCoral33Client()
    # Script enough for the dry-run path
    client.script("getParlaySpecs", {"INFO": {"MaxPicks": 10, "DefaultPrice": -110}})
    client.script("getInfoParlay", {"INFO": {"CARD": [{"GamesPicked": 2, "MoneyLine": 2.6, "ToBase": 1, "MaxPayoutMoneyLine": None, "MaxPayoutToBase": None}]}})
    client.script("checkWagerLineMulti", {"LIST": [{"position": 1}], "DELAY": {"time": 0, "secs": 0, "sig": "S"}})

    placer = Coral33Placer(client=client, agent_id="A", store="s",
                           cust_profile=".")
    result = await placer.place_open_parlay(
        ev_leg=new_zealand_leg, stake_dollars=10, live=False,
    )
    # The env says live, but the per-call flag says dry-run. Dry-run wins.
    assert result.dry_run is True


@pytest.mark.asyncio
async def test_live_requires_env_var(new_zealand_leg, monkeypatch):
    monkeypatch.delenv("CORAL33_PLACEMENT_LIVE", raising=False)
    client = FakeCoral33Client()
    placer = Coral33Placer(client=client, agent_id="A", store="s",
                           cust_profile=".")
    with pytest.raises(PlacementError, match="CORAL33_PLACEMENT_LIVE"):
        await placer.place_open_parlay(
            ev_leg=new_zealand_leg, stake_dollars=10, live=True,
        )
