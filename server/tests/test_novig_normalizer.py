from datetime import datetime, timezone

from server.odds.books.novig.mapping import family_for, family_id
from server.odds.books.novig.normalizer import (
    build_sibling_index, match_event, plan_market, prob_to_american,
    rows_for, split_event_description, take_quotes,
)


T0 = datetime(2026, 10, 3, 19, 30, tzinfo=timezone.utc)
EV = {
    "event_id": "ev1", "home_team": "Alabama Crimson Tide",
    "away_team": "Georgia Bulldogs", "commence_time": T0,
}


def _novig_event(desc="Georgia @ Alabama", starts=T0):
    return {"eventId": "n1", "description": desc, "league": "NCAAF",
            "sport": "FOOTBALL", "startsTs": int(starts.timestamp() * 1000)}


def _market(mtype, desc, strike, names, charged="WHEN_LIVE"):
    return {
        "marketId": "m1", "eventId": "n1", "marketType": mtype,
        "description": desc, "strike": strike, "status": "OPEN",
        "fee": {"coefficient": "0.03", "makerCredit": "0.5", "charged": charged},
        "outcomes": [{"outcomeId": f"o{i}", "name": n} for i, n in enumerate(names)],
    }


def _row(mk, name, point, price=-110, eid="ev1"):
    return {"bookmaker_key": "novig", "event_id": eid, "market_key": mk,
            "outcome_name": name, "outcome_point": point, "price_american": price}


# ── prices ──

def test_prob_to_american_matches_odds_api_rounding():
    assert prob_to_american(0.575) == -135
    assert prob_to_american(0.68) == -212      # exact half rounds toward zero
    assert prob_to_american(0.5) == 100
    assert prob_to_american(0.4) == 150
    assert prob_to_american(0.0) is None and prob_to_american(1.0) is None


def test_take_quote_is_one_minus_opposing_best_bid_with_size():
    m = _market("PASSING_YARDS", "Joe Burrow 268.5 PASSING_YARDS", "268.5",
                ["Over 268.5", "Under 268.5"])
    book = {"orders": {"o1": [
        {"orderId": "a", "price": "0.425", "qty": 50000},
        {"orderId": "b", "price": "0.425", "qty": 30000},
        {"orderId": "c", "price": "0.40", "qty": 99999},
    ]}}
    q = take_quotes(m, book)
    # Over takeable at 1 - 0.425 against 80k contracts (1¢ each).
    assert q == {"o0": (0.575, 460.0)}
    assert "o1" not in q   # nobody bids Over → Under not takeable


# ── events ──

def test_event_description_strips_tennis_rounds():
    assert split_event_description("Novak Djokovic @ Alexander Zverev Quarterfinals") \
        == ("Novak Djokovic", "Alexander Zverev")
    assert split_event_description("Yihan Qu @ Wushuang Zheng 1st Qualifying Round") \
        == ("Yihan Qu", "Wushuang Zheng")
    assert split_event_description("ATL vs LAD SERIES_WINNER") is None


def test_match_event_prefix_names_and_window():
    # Novig drops NCAAF mascots: "Alabama" ↔ "Alabama Crimson Tide".
    other = {**EV, "event_id": "x", "home_team": "Alabama State Hornets",
             "away_team": "Jackson State Tigers"}
    assert match_event(_novig_event(), "ncaaf", [other, EV]) == (EV, True)
    late = _novig_event(starts=datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc))
    assert match_event(late, "ncaaf", [EV]) is None


def test_match_event_reports_flipped_orientation():
    hit = match_event(_novig_event("Alabama @ Georgia"), "ncaaf", [EV])
    assert hit == (EV, False)


def test_match_event_applies_aliases():
    ufc = {"event_id": "u1", "home_team": "Johnny Walker",
           "away_team": "Michael Parkin", "commence_time": T0}
    nev = _novig_event("Mick Parkin @ Johnny Walker")
    assert match_event(nev, "ufc", [ufc]) is None
    assert match_event(nev, "ufc", [ufc], {"mick parkin": "michael parkin"}) == (ufc, True)


# ── planning ──

def test_spread_plan_maps_home_strike_into_existing_slot():
    idx = build_sibling_index(
        [_row("spreads", "Georgia Bulldogs", -2.5), _row("spreads", "Alabama Crimson Tide", 2.5)],
        {"ev1": EV},
    )
    m = _market("SPREAD", "ALA +2.5", "2.5", ["ALA +2.5", "UGA -2.5"])
    plan = plan_market(m, "ncaaf", EV, True, idx)
    assert sorted(plan) == [
        ("o0", "spreads", "Alabama Crimson Tide", 2.5),
        ("o1", "spreads", "Georgia Bulldogs", -2.5),
    ]
    # A line betting-db has never seen is not polled at all.
    other = _market("SPREAD", "ALA -5.5", "-5.5", ["ALA -5.5", "UGA +5.5"])
    assert plan_market(other, "ncaaf", EV, True, idx) == []


def test_spread_plan_when_novig_home_is_cache_away():
    idx = build_sibling_index([_row("alternate_spreads", "Georgia Bulldogs", -2.5)], {"ev1": EV})
    # Novig lists Georgia as home: its strike -2.5 is Georgia's line.
    m = _market("SPREAD", "UGA -2.5", "-2.5", ["UGA -2.5", "ALA +2.5"])
    plan = plan_market(m, "ncaaf", EV, False, idx)
    assert sorted(plan) == [
        ("o0", "alternate_spreads", "Georgia Bulldogs", -2.5),
        ("o1", "alternate_spreads", "Alabama Crimson Tide", 2.5),
    ]


