import json
from unittest.mock import patch, MagicMock
from simulate import run_plan_b, parse_simulation_result, MLB_SYSTEM_PROMPT


MOCK_LLM_RESPONSE = json.dumps({
    "analyst_assessments": [
        {"role": "pitching", "game_winner": "NYY", "reasoning": "Cole is elite"},
    ],
    "predictions": {
        "moneyline": {
            "home_win_prob": 0.58,
            "away_win_prob": 0.42,
            "value_side": "none",
            "edge": 0.0,
            "confidence": "medium",
        },
        "run_line": {
            "favorite_cover_prob": 0.38,
            "value_side": "underdog_rl",
            "edge": 0.04,
            "confidence": "low",
        },
        "total": {
            "projected_total": 8.2,
            "over_prob": 0.45,
            "under_prob": 0.55,
            "value_side": "under",
            "edge": 0.03,
            "confidence": "medium",
        },
        "first_5": {
            "f5_home_win_prob": 0.55,
            "f5_away_win_prob": 0.45,
            "f5_projected_total": 4.0,
            "f5_ml_value": "none",
            "f5_total_value": "under",
            "confidence": "medium",
        },
        "predicted_score": {"away": 3, "home": 5},
        "key_factors": ["Cole dominance", "wind blowing in"],
    },
})


def test_parse_simulation_result_valid():
    result = parse_simulation_result(MOCK_LLM_RESPONSE)
    assert result["predictions"]["moneyline"]["home_win_prob"] == 0.58
    assert result["predictions"]["total"]["projected_total"] == 8.2


def test_parse_simulation_result_invalid():
    result = parse_simulation_result("not json at all")
    assert result is None


def test_system_prompt_exists():
    assert "MLB" in MLB_SYSTEM_PROMPT
    assert "JSON" in MLB_SYSTEM_PROMPT


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
