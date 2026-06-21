"""Tests for canonicalize_spread_outcome (M4)."""


def test_negative_point_passes_through_unchanged():
    """The favored team's view (negative point) is already canonical."""
    from server.odds.books.spread_orientation import canonicalize_spread_outcome
    name, point = canonicalize_spread_outcome(
        "Boston Celtics", -2.5, "Boston Celtics", "Miami Heat",
    )
    assert name == "Boston Celtics"
    assert point == -2.5


def test_positive_point_flips_to_other_team_negated():
    """The underdog's view (positive point) gets canonicalized: the
    outcome becomes the OTHER team with the point negated."""
    from server.odds.books.spread_orientation import canonicalize_spread_outcome
    # Heat +2.5 → Celtics -2.5
    name, point = canonicalize_spread_outcome(
        "Miami Heat", 2.5, "Boston Celtics", "Miami Heat",
    )
    assert name == "Boston Celtics"
    assert point == -2.5


def test_pickem_zero_passes_through_unchanged():
    """Pick'em (point = 0) has no orientation; pass through."""
    from server.odds.books.spread_orientation import canonicalize_spread_outcome
    name, point = canonicalize_spread_outcome(
        "Miami Heat", 0.0, "Boston Celtics", "Miami Heat",
    )
    assert name == "Miami Heat"
    assert point == 0.0


def test_idempotent_on_re_application():
    """Re-applying canonicalize_spread_outcome produces the same result."""
    from server.odds.books.spread_orientation import canonicalize_spread_outcome
    first = canonicalize_spread_outcome(
        "Miami Heat", 2.5, "Boston Celtics", "Miami Heat",
    )
    second = canonicalize_spread_outcome(
        first[0], first[1], "Boston Celtics", "Miami Heat",
    )
    assert second == first


def test_unknown_team_passes_through():
    """If outcome_name matches neither home nor away (e.g., a typo or
    unresolved alias), pass through unchanged — never silently swap to
    the wrong team."""
    from server.odds.books.spread_orientation import canonicalize_spread_outcome
    name, point = canonicalize_spread_outcome(
        "Unknown Team", 2.5, "Boston Celtics", "Miami Heat",
    )
    assert name == "Unknown Team"
    assert point == 2.5


def test_is_spread_market_helper():
    """The market_key dispatcher recognizes all spread-family keys."""
    from server.odds.books.spread_orientation import is_spread_market
    assert is_spread_market("spreads") is True
    assert is_spread_market("alternate_spreads") is True
    assert is_spread_market("spreads_h1") is True
    assert is_spread_market("alternate_spreads_1st_5_innings") is True
    assert is_spread_market("h2h") is False
    assert is_spread_market("totals") is False
    assert is_spread_market("alternate_totals") is False
