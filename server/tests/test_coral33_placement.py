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
    # Synchronous chain: getParlaySpecs (cached after first), then
    # getInfoParlay + checkWagerLineMulti in parallel (order between them
    # is not deterministic — both fire concurrently via asyncio.gather),
    # then insertWagerParlay. getPendingByTicket is now fire-and-forget
    # so it may or may not have landed by the time we observe.
    posts_sync = [op for op, _ in client.posts if op != "getPendingByTicket"]
    assert posts_sync[0] == "getParlaySpecs"
    assert set(posts_sync[1:3]) == {"getInfoParlay", "checkWagerLineMulti"}
    assert posts_sync[3] == "insertWagerParlay"
    # Yield once so the background getPendingByTicket task can fire,
    # then verify it lands.
    import asyncio as _asyncio
    await _asyncio.sleep(0)
    assert "getPendingByTicket" in [op for op, _ in client.posts]


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


# --- Spread + total self-heal tests -------------------------------------

def _fake_game_with_spread_and_total() -> dict:
    """Mirrors the shape Get_LeagueLines2 returns. Team1=away convention."""
    return {
        "GameNum": 619139524,
        "Team1ID": "Cincinnati Reds",
        "Team1RotNum": 954,
        "Team2ID": "Milwaukee Brewers",
        "Team2RotNum": 953,
        "MoneyLine1": +110, "MoneyLineDecimal1": 2.10,
        "MoneyLineNumerator1": 11, "MoneyLineDenominator1": 10,
        "MoneyLine2": -130, "MoneyLineDecimal2": 1.77,
        "MoneyLineNumerator2": 10, "MoneyLineDenominator2": 13,
        "Spread": -1.5,         # signed from Team1's perspective
        "SpreadAdj1": -110, "SpreadDecimal1": 1.909,
        "SpreadNumerator1": 10, "SpreadDenominator1": 11,
        "SpreadAdj2": -110, "SpreadDecimal2": 1.909,
        "SpreadNumerator2": 10, "SpreadDenominator2": 11,
        "TotalPoints": 8.5,
        "TtlPtsAdj1": -105, "TtlPointsDecimal1": 1.952,
        "TtlPointsNumerator1": 20, "TtlPointsDenominator1": 21,
        "TtlPtsAdj2": -115, "TtlPointsDecimal2": 1.87,
        "TtlPointsNumerator2": 20, "TtlPointsDenominator2": 23,
        "SportType": "Baseball            ",
        "SportSubType": "MLB         ",
        "GameDateTime": "2026-06-23 19:10:01.000",
    }


def test_extract_price_fields_moneyline():
    """Side determination + price extraction for h2h."""
    from server.odds.books.coral33.placement import Coral33Placer
    g = _fake_game_with_spread_and_total()
    leg = LegSpec(sport_type="", sport_sub_type="", period="Game",
                  line_type="M", game_num=0, chosen_team_id="", rot_num=0,
                  price_american=0, price_decimal=0.0,
                  price_numerator=0, price_denominator=0)
    # Team1 side: Cincinnati Reds
    out = Coral33Placer._extract_price_fields(g, side=1, ev_leg=leg)
    assert out["chosen_team_id"] == "Cincinnati Reds"
    assert out["rot_num"] == 954
    assert out["price_american"] == +110


def test_extract_price_fields_spread_team1_takes_signed_value():
    """Team1 spread = +Spread; Team2 spread = -Spread (Coral signs from
    Team1's perspective)."""
    from server.odds.books.coral33.placement import Coral33Placer
    g = _fake_game_with_spread_and_total()  # Spread = -1.5
    leg_S = LegSpec(sport_type="", sport_sub_type="", period="Game",
                    line_type="S", game_num=0, chosen_team_id="", rot_num=0,
                    price_american=0, price_decimal=0.0,
                    price_numerator=0, price_denominator=0)
    side1 = Coral33Placer._extract_price_fields(g, side=1, ev_leg=leg_S)
    side2 = Coral33Placer._extract_price_fields(g, side=2, ev_leg=leg_S)
    assert side1["spread"] == -1.5    # Reds -1.5 (Team1 is favored)
    assert side2["spread"] == +1.5    # Brewers +1.5
    assert side1["price_american"] == -110
    assert side2["price_american"] == -110


def test_extract_price_fields_total_over_under_mapping():
    """Side=1 → Over, Side=2 → Under (Coral convention)."""
    from server.odds.books.coral33.placement import Coral33Placer
    g = _fake_game_with_spread_and_total()
    leg_T = LegSpec(sport_type="", sport_sub_type="", period="Game",
                    line_type="T", game_num=0, chosen_team_id="", rot_num=0,
                    price_american=0, price_decimal=0.0,
                    price_numerator=0, price_denominator=0,
                    total_points=8.5)
    over = Coral33Placer._extract_price_fields(g, side=1, ev_leg=leg_T)
    under = Coral33Placer._extract_price_fields(g, side=2, ev_leg=leg_T)
    assert over["chosen_team_id"] == "Over"
    assert over["total_points"] == 8.5
    assert over["price_american"] == -105
    assert under["chosen_team_id"] == "Under"
    assert under["total_points"] == 8.5
    assert under["price_american"] == -115


