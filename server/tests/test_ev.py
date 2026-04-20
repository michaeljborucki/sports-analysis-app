"""Tests for the +EV scanner.

All fixtures are synthetic game dicts matching the shape produced by
`rows_to_games` — Market → Outcome → prices[] with commission already applied.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from server.odds.devig import (
    american_to_decimal,
    american_to_implied_prob,
    devig_n_way,
    devig_two_way,
    implied_to_american,
)
from server.odds.ev import scan_all_ev


NOW = datetime(2026, 4, 20, 18, 0, 0, tzinfo=timezone.utc)


def _price(book: str, american: int, *, age_s: int = 5, point: float | None = None) -> dict:
    return {
        "bookmaker_key": book,
        "price_american": american,
        "point": point,
        "fetched_at": NOW - timedelta(seconds=age_s),
    }


def _outcome(name: str, prices: list[dict]) -> dict:
    return {
        "outcome_name": name,
        "prices": prices,
        "best_price": prices[0] if prices else None,
        "consensus_price_american": prices[0]["price_american"] if prices else 0,
    }


def _market(key: str, outcomes: list[dict]) -> dict:
    return {"market_key": key, "outcomes": outcomes}


def _game(markets: list[dict], *, event_id: str = "game1", sport: str = "nba") -> dict:
    return {
        "event_id": event_id,
        "sport_key": sport,
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": NOW + timedelta(hours=2),
        "is_live": False,
        "markets": markets,
        "stale_seconds": 0,
    }


# ---------------- devig helpers ----------------


def test_american_to_decimal_examples():
    assert american_to_decimal(100) == pytest.approx(2.0)
    assert american_to_decimal(-110) == pytest.approx(1.9091, abs=1e-3)
    assert american_to_decimal(250) == pytest.approx(3.5)


def test_implied_to_american_roundtrip():
    for american in (-400, -150, -110, 100, 150, 300, 600):
        p = american_to_implied_prob(american)
        # Devig-free roundtrip: at vig-free price, implied_to_american should
        # return close to the original.
        assert abs(implied_to_american(p) - american) <= 1


def test_devig_two_way_sums_to_one():
    a, b = devig_two_way(-110, -110)
    assert a + b == pytest.approx(1.0)
    assert a == pytest.approx(0.5, abs=1e-6)


def test_devig_n_way_sums_to_one():
    probs = devig_n_way([150, 250, -140])
    assert sum(probs) == pytest.approx(1.0, abs=1e-9)
    assert all(0 < p < 1 for p in probs)


# ---------------- EV math golden case ----------------


def test_ev_math_golden_case():
    """Pinnacle -110/-110 → fair 50/50. Offered +105 on the home side →
    EV = 0.5 * 1.05 - 0.5 * 1 = +2.5% ROI."""
    game = _game([
        _market("h2h", [
            _outcome("Home", [
                _price("pinnacle", -110),
                _price("draftkings", 105),
            ]),
            _outcome("Away", [
                _price("pinnacle", -110),
                _price("draftkings", -115),
            ]),
        ])
    ])
    ops = scan_all_ev([game], now=NOW, min_ev_pct=0.1)
    home_ev = [o for o in ops if o["outcome_name"] == "Home" and o["book"] == "draftkings"]
    assert len(home_ev) == 1
    op = home_ev[0]
    assert op["ev_pct"] == pytest.approx(2.5, abs=0.01)
    assert op["fair_probability"] == pytest.approx(0.5, abs=1e-6)
    assert op["source"] == "pinnacle"
    assert op["kelly_full_pct"] == pytest.approx(op["ev_pct"] / (american_to_decimal(105) - 1))
    assert op["kelly_quarter_pct"] == pytest.approx(op["kelly_full_pct"] / 4)


def test_consensus_fallback_when_pinnacle_absent():
    """No Pinnacle → devig each book, take median fair prob."""
    game = _game([
        _market("h2h", [
            _outcome("Home", [
                _price("draftkings", -110),
                _price("fanduel", -108),
                _price("betonlineag", -112),
            ]),
            _outcome("Away", [
                _price("draftkings", -110),
                _price("fanduel", -112),
                _price("betonlineag", -108),
            ]),
        ])
    ])
    ops = scan_all_ev([game], now=NOW, min_ev_pct=-10)
    sources = {o["source"] for o in ops}
    assert sources == {"consensus"}
    assert all(o["anchor_book_count"] >= 2 for o in ops)


def test_consensus_requires_at_least_two_books():
    """Single book posting both sides → no consensus fallback."""
    game = _game([
        _market("h2h", [
            _outcome("Home", [_price("draftkings", 105)]),
            _outcome("Away", [_price("draftkings", -115)]),
        ])
    ])
    ops = scan_all_ev([game], now=NOW, min_ev_pct=-10)
    assert ops == []


def test_pinnacle_offered_side_is_excluded():
    """If pinnacle is the anchor, don't emit "Pinnacle EV X%" — that's
    fair by definition."""
    game = _game([
        _market("h2h", [
            _outcome("Home", [
                _price("pinnacle", 110),           # offered (would be +5% EV)
                _price("draftkings", 115),
            ]),
            _outcome("Away", [
                _price("pinnacle", -130),
                _price("draftkings", -130),
            ]),
        ])
    ])
    ops = scan_all_ev([game], now=NOW, min_ev_pct=-10)
    pinnacle_rows = [o for o in ops if o["book"] == "pinnacle"]
    assert pinnacle_rows == []
    # DK should still produce an EV row
    dk_rows = [o for o in ops if o["book"] == "draftkings"]
    assert len(dk_rows) >= 1


def test_stale_offered_price_dropped():
    game = _game([
        _market("h2h", [
            _outcome("Home", [
                _price("pinnacle", -110),
                _price("draftkings", 110, age_s=120),   # stale
            ]),
            _outcome("Away", [
                _price("pinnacle", -110),
                _price("draftkings", -110),
            ]),
        ])
    ])
    ops = scan_all_ev([game], now=NOW, min_ev_pct=-10)
    dk_home = [o for o in ops if o["book"] == "draftkings" and o["outcome_name"] == "Home"]
    assert dk_home == []


def test_longshot_cutoff_filters_long_prices():
    game = _game([
        _market("h2h", [
            _outcome("Home", [
                _price("pinnacle", -120),
                _price("draftkings", 1500),   # +1500 longshot
            ]),
            _outcome("Away", [
                _price("pinnacle", 105),
                _price("draftkings", 100),
            ]),
        ])
    ])
    ops = scan_all_ev([game], now=NOW, min_ev_pct=-10, max_longshot_american=800)
    dk_home = [o for o in ops if o["book"] == "draftkings" and o["outcome_name"] == "Home"]
    assert dk_home == []


def test_high_ev_marked_low_confidence():
    game = _game([
        _market("h2h", [
            _outcome("Home", [
                _price("pinnacle", -110),
                _price("draftkings", 500),  # way off market → huge paper EV
            ]),
            _outcome("Away", [
                _price("pinnacle", -110),
                _price("draftkings", -110),
            ]),
        ])
    ])
    ops = scan_all_ev([game], now=NOW, min_ev_pct=1.0)
    home = [o for o in ops if o["outcome_name"] == "Home" and o["book"] == "draftkings"]
    assert home and home[0]["confidence"] == "low"


def test_also_in_arb_flag_when_keys_match():
    game = _game([
        _market("h2h", [
            _outcome("Home", [
                _price("pinnacle", -110),
                _price("draftkings", 120),
            ]),
            _outcome("Away", [
                _price("pinnacle", -110),
                _price("draftkings", -110),
            ]),
        ])
    ])
    arb_keys = {("game1", "h2h", None)}
    ops = scan_all_ev([game], now=NOW, min_ev_pct=-10, arb_keys=arb_keys)
    dk = [o for o in ops if o["book"] == "draftkings" and o["outcome_name"] == "Home"]
    assert dk and dk[0]["also_in_arb"] is True


def test_three_way_markets_are_skipped():
    """3-way h2h markets (soccer, MLB period ties) are not emitted — the
    sports currently in scope don't use them and the product explicitly
    excludes them."""
    game = _game([
        _market("h2h_3_way", [
            _outcome("Home", [
                _price("pinnacle", 150),
                _price("draftkings", 180),
            ]),
            _outcome("Draw", [
                _price("pinnacle", 260),
                _price("draftkings", 280),
            ]),
            _outcome("Away", [
                _price("pinnacle", 200),
                _price("draftkings", 210),
            ]),
        ]),
        _market("h2h_3_way_1st_5_innings", [
            _outcome("Home", [_price("pinnacle", 150)]),
            _outcome("Draw", [_price("pinnacle", 260)]),
            _outcome("Away", [_price("pinnacle", 200)]),
        ]),
    ])
    ops = scan_all_ev([game], now=NOW, min_ev_pct=-100)
    assert ops == []


def test_alt_line_pairing_by_point_devigs_separately():
    """Alternate spreads at +3.5/-3.5 devig independently from +7.5/-7.5."""
    game = _game([
        _market("alternate_spreads", [
            _outcome("Home", [
                _price("pinnacle", -130, point=-3.5),
            ]),
            _outcome("Away", [
                _price("pinnacle", 110, point=3.5),
            ]),
            _outcome("Home", [
                _price("pinnacle", 180, point=-7.5),
                _price("draftkings", 220, point=-7.5),
            ]),
            _outcome("Away", [
                _price("pinnacle", -220, point=7.5),
                _price("draftkings", -240, point=7.5),
            ]),
        ])
    ])
    # This synthetic shape is what rows_to_games would produce when two
    # outcomes share a name — each (name, point) is a separate outcome entry
    # in our market's outcomes list. Scanner must handle that.
    # For this test we just want: scan doesn't crash + emits alt-spread rows.
    ops = scan_all_ev([game], now=NOW, min_ev_pct=-20)
    dk_rows = [o for o in ops if o["book"] == "draftkings"]
    # DK posted only the -7.5/+7.5 pair, so we should see rows at point=±7.5.
    assert dk_rows
    assert all(abs(o["point"]) == 7.5 for o in dk_rows if o["point"] is not None)


def test_sort_by_ev_desc():
    g1 = _game([_market("h2h", [
        _outcome("Home", [_price("pinnacle", -110), _price("draftkings", 110)]),
        _outcome("Away", [_price("pinnacle", -110), _price("draftkings", -110)]),
    ])], event_id="g1")
    g2 = _game([_market("h2h", [
        _outcome("Home", [_price("pinnacle", -110), _price("draftkings", 150)]),
        _outcome("Away", [_price("pinnacle", -110), _price("draftkings", -110)]),
    ])], event_id="g2")
    ops = scan_all_ev([g1, g2], now=NOW, min_ev_pct=-10)
    # Higher EV game should come first
    assert ops[0]["event_id"] == "g2"


def test_player_props_pair_per_player():
    """Two players' Over/Under rows must NOT pair across players. Each
    player's Over/Under pairs independently under the same market_key and
    point."""
    game = _game([
        _market("player_points", [
            _outcome("LeBron James Over",  [
                _price("pinnacle",   -110, point=25.5),
                _price("draftkings", +110, point=25.5),
            ]),
            _outcome("LeBron James Under", [
                _price("pinnacle",   -110, point=25.5),
                _price("draftkings", -110, point=25.5),
            ]),
            _outcome("Jayson Tatum Over",  [
                _price("pinnacle",   -120, point=28.5),
                _price("draftkings", +105, point=28.5),
            ]),
            _outcome("Jayson Tatum Under", [
                _price("pinnacle",   +100, point=28.5),
                _price("draftkings", -115, point=28.5),
            ]),
        ])
    ])
    ops = scan_all_ev([game], now=NOW, min_ev_pct=-20)
    # Both players' Over should emit EV rows (offered +110 / +105 vs
    # pinnacle-anchored fair 50/50 and 54.5/45.5).
    lebron = [o for o in ops if o["outcome_name"] == "LeBron James Over" and o["book"] == "draftkings"]
    tatum  = [o for o in ops if o["outcome_name"] == "Jayson Tatum Over"  and o["book"] == "draftkings"]
    assert len(lebron) == 1
    assert len(tatum) == 1
    # Different fair probs → different EVs
    assert abs(lebron[0]["fair_probability"] - 0.5) < 1e-6
    assert tatum[0]["fair_probability"] != pytest.approx(0.5, abs=0.01)


def test_player_prop_old_cache_rows_do_not_pair():
    """Pre-fix rows (outcome_name='Over'/'Under' without player prefix) must
    NOT cross-pair across players — they fall into distinct single-entry
    buckets and get skipped cleanly."""
    game = _game([
        _market("player_points", [
            # Pre-fix bare outcomes — shouldn't pair
            _outcome("Over",  [_price("pinnacle", -110, point=25.5)]),
            _outcome("Under", [_price("pinnacle", -110, point=25.5)]),
        ])
    ])
    ops = scan_all_ev([game], now=NOW, min_ev_pct=-100)
    # No draftkings rows here so nothing to emit regardless — but critically,
    # this must not crash or produce cross-player ghosts.
    assert ops == []


def test_max_results_caps_server_side():
    games = []
    for i in range(50):
        games.append(_game([
            _market("h2h", [
                _outcome("Home", [_price("pinnacle", -110), _price("draftkings", 115)]),
                _outcome("Away", [_price("pinnacle", -110), _price("draftkings", -115)]),
            ])
        ], event_id=f"g{i}"))
    ops = scan_all_ev(games, now=NOW, min_ev_pct=-10, max_results=10)
    assert len(ops) == 10
