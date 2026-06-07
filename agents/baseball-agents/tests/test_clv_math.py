"""Regression tests for tracker.compute_clv.

CLV math has subtle sign-flip cases:
- favorite/favorite (-/-): better price is closer to 0
- dog/dog (+/+): better price is more positive
- mixed sign: line crossed the zero point (use decimal diff)

Pin every combination so refactors don't silently invert CLV.
"""
import pytest
from tracker import compute_clv


# ---------------------------------------------------------------------------
# Same sign — both favorites
# ---------------------------------------------------------------------------

def test_both_favorites_we_got_better_price():
    """Bet at -120, closed at -150 → we got the better number → positive CLV."""
    clv = compute_clv(bet_odds=-120, close_odds=-150)
    assert clv["clv_cents"] == 30
    assert clv["clv_pct"] > 0


def test_both_favorites_we_got_worse_price():
    """Bet at -150, closed at -120 → close moved toward us → negative CLV."""
    clv = compute_clv(bet_odds=-150, close_odds=-120)
    assert clv["clv_cents"] == -30
    assert clv["clv_pct"] < 0


def test_both_favorites_no_movement():
    clv = compute_clv(bet_odds=-110, close_odds=-110)
    assert clv["clv_cents"] == 0
    assert clv["clv_pct"] == 0.0


# ---------------------------------------------------------------------------
# Same sign — both dogs
# ---------------------------------------------------------------------------

def test_both_dogs_we_got_better_price():
    """Bet at +150, closed at +120 → we got more upside → positive CLV."""
    clv = compute_clv(bet_odds=+150, close_odds=+120)
    assert clv["clv_cents"] == 30
    assert clv["clv_pct"] > 0


def test_both_dogs_we_got_worse_price():
    """Bet at +120, closed at +150 → close moved away from us → negative CLV."""
    clv = compute_clv(bet_odds=+120, close_odds=+150)
    assert clv["clv_cents"] == -30
    assert clv["clv_pct"] < 0


def test_both_dogs_no_movement():
    clv = compute_clv(bet_odds=+105, close_odds=+105)
    assert clv["clv_cents"] == 0
    assert clv["clv_pct"] == 0.0


# ---------------------------------------------------------------------------
# Mixed signs — line crossed (bet was dog → close became favorite, or vice versa)
# ---------------------------------------------------------------------------

def test_bet_dog_close_favorite():
    """Bet at +110, closed at -110 → we caught the line moving against us → +CLV."""
    clv = compute_clv(bet_odds=+110, close_odds=-110)
    assert clv["clv_pct"] > 0  # decimal 2.10 / 1.91 > 1 → positive
    assert clv["clv_cents"] > 0


def test_bet_favorite_close_dog():
    """Bet at -110, closed at +110 → we got the worst of the move → -CLV."""
    clv = compute_clv(bet_odds=-110, close_odds=+110)
    assert clv["clv_pct"] < 0
    assert clv["clv_cents"] < 0


# ---------------------------------------------------------------------------
# Output schema contract
# ---------------------------------------------------------------------------

def test_output_keys():
    clv = compute_clv(bet_odds=-120, close_odds=-130)
    assert set(clv.keys()) == {"clv_cents", "clv_pct"}


def test_output_types():
    clv = compute_clv(bet_odds=-120, close_odds=-130)
    assert isinstance(clv["clv_cents"], int)
    assert isinstance(clv["clv_pct"], float)


# ---------------------------------------------------------------------------
# Realistic snapshot — pin known values from production data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bet_odds,close_odds,expected_cents", [
    (-101, -104, 3),     # fav/fav small move toward us
    (+150, +152, -2),    # dog/dog small move away
    (-200, -195, -5),    # fav/fav close moved toward us → -CLV
    (+170, +166, 4),     # dog/dog close moved against us → +CLV
])
def test_realistic_clv_cents_pin(bet_odds, close_odds, expected_cents):
    clv = compute_clv(bet_odds, close_odds)
    assert clv["clv_cents"] == expected_cents
