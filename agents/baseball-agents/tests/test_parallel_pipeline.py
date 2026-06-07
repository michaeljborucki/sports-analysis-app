"""Tests for parallel game processing in main.py."""
from unittest.mock import patch, MagicMock
from main import (
    _screen_game, _simulate_game, _process_game, _NO_ODDS, _SCREEN_FAILED,
)


def _make_game(away="NYY", home="BOS"):
    return {
        "away_team": away, "home_team": home,
        "away_pitcher": "TestPitcher", "home_pitcher": "TestPitcher",
        "away_team_id": 147, "home_team_id": 111,
    }


def _make_odds(away="NYY", home="BOS"):
    odds = MagicMock()
    odds.moneyline = {"away": -110, "home": 100}
    odds.run_line = {"away": {"line": -1.5, "odds": 150}, "home": {"line": 1.5, "odds": -170}}
    odds.total = {"over": {"line": 8.5, "odds": -110}, "under": {"line": 8.5, "odds": -110}}
    odds.f5_moneyline = {}
    odds.f5_total = {}
    odds.f3_moneyline = {}
    odds.f3_total = {}
    odds.f1_total = {}
    odds.team_total_home = {}
    odds.team_total_away = {}
    odds.implied_probs = {"away": 0.52, "home": 0.48}
    return odds


@patch("main.get_starter_profile", return_value={"name": "TestPitcher", "era": 3.50})
@patch("main.get_team_profile", return_value={"record": "10-5"})
@patch("main.get_game_environment", return_value={"venue": "Test Park"})
@patch("main.get_bullpen_state", return_value={})
@patch("main.build_briefing", return_value="Test briefing")
@patch("main.run_plan_b", return_value={"moneyline": {"away_win": 0.55, "home_win": 0.45}})
@patch("main.analyze_all_edges", return_value=[{"edge": 0.06, "bet_type": "moneyline", "side": "NYY"}])
def test_screen_game_returns_result(mock_edges, mock_planb, mock_brief,
                                     mock_bullpen, mock_env, mock_team, mock_pitcher):
    game = _make_game()
    odds_map = {"NYY@BOS": _make_odds()}
    result = _screen_game(game, odds_map, {}, "2026-03-22")
    assert result is not None
    game_key, brief, game_data, max_edge = result
    assert game_key == "NYY@BOS"
    assert max_edge == 0.06


@patch("main.get_starter_profile", return_value={"name": "TestPitcher"})
@patch("main.get_team_profile", return_value={"record": "10-5"})
@patch("main.get_game_environment", return_value={"venue": "Test Park"})
@patch("main.get_bullpen_state", return_value={})
@patch("main.build_briefing", return_value="Test briefing")
@patch("main.run_plan_b", return_value=None)
def test_screen_game_returns_none_on_failed_screen(mock_planb, mock_brief,
                                                     mock_bullpen, mock_env,
                                                     mock_team, mock_pitcher):
    game = _make_game()
    odds_map = {"NYY@BOS": _make_odds()}
    result = _screen_game(game, odds_map, {}, "2026-03-22")
    assert result == _SCREEN_FAILED


def test_screen_game_returns_no_odds_when_no_odds():
    game = _make_game()
    result = _screen_game(game, {}, {}, "2026-03-22")
    assert result == _NO_ODDS


@patch("main.run_mirofish", return_value={
    "moneyline": {"away_win": 0.58, "home_win": 0.42},
    "ensemble_meta": {"cost_usd": 0.05, "phase_reached": 2, "total_calls": 12},
})
@patch("main.analyze_all_edges", return_value=[
    {"edge": 0.06, "bet_type": "moneyline", "side": "NYY",
     "odds": -110, "kelly_pct": 0.02, "sim_prob": 0.58, "market_prob": 0.52},
])
@patch("main.log_bet")
def test_simulate_game_returns_bets(mock_log, mock_edges, mock_sim):
    game_data = {
        "odds": {"moneyline": {"away": -110}},
        "odds_obj": MagicMock(event_id=None),
        "home_team": "BOS",
        "game_pk": None,
    }
    gk, bets, result = _simulate_game("NYY@BOS", "briefing", game_data, "2026-03-22")
    assert gk == "NYY@BOS"
    assert len(bets) == 1
    assert bets[0]["game"] == "NYY@BOS"
    assert mock_log.called


@patch("main.run_mirofish", return_value=None)
def test_simulate_game_handles_failed_sim(mock_sim):
    game_data = {"odds": {}, "odds_obj": MagicMock(event_id=None),
                 "home_team": "BOS", "game_pk": None}
    gk, bets, result = _simulate_game("NYY@BOS", "briefing", game_data, "2026-03-22")
    assert bets == []
    assert result is None


# ---------- _process_game (per-game unit for the priority rule) ----------


@patch("agents.analyzed_games.mark_analyzed")
@patch("main._screen_game", return_value=_NO_ODDS)
def test_process_game_no_odds(mock_screen, mock_mark):
    out = _process_game(_make_game(), {}, {}, "2026-03-22")
    assert out == {"game_key": "NYY@BOS", "status": "no_odds", "bets": [], "max_edge": 0.0}
    mock_mark.assert_called_once_with("2026-03-22", "NYY@BOS", "no_odds")


@patch("agents.analyzed_games.mark_analyzed")
@patch("main._screen_game", return_value=_SCREEN_FAILED)
def test_process_game_screen_failed(mock_screen, mock_mark):
    out = _process_game(_make_game(), {}, {}, "2026-03-22")
    assert out["status"] == "screen_error"
    assert out["bets"] == []
    mock_mark.assert_called_once_with("2026-03-22", "NYY@BOS", "screen_error")


@patch("agents.analyzed_games.mark_analyzed")
@patch("main._simulate_game")
@patch("main._screen_game", return_value=("NYY@BOS", "brief", {"k": "v"}, 0.01))
def test_process_game_no_edge_skips_simulation(mock_screen, mock_sim, mock_mark):
    # max_edge 0.01 < SCREEN_EDGE_THRESHOLD (0.03) → no sim, no bets.
    out = _process_game(_make_game(), {}, {}, "2026-03-22")
    assert out["status"] == "no_edge"
    assert out["bets"] == []
    mock_sim.assert_not_called()
    mock_mark.assert_called_once_with("2026-03-22", "NYY@BOS", "no_edge")


@patch("agents.analyzed_games.mark_analyzed")
@patch("main._simulate_game", return_value=("NYY@BOS", [{"edge": 0.06}], {"ensemble_meta": {}}))
@patch("main._screen_game", return_value=("NYY@BOS", "brief", {"k": "v"}, 0.08))
def test_process_game_flagged_runs_sim_and_returns_bets(mock_screen, mock_sim, mock_mark):
    out = _process_game(_make_game(), {}, {}, "2026-03-22")
    assert out["status"] == "flagged"
    assert out["max_edge"] == 0.08
    assert out["bets"] == [{"edge": 0.06}]
    mock_sim.assert_called_once()
    # Flagged is marked before the expensive sim runs.
    mock_mark.assert_called_once_with("2026-03-22", "NYY@BOS", "flagged")
