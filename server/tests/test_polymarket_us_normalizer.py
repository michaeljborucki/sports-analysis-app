"""Offline tests for the Polymarket US normalizer (fixtures under
server/tests/fixtures/polymarket_us — real, trimmed gateway payloads)."""
from __future__ import annotations

import collections
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.odds.books.coral33.event_matcher import _normalize_team
from server.odds.books.polymarket_us import mapping
from server.odds.books.polymarket_us.normalizer import (
    BOOK_KEY,
    DEFAULT_FEE_COEFFICIENT,
    NormalizedEvent,
    american_from_book,
    buy_price_to_american,
    normalize_event,
)
from server.odds.player_names import normalize_player_name


FIX = Path(__file__).parent / "fixtures" / "polymarket_us"

# league -> (sport, home canonical, away canonical) as the Odds API names them.
CANON = {
    "nba": ("nba", "Golden State Warriors", "Memphis Grizzlies"),
    "nfl": ("nfl", "New Orleans Saints", "Pittsburgh Steelers"),
    "cfb": ("ncaaf", "Stanford Cardinal", "NC State Wolfpack"),
    "nhl": ("nhl", "Colorado Avalanche", "Tampa Bay Lightning"),
    "mlb": ("mlb", "Milwaukee Brewers", "Tampa Bay Rays"),
    "epl": ("soccer", "Arsenal", "Everton"),
    "mls": ("soccer", "Nashville SC", "CF Montréal"),
    "wnba": ("wnba", "Atlanta Dream", "Golden State Valkyries"),
}

# Market keys each fixture must produce (subset check).
EXPECTED_KEYS = {
    "nba": {"h2h", "spreads", "alternate_spreads", "totals", "alternate_totals",
            "team_totals", "alternate_team_totals", "spreads_h1", "totals_h1",
            "team_totals_h1", "h2h_3_way_h1", "spreads_q3", "totals_q4",
            "h2h_3_way_q4", "player_points", "player_rebounds", "player_assists",
            "player_threes", "player_blocks", "player_steals",
            "player_points_rebounds_assists"},
    "nfl": {"h2h", "spreads", "alternate_spreads", "totals", "alternate_totals",
            "team_totals", "alternate_team_totals", "spreads_h1", "totals_h1",
            "team_totals_h1", "spreads_q1", "totals_q1", "player_pass_yds",
            "player_pass_tds", "player_pass_attempts", "player_pass_completions",
            "player_pass_interceptions", "player_rush_yds", "player_reception_yds",
            "player_receptions", "player_reception_longest"},
    "cfb": {"h2h", "spreads", "alternate_spreads", "totals", "alternate_totals",
            "team_totals", "alternate_team_totals", "spreads_h1", "totals_h1"},
    "nhl": {"h2h", "spreads", "totals", "team_totals", "h2h_3_way", "spreads_p1",
            "totals_p1", "h2h_3_way_p3", "player_points", "player_assists",
            "player_goals"},
    "mlb": {"h2h", "spreads", "alternate_spreads", "spreads_1st_5_innings",
            "totals_1st_5_innings", "h2h_3_way_1st_5_innings",
            "h2h_3_way_1st_1_innings", "totals_1st_1_innings", "nrfi"},
    "epl": {"h2h", "spreads", "alternate_spreads", "totals", "team_totals"},
    "mls": {"h2h", "spreads", "totals", "team_totals"},
    "wnba": {"h2h", "spreads", "alternate_spreads", "totals", "alternate_totals",
             "player_points", "player_rebounds", "player_assists", "player_threes"},
}


def _load(league: str) -> dict:
    return json.loads((FIX / f"{league}_event.json").read_text())


def _start(ev: dict) -> datetime:
    return datetime.fromisoformat(ev["startTime"].replace("Z", "+00:00"))


def _matcher(home: str, away: str, commence: datetime, event_id: str = "EVT"):
    """Fake match_event: equality on normalized names (either orientation),
    like PolymarketEventMatcher, returning the cache's home/away."""
    calls: list[tuple] = []

    def match(sport, a, b, when):
        calls.append((sport, a, b, when))
        want = {_normalize_team(home, {}, sport), _normalize_team(away, {}, sport)}
        got = {_normalize_team(a, {}, sport), _normalize_team(b, {}, sport)}
        if got == want:
            return {"event_id": event_id, "home_team": home,
                    "away_team": away, "commence_time": commence}
        return None

    match.calls = calls
    return match


