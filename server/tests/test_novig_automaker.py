import pytest

from server.automaker.novig_maker import ev_at, kelly_qty, make_price


def test_make_price_is_one_tick_above_own_best_bid():
    assert make_price({"own_best_bid": [0.40, 100], "other_best_bid": [0.50, 50]}) == 0.405


def test_make_price_joins_bid_on_one_tick_spread():
    # Take price for this side = 1 - 0.595 = 0.405, so 0.405 would cross.
    assert make_price({"own_best_bid": [0.40, 100], "other_best_bid": [0.595, 50]}) == 0.40


def test_make_price_needs_a_bid_to_improve_on():
    assert make_price({"own_best_bid": None, "other_best_bid": [0.5, 10]}) is None


def test_ev_is_on_the_make_price():
    assert ev_at(0.52, 0.50) == pytest.approx(0.04)


def test_half_kelly_sizing_in_contracts():
    # f = (0.52 - 0.50) / 0.50 = 4%; half Kelly of $2000 = $40 -> 8000 contracts at 0.50.
    qty, cost = kelly_qty(0.52, 0.50, 2000.0)
    assert qty == 8000
    assert cost == pytest.approx(40.0)


def test_no_edge_no_size():
    assert kelly_qty(0.48, 0.50, 2000.0) == (0, 0.0)


def _hedge_maker(positions):
    import asyncio
    from server.automaker import novig_maker as nm

    class Wrapped:
        def __init__(self, m):
            self.m = m
            self.hedge_ids = m.hedge_ids

        async def hedge_plan(self, cands, orders, cutoff):
            return self.m.hedge_plan(cands, orders, cutoff, positions)

    m = nm.Maker.__new__(nm.Maker)
    m.hedge_ids, m.log = {}, lambda *a, **k: None
    return Wrapped(m), asyncio


def _cands(bid_a, bid_b):
    base = {"market_id": "M", "commence_time": "2099-01-01T00:00:00+00:00"}
    return {
        "A": dict(base, outcome_id="A", other_outcome_id="B",
                  own_best_bid=[bid_a, 100], other_best_bid=[bid_b, 100]),
        "B": dict(base, outcome_id="B", other_outcome_id="A",
                  own_best_bid=[bid_b, 100], other_best_bid=[bid_a, 100]),
    }


def test_hedge_posts_one_tick_above_other_side_when_arb_clears_1pct():
    from datetime import datetime, timezone
    # Filled 1000 contracts of A at 0.50 ($5.00). B best bid 0.45 -> hedge at 0.455.
    m, aio = _hedge_maker([{"marketId": "M", "outcomeId": "A", "qty": 1000, "cost": "5.00000"}])
    want = aio.run(m.hedge_plan(_cands(0.52, 0.45), [], datetime.now(timezone.utc)))
    assert want["B"]["price"] == 0.455
    assert want["B"]["qty"] == 1000
    assert want["B"]["roi"] == pytest.approx(1 / 0.955 - 1)


def test_no_hedge_below_1pct_arb():
    from datetime import datetime, timezone
    # A at 0.50, B best bid 0.49 -> hedge 0.495 -> pair 0.995 -> 0.5% < 1%.
    m, aio = _hedge_maker([{"marketId": "M", "outcomeId": "A", "qty": 1000, "cost": "5.00000"}])
    assert aio.run(m.hedge_plan(_cands(0.50, 0.49), [], datetime.now(timezone.utc))) == {}


def test_hedge_does_not_outbid_itself():
    from datetime import datetime, timezone
    m, aio = _hedge_maker([{"marketId": "M", "outcomeId": "A", "qty": 1000, "cost": "5.00000"}])
    m.hedge_ids["h1"] = {}
    ours = [{"orderId": "h1", "outcomeId": "B", "price": "0.455", "qty": 1000}]
    want = aio.run(m.hedge_plan(_cands(0.52, 0.455), ours, datetime.now(timezone.utc)))
    assert want["B"]["price"] == 0.455   # we are the best bid: hold, don't ratchet up


def test_order_is_target_minus_what_already_filled():
    # Target: half Kelly f=4% of $2000 = $40. Already filled $10 -> post $30.
    qty, cost = kelly_qty(0.52, 0.50, 2000.0, held=10.0)
    assert cost == pytest.approx(30.0)


def test_no_order_once_filled_stake_meets_target():
    # Target $40, already filled $45 (target dropped since) -> post nothing.
    assert kelly_qty(0.52, 0.50, 2000.0, held=45.0) == (0, 0.0)
