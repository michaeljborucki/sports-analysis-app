"""Regression test pinning the LLM prompt format.

The briefing string is the contract between ``briefing.build_briefing`` and the
LLM ensemble. Silent format drift (added whitespace, reordered fields, changed
numeric precision) can shift ensemble outputs without anyone noticing. This test
asserts byte-equality against a golden file.

If the test fails because you intentionally edited the template, eyeball the
diff and then copy the new output into ``tests/fixtures/golden_briefing.txt``.
Do NOT blindly regenerate the fixture.
"""
import os
from briefing import build_briefing


FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "golden_briefing.txt")


MATCH_DATA = {
    "tournament": "Madrid Open",
    "round": "QF",
    "surface": "clay",
    "indoor_outdoor": "outdoor",
    "best_of": 3,
    "player_a": {
        "name": "Carlos Alcaraz",
        "ranking": 2,
        "elo": 2180,
        "surface_elo": 2210,
        "season_record": "22-4",
        "surface_record": "10-1",
        "serve_stats": {
            "first_serve_pct": "65%", "first_serve_win_pct": "76%",
            "second_serve_win_pct": "55%", "ace_rate": "8", "df_rate": "2",
        },
        "return_stats": {"return_pts_won_pct": "42%", "bp_conversion_pct": "45%"},
        "hand": "R", "backhand": "two-handed", "height": "183cm", "age": 22,
        "days_since_last_match": 2,
        "recent_form": [
            {"tourney_date": "2026-04-15", "tourney_name": "Monte Carlo",
             "opponent": "Ruud", "score": "6-3 6-4", "surface": "clay"},
        ],
    },
    "player_b": {
        "name": "Jannik Sinner",
        "ranking": 1,
        "elo": 2200,
        "surface_elo": 2180,
        "season_record": "24-3",
        "surface_record": "9-2",
        "serve_stats": {
            "first_serve_pct": "63%", "first_serve_win_pct": "74%",
            "second_serve_win_pct": "54%", "ace_rate": "7", "df_rate": "2",
        },
        "return_stats": {"return_pts_won_pct": "41%", "bp_conversion_pct": "43%"},
        "hand": "R", "backhand": "two-handed", "height": "188cm", "age": 24,
        "days_since_last_match": 3,
        "recent_form": [
            {"tourney_date": "2026-04-14", "tourney_name": "Monte Carlo",
             "opponent": "Zverev", "score": "6-4 6-3", "surface": "clay"},
        ],
    },
    "head_to_head": {"overall": "5-4 Sinner", "surface": "3-2 Alcaraz"},
    "conditions": {
        "surface": "clay", "indoor_outdoor": "outdoor",
        "temperature": "22C", "wind": "light", "altitude": "660m", "session": "day",
    },
    "odds": {
        "moneyline": {"player_a": -130, "player_b": 110},
        "game_handicap": {
            "player_a_point": -2.5, "player_a_odds": -110,
            "player_b_point": 2.5, "player_b_odds": -110,
        },
        "total_games": {"line": 22.5, "over_odds": -110, "under_odds": -110},
        "implied_probs": {"player_a": 0.565, "player_b": 0.435},
    },
    "injuries": {"player_a": "None reported", "player_b": "None reported"},
}


def test_briefing_format_matches_golden():
    actual = build_briefing(MATCH_DATA)
    with open(FIXTURE_PATH) as f:
        expected = f.read()
    assert actual == expected, (
        "briefing template drift detected — review the diff and update "
        "tests/fixtures/golden_briefing.txt only if the change is intentional."
    )


def test_briefing_includes_all_required_sections():
    """Sanity guard: if the template is ever torn up, these must still appear."""
    brief = build_briefing(MATCH_DATA)
    for required in [
        "BETTING LINES:",
        "PLAYER PROFILES",
        "HEAD-TO-HEAD",
        "CONDITIONS",
        "INJURIES",
        "PREDICTION TASK",
        "MATCH WINNER",
        "GAME HANDICAP",
        "TOTAL GAMES",
    ]:
        assert required in brief, f"briefing missing required section: {required!r}"


def test_briefing_uses_player_names_not_placeholders():
    brief = build_briefing(MATCH_DATA)
    assert "Carlos Alcaraz" in brief
    assert "Jannik Sinner" in brief
    # Literal "TBD" placeholders should not appear when both players are named.
    assert "TBD" not in brief
