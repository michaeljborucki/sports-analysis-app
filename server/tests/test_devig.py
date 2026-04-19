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
