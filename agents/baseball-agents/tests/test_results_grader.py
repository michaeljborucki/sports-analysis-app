from unittest.mock import patch, MagicMock
import pandas as pd
from agents.results_grader import grade_bet, run_results_grader


class FakeRow:
    def __init__(self, d):
        self._d = d
    def __getitem__(self, key):
        return self._d[key]


SCORE = {
    "away": "BOS", "home": "NYY",
    "away_score": 3, "home_score": 5,
    "away_score_5": 1, "home_score_5": 3,
    "total_runs": 8, "total_runs_5": 4,
}


def test_grade_moneyline_home_win():
    row = FakeRow({"bet_type": "moneyline", "side": "home"})
    assert grade_bet(row, SCORE) == "W"


def test_grade_moneyline_away_loss():
    row = FakeRow({"bet_type": "moneyline", "side": "away"})
    assert grade_bet(row, SCORE) == "L"


def test_grade_run_line_home_covers():
    # NYY won by 2, -1.5 covers
    row = FakeRow({"bet_type": "run_line", "side": "home -1.5"})
    assert grade_bet(row, SCORE) == "W"


def test_grade_run_line_home_doesnt_cover():
    score = {**SCORE, "home_score": 4}  # won by 1, doesn't cover -1.5
    row = FakeRow({"bet_type": "run_line", "side": "home -1.5"})
    assert grade_bet(row, score) == "L"


def test_grade_total_over_win():
    row = FakeRow({"bet_type": "total", "side": "over 7.5"})
    assert grade_bet(row, SCORE) == "W"  # 8 > 7.5


def test_grade_total_under_win():
    row = FakeRow({"bet_type": "total", "side": "under 8.5"})
    assert grade_bet(row, SCORE) == "W"  # 8 < 8.5


def test_grade_total_under_loss():
    row = FakeRow({"bet_type": "total", "side": "under 7.5"})
    assert grade_bet(row, SCORE) == "L"  # 8 > 7.5


def test_grade_f5_ml():
    row = FakeRow({"bet_type": "first_5", "side": "home F5 ML"})
    assert grade_bet(row, SCORE) == "W"  # home_5=3 > away_5=1


# ---------------------------------------------------------------------------
# Postponed-game auto-push (sportsbook convention: void → refund → Push)
# ---------------------------------------------------------------------------

@patch("agents.results_grader.send_grade_notifications")
@patch("agents.results_grader.send_season_notification")
@patch("agents.results_grader._ensure_clv_for_date", return_value=0)
@patch("agents.results_grader.get_summary",
       return_value={"record": "0-0-0", "profit": 0, "roi": 0, "total_bets": 0})
@patch("agents.results_grader.update_result")
@patch("agents.results_grader.load_bets")
@patch("agents.results_grader.get_postponed_games")
@patch("agents.results_grader.get_final_scores")
def test_postponed_game_bets_are_marked_push(
    mock_final, mock_postponed, mock_load_bets, mock_update, *_
):
    """Bets on postponed games must auto-grade as P, not stay pending."""
    mock_final.return_value = [
        {"away": "BOS", "home": "NYY", "away_score": 3, "home_score": 5,
         "total_runs": 8, "game_pk": 1,
         "away_score_1": 0, "home_score_1": 0, "total_runs_1": 0,
         "away_score_3": 1, "home_score_3": 2, "total_runs_3": 3,
         "away_score_5": 1, "home_score_5": 3, "total_runs_5": 4,
         "status": "Final"},
    ]
    mock_postponed.return_value = [
        {"away": "MIL", "home": "KC", "status": "Postponed", "game_pk": 2},
    ]
    mock_load_bets.return_value = pd.DataFrame([
        # Index 0: bet on the completed game — should be graded normally
        {"date": "2026-04-03", "game": "BOS@NYY", "bet_type": "moneyline",
         "side": "home", "odds": -150, "sim_prob": 0.6,
         "edge": 0.05, "kelly_pct": 0.02, "result": "", "profit": "",
         "close_odds": "", "close_prob": "", "clv_cents": "", "clv_pct": ""},
        # Index 1: bet on postponed game — should be pushed
        {"date": "2026-04-03", "game": "MIL@KC", "bet_type": "total",
         "side": "over 8.5", "odds": -110, "sim_prob": 0.55,
         "edge": 0.03, "kelly_pct": 0.01, "result": "", "profit": "",
         "close_odds": "", "close_prob": "", "clv_cents": "", "clv_pct": ""},
        # Index 2: second bet on postponed game — also pushed
        {"date": "2026-04-03", "game": "MIL@KC", "bet_type": "nrfi",
         "side": "NRFI", "odds": 110, "sim_prob": 0.52,
         "edge": 0.03, "kelly_pct": 0.01, "result": "", "profit": "",
         "close_odds": "", "close_prob": "", "clv_cents": "", "clv_pct": ""},
    ])

    run_results_grader("2026-04-03", notify=False)

    results_by_idx = {call.args[0]: call.args[1] for call in mock_update.call_args_list}
    assert results_by_idx[0] == "W"    # BOS@NYY moneyline home — completed game graded normally
    assert results_by_idx[1] == "P"    # MIL@KC bet pushed
    assert results_by_idx[2] == "P"    # MIL@KC second bet pushed


@patch("agents.results_grader.send_grade_notifications")
@patch("agents.results_grader.send_season_notification")
@patch("agents.results_grader._ensure_clv_for_date", return_value=0)
@patch("agents.results_grader.get_summary",
       return_value={"record": "0-0-0", "profit": 0, "roi": 0, "total_bets": 0})
@patch("agents.results_grader.update_result")
@patch("agents.results_grader.load_bets")
@patch("agents.results_grader.get_postponed_games", return_value=[])
@patch("agents.results_grader.get_final_scores")
def test_no_postponed_means_no_auto_push(
    mock_final, mock_postponed, mock_load_bets, mock_update, *_
):
    """Sanity: when no games are postponed, no bets get auto-pushed."""
    mock_final.return_value = [
        {"away": "BOS", "home": "NYY", "away_score": 3, "home_score": 5,
         "total_runs": 8, "game_pk": 1,
         "away_score_1": 0, "home_score_1": 0, "total_runs_1": 0,
         "away_score_3": 1, "home_score_3": 2, "total_runs_3": 3,
         "away_score_5": 1, "home_score_5": 3, "total_runs_5": 4,
         "status": "Final"},
    ]
    mock_load_bets.return_value = pd.DataFrame([
        {"date": "2026-04-03", "game": "BOS@NYY", "bet_type": "moneyline",
         "side": "home", "odds": -150, "sim_prob": 0.6,
         "edge": 0.05, "kelly_pct": 0.02, "result": "", "profit": "",
         "close_odds": "", "close_prob": "", "clv_cents": "", "clv_pct": ""},
    ])

    run_results_grader("2026-04-03", notify=False)

    # Only the normal-grade call
    results = [call.args[1] for call in mock_update.call_args_list]
    assert "P" not in results
    assert results == ["W"]
