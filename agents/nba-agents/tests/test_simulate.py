import json
from unittest.mock import patch, MagicMock
from simulate import run_plan_b, parse_simulation_result, NBA_SYSTEM_PROMPT, _average_results, _average_prop_results, PROP_SYSTEM_PROMPT
from tests.ensemble_fixtures import MOCK_PREDICTION_JSON


def test_parse_simulation_result_valid():
    result = parse_simulation_result(MOCK_PREDICTION_JSON)
    assert result["predictions"]["moneyline"]["home_win_prob"] == 0.58
    assert result["predictions"]["total"]["projected_total"] == 218.5


def test_parse_simulation_result_invalid():
    result = parse_simulation_result("not json at all")
    assert result is None


def test_system_prompt_exists():
    assert "NBA" in NBA_SYSTEM_PROMPT
    assert "JSON" in NBA_SYSTEM_PROMPT


@patch("simulate.openai.OpenAI")
def test_run_plan_b_calls_api(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = MOCK_PREDICTION_JSON
    mock_choice.finish_reason = "stop"
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    result = run_plan_b("Test briefing content")
    assert result is not None
    assert "predictions" in result
    assert "spread" in result["predictions"]
    assert "first_half" in result["predictions"]
    assert result["predictions"]["first_half"]["h1_home_win_prob"] == 0.56


def test_nba_system_prompt_includes_q1():
    from simulate import NBA_SYSTEM_PROMPT
    assert "q1" in NBA_SYSTEM_PROMPT.lower()


def test_nba_system_prompt_includes_team_totals():
    from simulate import NBA_SYSTEM_PROMPT
    assert "team_totals" in NBA_SYSTEM_PROMPT


def test_prop_system_prompt_exists():
    from simulate import PROP_SYSTEM_PROMPT
    assert "player_props" in PROP_SYSTEM_PROMPT


def test_average_results_covers_q1():
    from simulate import _average_results
    results = [
        {"predictions": {"q1": {"q1_home_win_prob": 0.55, "q1_projected_total": 56.0}}},
        {"predictions": {"q1": {"q1_home_win_prob": 0.60, "q1_projected_total": 58.0}}},
    ]
    avg = _average_results(results)
    assert abs(avg["predictions"]["q1"]["q1_home_win_prob"] - 0.575) < 0.01


def test_average_prop_results():
    from simulate import _average_prop_results
    results = [
        {"player_props": {"Tatum": {"points": {"over_prob": 0.60, "projected": 28.0}}}},
        {"player_props": {"Tatum": {"points": {"over_prob": 0.70, "projected": 30.0}}}},
    ]
    avg = _average_prop_results(results)
    assert abs(avg["player_props"]["Tatum"]["points"]["over_prob"] - 0.65) < 0.01
    assert abs(avg["player_props"]["Tatum"]["points"]["projected"] - 29.0) < 0.1
