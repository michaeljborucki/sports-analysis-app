import json
from unittest.mock import patch, MagicMock
from ensemble.runner import run_single_model, strip_thinking, estimate_cost
from tests.ensemble_fixtures import MOCK_PREDICTION_JSON


def test_strip_thinking_removes_think_blocks():
    raw = '<think>Some reasoning here\nmore thinking</think>{"predictions": {}}'
    assert strip_thinking(raw).startswith("{")

def test_strip_thinking_fallback_finds_json():
    raw = "Some preamble text {\"predictions\": {}}"
    assert strip_thinking(raw).startswith("{")

def test_strip_thinking_clean_input():
    raw = '{"predictions": {}}'
    assert strip_thinking(raw) == '{"predictions": {}}'

def test_estimate_cost():
    cost = estimate_cost(1000, 500, 2.50, 10.00)
    assert abs(cost - 0.0075) < 0.0001

@patch("ensemble.runner.openai.OpenAI")
def test_run_single_model_success(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = MOCK_PREDICTION_JSON
    mock_choice.finish_reason = "stop"
    mock_response = MagicMock(choices=[mock_choice])
    mock_response.usage.prompt_tokens = 500
    mock_response.usage.completion_tokens = 300
    mock_client.chat.completions.create.return_value = mock_response
    result = run_single_model(
        model_key="kimi", model_id="moonshotai/kimi-k2.5",
        briefing="Test briefing", temperature=0.7, max_tokens=12288,
        timeout=45, input_price=0.45, output_price=2.25,
    )
    assert result is not None
    assert result["parsed"]["predictions"]["moneyline"]["home_win_prob"] == 0.65
    assert result["cost"] > 0
    assert result["model_key"] == "kimi"

@patch("ensemble.runner.openai.OpenAI")
def test_run_single_model_api_error_returns_none(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("API error")
    result = run_single_model(
        model_key="kimi", model_id="moonshotai/kimi-k2.5",
        briefing="Test briefing", temperature=0.7, max_tokens=12288,
        timeout=45, input_price=0.45, output_price=2.25,
    )
    assert result is None

@patch("ensemble.runner.openai.OpenAI")
def test_run_single_model_invalid_json_returns_none(MockOpenAI):
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = "not valid json at all"
    mock_choice.finish_reason = "stop"
    mock_response = MagicMock(choices=[mock_choice])
    mock_response.usage.prompt_tokens = 500
    mock_response.usage.completion_tokens = 300
    mock_client.chat.completions.create.return_value = mock_response
    result = run_single_model(
        model_key="kimi", model_id="moonshotai/kimi-k2.5",
        briefing="Test briefing", temperature=0.7, max_tokens=12288,
        timeout=45, input_price=0.45, output_price=2.25,
    )
    assert result is None

@patch("ensemble.runner.openai.OpenAI")
def test_run_single_model_custom_system_prompt(MockOpenAI):
    """Verify system_prompt override works (used by challenger)."""
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_choice = MagicMock()
    mock_choice.message.content = '{"challenges": [{"bet_type": "moneyline", "verdict": "approve"}]}'
    mock_choice.finish_reason = "stop"
    mock_response = MagicMock(choices=[mock_choice])
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 50
    mock_client.chat.completions.create.return_value = mock_response
    result = run_single_model(
        model_key="claude_challenger", model_id="anthropic/claude-sonnet-4",
        briefing="Challenge prompt", temperature=0.7, max_tokens=12288,
        timeout=45, input_price=3.00, output_price=15.00,
        system_prompt="You are an adversarial analyst.",
    )
    assert result is not None
    # Verify the custom system prompt was passed
    call_args = mock_client.chat.completions.create.call_args
    messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
    assert messages[0]["content"] == "You are an adversarial analyst."