def test_determine_side_total_maps_over_under_to_side():
    """Side=1 for 'Over', side=2 for 'Under', None for anything else."""
    from server.odds.books.coral33.placement import Coral33Placer
    g = _fake_game_with_spread_and_total()
    leg_T = LegSpec(sport_type="", sport_sub_type="", period="Game",
                    line_type="T", game_num=0, chosen_team_id="", rot_num=0,
                    price_american=0, price_decimal=0.0,
                    price_numerator=0, price_denominator=0)
    assert Coral33Placer._determine_side(g, "Over", leg_T) == 1
    assert Coral33Placer._determine_side(g, "Under", leg_T) == 2
    assert Coral33Placer._determine_side(g, "over", leg_T) == 1   # case-insensitive
    assert Coral33Placer._determine_side(g, "Nope", leg_T) is None


# --- Alt-line / point-match tests --------------------------------------

def test_strip_alt_suffix_handles_common_patterns():
    """Coral33's ALT LINE tab suffixes team names with ' Alt RL',
    ' Alt PL', etc. The placer's team match must strip these so 'Orioles
    Alt RL' matches our cache's bare 'Baltimore Orioles'."""
    from server.odds.books.coral33.placement import Coral33Placer
    assert Coral33Placer._strip_alt_suffix("Orioles Alt RL") == "Orioles"
    assert Coral33Placer._strip_alt_suffix("Lakers Alt PL") == "Lakers"
    assert Coral33Placer._strip_alt_suffix("Bruins Alt MoneyLine") == "Bruins"
    assert Coral33Placer._strip_alt_suffix("Plain Team") == "Plain Team"
    assert Coral33Placer._strip_alt_suffix("") == ""


def test_team_match_works_through_alt_suffix():
    """Loose match must succeed for an ALT LINE entry whose team name
    has ' Alt RL' tacked on."""
    from server.odds.books.coral33.placement import Coral33Placer
    # Cache name: "Baltimore Orioles"; ALT LINE entry: "Orioles Alt RL"
    assert Coral33Placer._team_match("Orioles Alt RL", "Baltimore Orioles")
    assert Coral33Placer._team_match("Angels Alt RL", "Los Angeles Angels")


def test_point_matches_per_line_type():
    """_point_matches must enforce spread/total point equality (within
    0.01) for S/T, and always-True for M."""
    from server.odds.books.coral33.placement import Coral33Placer
    m = LegSpec(sport_type="", sport_sub_type="", period="Game",
                line_type="M", game_num=0, chosen_team_id="", rot_num=0,
                price_american=0, price_decimal=0.0,
                price_numerator=0, price_denominator=0)
    assert Coral33Placer._point_matches(m, {"spread": 0, "total_points": 0})

    s = LegSpec(sport_type="", sport_sub_type="", period="Game",
                line_type="S", game_num=0, chosen_team_id="", rot_num=0,
                price_american=0, price_decimal=0.0,
                price_numerator=0, price_denominator=0,
                spread=-1.5)
    assert Coral33Placer._point_matches(s, {"spread": -1.5, "total_points": 0})
    assert not Coral33Placer._point_matches(s, {"spread": +1.5, "total_points": 0})

    t = LegSpec(sport_type="", sport_sub_type="", period="Game",
                line_type="T", game_num=0, chosen_team_id="", rot_num=0,
                price_american=0, price_decimal=0.0,
                price_numerator=0, price_denominator=0,
                total_points=8.5)
    assert Coral33Placer._point_matches(t, {"spread": 0, "total_points": 8.5})
    assert not Coral33Placer._point_matches(t, {"spread": 0, "total_points": 9.0})


def test_sport_key_to_coral_has_alt_subtypes_for_mlb_nba_nhl():
    """Big-3 US team sports must have ALT LINE subtypes mapped so the
    placer can fall through to them on alt spread/total bets."""
    from server.odds.books.coral33.placement import Coral33Placer
    mlb = Coral33Placer.SPORT_KEY_TO_CORAL["mlb"]
    assert mlb[2] == ["MLB ALT LINE"]
    nba = Coral33Placer.SPORT_KEY_TO_CORAL["nba"]
    assert nba[2] == ["NBA ALT LINE"]
    nhl = Coral33Placer.SPORT_KEY_TO_CORAL["nhl"]
    assert nhl[2] == ["HOCKEY ALTER"]
    # Sports without alt subtypes — empty list (not None)
    assert Coral33Placer.SPORT_KEY_TO_CORAL["soccer"][2] == []
    assert Coral33Placer.SPORT_KEY_TO_CORAL["tennis"][2] == []
