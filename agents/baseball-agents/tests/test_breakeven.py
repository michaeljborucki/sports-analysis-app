import pytest
from scrapers.odds import prob_to_american, american_to_implied_prob


def test_breakeven_at_50_pct():
    assert prob_to_american(0.5) == -100


def test_breakeven_dog_side():
    assert prob_to_american(0.45) == 122
    assert prob_to_american(0.40) == 150
    assert prob_to_american(0.333) == 200


def test_breakeven_favorite_side():
    assert prob_to_american(0.55) == -122
    assert prob_to_american(0.60) == -150
    assert prob_to_american(0.667) == -200


def test_breakeven_roundtrip():
    """Implied prob of breakeven odds should match the input prob."""
    for p in [0.10, 0.25, 0.40, 0.50, 0.55, 0.65, 0.80, 0.90]:
        odds = prob_to_american(p)
        back = american_to_implied_prob(odds)
        assert abs(back - p) < 0.005, f"prob={p} odds={odds} back={back}"


def test_breakeven_rejects_invalid():
    with pytest.raises(ValueError):
        prob_to_american(0.0)
    with pytest.raises(ValueError):
        prob_to_american(1.0)
    with pytest.raises(ValueError):
        prob_to_american(-0.1)
    with pytest.raises(ValueError):
        prob_to_american(1.5)
