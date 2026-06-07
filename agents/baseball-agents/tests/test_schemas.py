"""Schema regression tests — pin CSV column lists.

If any of these assertions fail, the schema has drifted. Either:
  (a) the change is intentional → update the test AND every reader/writer of
      that file, or
  (b) the change is accidental → revert it.

These tests catch the worst class of bug: a subtle column rename that
silently breaks downstream code days later.
"""
import tracker
from scrapers import closing_lines as cl
from agents import analyzed_games as ag


# ---------------------------------------------------------------------------
# bets.csv — the source of truth for all logged bets
# ---------------------------------------------------------------------------

def test_bets_csv_columns():
    expected = [
        "date", "game", "game_time", "bet_type", "side", "odds", "sim_prob",
        "market_prob", "edge", "kelly_pct", "result", "profit",
        "close_odds", "close_prob", "clv_cents", "clv_pct",
    ]
    assert tracker.COLUMNS == expected


def test_bets_csv_required_columns_present():
    """Required for every reader: date, game, bet_type, side, odds."""
    required = {"date", "game", "bet_type", "side", "odds"}
    assert required.issubset(set(tracker.COLUMNS))


def test_bets_csv_clv_columns_present():
    """CLV columns are the contract between grader and analyst tools."""
    clv_cols = {"close_odds", "close_prob", "clv_cents", "clv_pct"}
    assert clv_cols.issubset(set(tracker.COLUMNS))


# ---------------------------------------------------------------------------
# closing_lines.csv — the CLV ground truth
# ---------------------------------------------------------------------------

def test_closing_lines_csv_columns():
    expected = [
        "date", "game", "market", "side", "line",
        "close_odds", "close_prob_devig", "captured_at", "player_name",
    ]
    assert cl.COLUMNS == expected


def test_closing_lines_player_name_required():
    """player_name column is the prop-vs-mainline differentiator. Removing
    it would silently break prop CLV lookup (mainlines would still work)."""
    assert "player_name" in cl.COLUMNS


def test_closing_lines_capture_window():
    """Capture window is a system-wide constant — changing it requires
    coordinating cron schedules and operator expectations."""
    assert cl.CAPTURE_WINDOW_MINUTES == (5, 30)


def test_closing_lines_prop_markets():
    """The PROP_MARKETS set is the contract for which markets get player_name
    treatment. Adding/removing requires coordinating with parsing + lookup."""
    expected = {
        "pitcher_strikeouts", "pitcher_earned_runs", "pitcher_outs", "pitcher_hits_allowed",
        "batter_total_bases", "batter_rbis", "batter_hits", "batter_runs_scored",
        "batter_hits_runs_rbis", "batter_strikeouts",
    }
    assert cl.PROP_MARKETS == expected


# ---------------------------------------------------------------------------
# analyzed_games.csv — pipeline state
# ---------------------------------------------------------------------------

def test_analyzed_games_columns():
    assert ag._COLUMNS == ["date", "game", "status", "analyzed_at"]


# ---------------------------------------------------------------------------
# tracker.PROP_BET_TYPES — must align with closing_lines.PROP_MARKETS
# ---------------------------------------------------------------------------

def test_prop_bet_types_align_with_prop_markets():
    """tracker._parse_bet_for_clv branches on PROP_BET_TYPES; closing_lines
    extracts PROP_MARKETS from raw event JSON. They must match — otherwise
    we either capture closing lines we can't look up, or look up players
    we never capture."""
    assert tracker.PROP_BET_TYPES == cl.PROP_MARKETS