def _run(league: str, **kw) -> tuple[NormalizedEvent, dict]:
    ev = _load(league)
    _sport, home, away = CANON[league]
    start = _start(ev)
    res = normalize_event(ev, league, start - timedelta(hours=2),
                          _matcher(home, away, start, f"E-{league}"), **kw)
    return res, ev


def _market(ev: dict, slug: str) -> dict:
    return next(m for m in ev["markets"] if m["slug"] == slug)


def _rows_for(res: NormalizedEvent, slug: str) -> list[dict]:
    return [r for r in res.rows if r["_market_slug"] == slug]


# ── fee math ────────────────────────────────────────────────────────────

def test_fee_math_even_money():
    # c = 0.5 + 0.0695*0.25 = 0.517375; profit 0.482625;
    # -0.517375/0.482625*100 = -107.2002 -> floor (against bettor) = -108
    assert buy_price_to_american(0.50, 0.0695) == -108
    assert buy_price_to_american(0.50) == -108


def test_fee_math_underdog_and_favorite_round_against_bettor():
    # p=0.40: c = 0.4 + 0.0695*0.24 = 0.41668 -> +139.99 -> 139
    assert buy_price_to_american(0.40, 0.0695) == 139
    # p=0.70: c = 0.7 + 0.0695*0.21 = 0.714595 -> -250.37 -> -251
    assert buy_price_to_american(0.70, 0.0695) == -251
    # zero fee: 0.5 -> exactly -100 / +100 boundary
    assert buy_price_to_american(0.50, 0.0) == 100


@pytest.mark.parametrize("p", [0, 1, -0.1, 1.2, float("nan"), None, "x"])
def test_fee_math_rejects_out_of_range(p):
    assert buy_price_to_american(p) is None


# ── order book ──────────────────────────────────────────────────────────

BIDS = [{"px": {"value": "0.48"}, "qty": "100"}, {"px": {"value": "0.47"}, "qty": "500"}]
OFFERS = [{"px": {"value": "0.50"}, "qty": "200"}, {"px": {"value": "0.51"}, "qty": "900"}]


def test_book_long_buys_best_offer():
    am, stake = american_from_book(BIDS, OFFERS, True, 0.0695)
    assert am == buy_price_to_american(0.50, 0.0695) == -108
    assert stake == pytest.approx(100.0)          # 0.50 * 200


def test_book_short_buys_one_minus_best_bid():
    am, stake = american_from_book(BIDS, OFFERS, False, 0.0695)
    assert am == buy_price_to_american(0.52, 0.0695)
    assert stake == pytest.approx(52.0)           # (1-0.48) * 100


def test_book_unsorted_and_empty():
    am, _ = american_from_book(list(reversed(BIDS)), list(reversed(OFFERS)), True, 0.0695)
    assert am == -108
    assert american_from_book([], OFFERS, False, 0.0695) == (None, None)
    assert american_from_book(BIDS, [], True, 0.0695) == (None, None)
    assert american_from_book([{"px": {"value": "0"}, "qty": "5"}], [], False, 0.07) == (None, None)


# ── full events ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("league", sorted(CANON))
def test_fixture_normalization(league):
    res, _ev = _run(league)
    sport, home, away = CANON[league]
    assert isinstance(res.unmapped, collections.Counter)
    assert res.event_id == f"E-{league}"
    assert res.rows
    keys = {r["market_key"] for r in res.rows}
    missing = EXPECTED_KEYS[league] - keys
    assert not missing, missing
    # Only keys the app knows for the sport.
    assert keys <= mapping.known_market_keys(sport), keys - mapping.known_market_keys(sport)
    # No duplicate primary keys.
    pks = [(r["event_id"], r["market_key"], r["outcome_name"], r["outcome_point"]) for r in res.rows]
    assert len(pks) == len(set(pks))
    for r in res.rows:
        assert r["bookmaker_key"] == BOOK_KEY
        assert r["sport_key"] == sport
        assert (r["home_team"], r["away_team"]) == (home, away)
        assert isinstance(r["price_american"], int)
        assert r["max_stake_dollars"] is None and r["wager_type"] is None
        assert r["_market_slug"] and isinstance(r["_long"], bool)
        assert r["_fee"] == pytest.approx(0.0695)
        if sport == "soccer":
            assert r["league_key"] == mapping.SOCCER_LEAGUES[league][0]
        else:
            assert r["league_key"] is None
    # Document what isn't mapped (shown with -s).
    print(f"\n{league}: {len(res.rows)} rows; unmapped={dict(sorted(res.unmapped.items()))}; "
          f"skipped={dict(res.skipped)}")


