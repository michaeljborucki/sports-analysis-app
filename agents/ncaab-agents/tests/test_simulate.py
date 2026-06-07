import json
from unittest.mock import patch, MagicMock
from simulate import run_plan_b, parse_simulation_result, SYSTEM_PROMPT


MOCK_LLM_RESPONSE = json.dumps({
    "analyst_assessments": [
        {"role": "efficiency", "pick": "Duke", "reasoning": "Superior AdjEM"},
    ],
    "predictions": {
        "moneyline": {
            "home_win_prob": 0.65,
            "away_win_prob": 0.35,
            "value_side": "home",
            "edge": 0.06,
            "confidence": "medium",
        },
        "spread": {
            "favorite_cover_prob": 0.55,
            "value_side": "favorite",
            "edge": 0.04,
            "confidence": "medium",
        },
        "total": {
            "projected_total": 142.5,
            "over_prob": 0.55,
            "under_prob": 0.45,
            "value_side": "over",
            "edge": 0.05,
            "confidence": "medium",
        },
        "first_half": {
            "h1_home_win_prob": 0.60,
            "h1_away_win_prob": 0.40,
            "h1_projected_total": 68.5,
            "h1_ml_value": "home",
            "h1_total_value": "under",
            "confidence": "medium",
        },
        "predicted_score": {"away": 65, "home": 78},
        "key_factors": ["Efficiency gap", "Home court"],
    },
})


def test_parse_simulation_result_valid():
    result = parse_simulation_result(MOCK_LLM_RESPONSE)
    assert result["predictions"]["moneyline"]["home_win_prob"] == 0.65
    assert result["predictions"]["total"]["projected_total"] == 142.5


def test_parse_simulation_result_invalid():
    result = parse_simulation_result("not json at all")
    assert result is None


def test_system_prompt_exists():
    assert "NCAAB" in SYSTEM_PROMPT
    assert "JSON" in SYSTEM_PROMPT
    assert "spread" in SYSTEM_PROMPT
    assert "first_half" in SYSTEM_PROMPT


@patch("simulate.openai.OpenAI")
def test_run_plan_b_calls_api(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = MOCK_LLM_RESPONSE
    mock_choice.finish_reason = "stop"
    mock_resp = MagicMock(choices=[mock_choice])
    mock_resp.usage.prompt_tokens = 100
    mock_resp.usage.completion_tokens = 200
    mock_client.chat.completions.create.return_value = mock_resp

    result = run_plan_b("Test briefing content")
    assert result is not None
    assert "predictions" in result
