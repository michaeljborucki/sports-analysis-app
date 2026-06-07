"""Simulation layer: Plan B (direct Kimi) and MiroFish ensemble."""
import json
import logging
import time
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, KIMI_MODEL

logger = logging.getLogger("mirofish.simulate")


TENNIS_SYSTEM_PROMPT = """You are an elite tennis prediction system analyzing a professional match.
Simulate a panel of 6 expert analysts:

1. SERVE ANALYST: Evaluates serve quality, first serve percentage, ace potential,
   second serve vulnerability, and how the serve matches up against the returner's
   skills. Service game hold percentages on this surface.
2. RETURN & RALLY ANALYST: Evaluates return effectiveness, ability to neutralize
   serve, baseline rally tolerance, and break point conversion. Who controls
   the rallies from the back of the court?
3. SURFACE & CONDITIONS ANALYST: Evaluates how each player's game translates to
   this specific surface. Clay grinders on hard courts, grass specialists on clay, etc.
   Altitude, temperature, ball speed, and indoor/outdoor adjustments.
4. FORM & FITNESS ANALYST: Evaluates recent results, match load, travel schedule,
   injury concerns, and competitive sharpness. Is this player peaking or fatigued?
   Surface transition effects (just switched from clay to grass, etc.).
5. MARKET ANALYST: Evaluates the betting lines for value. Is the market
   correctly pricing the surface matchup? Is name recognition inflating the
   favorite's odds? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. What upset scenario is being overlooked?
   Is the favorite's recent form on a different surface? Is the underdog's
   style a bad matchup for the favorite? Motivation factors (defending champion
   vs player with nothing to lose)?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "serve", "pick": "PLAYER", "reasoning": "..."},
    {"role": "return", "pick": "PLAYER", "reasoning": "..."},
    {"role": "surface", "pick": "PLAYER", "reasoning": "..."},
    {"role": "form", "pick": "PLAYER", "reasoning": "..."},
    {"role": "market", "pick": "PLAYER", "reasoning": "..."},
    {"role": "contrarian", "pick": "PLAYER", "reasoning": "..."}
  ],
  "predictions": {
    "moneyline": {
      "player_a_win_prob": 0.XX,
      "player_b_win_prob": 0.XX,
      "value_side": "player_a|player_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "game_handicap": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_games": {
      "projected_games": XX.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_result": {"winner": "PLAYER", "score": "6-4 6-3"},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only."""


def parse_simulation_result(raw: str | None) -> dict | None:
    """Parse JSON response from LLM, handling common issues."""
    if not raw:
        return None
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
    """Run direct Kimi call (Plan B) — fast screen at ~$0.06/match."""
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
            response = client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[
                    {"role": "system", "content": TENNIS_SYSTEM_PROMPT},
                    {"role": "user", "content": briefing},
                ],
                temperature=0.7,
                max_tokens=12288,
            )
            elapsed = time.time() - t0
            choice = response.choices[0]
            in_tok = getattr(response.usage, 'prompt_tokens', 0)
            out_tok = getattr(response.usage, 'completion_tokens', 0)
            logger.debug("Plan B run %d: %.1fs, %d/%d tokens, finish=%s",
                         run_idx + 1, elapsed, in_tok, out_tok, choice.finish_reason)
            if choice.finish_reason == "length":
                logger.warning("Plan B run %d: response truncated", run_idx + 1)
            raw = choice.message.content
            parsed = parse_simulation_result(raw)
            if parsed:
                results.append(parsed)
            else:
                logger.warning("Plan B run %d: failed to parse JSON", run_idx + 1)
        except Exception as e:
            logger.error("Plan B run %d error: %s", run_idx + 1, e)

    if not results:
        return None
    if len(results) == 1:
        return results[0]
    return _average_results(results)


def run_mirofish(briefing: str, runs: int = 3, odds: dict = None) -> dict | None:
    """Run multi-model ensemble simulation with Plan B fallback."""
    try:
        logger.info("MiroFish: attempting ensemble simulation")
        from ensemble import run_ensemble
        t0 = time.time()
        result = run_ensemble(briefing, odds=odds)
        elapsed = time.time() - t0
        if result:
            meta = result.get("ensemble_meta", {})
            logger.info("MiroFish: ensemble succeeded in %.1fs (phase=%d, calls=%d, cost=$%.4f)",
                        elapsed, meta.get("phase_reached", 0),
                        meta.get("total_calls", 0), meta.get("cost_usd", 0))
            return result
        logger.warning("MiroFish: ensemble returned None, falling back to Plan B")
    except Exception as e:
        logger.error("MiroFish: ensemble failed (%s), falling back to Plan B", e)
    return run_plan_b(briefing, runs=runs)


def _average_results(results: list[dict]) -> dict:
    """Average probability fields across multiple simulation runs."""
    base = results[0].copy()

    preds = base.get("predictions", {})
    prob_fields = {
        "moneyline": ["player_a_win_prob", "player_b_win_prob", "edge"],
        "game_handicap": ["favorite_cover_prob", "edge"],
        "total_games": ["projected_games", "over_prob", "under_prob", "edge"],
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
    base["ensemble_runs"] = len(results)
    return base
