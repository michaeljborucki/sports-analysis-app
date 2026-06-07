"""Regression tests pinning Discord notify format.

``format_match_block`` emits the code-fenced block that ships to Discord
per match. Layout drift (column widths, header ordering, code-fence markers)
either breaks the visual grid or breaks downstream parsing of our own archive.
"""
import os

from notify.format import format_match_block


FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "golden_match_block.txt")


CANONICAL_PICKS = [
    {"game": "Carlos Alcaraz vs Jannik Sinner",
     "bet_type": "moneyline", "side": "player_a",
     "odds": -130, "sim_prob": 0.62, "edge": 0.055, "kelly_pct": 0.0096},
    {"game": "Carlos Alcaraz vs Jannik Sinner",
     "bet_type": "total_games", "side": "over 22.5",
     "odds": -110, "sim_prob": 0.60, "edge": 0.10, "kelly_pct": 0.015},
]


def test_format_match_block_matches_golden():
    actual = format_match_block("Carlos Alcaraz vs Jannik Sinner", CANONICAL_PICKS)
    with open(FIXTURE_PATH) as f:
        expected = f.read()
    assert actual == expected, (
        "Discord match-block format drift — review diff and update "
        "tests/fixtures/golden_match_block.txt only if intentional."
    )


def test_format_match_block_is_code_fenced():
    """Discord renders the block as monospace via triple backticks — must not regress."""
    out = format_match_block("A vs B", CANONICAL_PICKS)
    assert out.startswith("```\n")
    assert out.endswith("\n```")


def test_format_match_block_sorts_picks_by_edge_desc():
    """Higher-edge picks appear first in the rendered block."""
    out = format_match_block("Carlos Alcaraz vs Jannik Sinner", CANONICAL_PICKS)
    lines = out.splitlines()
    # Find the two pick lines (two-space leading + not a separator)
    pick_lines = [
        line for line in lines
        if line.startswith("  ") and "|" in line and "TYPE" not in line
    ]
    assert len(pick_lines) == 2
    # total_games (edge 0.10) should sort before moneyline (edge 0.055)
    assert "total_games" in pick_lines[0]
    assert "moneyline" in pick_lines[1]


def test_format_match_block_resolves_player_names_in_side():
    """'player_a' token in side must be replaced with the game's first name."""
    out = format_match_block("Carlos Alcaraz vs Jannik Sinner", CANONICAL_PICKS)
    assert "Carlos Alcaraz" in out
    assert "player_a" not in out  # token must be resolved, not leaked


# ==========================================================================
#  Match-start-time rendering (added 2026-04-23)
# ==========================================================================

def test_format_match_block_includes_time_when_start_time_present():
    """When picks carry ``start_time``, it renders in the match header."""
    picks_with_time = [
        {**p, "start_time": "2026-04-23T14:00:00Z"} for p in CANONICAL_PICKS
    ]
    out = format_match_block("Carlos Alcaraz vs Jannik Sinner", picks_with_time)
    # UTC 14:00 → Denver MT 8:00 AM (MDT during spring)
    assert "8:00 AM MT" in out
    # Separator (em-dash) appears between match and time
    assert "Carlos Alcaraz vs Jannik Sinner — " in out


def test_format_match_block_omits_time_suffix_when_start_time_missing():
    """Backward compat: picks without ``start_time`` produce the bare header."""
    # Canonical picks (no start_time) — header must have NO em-dash suffix
    out = format_match_block("Carlos Alcaraz vs Jannik Sinner", CANONICAL_PICKS)
    assert "Carlos Alcaraz vs Jannik Sinner — " not in out
    assert "Carlos Alcaraz vs Jannik Sinner\n----" in out


def test_format_start_time_local_parses_iso_z_suffix():
    from notify.format import format_start_time_local
    assert format_start_time_local("2026-04-23T14:00:00Z") == "8:00 AM MT"


def test_format_start_time_local_parses_iso_utc_offset():
    from notify.format import format_start_time_local
    assert format_start_time_local("2026-04-23T14:00:00+00:00") == "8:00 AM MT"


def test_format_start_time_local_handles_missing_or_invalid():
    from notify.format import format_start_time_local
    assert format_start_time_local("") == ""
    assert format_start_time_local(None) == ""  # type: ignore[arg-type]
    assert format_start_time_local("garbage") == ""


def test_format_start_time_local_shows_pm_for_evening_matches():
    """A 23:30 UTC match is 5:30 PM MT (in MDT) — confirms PM rendering."""
    from notify.format import format_start_time_local
    out = format_start_time_local("2026-04-23T23:30:00Z")
    assert "PM" in out
    assert "5:30" in out
