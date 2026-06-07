from unittest.mock import patch, MagicMock
from simulate import TENNIS_SYSTEM_PROMPT, parse_simulation_result, run_plan_b


def test_tennis_system_prompt_exists():
    assert "tennis" in TENNIS_SYSTEM_PROMPT.lower()
    assert "serve analyst" in TENNIS_SYSTEM_PROMPT.lower()
    assert "surface" in TENNIS_SYSTEM_PROMPT.lower()


def test_tennis_system_prompt_has_json_structure():
    assert "player_a_win_prob" in TENNIS_SYSTEM_PROMPT
    assert "game_handicap" in TENNIS_SYSTEM_PROMPT
    assert "total_games" in TENNIS_SYSTEM_PROMPT
    assert "projected_games" in TENNIS_SYSTEM_PROMPT


def test_no_mlb_in_system_prompt():
    assert "MLB" not in TENNIS_SYSTEM_PROMPT
    assert "pitcher" not in TENNIS_SYSTEM_PROMPT.lower()
    assert "run_line" not in TENNIS_SYSTEM_PROMPT
    assert "first_5" not in TENNIS_SYSTEM_PROMPT


def test_parse_simulation_result_valid_json():
    raw = '{"predictions": {"moneyline": {"player_a_win_prob": 0.55}}}'
    result = parse_simulation_result(raw)
    assert result is not None
    assert result["predictions"]["moneyline"]["player_a_win_prob"] == 0.55


def test_parse_simulation_result_strips_markdown():
    raw = '```json\n{"key": "value"}\n```'
    result = parse_simulation_result(raw)
    assert result == {"key": "value"}


def test_parse_simulation_result_none():
    assert parse_simulation_result(None) is None
    assert parse_simulation_result("not json") is None


@patch("simulate.openai.OpenAI")
def test_run_plan_b_returns_parsed(mock_openai_cls):
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = '{"predictions": {"moneyline": {"player_a_win_prob": 0.6}}}'
    mock_choice.finish_reason = "stop"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 200
    mock_client.chat.completions.create.return_value = mock_response

    result = run_plan_b("test briefing")
    assert result is not None
    assert "predictions" in result
