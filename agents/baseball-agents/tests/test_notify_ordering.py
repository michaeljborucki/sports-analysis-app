"""Bet-type ordering in Discord notifications (2026-05-12).

The grades-header and season-totals messages were previously sorted by
descending frequency, which put `batter_*` props at the top on heavy
prop days and buried the mainlines the operator actually cares about.

New required order in any per-bet-type breakdown:
  1. moneyline
  2. run_line
  3. total
  4. nrfi
  5. team_total_home
  6. team_total_away
  7. everything else (alphabetical for determinism)
"""
from notify.format import format_grade_header, format_season_summary


def _bet(bt: str, side: str = "home", result: str = "W", odds: int = -110):
    return {
        "bet_type": bt,
        "side": side,
        "odds": odds,
        "result": result,
        "clv_cents": "",
    }


SAMPLE_BETS = [
    _bet("batter_total_bases", "Alice under 0.5", "W", 130),
    _bet("nrfi", "NRFI", "L", -110),
    _bet("pitcher_strikeouts", "Bob under 4.5", "W", -110),
    _bet("moneyline", "home", "W", -130),
    _bet("team_total_away", "away under 3.5", "L", -110),
    _bet("run_line", "home -1.5", "W", 140),
    _bet("total", "under 8.0", "W", -110),
    _bet("team_total_home", "home over 4.5", "W", 100),
    _bet("batter_hits", "Carol under 0.5", "L", 180),
]


def _bet_type_line_order(msg: str) -> list[str]:
    """Return the bet types from breakdown lines, in their appearance order."""
    out = []
    for line in msg.splitlines():
        s = line.strip()
        if not s.startswith("•"):
            continue
        # Pattern: "• `<bet_type>...`  ..."
        # Extract the first backtick-delimited token.
        first_tick = s.find("`")
        second_tick = s.find("`", first_tick + 1)
        if first_tick < 0 or second_tick < 0:
            continue
        bt = s[first_tick + 1:second_tick].strip()
        out.append(bt)
    return out


EXPECTED_PREFIX = [
    "moneyline",
    "run_line",
    "total",
    "nrfi",
    "team_total_home",
    "team_total_away",
]


def test_format_grade_header_uses_required_order():
    msg = format_grade_header("2026-05-12", SAMPLE_BETS)
    order = _bet_type_line_order(msg)
    # First six lines are the mainline types in the exact required order.
    assert order[:6] == EXPECTED_PREFIX, f"got {order}"


def test_format_season_summary_uses_required_order():
    msg = format_season_summary("2026-05-12", SAMPLE_BETS)
    order = _bet_type_line_order(msg)
    assert order[:6] == EXPECTED_PREFIX, f"got {order}"


def test_props_appear_after_mainlines():
    """Anything not in the explicit list must come after team_total_away."""
    msg = format_season_summary("2026-05-12", SAMPLE_BETS)
    order = _bet_type_line_order(msg)
    # team_total_away index must be before every prop bet type.
    tta = order.index("team_total_away")
    for prop in ("batter_total_bases", "batter_hits", "pitcher_strikeouts"):
        assert order.index(prop) > tta, f"{prop} should come after team_total_away"


def test_unknown_bet_types_sorted_alphabetically():
    """Determinism: bet types outside the explicit list sort alphabetically."""
    msg = format_season_summary("2026-05-12", SAMPLE_BETS)
    order = _bet_type_line_order(msg)
    props_only = [bt for bt in order if bt not in EXPECTED_PREFIX]
    assert props_only == sorted(props_only), f"got {props_only}"


def test_partial_set_still_in_order():
    """Missing types in the explicit list don't shuffle the others."""
    bets = [
        _bet("moneyline", "home", "W"),
        _bet("nrfi", "NRFI", "L"),
        _bet("team_total_home", "home over 4.5", "W"),
    ]
    msg = format_grade_header("2026-05-12", bets)
    order = _bet_type_line_order(msg)
    assert order == ["moneyline", "nrfi", "team_total_home"]
