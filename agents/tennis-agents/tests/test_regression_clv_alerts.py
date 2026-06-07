"""Regression tests pinning CLV presentation in the grades Discord channel.

CLV is the one signal you can't fake — surfacing it in the daily grades alert
is how you spot model regressions months before ROI shows it. These tests pin:

1. Per-bet CLV column in the grade match block (exact format).
2. Header aggregate (CLV avg, beat/lost/flat counts, untracked bucket).
3. ``_format_clv_cents`` edge cases (missing, nan, garbage).
4. ``_aggregate_clv`` counting semantics.
5. ``send_grade_notifications`` backfill hook (fetches CLV at notify-time if
   the bet row in bets.csv lacks it).
"""
import os

import pytest

from notify.format import (
    format_grade_match_block, format_grade_header,
    _format_clv_cents, _aggregate_clv,
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
GOLDEN_MATCH_BLOCK = os.path.join(FIXTURES_DIR, "golden_grade_match_block.txt")
GOLDEN_HEADER = os.path.join(FIXTURES_DIR, "golden_grade_header.txt")


# Canonical graded-pick fixture: covers every CLV state we want to show.
# +CLV (beat), -CLV (lost), flat CLV (exactly 0), and untracked (no close).
def _canonical_picks():
    return [
        {"date": "2026-04-19", "game": "Carlos Alcaraz vs Jannik Sinner",
         "bet_type": "moneyline", "side": "player_a", "odds": -130,
         "result": "W", "profit": 1.0,
         "close_odds": -150, "close_prob": 0.60, "clv_cents": 20, "clv_pct": 0.0615},
        {"date": "2026-04-19", "game": "Carlos Alcaraz vs Jannik Sinner",
         "bet_type": "total_games", "side": "over 22.5", "odds": -110,
         "result": "L", "profit": -1.1,
         "close_odds": -90, "close_prob": 0.47, "clv_cents": -20, "clv_pct": -0.0952},
        {"date": "2026-04-19", "game": "Iga Swiatek vs Coco Gauff",
         "bet_type": "game_handicap", "side": "player_b 2.5", "odds": -110,
         "result": "W", "profit": 1.0,
         "close_odds": -110, "close_prob": 0.524, "clv_cents": 0, "clv_pct": 0.0},
        {"date": "2026-04-19", "game": "Iga Swiatek vs Coco Gauff",
         "bet_type": "moneyline", "side": "player_a", "odds": +120,
         "result": "L", "profit": -1.0,
         # No close captured → untracked. Empty strings mirror bets.csv values.
         "close_odds": "", "close_prob": "", "clv_cents": "", "clv_pct": ""},
    ]


# ==========================================================================
#  Per-bet CLV column
# ==========================================================================
def test_grade_match_block_includes_clv_column_header():
    out = format_grade_match_block("A vs B", _canonical_picks()[:1])
    assert "CLV" in out


def test_grade_match_block_matches_golden_beat_and_lost():
    """First match in the fixture: a +CLV winner and a -CLV loser."""
    picks = [p for p in _canonical_picks()
             if p["game"] == "Carlos Alcaraz vs Jannik Sinner"]
    actual = format_grade_match_block("Carlos Alcaraz vs Jannik Sinner", picks)
    with open(GOLDEN_MATCH_BLOCK) as f:
        expected = f.read()
    assert actual == expected, (
        "Grade match block drift — review diff and update "
        "tests/fixtures/golden_grade_match_block.txt only if intentional."
    )


def test_grade_match_block_flat_and_untracked_render_correctly():
    picks = [p for p in _canonical_picks()
             if p["game"] == "Iga Swiatek vs Coco Gauff"]
    out = format_grade_match_block("Iga Swiatek vs Coco Gauff", picks)
    # Flat CLV renders as "+0"
    assert "    +0" in out or "   +0" in out
    # Untracked renders as "n/a" (not empty or 0)
    assert "n/a" in out


# ==========================================================================
#  _format_clv_cents edge cases
# ==========================================================================
@pytest.mark.parametrize("bet,expected", [
    ({"clv_cents": 20},        " +20"),
    ({"clv_cents": -20},       " -20"),
    ({"clv_cents": 0},         "  +0"),
    ({"clv_cents": 100},       "+100"),
    ({"clv_cents": -100},      "-100"),
    ({"clv_cents": ""},        "  n/a"),
    ({"clv_cents": "nan"},     "  n/a"),
    ({"clv_cents": "NaN"},     "  n/a"),
    ({"clv_cents": None},      "  n/a"),
    ({},                       "  n/a"),
    ({"clv_cents": "garbage"}, "  n/a"),
    # Strings that parse as numbers should work (pandas sometimes hands us strings)
    ({"clv_cents": "20"},      " +20"),
    ({"clv_cents": "-20"},     " -20"),
])
def test_format_clv_cents(bet, expected):
    assert _format_clv_cents(bet) == expected


# ==========================================================================
#  _aggregate_clv counting
# ==========================================================================
def test_aggregate_clv_canonical_fixture():
    agg = _aggregate_clv(_canonical_picks())
    assert agg == {
        "beat": 1, "lost": 1, "flat": 1, "untracked": 1,
        "tracked": 3, "avg_pct": -1.1,  # (6.15 + -9.52 + 0) / 3 = -1.12, ×1 = -1.1
    }


def test_aggregate_clv_empty_list():
    assert _aggregate_clv([]) == {
        "beat": 0, "lost": 0, "flat": 0, "untracked": 0,
        "tracked": 0, "avg_pct": 0.0,
    }


def test_aggregate_clv_all_untracked():
    bets = [{"clv_cents": ""}, {"clv_cents": "nan"}, {}]
    agg = _aggregate_clv(bets)
    assert agg["tracked"] == 0
    assert agg["untracked"] == 3
    assert agg["avg_pct"] == 0.0


# ==========================================================================
#  Grade header aggregate line
# ==========================================================================
def test_grade_header_matches_golden():
    actual = format_grade_header("2026-04-19", _canonical_picks())
    with open(GOLDEN_HEADER) as f:
        expected = f.read()
    assert actual == expected, (
        "Grade header drift — review diff and update "
        "tests/fixtures/golden_grade_header.txt only if intentional."
    )


def test_grade_header_includes_clv_avg():
    out = format_grade_header("2026-04-19", _canonical_picks())
    assert "CLV avg" in out


def test_grade_header_includes_untracked_count():
    out = format_grade_header("2026-04-19", _canonical_picks())
    assert "1 untracked" in out


def test_grade_header_per_type_includes_clv():
    out = format_grade_header("2026-04-19", _canonical_picks())
    # moneyline has 2 bets, one +CLV (+6.15%) and one untracked.
    # Average of tracked = 6.15, rounded 1dp = 6.2
    assert "CLV +6.2%" in out or "CLV +6.1%" in out


def test_grade_header_omits_clv_line_when_no_bets_tracked():
    """If every bet is untracked OR there are no bets, the CLV line should still
    render gracefully (showing 'avg 0.0% · N untracked' or just omit)."""
    bets_untracked = [
        {"bet_type": "moneyline", "side": "x", "odds": -110,
         "result": "W", "profit": 1.0, "clv_cents": ""},
    ]
    out = format_grade_header("2026-04-19", bets_untracked)
    # Untracked-only case should mention untracked or show 0.0%
    assert "untracked" in out or "0.0%" in out


# ==========================================================================
#  CLV backfill hook in send_grade_notifications
# ==========================================================================
def test_send_grade_notifications_backfills_missing_clv(monkeypatch, tmp_path):
    """If a graded bet is missing close_odds in bets.csv, the notifier should
    call lookup_clv and populate the in-memory pick before formatting."""
    import pandas as pd

    from notify import grades as grades_mod
    from config import DATA_DIR

    # Stage a bets.csv with one graded bet missing CLV
    bets_csv = tmp_path / "bets.csv"
    pd.DataFrame([{
        "date": "2026-04-19", "start_time": "", "game": "A vs B",
        "bet_type": "moneyline", "side": "player_a",
        "odds": -120, "sim_prob": 0.60, "sim_prob_raw": 0.60,
        "market_prob": 0.55, "edge": 0.05, "kelly_pct": 0.01,
        "result": "W", "profit": 1.0,
        "close_odds": "", "close_prob": "", "clv_cents": "", "clv_pct": "",
    }]).to_csv(bets_csv, index=False)

    # Redirect load_bets to read our stage
    monkeypatch.setattr(grades_mod, "load_bets",
                        lambda: pd.read_csv(bets_csv))

    # Fake lookup_clv — only called because the bet is missing CLV
    calls = []
    def fake_lookup_clv(bet):
        calls.append(bet.get("game"))
        return {"close_odds": -140, "close_prob": 0.58, "clv_cents": 20, "clv_pct": 0.08}

    # tracker is imported lazily inside the backfill block
    import tracker as tracker_mod
    monkeypatch.setattr(tracker_mod, "lookup_clv", fake_lookup_clv)

    # Stub out the actual Discord send so we don't hit the network
    monkeypatch.setattr(grades_mod, "send_discord", lambda url, msgs: len(msgs))

    # Minimal alerts config allowing moneyline and enabling grades channel
    def fake_load_alerts_config(path=None):
        return {
            "bet_types": ["moneyline", "game_handicap", "total_games"],
            "discord_grades": {"enabled": True, "webhook_url": "https://example/grades"},
            "discord_summary": {"enabled": False, "webhook_url": ""},
        }
    monkeypatch.setattr(grades_mod, "load_alerts_config", fake_load_alerts_config)

    # Use a throwaway sent-log so we don't depend on state from the real DATA_DIR
    sent_log = tmp_path / "grade_notifications_sent.json"
    monkeypatch.setattr(grades_mod, "SENT_LOG_PATH", str(sent_log))

    result = grades_mod.send_grade_notifications("2026-04-19")

    assert "A vs B" in calls, "lookup_clv should have been called for the untracked bet"
    assert result["grades_sent"] >= 1


def test_send_grade_notifications_skips_backfill_when_clv_already_present(monkeypatch, tmp_path):
    """If close_odds is already populated, no lookup_clv call should happen."""
    import pandas as pd

    from notify import grades as grades_mod

    bets_csv = tmp_path / "bets.csv"
    pd.DataFrame([{
        "date": "2026-04-19", "start_time": "", "game": "A vs B",
        "bet_type": "moneyline", "side": "player_a",
        "odds": -120, "sim_prob": 0.60, "sim_prob_raw": 0.60,
        "market_prob": 0.55, "edge": 0.05, "kelly_pct": 0.01,
        "result": "W", "profit": 1.0,
        "close_odds": -140, "close_prob": 0.58, "clv_cents": 20, "clv_pct": 0.08,
    }]).to_csv(bets_csv, index=False)

    monkeypatch.setattr(grades_mod, "load_bets",
                        lambda: pd.read_csv(bets_csv))

    calls = []
    def fake_lookup_clv(bet):
        calls.append(bet.get("game"))
        return None

    import tracker as tracker_mod
    monkeypatch.setattr(tracker_mod, "lookup_clv", fake_lookup_clv)

    monkeypatch.setattr(grades_mod, "send_discord", lambda url, msgs: len(msgs))
    monkeypatch.setattr(grades_mod, "load_alerts_config",
                        lambda path=None: {
                            "bet_types": ["moneyline"],
                            "discord_grades": {"enabled": True, "webhook_url": "https://example/grades"},
                            "discord_summary": {"enabled": False, "webhook_url": ""},
                        })
    monkeypatch.setattr(grades_mod, "SENT_LOG_PATH", str(tmp_path / "sent.json"))

    grades_mod.send_grade_notifications("2026-04-19")
    assert calls == [], "lookup_clv should NOT be called when CLV is already stored"
