"""Simulation layer: Plan B (direct Kimi) and MiroFish 512-agent."""
import json
import logging
import time
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, KIMI_MODEL

logger = logging.getLogger("mirofish.simulate")


def parse_simulation_result(raw: str | None) -> dict | None:
    """Parse JSON response from LLM, handling common issues."""
    if not raw:
        return None
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_plan_b(briefing: str, game_config=None, runs: int = 1) -> dict | None:
    """Run direct Kimi call (Plan B) — fast screen at ~$0.06/game.

    Args:
        briefing: Pre-built briefing string from the game-specific briefing module.
        game_config: Game module (e.g. games.cs2). Must expose a prompt submodule
                     with a SYSTEM_PROMPT attribute.
        runs: Number of independent runs to average for stability.

    If runs > 1, average the probability estimates across runs for stability.
    """
    if game_config is None:
        raise ValueError("run_plan_b requires a game_config (game module) — no default game")
    system_prompt = game_config.prompt.SYSTEM_PROMPT

    client = openai.OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
        timeout=120,
    )

    logger.info("Plan B: starting %d run(s) via %s", runs, KIMI_MODEL)
    results = []
    for run_idx in range(runs):
        try:
            t0 = time.time()
            logger.debug("Plan B run %d/%d: calling API...", run_idx + 1, runs)
            response = client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": briefing},
                ],
                temperature=0.7,
                max_tokens=12288,
            )
            elapsed = time.time() - t0
            choice = response.choices[0]
            in_tok = getattr(response.usage, 'prompt_tokens', 0)
            out_tok = getattr(response.usage, 'completion_tokens', 0)
            logger.debug("Plan B run %d: %.1fs, %d/%d tokens (in/out), finish=%s",
                         run_idx + 1, elapsed, in_tok, out_tok, choice.finish_reason)
            if choice.finish_reason == "length":
                logger.warning("Plan B run %d: response truncated (finish_reason=length)", run_idx + 1)
            raw = choice.message.content
            parsed = parse_simulation_result(raw)
            if parsed:
                results.append(parsed)
                logger.debug("Plan B run %d: parsed successfully", run_idx + 1)
            else:
                logger.warning("Plan B run %d: failed to parse JSON response", run_idx + 1)
        except Exception as e:
            logger.error("Plan B run %d error: %s", run_idx + 1, e)

    if not results:
        logger.warning("Plan B: all %d runs failed — returning None", runs)
        return None

    if len(results) == 1:
        logger.info("Plan B: 1/%d run(s) succeeded", runs)
        return results[0]

    # Average probabilities across runs
    logger.info("Plan B: averaging %d/%d successful runs", len(results), runs)
    return _average_results(results)


def run_mirofish(briefing: str, odds: dict = None, game_config=None, runs: int = 3) -> dict | None:
    """Run multi-model ensemble simulation with Plan B fallback.

    Args:
        briefing: Pre-built briefing string from the game-specific briefing module.
        odds: Game odds dict for consensus normalization.
        game_config: Game module (e.g. games.cs2). Passed through to ensemble and Plan B.
        runs: Number of Plan B fallback runs if ensemble fails.
    """
    try:
        logger.info("MiroFish: attempting ensemble simulation")
        from ensemble import run_ensemble
        import inspect
        t0 = time.time()
        # Pass game_config if the ensemble supports it (Task 8 will add full support)
        sig = inspect.signature(run_ensemble)
        if "game_config" in sig.parameters:
            result = run_ensemble(briefing, odds=odds, game_config=game_config)
        else:
            result = run_ensemble(briefing, odds=odds)
        elapsed = time.time() - t0
        if result:
            meta = result.get("ensemble_meta", {})
            logger.info("MiroFish: ensemble succeeded in %.1fs (phase=%d, calls=%d, cost=$%.4f)",
                        elapsed, meta.get("phase_reached", 0),
                        meta.get("total_calls", 0), meta.get("cost_usd", 0))
            return result
        logger.warning("MiroFish: ensemble returned None after %.1fs, falling back to Plan B", elapsed)
    except Exception as e:
        logger.error("MiroFish: ensemble failed (%s), falling back to Plan B", e)
    return run_plan_b(briefing, game_config=game_config, runs=runs)


def _average_results(results: list[dict]) -> dict:
    """Average probability fields across multiple simulation runs."""
    base = results[0].copy()
    n = len(results)

    preds = base.get("predictions", {})
    prob_fields = {
        "moneyline": ["team_a_win_prob", "team_b_win_prob", "edge"],
        "map_handicap": ["favorite_cover_prob", "edge"],
        "total_maps": ["projected_maps", "over_prob", "under_prob", "edge"],
    }

    for section, fields in prob_fields.items():
        if section not in preds:
            continue
        for field in fields:
            values = []
            for r in results:
                val = r.get("predictions", {}).get(section, {}).get(field)
                if val is not None:
                    values.append(float(val))
            if values:
                preds[section][field] = round(sum(values) / len(values), 4)

    base["predictions"] = preds
    base["ensemble_runs"] = n
    return base
