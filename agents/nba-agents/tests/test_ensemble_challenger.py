import json
from unittest.mock import patch, MagicMock
from ensemble.challenger import build_challenge_prompt, parse_challenge_response, run_challenge

def test_build_challenge_prompt_includes_briefing():
    prompt = build_challenge_prompt(
        briefing="LAL@BOS game data...",
        ensemble_predictions={"moneyline": {"home_win_prob": 0.58}},
        model_agreement={"moneyline": "5/6 models say home, avg edge 7.2%"},
    )
    assert "LAL@BOS" in prompt
    assert "adversarial" in prompt.lower() or "consensus" in prompt.lower()

def test_parse_challenge_approve():
    raw = json.dumps({
        "challenges": [
            {"bet_type": "moneyline", "verdict": "approve", "reasoning": "looks solid", "flaw_found": None}
        ]
    })
    result = parse_challenge_response(raw)
    assert result is not None
    assert result["moneyline"] == "approve"

def test_parse_challenge_kill():
    raw = json.dumps({
        "challenges": [
            {"bet_type": "moneyline", "verdict": "kill", "reasoning": "bad", "flaw_found": "overfit"},
            {"bet_type": "total", "verdict": "approve", "reasoning": "fine", "flaw_found": None},
        ]
    })
    result = parse_challenge_response(raw)
    assert result["moneyline"] == "kill"
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
                {"bet_type": "moneyline", "verdict": "approve", "reasoning": "ok", "flaw_found": None}
            ]
        },
        "temperature": 0.7,
        "cost": 0.05,
    }
    verdicts, cost = run_challenge(
        briefing="test", ensemble_predictions={}, model_agreement={},
        surviving_slots=["moneyline"],
    )
    assert verdicts["moneyline"] == "approve"
    assert cost > 0

@patch("ensemble.challenger.run_single_model")
def test_run_challenge_failure_approves_all(mock_runner):
    mock_runner.return_value = None
    verdicts, cost = run_challenge(
        briefing="test", ensemble_predictions={}, model_agreement={},
        surviving_slots=["moneyline", "total"],
    )
    assert verdicts["moneyline"] == "approve"
    assert verdicts["total"] == "approve"
    assert cost == 0
