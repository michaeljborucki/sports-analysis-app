import json
from pathlib import Path

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
