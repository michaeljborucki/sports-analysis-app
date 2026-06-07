"""Simulation layer: Plan B (direct Kimi) and MiroFish 512-agent."""
import json
import logging
import time
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, KIMI_MODEL

logger = logging.getLogger("mirofish.simulate")


SYSTEM_PROMPT = """You are an elite NCAAB prediction system analyzing a college basketball game.

CRITICAL CALIBRATION WARNINGS:
- Betting markets are highly efficient. The posted line is the best available estimate ~50% of the time.
- LLM prediction systems historically overestimate college basketball totals by 3-5 points. Resist the urge to push totals above the market line without specific, quantifiable evidence.
- Do NOT assume tournament games automatically go over. The empirical over rate in NCAA tournament games is approximately 48% — essentially a coin flip.
- A "projected total" in the briefing is a naive calculation. Treat it as ONE input, not ground truth.

Evaluate from these 5 expert perspectives:

1. EFFICIENCY ANALYST: Evaluates tempo-free efficiency metrics — adjusted offensive
   and defensive efficiency, Four Factors (eFG%, TOV%, OREB%, FT Rate). How do
   the efficiency profiles match up? Which team has the fundamental edge?
2. TEMPO & MATCHUP ANALYST: Evaluates pace matchup and how it affects scoring.
   Fast team vs slow team = what projected pace? How many possessions?
   Projected score = efficiency × pace.
3. ROSTER & SITUATIONAL ANALYST: Evaluates returning production, transfer portal
   impact, coaching stability, key player contributions, home court advantage,
   conference dynamics, rivalry factor, tournament implications, travel fatigue,
   and scheduling spots (lookahead, letdown).
4. MARKET ANALYST: Evaluates the betting lines for value. Is the spread
   properly reflecting the efficiency gap? Is the total accounting for tempo?
   Small-conference games are often mispriced — is this one of them?
   Where might the market be wrong and WHY specifically?
5. SYNTHESIS: Weigh all perspectives. Where do analysts agree? Where do they
   disagree? First estimate your own projected total and win probability
   BEFORE comparing to the market line. Then assess whether there is value.

IMPORTANT: Form your own projected total and win probability independently
from the efficiency data BEFORE looking at the betting lines. Then compare
your projection to the market to find value.

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "efficiency", "pick": "TEAM", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "home_win_prob": 0.XX,
      "away_win_prob": 0.XX,
      "value_side": "home|away|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "spread": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total": {
      "projected_total": XXX.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "first_half": {
      "h1_home_win_prob": 0.XX,
      "h1_away_win_prob": 0.XX,
      "h1_projected_total": XX.X,
      "h1_over_prob": 0.XX,
      "h1_under_prob": 0.XX,
      "h1_favorite_cover_prob": 0.XX,
      "h1_ml_value": "home|away|none",
      "h1_total_value": "over|under|none",
      "h1_spread_value": "favorite|underdog|none",
      "confidence": "low|medium|high"
    },
    "predicted_score": {"away": XX, "home": XX},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only."""

MODEL_PROMPT_VARIANTS = {
    "kimi": "Focus especially on efficiency metrics and Four Factors differentials. Weight statistical evidence over narrative.",
    "claude": "Focus especially on market efficiency. Assume the line is correct unless you find specific, quantifiable reasons it is wrong. Be skeptical of edges over 8%.",
    "gpt4o": "Focus especially on situational factors: home court, scheduling, travel, motivation. These are where markets are most likely to misprice.",
    "gemini": "Focus especially on tempo matchup and pace. Calculate your own projected pace and total independently before looking at any provided projections.",
    "deepseek": "Focus especially on contrarian analysis. For each market, argue AGAINST the obvious side first. Only pick the obvious side if the contrarian case fails.",
    "maverick": "Focus especially on roster context and recent form. Trends in last 5-10 games matter more than season averages when recent rotation changes occurred.",
}


def get_model_prompt(model_key: str) -> str:
    """Return model-specific system prompt to reduce correlation between models."""
    variant = MODEL_PROMPT_VARIANTS.get(model_key, "")
    if variant:
        return SYSTEM_PROMPT + f"\n\nYOUR SPECIFIC FOCUS: {variant}"
    return SYSTEM_PROMPT


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


def run_plan_b(briefing: str, runs: int = 1) -> dict | None:
    """Run direct Kimi call (Plan B) — fast screen at ~$0.06/game.

    If runs > 1, average the probability estimates across runs for stability.
    """
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
                    {"role": "system", "content": SYSTEM_PROMPT},
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


def run_mirofish(briefing: str, runs: int = 3, odds: dict = None, game_data: dict = None) -> dict | None:
    """Run multi-model ensemble simulation with Plan B fallback.

    Args:
        odds: Game odds dict for spread consensus normalization.
        game_data: Full game data dict for stat_anchor model.
    """
    try:
        logger.info("MiroFish: attempting ensemble simulation")
        from ensemble import run_ensemble
        t0 = time.time()
        result = run_ensemble(briefing, odds=odds, game_data=game_data)
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
    return run_plan_b(briefing, runs=runs)


def _average_results(results: list[dict]) -> dict:
    """Average probability fields across multiple simulation runs."""
    base = results[0].copy()
    n = len(results)

    preds = base.get("predictions", {})
    prob_fields = {
        "moneyline": ["home_win_prob", "away_win_prob", "edge"],
        "spread": ["favorite_cover_prob", "edge"],
        "total": ["projected_total", "over_prob", "under_prob", "edge"],
        "first_half": ["h1_home_win_prob", "h1_away_win_prob", "h1_favorite_cover_prob", "h1_projected_total"],
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
