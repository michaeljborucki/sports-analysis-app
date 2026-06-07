import json
from unittest.mock import patch, MagicMock
from simulate import run_plan_b, parse_simulation_result, SOCCER_SYSTEM_PROMPT


MOCK_LLM_RESPONSE = json.dumps({
    "analyst_assessments": [
        {"role": "xg_attacking", "pick": "Inter Miami CF", "reasoning": "Strong xG"},
    ],
    "predictions": {
        "asian_handicap": {
            "home_cover_prob": 0.55,
            "away_cover_prob": 0.45,
            "value_side": "home",
            "edge": 0.05,
            "confidence": "medium",
        },
        "total": {
            "projected_goals": 2.8,
            "over_prob": 0.58,
            "under_prob": 0.42,
            "value_side": "over",
            "edge": 0.04,
            "confidence": "medium",
        },
        "btts": {
            "btts_yes_prob": 0.60,
            "btts_no_prob": 0.40,
            "value_side": "yes",
            "edge": 0.05,
            "confidence": "medium",
        },
        "predicted_score": {"home": 2, "away": 1},
        "key_factors": ["xG advantage", "home form"],
    },
})


def test_system_prompt_is_soccer():
    assert "soccer" in SOCCER_SYSTEM_PROMPT.lower() or "football" in SOCCER_SYSTEM_PROMPT.lower()
    assert "MLB" not in SOCCER_SYSTEM_PROMPT
    assert "pitching" not in SOCCER_SYSTEM_PROMPT.lower()
    assert "asian_handicap" in SOCCER_SYSTEM_PROMPT
    assert "btts" in SOCCER_SYSTEM_PROMPT


def test_parse_simulation_result_soccer():
    result = parse_simulation_result(MOCK_LLM_RESPONSE)
    assert result is not None
    assert "asian_handicap" in result["predictions"]
    assert "btts" in result["predictions"]
    assert result["predictions"]["total"]["projected_goals"] == 2.8


def test_parse_simulation_result_strips_markdown():
    raw = '```json\n{"predictions": {}}\n```'
    result = parse_simulation_result(raw)
    assert result is not None


def test_parse_simulation_result_returns_none_for_garbage():
    assert parse_simulation_result("not json") is None
    assert parse_simulation_result(None) is None
    assert parse_simulation_result("") is None


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