def test_nba_player_prop_over_under_from_yes_no_quotes():
    res, ev = _run("nba")
    m = next(m for m in ev["markets"]
             if m["sportsMarketType"] == "basketball_player_points"
             and m["marketSides"][0]["quote"] and m["marketSides"][0]["tradable"])
    q = m["question"]
    name = q[len("Will "):q.index(" record")]
    rows = _rows_for(res, m["slug"])
    over = next(r for r in rows if r["_long"])
    assert over["market_key"] == "player_points"
    assert over["outcome_name"] == f"{normalize_player_name(name, 'nba', 'player_points')} Over"
    assert over["outcome_point"] == float(m["line"]) - 0.5
    yes = next(s for s in m["marketSides"] if s["long"])
    assert over["price_american"] == buy_price_to_american(float(yes["quote"]["value"]), m["feeCoefficient"])


def test_wnba_prop_under_side_from_no_quote():
    res, ev = _run("wnba")
    m = next(m for m in ev["markets"]
             if m["sportsMarketType"] == "basketball_player_points"
             and all(s["quote"] and s["tradable"] for s in m["marketSides"]))
    rows = {r["outcome_name"].rsplit(" ", 1)[1]: r for r in _rows_for(res, m["slug"])}
    no = next(s for s in m["marketSides"] if not s["long"])
    assert rows["Under"]["price_american"] == buy_price_to_american(float(no["quote"]["value"]), 0.0695)
    assert rows["Under"]["_long"] is False
    assert rows["Under"]["outcome_point"] == rows["Over"]["outcome_point"] == float(m["line"]) - 0.5


def test_nfl_spread_sides_keep_their_own_signed_point():
    res, ev = _run("nfl")
    slug = "asc-nfl-pit-no-2026-10-25-neg-3pt5"
    rows = {r["outcome_name"]: r for r in _rows_for(res, slug)}
    assert rows["Pittsburgh Steelers"]["outcome_point"] == -3.5
    assert rows["Pittsburgh Steelers"]["_long"] is True
    assert rows["New Orleans Saints"]["outcome_point"] == 3.5
    assert rows["New Orleans Saints"]["_long"] is False
    assert {r["market_key"] for r in rows.values()} == {"spreads"}   # balanced -> main
    m = _market(ev, slug)
    short = next(s for s in m["marketSides"] if not s["long"])
    assert rows["New Orleans Saints"]["price_american"] == buy_price_to_american(
        float(short["quote"]["value"]), 0.0695)


def test_main_vs_alternate_uses_published_main_total():
    res, _ev = _run("nba")
    mains = {r["outcome_point"] for r in res.rows if r["market_key"] == "totals"}
    assert mains == {231.5}          # eventState.mainTotalLine
    assert all(r["outcome_point"] != 231.5 for r in res.rows if r["market_key"] == "alternate_totals")
    # one main market per spread group
    assert len([r for r in res.rows if r["market_key"] == "spreads"]) == 2


def test_soccer_full_time_3way_is_h2h_with_draw():
    res, _ev = _run("epl")
    h2h = {r["outcome_name"]: r for r in res.rows if r["market_key"] == "h2h"}
    assert set(h2h) == {"Arsenal", "Everton", "Draw"}
    assert all(r["outcome_point"] is None and r["_long"] for r in h2h.values())
    assert h2h["Draw"]["league_title"] == "EPL"


def test_nhl_regulation_3way_and_period_3way():
    res, _ev = _run("nhl")
    reg = {r["outcome_name"] for r in res.rows if r["market_key"] == "h2h_3_way"}
    assert reg == {"Colorado Avalanche", "Tampa Bay Lightning", "Draw"}
    assert "Draw" in {r["outcome_name"] for r in res.rows if r["market_key"] == "h2h_3_way_p3"}


