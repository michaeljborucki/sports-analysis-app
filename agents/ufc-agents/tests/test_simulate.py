from unittest.mock import patch, MagicMock
import json
from simulate import UFC_SYSTEM_PROMPT, parse_simulation_result


def test_system_prompt_is_ufc():
    assert "UFC" in UFC_SYSTEM_PROMPT
    assert "MLB" not in UFC_SYSTEM_PROMPT
    assert "STRIKING ANALYST" in UFC_SYSTEM_PROMPT
    assert "GRAPPLING ANALYST" in UFC_SYSTEM_PROMPT
    assert "round_probabilities" in UFC_SYSTEM_PROMPT
    assert "STYLE MATCHUP ANALYST" in UFC_SYSTEM_PROMPT
    assert "Confidence values are 0.0-1.0 numeric" in UFC_SYSTEM_PROMPT


def test_parse_simulation_result_valid():
    raw = json.dumps({
        "analyst_assessments": [
            {"role": "striking", "pick": "Fighter A", "reasoning": "..."}
        ],
        "predictions": {
            "moneyline": {
                "fighter_a_win_prob": 0.65,
                "fighter_b_win_prob": 0.35,
                "value_side": "fighter_a",
                "edge": 0.05,
                "confidence": "medium",
            },
            "total_rounds": {
                "projected_rounds": 2.5,
                "over_prob": 0.45,
                "under_prob": 0.55,
                "value_side": "under",
                "edge": 0.06,
                "confidence": "medium",
            },
            "method": {
                "ko_tko_prob": 0.30,
                "submission_prob": 0.35,
                "decision_prob": 0.35,
                "most_likely": "Submission",
                "value_method": "sub",
                "confidence": "medium",
            },
            "predicted_result": {"winner": "Fighter A", "method": "Submission", "round": 3},
            "key_factors": ["wrestling advantage", "submission threat"],
        },
    })
    result = parse_simulation_result(raw)
    assert result is not None
    assert "predictions" in result
    assert "moneyline" in result["predictions"]
    assert "total_rounds" in result["predictions"]
    assert "method" in result["predictions"]


def test_parse_simulation_result_markdown_fences():
    raw = '```json\n{"predictions": {}}\n```'
    result = parse_simulation_result(raw)
    assert result is not None


def test_parse_simulation_result_invalid():
    result = parse_simulation_result("not json at all")
    assert result is None


def test_parse_simulation_result_empty():
    result = parse_simulation_result("")
    assert result is None