def test_moneyline_total_team_total_and_prop_plans():
    rows = [
        _row("h2h", "Alabama Crimson Tide", None),
        _row("totals", "Over", 54.5),
        _row("alternate_team_totals", "Alabama Crimson Tide Over", 27.5),
        _row("player_pass_yds", "jalen milroe Over", 212.5),
    ]
    idx = build_sibling_index(rows, {"ev1": EV})
    ml = plan_market(_market("MONEY", "ALA", "0", ["ALA", "UGA"]), "ncaaf", EV, True, idx)
    assert sorted(ml) == [("o0", "h2h", "Alabama Crimson Tide", None),
                          ("o1", "h2h", "Georgia Bulldogs", None)]
    tot = plan_market(_market("TOTAL", "UGA @ ALA t54.5", "54.5", ["Over 54.5", "Under 54.5"]),
                      "ncaaf", EV, True, idx)
    assert sorted(tot) == [("o0", "totals", "Over", 54.5), ("o1", "totals", "Under", 54.5)]
    tt = plan_market(_market("TEAM_TOTAL", "Alabama 27.5 TEAM_TOTAL", "27.5",
                             ["Over 27.5", "Under 27.5"]), "ncaaf", EV, True, idx)
    assert ("o1", "alternate_team_totals", "Alabama Crimson Tide Under", 27.5) in tt
    prop = plan_market(_market("PASSING_YARDS", "Jalen Milroe 212.5 PASSING_YARDS", "212.5",
                               ["Over 212.5", "Under 212.5"]), "ncaaf", EV, True, idx)
    assert sorted(prop) == [("o0", "player_pass_yds", "jalen milroe Over", 212.5),
                            ("o1", "player_pass_yds", "jalen milroe Under", 212.5)]


def test_rows_for_writes_only_takeable_sides_with_stake():
    m = _market("TOTAL", "UGA @ ALA t54.5", "54.5", ["Over 54.5", "Under 54.5"])
    plan = [("o0", "totals", "Over", 54.5), ("o1", "totals", "Under", 54.5)]
    rows = rows_for(m, plan, {"o0": (0.575, 460.0)}, "ncaaf", EV, T0)
    assert len(rows) == 1
    r = rows[0]
    assert (r["bookmaker_key"], r["market_key"], r["outcome_name"], r["outcome_point"]) \
        == ("novig", "totals", "Over", 54.5)
    assert r["price_american"] == -135 and r["max_stake_dollars"] == 460.0


def test_always_charged_market_prices_in_taker_fee():
    m = _market("TOTAL", "x", "54.5", ["Over 54.5", "Under 54.5"], charged="ALWAYS")
    rows = rows_for(m, [("o0", "totals", "Over", 54.5)], {"o0": (0.5, 1.0)}, "ncaaf", EV, T0)
    # 0.5 + 0.03 * 0.25 = 0.5075 → -103
    assert rows[0]["price_american"] == -103


def test_mapping_families():
    assert family_for("mlb", "SPREAD_1H")[1][0] == "spreads_1st_5_innings"
    assert family_for("nfl", "RECEIVING_YARDS") == (
        "prop", ("player_reception_yds", "player_reception_yds_alternate"))
    assert family_for("nfl", "FIRST_TOUCHDOWN_SCORER") is None
    assert family_id("alternate_spreads") == family_id("spreads")
    assert family_id("player_pass_yds_alternate") == "player_pass_yds"


# ── maker quotes ──

from server.odds.books.novig.normalizer import maker_quotes, next_tick  # noqa: E402


def test_next_tick_walks_the_price_grid():
    assert next_tick(0.001) == 0.002
    assert next_tick(0.049) == 0.05
    assert next_tick(0.05) == 0.055      # band change: 0.001 → 0.005 steps
    assert next_tick(0.425) == 0.43
    assert next_tick(0.94) == 0.945
    assert next_tick(0.945) == 0.95      # band change: 0.005 → 0.001 steps
    assert next_tick(0.95) == 0.951
    assert next_tick(0.999) is None


def test_maker_quote_improves_bid_by_one_tick():
    m = _market("TOTAL", "x", "54.5", ["Over 54.5", "Under 54.5"])
    book = {"orders": {
        "o0": [{"orderId": "a", "price": "0.40", "qty": 100}],
        "o1": [{"orderId": "b", "price": "0.50", "qty": 100}],
    }}
    # Over: bid 0.40 → post 0.405 (take is 0.50, not crossed).
    # Under: bid 0.50 → post 0.505 (take is 0.60).
    assert maker_quotes(m, book) == {"o0": 0.405, "o1": 0.505}


def test_maker_quote_joins_bid_on_one_tick_spread_and_needs_a_bid():
    m = _market("TOTAL", "x", "54.5", ["Over 54.5", "Under 54.5"])
    book = {"orders": {
        "o0": [{"orderId": "a", "price": "0.495", "qty": 100}],
        "o1": [{"orderId": "b", "price": "0.50", "qty": 100}],
    }}
    # Over take = 0.50, bid+tick = 0.50 would cross → join at 0.495.
    q = maker_quotes(m, book)
    assert q["o0"] == 0.495
    one_sided = {"orders": {"o1": [{"orderId": "b", "price": "0.425", "qty": 1}]}}
    # Nobody bids Over → nothing to improve on; Under still quotes.
    assert maker_quotes(m, one_sided) == {"o1": 0.43}


def test_maker_rows_carry_maker_book_and_no_stake():
    m = _market("TOTAL", "x", "54.5", ["Over 54.5", "Under 54.5"])
    plan = [("o1", "totals", "Under", 54.5)]
    rows = rows_for(m, plan, {"o1": (0.43, None)}, "ncaaf", EV, T0, book_key="novig_maker")
    assert rows[0]["bookmaker_key"] == "novig_maker"
    assert rows[0]["price_american"] == 133 and rows[0]["max_stake_dollars"] is None