def test_team_totals_encoding_yes_no_and_over_under():
    res, _ev = _run("nhl")   # Yes/No shaped
    tt = [r for r in res.rows if "team_totals" in r["market_key"]]
    assert tt and all(r["outcome_name"].rsplit(" ", 1)[0] in CANON["nhl"][1:] for r in tt)
    assert {r["outcome_name"].rsplit(" ", 1)[1] for r in tt} == {"Over", "Under"}
    res, _ev = _run("nba")   # Over/Under shaped
    assert any(r["outcome_name"] == "Golden State Warriors Over" for r in res.rows
               if r["market_key"] == "team_totals")


def test_mlb_nrfi_yes_means_run_scored():
    res, ev = _run("mlb")
    m = next(m for m in ev["markets"] if m["sportsMarketType"] == "baseball_team_first_inning_run")
    rows = {r["outcome_name"]: r for r in _rows_for(res, m["slug"])}
    yes = next(s for s in m["marketSides"] if s["description"] == "Yes")
    assert rows["Yes"]["market_key"] == "nrfi"
    assert rows["Yes"]["price_american"] == buy_price_to_american(float(yes["quote"]["value"]), 0.0695)
    assert rows["Yes"]["_long"] is True and rows["No"]["_long"] is False


def test_flipped_cache_orientation_maps_team_ids():
    ev = _load("nba")
    start = _start(ev)
    # Cache says Memphis is home: team ids must still map by name.
    res = normalize_event(ev, "nba", start - timedelta(hours=1),
                          _matcher("Memphis Grizzlies", "Golden State Warriors", start))
    rows = {r["outcome_name"]: r for r in _rows_for(res, "aec-nba-mem-gs-2026-10-23")}
    assert rows["Memphis Grizzlies"]["_long"] is True        # long side = Grizzlies
    assert rows["Golden State Warriors"]["_long"] is False


def test_unmatched_event_emits_nothing_but_reports_unmapped():
    ev = _load("nfl")
    res = normalize_event(ev, "nfl", _start(ev) - timedelta(hours=1), lambda *a: None)
    assert res.event_id is None and res.rows == []
    assert res.unmapped["football_player_touchdowns"] == 40


def test_live_event_skipped_by_default():
    ev = _load("mlb")
    start = _start(ev)
    m = _matcher(*CANON["mlb"][1:], start)
    res = normalize_event(ev, "mlb", start + timedelta(minutes=5), m)
    assert res.rows == [] and res.event_id == "EVT" and res.skipped["live_event"] == 1
    res = normalize_event(ev, "mlb", start + timedelta(minutes=5), m, include_live=True)
    assert res.rows


def test_duplicate_pk_closed_and_crossed_markets():
    ev = copy.deepcopy(_load("wnba"))
    start = _start(ev)
    h2h = next(m for m in ev["markets"] if m["sportsMarketType"] == "basketball_team_full_game_winner")
    dup = copy.deepcopy(h2h)
    dup["slug"] = "zzz-dup"
    closed = copy.deepcopy(h2h)
    closed["slug"], closed["closed"], closed["status"] = "zzz-closed", True, "MARKET_STATUS_CLOSED"
    crossed = copy.deepcopy(h2h)
    crossed["slug"] = "aaa-crossed"
    for s in crossed["marketSides"]:
        s["quote"] = {"value": "0.40", "currency": "USD"}
    ev["markets"] += [dup, closed, crossed]
    res = normalize_event(ev, "wnba", start - timedelta(hours=1), _matcher(*CANON["wnba"][1:], start))
    h2h_rows = [r for r in res.rows if r["market_key"] == "h2h"]
    assert len(h2h_rows) == 2 and {r["_market_slug"] for r in h2h_rows} == {h2h["slug"]}
    assert res.skipped["duplicate_pk:basketball_team_full_game_winner"] == 2
    assert res.skipped["closed"] >= 1
    assert res.skipped["crossed_book"] == 1


def test_untradable_or_unquoted_side_emits_no_row():
    res, ev = _run("nba")
    m = next(m for m in ev["markets"] if m["sportsMarketType"] == "basketball_player_steals"
             and m["marketSides"][1]["quote"] is None)
    rows = _rows_for(res, m["slug"])
    assert [r["_long"] for r in rows] == [True]


def test_every_unmapped_type_has_a_reason():
    for league, (sport, _h, _a) in CANON.items():
        res, _ = _run(league)
        for smt in res.unmapped:
            kind, reason, _ = mapping.classify(sport, smt)
            assert kind is None and reason, (league, smt)
