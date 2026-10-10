import pytest

from server.odds.devig import american_to_implied_prob, devig_two_way


def test_american_to_implied_prob_negative():
    assert abs(american_to_implied_prob(-110) - 0.5238) < 0.001


def test_american_to_implied_prob_positive():
    assert abs(american_to_implied_prob(150) - 0.4000) < 0.001


def test_devig_two_way_balanced():
    home, away = devig_two_way(-110, -110)
    assert abs(home - 0.5) < 0.001
    assert abs(away - 0.5) < 0.001


def test_devig_two_way_skewed():
    home, away = devig_two_way(-200, 170)
    assert home > away
    assert abs((home + away) - 1.0) < 0.0001


def test_american_to_implied_prob_is_cached():
    """Repeat calls on the same odds hit the LRU cache, not the math."""
    american_to_implied_prob.cache_clear()
    american_to_implied_prob(-110)
    american_to_implied_prob(-110)
    info = american_to_implied_prob.cache_info()
    assert info.hits >= 1



def test_power_devig_shrinks_longshots():
    """Power devig (2026-10-10): even markets unchanged, longshots get less
    than proportional scaling gives them."""
    from server.odds.devig import devig_two_way, devig_n_way
    a, b = devig_two_way(-110, -110)
    assert abs(a - 0.5) < 1e-12 and abs(b - 0.5) < 1e-12
    dog, fav = devig_two_way(600, -1000)
    assert abs(dog - 0.1047) < 5e-4 and abs(dog + fav - 1.0) < 1e-12   # proportional: 0.136
    probs = devig_n_way([150, 250, 200])
    assert abs(sum(probs) - 1.0) < 1e-12 and probs[0] > probs[2] > probs[1]
