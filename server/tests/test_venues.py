"""Opt-in virtual books (novig_maker) and cross-venue pairing."""
from server.odds.arbitrage import best_cross_venue_pair
from server.odds.normalize import _link_maker_counterparts
from server.odds.venues import book_allowed, venue


def _p(book, price):
    return {"bookmaker_key": book, "price_american": price}


def test_opt_in_book_requires_explicit_filter():
    assert not book_allowed("novig_maker", None)
    assert not book_allowed("novig_maker", {"novig", "draftkings"})
    assert book_allowed("novig_maker", {"novig_maker"})
    assert book_allowed("draftkings", None)
    assert venue("novig_maker") == "novig"


def test_pairing_skips_maker_vs_take_on_same_venue():
    a = {"prices": [_p("novig_maker", 120), _p("draftkings", 105)]}
    b = {"prices": [_p("novig", -105), _p("fanduel", -110)]}
    books = {"novig", "novig_maker", "draftkings", "fanduel"}
    pa, pb = best_cross_venue_pair(a, b, books)
    # novig_maker +120 vs novig -105 is one venue; the best legal pair is
    # maker +120 vs FanDuel -110 (lower total than DK +105 vs novig -105).
    assert (pa["bookmaker_key"], pb["bookmaker_key"]) == ("novig_maker", "fanduel")


def test_pairing_without_opt_in_books_is_unchanged():
    a = {"prices": [_p("novig_maker", 150), _p("draftkings", 105)]}
    b = {"prices": [_p("draftkings", -110), _p("fanduel", -120)]}
    # Filter omits novig_maker → it's invisible; DK vs DK is same book → None,
    # exactly the pre-existing behavior.
    assert best_cross_venue_pair(a, b, None) is None


def test_counterparts_link_take_and_maker():
    prices = [_p("novig", -135), _p("novig_maker", -128), _p("draftkings", -140)]
    _link_maker_counterparts(prices)
    assert prices[0]["counterpart_price_american"] == -128
    assert prices[1]["counterpart_price_american"] == -135
    assert "counterpart_price_american" not in prices[2]


def _h2h_game(a_prices, b_prices):
    return {
        "event_id": "e", "home_team": "H", "away_team": "A",
        "commence_time": "2026-10-14T00:00:00Z",
        "markets": [{"market_key": "h2h", "outcomes": [
            {"outcome_name": "H", "prices": a_prices},
            {"outcome_name": "A", "prices": b_prices},
        ]}],
    }


def test_promo_scanners_hedge_at_maker_price_when_named():
    from server.odds.free_bet import scan_all_free_bets
    from server.odds.profit_boost import scan_all_profit_boost

    a = [_p("coral33", 200), _p("novig", 190)]
    b = [_p("novig", -240), _p("novig_maker", -215), _p("fanduel", -250)]
    _link_maker_counterparts(b)
    g = _h2h_game(a, b)
    books = {"coral33", "fanduel", "novig", "novig_maker"}

    fb = scan_all_free_bets([g], hedge_books_filter=books,
                            free_bet_books_filter={"coral33"})
    pb = scan_all_profit_boost([g], hedge_books_filter=books,
                               boost_books_filter={"coral33"}, boost_pct=30)
    for op in (fb[0], pb[0]):
        assert op["hedge_leg"]["book"] == "novig_maker"
        assert op["hedge_leg"]["counterpart_price_american"] == -240

    # Without novig_maker in the filter, the maker quote stays invisible.
    take_books = books - {"novig_maker"}
    fb_take = scan_all_free_bets([g], hedge_books_filter=take_books,
                                 free_bet_books_filter={"coral33"})
    assert fb_take[0]["hedge_leg"]["book"] == "novig"


def test_promo_scanners_never_pair_novig_take_with_novig_maker():
    from server.odds.free_bet import scan_all_free_bets
    from server.odds.profit_boost import scan_all_profit_boost

    # Only legal pairings are same-venue Novig take vs Novig maker → none.
    g = _h2h_game([_p("novig", 200)], [_p("novig_maker", -150)])
    books = {"novig", "novig_maker"}
    assert scan_all_free_bets([g], hedge_books_filter=books) == []
    assert scan_all_profit_boost([g], hedge_books_filter=books, boost_pct=50) == []


def test_promo_leg_never_lands_on_maker_quote():
    from server.odds.free_bet import scan_all_free_bets
    from server.odds.profit_boost import scan_all_profit_boost

    g = _h2h_game([_p("novig_maker", 300)], [_p("fanduel", -150)])
    books = {"novig_maker", "fanduel"}
    for op in scan_all_free_bets([g], hedge_books_filter=books):
        assert op["free_leg"]["book"] != "novig_maker"
    for op in scan_all_profit_boost([g], hedge_books_filter=books, boost_pct=50):
        assert op["boost_leg"]["book"] != "novig_maker"
