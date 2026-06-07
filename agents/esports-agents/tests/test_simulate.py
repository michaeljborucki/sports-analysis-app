import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import pytest
from simulate import run_plan_b, parse_simulation_result


# ---------------------------------------------------------------------------
# Shared mock data (CS2-shaped response)
# ---------------------------------------------------------------------------

MOCK_LLM_RESPONSE = json.dumps({
    "analyst_assessments": [
        {"role": "fragging", "pick": "Natus Vincere", "reasoning": "s1mple is in peak form"},
    ],
    "predictions": {
        "moneyline": {
            "team_a_win_prob": 0.60,
            "team_b_win_prob": 0.40,
            "value_side": "team_a",
            "edge": 0.05,
            "confidence": "medium",
        },
        "map_handicap": {
            "favorite_cover_prob": 0.45,
            "value_side": "underdog",
            "edge": 0.03,
            "confidence": "low",
        },
        "total_maps": {
            "projected_maps": 2.4,
            "over_prob": 0.42,
            "under_prob": 0.58,
            "value_side": "under",
            "edge": 0.04,
            "confidence": "medium",
        },
        "predicted_result": {"winner": "Natus Vincere", "score": "2-1"},
        "key_factors": ["s1mple AWP dominance", "map pool advantage"],
    },
})


def _make_game_config(system_prompt: str = "FAKE_SYSTEM_PROMPT"):
    """Build a minimal game_config mock with a prompt submodule."""
    prompt_mod = SimpleNamespace(SYSTEM_PROMPT=system_prompt)
    return SimpleNamespace(prompt=prompt_mod)


# ---------------------------------------------------------------------------
# parse_simulation_result
# ---------------------------------------------------------------------------

def test_parse_simulation_result_valid():
    result = parse_simulation_result(MOCK_LLM_RESPONSE)
    assert result["predictions"]["moneyline"]["team_a_win_prob"] == 0.60
    assert result["predictions"]["total_maps"]["projected_maps"] == 2.4


def test_parse_simulation_result_invalid():
    result = parse_simulation_result("not json at all")
    assert result is None


def test_parse_simulation_result_strips_markdown():
    wrapped = "```json\n" + MOCK_LLM_RESPONSE + "\n```"
    result = parse_simulation_result(wrapped)
    assert result is not None
    assert "predictions" in result


# ---------------------------------------------------------------------------
# run_plan_b — signature and game_config usage
# ---------------------------------------------------------------------------

def test_run_plan_b_requires_game_config():
    """run_plan_b should raise if game_config is not provided."""
    with pytest.raises(ValueError, match="game_config"):
        run_plan_b("Some briefing")


@patch("simulate.openai.OpenAI")
def test_run_plan_b_uses_game_config_system_prompt(MockOpenAI):
    """run_plan_b should use the system prompt from game_config.prompt.SYSTEM_PROMPT."""
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client

    mock_choice = MagicMock()
    mock_choice.message.content = MOCK_LLM_RESPONSE
    mock_choice.finish_reason = "stop"
    mock_response = MagicMock(choices=[mock_choice])
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 200
    mock_client.chat.completions.create.return_value = mock_response

    game_config = _make_game_config("MY_CUSTOM_SYSTEM_PROMPT")
    result = run_plan_b("Test briefing content", game_config=game_config)

    assert result is not None
    assert "predictions" in result

    # Verify the custom system prompt was sent, not any MLB prompt
    call_kwargs = mock_client.chat.completions.create.call_args
    messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][0]
    system_messages = [m for m in messages if m["role"] == "system"]
    assert len(system_messages) == 1
    assert system_messages[0]["content"] == "MY_CUSTOM_SYSTEM_PROMPT"


@patch("simulate.openai.OpenAI")
def test_run_plan_b_uses_cs2_system_prompt(MockOpenAI):
    """run_plan_b with the real cs2 game module uses CS2_SYSTEM_PROMPT."""
    from games import cs2

    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client

    mock_choice = MagicMock()
    mock_choice.message.content = MOCK_LLM_RESPONSE
    mock_choice.finish_reason = "stop"
    mock_response = MagicMock(choices=[mock_choice])
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 200
    mock_client.chat.completions.create.return_value = mock_response

    result = run_plan_b("Test briefing", game_config=cs2)

    assert result is not None

    call_kwargs = mock_client.chat.completions.create.call_args
    messages = call_kwargs[1]["messages"] if call_kwargs[1] else call_kwargs[0][0]
    system_messages = [m for m in messages if m["role"] == "system"]
    assert system_messages[0]["content"] == cs2.prompt.SYSTEM_PROMPT
    # Must NOT contain any MLB-specific terminology
    assert "MLB" not in system_messages[0]["content"]
    assert "CS2" in system_messages[0]["content"]


@patch("simulate.openai.OpenAI")
def test_run_plan_b_api_failure_returns_none(MockOpenAI):
    """run_plan_b returns None when the API call raises an exception."""
    mock_client = MagicMock()
    MockOpenAI.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("network error")

    game_config = _make_game_config()
    result = run_plan_b("Test briefing", game_config=game_config)
    assert result is None
