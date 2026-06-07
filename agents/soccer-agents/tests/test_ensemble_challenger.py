import json
from unittest.mock import patch, MagicMock
from ensemble.challenger import build_challenge_prompt, parse_challenge_response, run_challenge

def test_build_challenge_prompt_includes_briefing():
    prompt = build_challenge_prompt(
        briefing="Arsenal vs Chelsea game data...",
        ensemble_predictions={"asian_handicap": {"home_cover_prob": 0.58}},
        model_agreement={"asian_handicap": "5/6 models say home, avg edge 7.2%"},
    )
    assert "Arsenal" in prompt
    assert "adversarial" in prompt.lower() or "consensus" in prompt.lower()

def test_parse_challenge_approve():
    raw = json.dumps({
        "challenges": [
            {"bet_type": "asian_handicap", "verdict": "approve", "reasoning": "looks solid", "flaw_found": None}
        ]
    })
    result = parse_challenge_response(raw)
    assert result is not None
    assert result["asian_handicap"] == "approve"

def test_parse_challenge_kill():
    raw = json.dumps({
        "challenges": [
            {"bet_type": "asian_handicap", "verdict": "kill", "reasoning": "bad", "flaw_found": "overfit"},
            {"bet_type": "total", "verdict": "approve", "reasoning": "fine", "flaw_found": None},
        ]
    })
    result = parse_challenge_response(raw)
    assert result["asian_handicap"] == "kill"
    assert result["total"] == "approve"

def test_parse_challenge_invalid_json():
    result = parse_challenge_response("not json")
    assert result is None

@patch("ensemble.challenger.run_single_model")
def test_run_challenge_success(mock_runner):
    mock_runner.return_value = {
        "model_key": "claude",
        "parsed": {
            "challenges": [
                {"bet_type": "asian_handicap", "verdict": "approve", "reasoning": "ok", "flaw_found": None}
            ]
        },
        "temperature": 0.7,
        "cost": 0.05,
    }
    verdicts, cost = run_challenge(
        briefing="test", ensemble_predictions={}, model_agreement={},
        surviving_slots=["asian_handicap"],
    )
    assert verdicts["asian_handicap"] == "approve"
    assert cost > 0

@patch("ensemble.challenger.run_single_model")
def test_run_challenge_failure_approves_all(mock_runner):
    mock_runner.return_value = None
    verdicts, cost = run_challenge(
        briefing="test", ensemble_predictions={}, model_agreement={},
        surviving_slots=["asian_handicap", "total"],
    )
    assert verdicts["asian_handicap"] == "approve"
    assert verdicts["total"] == "approve"
    assert cost == 0
