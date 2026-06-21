"""Tests for max_stake_dollars propagation through the arb scanner."""
from server.odds.arbitrage import scan_all_arbs


def _game_with_two_books(
    market_kind: str, side_a_price: int, side_b_price: int,
    side_a_book: str, side_b_book: str,
    side_a_size: float | None, side_b_size: float | None,
    point: float | None = None,
):
    """Construct a one-event game dict that yields exactly one h2h arb
    opportunity between two distinct books."""
    return {
        "sport_key": "nba", "event_id": "e1",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": "2026-06-21T19:00:00+00:00",
        "is_live": False, "stale_seconds": 0,
        "markets": [{
            "market_key": market_kind,
            "outcomes": [
                {
                    "outcome_name": "BOS",
                    "prices": [{
                        "bookmaker_key": side_a_book,
                        "price_american": side_a_price,
                        "point": point,
                        "fetched_at": "2026-06-21T19:00:00+00:00",
                        "max_stake_dollars": side_a_size,
                    }],
                },
                {
                    "outcome_name": "MIA",
                    "prices": [{
                        "bookmaker_key": side_b_book,
                        "price_american": side_b_price,
                        "point": -point if point is not None else None,
                        "fetched_at": "2026-06-21T19:00:00+00:00",
                        "max_stake_dollars": side_b_size,
                    }],
                },
            ],
        }],
    }


def test_each_side_carries_its_max_stake():
    """An h2h arb between Polymarket ($50) and DK (None) yields:
    sides[0].max_stake_dollars == 50, sides[1].max_stake_dollars is None."""
    game = _game_with_two_books(
        "h2h", side_a_price=+200, side_b_price=-150,
        side_a_book="polymarket", side_b_book="draftkings",
        side_a_size=50.0, side_b_size=None,
    )
    opps = scan_all_arbs([game], books_filter=None)
    assert len(opps) == 1
    side_a = opps[0]["sides"][0]
    side_b = opps[0]["sides"][1]
    assert side_a["max_stake_dollars"] == 50.0
    assert side_b["max_stake_dollars"] is None


def test_max_total_stake_is_none_when_any_leg_is_none():
    """A sportsbook leg has unknown depth → no overall clamp."""
    game = _game_with_two_books(
        "h2h", +200, -150, "polymarket", "draftkings", 50.0, None,
    )
    opps = scan_all_arbs([game], books_filter=None)
    assert opps[0]["max_total_stake_dollars"] is None


def test_max_total_stake_clamps_to_binding_leg():
    """Both legs have depth → max total = min over legs of size/stake_pct."""
    # +110 / +110 is a tight arb (total implied 0.952, ROI 5%).
    # By symmetry stake_pct = 50/50; binding leg = polymarket at $50,
    # so max_total = $50 / 0.5 = $100.
    game = _game_with_two_books(
        "h2h", +110, +110, "polymarket", "kalshi", 50.0, 500.0,
    )
    opps = scan_all_arbs([game], books_filter=None)
    assert len(opps) == 1
    assert opps[0]["max_total_stake_dollars"] == 100.0
