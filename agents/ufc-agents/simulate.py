"""UFC simulation layer — 6-expert LLM panel and ensemble integration."""
import json
import logging
import os
from openai import OpenAI

from config import KIMI_MODEL, OPENROUTER_BASE_URL, OPENROUTER_API_KEY

logger = logging.getLogger("mirofish.simulate")

UFC_SYSTEM_PROMPT = """You are an elite UFC/MMA prediction system. You MUST simulate a
panel of 6 expert analysts who each provide independent assessments.

CRITICAL CONTEXT:
- Probabilities must sum to 1.0 for any binary outcome (e.g., fighter_a + fighter_b = 1.0)
- Method probabilities must sum to 1.0 (ko_tko + submission + decision = 1.0)
- For 5-round championship bouts: cardio advantage compounds, wrestlers tend to dominate late, KO rate drops in rounds 4-5
- For 3-round fights: explosive fighters have edge, pace management less critical
- Southpaw vs orthodox stance matchup significantly impacts striking angles and lead-hand dynamics
- Reach advantage >3 inches historically correlates with higher striking differential

ANALYST PANEL:

1. STRIKING ANALYST: Evaluate stand-up technique, volume vs power balance,
   striking accuracy and defense percentages, distance management, and
   significant strike differential (landed minus absorbed per minute).
   Factor in stance matchup (orthodox vs southpaw), reach advantage,
   and head/body/leg targeting patterns. How does each fighter perform
   when pressured vs when backing up?

2. GRAPPLING ANALYST: Evaluate wrestling credentials, takedown accuracy
   and defense rates, submission threat level, ground control time per
   fight, and scrambling ability. Consider chain wrestling, cage wrestling,
   and how each fighter performs off their back vs in top position.
   What is the likelihood the fight stays standing vs goes to the ground?

3. CARDIO & DURABILITY ANALYST: Evaluate gas tank based on historical
   fight pace, significant strikes absorbed per minute (chin durability),
   round-by-round performance trends (does fighter fade or improve?),
   and recovery ability after being hurt. For 5-round fights, who has
   the conditioning advantage in championship rounds?

4. STYLE MATCHUP ANALYST: This is the MOST IMPORTANT analysis. How do these
   specific styles interact? Pressure fighter vs counter-striker, wrestler
   vs anti-wrestler, grappler vs grappler. What is each fighter's path to
   victory? Where does each fighter want the fight to take place and who
   dictates where it happens? Consider historical performance against
   similar style opponents.

5. MARKET ANALYST: Evaluate the betting lines for value. Where is the
   public money likely flowing? Is the favorite overvalued due to name
   recognition, highlight reel knockouts, or recency bias? Where might
   the market be inefficient? Consider whether the line has moved and why.

6. CONTRARIAN: Challenge the consensus. What is the obvious narrative
   that might be wrong? What upset scenario is underpriced? What if
   the favorite's chin is cracked, the underdog made a camp change,
   or the weight cut was brutal? Be specific about the contrarian case.

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "striking", "pick": "FIGHTER_NAME", "confidence": 0.XX, "reasoning": "3-5 sentences with specific stats"},
    {"role": "grappling", "pick": "FIGHTER_NAME", "confidence": 0.XX, "reasoning": "..."},
    {"role": "cardio", "pick": "FIGHTER_NAME", "confidence": 0.XX, "reasoning": "..."},
    {"role": "matchup", "pick": "FIGHTER_NAME", "confidence": 0.XX, "reasoning": "..."},
    {"role": "market", "pick": "FIGHTER_NAME", "confidence": 0.XX, "reasoning": "..."},
    {"role": "contrarian", "pick": "FIGHTER_NAME", "confidence": 0.XX, "reasoning": "..."}
  ],
  "predictions": {
    "moneyline": {
      "fighter_a_win_prob": 0.XX,
      "fighter_b_win_prob": 0.XX,
      "value_side": "fighter_a|fighter_b|none",
      "edge": 0.XX,
      "confidence": 0.XX
    },
    "total_rounds": {
      "projected_rounds": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": 0.XX
    },
    "method": {
      "ko_tko_prob": 0.XX,
      "submission_prob": 0.XX,
      "decision_prob": 0.XX,
      "most_likely": "KO/TKO|Submission|Decision",
      "value_method": "ko_tko|submission|decision|none",
      "confidence": 0.XX
    },
    "round_probabilities": {
      "round_1_finish": 0.XX,
      "round_2_finish": 0.XX,
      "round_3_finish": 0.XX,
      "round_4_finish": 0.XX,
      "round_5_finish": 0.XX,
      "goes_to_decision": 0.XX
    },
    "predicted_result": {"winner": "FIGHTER_NAME", "method": "METHOD", "round": X},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
IMPORTANT: Confidence values are 0.0-1.0 numeric (NOT categorical). 0.90 = extremely certain, 0.50 = coin flip.
Method probabilities (ko_tko + submission + decision) MUST sum to 1.0.
Round finish probabilities + goes_to_decision MUST sum to 1.0.
No markdown, no backticks, no preamble. JSON only."""


