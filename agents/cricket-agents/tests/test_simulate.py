import json
from unittest.mock import patch, MagicMock
from simulate import run_plan_b, parse_simulation_result, SYSTEM_PROMPT


MOCK_LLM_RESPONSE = json.dumps({
    "analyst_assessments": [
        {"role": "pitch_conditions", "pick": "MI", "reasoning": "Batting pitch favours MI"},
    ],
    "predictions": {
        "moneyline": {
            "team_a_win_prob": 0.58,
            "team_b_win_prob": 0.42,
            "value_side": "team_a",
            "edge": 0.06,
            "confidence": "medium",
        },
        "total_runs": {
            "projected": 340.5,
            "confidence": "medium",
        },
        "predicted_result": {
            "winner": "MI",
            "winning_margin": "5 wickets",
            "projected_scores": {"batting_first": 178, "chasing": 179},
        },
        "key_factors": ["batting pitch", "dew factor"],
    },
})


def test_parse_simulation_result_valid():
    result = parse_simulation_result(MOCK_LLM_RESPONSE)
    assert result["predictions"]["moneyline"]["team_a_win_prob"] == 0.58
    assert result["predictions"]["total_runs"]["projected"] == 340.5


def test_parse_simulation_result_invalid():
    result = parse_simulation_result("not json at all")
    assert result is None


def test_system_prompt_exists():
    assert "T20" in SYSTEM_PROMPT
    assert "JSON" in SYSTEM_PROMPT


def test_system_prompt_has_cricket_analysts():
    assert "PITCH" in SYSTEM_PROMPT
    assert "BATTING" in SYSTEM_PROMPT
    assert "BOWLING" in SYSTEM_PROMPT
    assert "TOSS" in SYSTEM_PROMPT


def test_system_prompt_has_correct_schema():
    assert "team_a_win_prob" in SYSTEM_PROMPT
    assert "team_b_win_prob" in SYSTEM_PROMPT
    assert "total_runs" in SYSTEM_PROMPT
    assert "projected" in SYSTEM_PROMPT
    assert "batting_first" in SYSTEM_PROMPT


@patch("simulate.openai.OpenAI")
def test_run_plan_b_calls_api(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = MOCK_LLM_RESPONSE
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

    result = run_plan_b("Test briefing content")
    assert result is not None
    assert "predictions" in result
