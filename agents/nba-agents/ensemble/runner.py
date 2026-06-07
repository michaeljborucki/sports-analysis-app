"""Fire individual LLM calls via OpenRouter."""
import re
import time
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from simulate import NBA_SYSTEM_PROMPT, parse_simulation_result


def strip_thinking(raw: str) -> str:
    """Remove <think>...</think> blocks (DeepSeek R1) and find JSON."""
    text = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    if text and not text.startswith('{'):
        idx = text.find('{')
        if idx != -1:
            text = text[idx:]
    return text


def estimate_cost(input_tokens: int, output_tokens: int,
                  input_price: float, output_price: float) -> float:
    """Estimate cost in USD from token counts and per-million-token prices."""
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def run_single_model(
    model_key: str,
    model_id: str,
    briefing: str,
    temperature: float,
    max_tokens: int,
    timeout: int,
    input_price: float,
    output_price: float,
    system_prompt: str = None,
) -> dict | None:
    """Run a single LLM call. Returns parsed result dict or None on failure.

    Args:
        system_prompt: Override the default NBA_SYSTEM_PROMPT (used by challenger).
    """
    client = openai.OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        timeout=timeout,
    )
    sys_prompt = system_prompt or NBA_SYSTEM_PROMPT

    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": briefing},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except openai.RateLimitError:
        print(f"[ensemble] {model_key} rate limited, retrying in 2s...")
        time.sleep(2)
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": briefing},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as e:
            print(f"[ensemble] {model_key} retry failed: {e}")
            return None
    except Exception as e:
        print(f"[ensemble] {model_key} API error: {e}")
        return None

    choice = response.choices[0]
    if choice.finish_reason == "length":
        print(f"[ensemble] {model_key} warning: response truncated")

    raw = choice.message.content
    if not raw:
        return None

    if model_key == "deepseek":
        raw = strip_thinking(raw)

    parsed = parse_simulation_result(raw)
    if not parsed:
        print(f"[ensemble] {model_key} failed to parse JSON response")
        return None

    input_tokens = getattr(response.usage, 'prompt_tokens', 0)
    output_tokens = getattr(response.usage, 'completion_tokens', 0)
    cost = estimate_cost(input_tokens, output_tokens, input_price, output_price)

    return {
        "model_key": model_key,
        "parsed": parsed,
        "temperature": temperature,
        "cost": cost,
    }
