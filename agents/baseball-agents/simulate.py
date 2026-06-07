"""Simulation layer: Plan B (direct Kimi) and MiroFish 512-agent."""
import json
import logging
import time
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, KIMI_MODEL

logger = logging.getLogger("mirofish.simulate")


MLB_SYSTEM_PROMPT = """You are an elite MLB prediction system analyzing a game.
Simulate a panel of 6 expert analysts:

1. PITCHING ANALYST: Evaluates starter quality, pitch mix, splits, rest,
   time-through-order degradation. This drives F5 predictions heavily.
2. HITTING ANALYST: Evaluates lineup strength, platoon advantages,
   hot/cold streaks, and how the lineup matches up vs the starter.
3. BULLPEN ANALYST: Evaluates bullpen availability, fatigue, and how
   the game changes after the starter exits. Critical for full game vs F5 delta.
4. ENVIRONMENT ANALYST: Evaluates park factor, weather (wind, temp),
   day/night, and how these conditions affect run scoring.
5. MARKET ANALYST: Evaluates the betting lines for value. Where is the
   public money likely flowing? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. What is the obvious narrative
   that might be wrong? Where is the value on the unpopular side?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "pitching", "game_winner": "TEAM", "reasoning": "..."},
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
    "run_line": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite_rl|underdog_rl|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total": {
      "projected_total": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "home_total_value": "over|under|none",
      "away_total_value": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "first_inning": {
      "nrfi_prob": 0.XX,
      "f1_home_lead_prob": 0.XX,
      "f1_away_lead_prob": 0.XX,
      "f1_tie_prob": 0.XX,
      "nrfi_value": "nrfi|yrfi|none",
      "f1_rl_value": "home|away|none",
      "confidence": "low|medium|high"
    },
    "first_3": {
      "f3_home_win_prob": 0.XX,
      "f3_away_win_prob": 0.XX,
      "f3_projected_total": X.X,
      "f3_home_lead_prob": 0.XX,
      "f3_away_lead_prob": 0.XX,
      "f3_tie_prob": 0.XX,
      "f3_ml_value": "home|away|none",
      "f3_total_value": "over|under|none",
      "f3_rl_value": "home|away|none",
      "confidence": "low|medium|high"
    },
    "first_5": {
      "f5_home_win_prob": 0.XX,
      "f5_away_win_prob": 0.XX,
      "f5_projected_total": X.X,
      "f5_home_lead_prob": 0.XX,
      "f5_away_lead_prob": 0.XX,
      "f5_tie_prob": 0.XX,
      "f5_ml_value": "home|away|none",
      "f5_total_value": "over|under|none",
      "f5_rl_value": "home|away|none",
      "confidence": "low|medium|high"
    },
    "predicted_score": {"away": X, "home": X},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only."""


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
        pass

    # Fallback: extract JSON object from surrounding text
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            pass

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
                    {"role": "system", "content": MLB_SYSTEM_PROMPT},
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


def run_mirofish(briefing: str, runs: int = 3, odds: dict = None, game_label: str = None) -> dict | None:
    """Run multi-model ensemble simulation with Plan B fallback.

    Args:
        odds: Game odds dict for run_line consensus normalization.
    """
    try:
        logger.info("MiroFish: attempting ensemble simulation")
        from ensemble import run_ensemble
        t0 = time.time()
        result = run_ensemble(briefing, odds=odds, game_label=game_label)
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
        "run_line": ["favorite_cover_prob", "edge"],
        "total": ["projected_total", "over_prob", "under_prob", "edge"],
        "first_inning": ["nrfi_prob", "f1_home_lead_prob", "f1_away_lead_prob", "f1_tie_prob"],
        "first_3": ["f3_home_win_prob", "f3_away_win_prob", "f3_projected_total",
                     "f3_home_lead_prob", "f3_away_lead_prob", "f3_tie_prob"],
        "first_5": ["f5_home_win_prob", "f5_away_win_prob", "f5_projected_total",
                     "f5_home_lead_prob", "f5_away_lead_prob", "f5_tie_prob"],
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
