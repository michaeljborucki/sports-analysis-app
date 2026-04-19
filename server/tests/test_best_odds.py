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