def parse_simulation_result(raw: str) -> dict | None:
    """Parse raw LLM response into structured prediction dict."""
    if not raw:
        return None
    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse simulation result as JSON")
        return None


def run_plan_b(briefing: str, runs: int = 1, odds: dict = None) -> dict | None:
    """Run direct LLM simulation via Kimi (Plan B fallback).

    Args:
        briefing: Fight briefing document string
        runs: Number of independent runs to average
        odds: Optional odds dict for context

    Returns:
        Parsed prediction dict or None on failure
    """
    client = OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=OPENROUTER_API_KEY,
    )

    results = []
    for i in range(runs):
        try:
            response = client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[
                    {"role": "system", "content": UFC_SYSTEM_PROMPT},
                    {"role": "user", "content": briefing},
                ],
                temperature=0.7,
                max_tokens=4096,
            )
            raw = response.choices[0].message.content
            parsed = parse_simulation_result(raw)
            if parsed:
                results.append(parsed)
                logger.info("Plan B run %d/%d: success", i + 1, runs)
            else:
                logger.warning("Plan B run %d/%d: parse failed", i + 1, runs)
        except Exception as e:
            logger.error("Plan B run %d/%d failed: %s", i + 1, runs, e)

    if not results:
        return None

    if len(results) == 1:
        return results[0]

    return _average_results(results)


def _average_results(results: list[dict]) -> dict:
    """Average probability estimates across multiple runs."""
    base = results[0].copy()
    n = len(results)

    # Average moneyline probabilities
    ml_fields = ["fighter_a_win_prob", "fighter_b_win_prob", "edge"]
    for field in ml_fields:
        vals = [r.get("predictions", {}).get("moneyline", {}).get(field, 0) for r in results]
        if any(vals):
            base.setdefault("predictions", {}).setdefault("moneyline", {})[field] = round(sum(vals) / n, 4)

    # Average total rounds probabilities
    tr_fields = ["projected_rounds", "over_prob", "under_prob", "edge"]
    for field in tr_fields:
        vals = [r.get("predictions", {}).get("total_rounds", {}).get(field, 0) for r in results]
        if any(vals):
            base.setdefault("predictions", {}).setdefault("total_rounds", {})[field] = round(sum(vals) / n, 4)

    # Average method probabilities
    method_fields = ["ko_tko_prob", "submission_prob", "decision_prob"]
    for field in method_fields:
        vals = [r.get("predictions", {}).get("method", {}).get(field, 0) for r in results]
        if any(vals):
            base.setdefault("predictions", {}).setdefault("method", {})[field] = round(sum(vals) / n, 4)

    return base


def run_mirofish(briefing: str, odds: dict = None) -> dict | None:
    """Run full MiroFish ensemble simulation, falling back to Plan B.

    Attempts ensemble first (if available), falls back to direct Kimi call.
    """
    try:
        from ensemble.orchestrator import run_ensemble
        result = run_ensemble(briefing, odds)
        if result:
            logger.info("Ensemble simulation succeeded")
            return result
        logger.warning("Ensemble returned None, falling back to Plan B")
    except Exception as e:
        logger.warning("Ensemble failed (%s), falling back to Plan B", e)

    return run_plan_b(briefing, runs=1, odds=odds)
