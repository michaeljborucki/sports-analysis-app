from server.odds.best_odds import pick_best_price, median_american_odds


def test_pick_best_price_positive_odds_higher_is_better():
    prices = [("dk", 150), ("fd", 160), ("mgm", 145)]
    assert pick_best_price(prices) == ("fd", 160)


def test_pick_best_price_negative_odds_closer_to_zero_is_better():
    prices = [("dk", -150), ("fd", -140), ("mgm", -160)]
    assert pick_best_price(prices) == ("fd", -140)


def test_pick_best_price_mixed_signs():
    prices = [("dk", -110), ("fd", 105)]
    assert pick_best_price(prices) == ("fd", 105)


def test_pick_best_price_empty():
    assert pick_best_price([]) is None


def test_median_american_odds_odd_count():
    assert median_american_odds([-110, -115, -105]) == -110


def test_median_american_odds_even_count():
    result = median_american_odds([-110, -110])
    assert result == -110


def test_median_american_odds_empty_returns_none():
    assert median_american_odds([]) is None


# ──────────────────── A6: best_price_dict ────────────────────


def test_best_price_dict_picks_highest_payout():
    """Given 3 books at known American odds, returns the dict whose
    price gives the highest payout multiplier to the bettor."""
    from server.odds.best_odds import best_price_dict
    prices = [
        {"bookmaker_key": "draftkings", "price_american": -110},
        {"bookmaker_key": "fanduel",    "price_american": +120},  # best for bettor
        {"bookmaker_key": "betmgm",     "price_american": -120},
    ]
    result = best_price_dict(prices)
    assert result is not None
    assert result["bookmaker_key"] == "fanduel"
    assert result["price_american"] == 120


def test_best_price_dict_empty_returns_none():
    from server.odds.best_odds import best_price_dict
    assert best_price_dict([]) is None


def test_best_price_dict_preserves_full_dict():
    """The returned reference includes ALL keys from the original dict
    (point, fetched_at, etc.), not just bookmaker_key + price_american."""
    from server.odds.best_odds import best_price_dict
    prices = [
        {"bookmaker_key": "dk", "price_american": -110, "point": -2.5, "fetched_at": "ts1"},
        {"bookmaker_key": "fd", "price_american": +110, "point": -2.5, "fetched_at": "ts2"},
    ]
    result = best_price_dict(prices)
    assert result["point"] == -2.5
    assert result["fetched_at"] == "ts2"
