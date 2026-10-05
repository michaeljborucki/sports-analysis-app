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
