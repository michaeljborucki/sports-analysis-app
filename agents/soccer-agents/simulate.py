"""Simulation layer: Plan B (direct Kimi) and MiroFish ensemble."""
import json
import logging
import time
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, KIMI_MODEL

logger = logging.getLogger("mirofish.simulate")


SOCCER_SYSTEM_PROMPT = """You are an elite soccer/football prediction system analyzing a professional match.
Simulate a panel of 6 expert analysts:

1. xG & ATTACKING ANALYST: Evaluates expected goals data, shot quality,
   chance creation, and whether teams are over/underperforming their xG.
   Teams overperforming xG are regression candidates (bearish). Teams
   underperforming are value candidates (bullish).
2. DEFENSIVE & TACTICAL ANALYST: Evaluates defensive structure, pressing
   intensity (PPDA), clean sheet rate, and how the defensive approach
   matches up against the opponent's attacking style. Set piece vulnerability.
3. SQUAD & ROTATION ANALYST: Evaluates injuries, suspensions, and expected
   rotation. If a team has a Champions League match in 3 days, will they
   rest key players? How deep is the squad? New signings settling in?
4. MOTIVATION & CONTEXT ANALYST: Evaluates what's at stake. Title race teams
   play differently than mid-table teams with nothing to play for. Relegation
   battles create desperate, defensive football. Derbies are unpredictable.
5. MARKET ANALYST: Evaluates the betting lines for value. Is the Asian
   handicap reflecting the true quality gap? Is the total line accounting
   for both teams' xG profiles? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. Is the home team's form masking
   poor underlying xG numbers? Is the away team better than their league
   position suggests? What narrative is the market overweighting?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "xg_attacking", "pick": "TEAM_OR_SIDE", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "asian_handicap": {
      "home_cover_prob": 0.XX,
      "away_cover_prob": 0.XX,
      "value_side": "home|away|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total": {
      "projected_goals": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "btts": {
      "btts_yes_prob": 0.XX,
      "btts_no_prob": 0.XX,
      "value_side": "yes|no|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_score": {"home": X, "away": X},
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
                    {"role": "system", "content": SOCCER_SYSTEM_PROMPT},
                    {"role": "user", "content": briefing},
                ],
                temperature=0.7,
                max_tokens=12288,
            )
            elapsed = time.time() - t0
            choice = response.choices[0]
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


def run_mirofish(briefing: str, runs: int = 3, odds: dict = None,
                 match_data: dict = None) -> dict | None:
    """Run multi-model ensemble simulation with Plan B fallback.

    match_data is optional; when provided, the quant Poisson voter runs as a
    7th panel member alongside the 6 LLMs.
    """
    try:
        from ensemble import run_ensemble
        t0 = time.time()
        result = run_ensemble(briefing, odds=odds, match_data=match_data)
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
    n = len(results)

    preds = base.get("predictions", {})
    prob_fields = {
        "asian_handicap": ["home_cover_prob", "away_cover_prob", "edge"],
        "total": ["projected_goals", "over_prob", "under_prob", "edge"],
        "btts": ["btts_yes_prob", "btts_no_prob", "edge"],
    }

    for section, fields in prob_fields.items():
        if section not in preds:
            continue
        for f in fields:
            values = []
            for r in results:
                val = r.get("predictions", {}).get(section, {}).get(f)
                if val is not None:
                    values.append(float(val))
            if values:
                preds[section][f] = round(sum(values) / len(values), 4)

    base["predictions"] = preds
    base["ensemble_runs"] = n
    return base
