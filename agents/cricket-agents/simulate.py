"""Simulation layer: Plan B (direct Kimi) and MiroFish 512-agent."""
import json
import logging
import time
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, KIMI_MODEL

logger = logging.getLogger("mirofish.simulate")


SYSTEM_PROMPT = """You are an elite T20 cricket prediction system analyzing a match.
Simulate a panel of 6 expert analysts:

1. PITCH & CONDITIONS ANALYST (MOST IMPORTANT): Evaluates pitch type (batting/bowling/neutral),
   surface hardness, expected bounce and turn, dew factor (especially for night matches),
   weather impact, and how conditions will shift between innings.
2. BATTING ANALYST: Evaluates team batting depth, powerplay form, middle-over acceleration,
   death-overs hitting, strike rates, and match-up advantages vs the opposing attack.
3. BOWLING ANALYST: Evaluates bowling attack quality, powerplay wicket-taking ability,
   spin effectiveness in conditions, death-over specialists, and economy rates.
4. TOSS & CHASE ANALYST: Evaluates historical bat-first vs chase win rates at this venue,
   dew impact on second-innings chasing, and likely toss decision advantage.
5. MARKET ANALYST: Evaluates the betting lines for value. Where is public money flowing?
   Where might the market be inefficient given team form or conditions?
6. CONTRARIAN: Challenges the consensus. What obvious narrative might be wrong?
   Where is the value on the unpopular side?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "pitch_conditions", "pick": "TEAM", "reasoning": "..."},
    {"role": "batting", "pick": "TEAM", "reasoning": "..."},
    {"role": "bowling", "pick": "TEAM", "reasoning": "..."},
    {"role": "toss_chase", "pick": "TEAM", "reasoning": "..."},
    {"role": "market", "pick": "TEAM", "reasoning": "..."},
    {"role": "contrarian", "pick": "TEAM", "reasoning": "..."}
  ],
  "predictions": {
    "moneyline": {
      "team_a_win_prob": 0.XX,
      "team_b_win_prob": 0.XX,
      "value_side": "team_a|team_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_runs": {
      "projected": XXX.X,
      "confidence": "low|medium|high"
    },
    "team_total_runs": {
      "projected": XXX.X,
      "confidence": "low|medium|high"
    },
    "spread": {
      "projected": XX.X,
      "confidence": "low|medium|high"
    },
    "player_runs": [
      {"player": "Name", "projected": XX.X}
    ],
    "player_wickets": [
      {"player": "Name", "projected": X.X}
    ],
    "player_boundaries": [
      {"player": "Name", "projected": X.X}
    ],
    "player_sixes": [
      {"player": "Name", "projected": X.X}
    ],
    "powerplay_runs": {
      "projected": XX.X,
      "confidence": "low|medium|high"
    },
    "match_total_sixes": {
      "projected": XX.X,
      "confidence": "low|medium|high"
    },
    "match_total_fours": {
      "projected": XX.X,
      "confidence": "low|medium|high"
    },
    "first_over_runs": {
      "projected": X.X,
      "confidence": "low|medium|high"
    },
    "fall_of_first_wicket": {
      "projected": XX.X,
      "confidence": "low|medium|high"
    },
    "runs_conceded": [
      {"player": "Name", "projected": XX.X}
    ],
    "dot_balls": [
      {"player": "Name", "projected": X.X}
    ],
    "predicted_result": {
      "winner": "TEAM",
      "winning_margin": "X wickets|X runs",
      "projected_scores": {
        "batting_first": XXX,
        "chasing": XXX
      }
    },
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


def run_mirofish(briefing: str, runs: int = 3, odds: dict = None) -> dict | None:
    """Run multi-model ensemble simulation with Plan B fallback.

    Args:
        odds: Game odds dict for consensus normalization.
    """
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
        logger.warning("MiroFish: ensemble returned None after %.1fs, falling back to Plan B", elapsed)
    except Exception as e:
        logger.error("MiroFish: ensemble failed (%s), falling back to Plan B", e)
    return run_plan_b(briefing, runs=runs)


def _average_results(results: list[dict]) -> dict:
    """Average projected values across multiple simulation runs."""
    base = results[0].copy()
    n = len(results)
    preds = base.get("predictions", {})

    # Scalar bet types — average the "projected" field
    # Note: uses "total_runs" (LLM output key), not "match_total_runs" (BET_TYPES key)
    scalar_types = [
        "total_runs", "team_total_runs", "spread",
        "powerplay_runs", "match_total_sixes", "match_total_fours",
        "first_over_runs", "fall_of_first_wicket",
    ]
    for bet_type in scalar_types:
        values = []
        for r in results:
            val = r.get("predictions", {}).get(bet_type, {}).get("projected")
            if val is not None:
                values.append(float(val))
        if values and bet_type in preds:
            preds[bet_type]["projected"] = round(sum(values) / len(values), 1)

    # Moneyline — average probabilities
    ml_fields = ["team_a_win_prob", "team_b_win_prob", "edge"]
    for field in ml_fields:
        values = []
        for r in results:
            val = r.get("predictions", {}).get("moneyline", {}).get(field)
            if val is not None:
                values.append(float(val))
        if values and "moneyline" in preds:
            preds["moneyline"][field] = round(sum(values) / len(values), 4)

    # List bet types (player props) — average per player name
    list_types = [
        "player_runs", "player_wickets", "player_boundaries",
        "player_sixes", "runs_conceded", "dot_balls",
    ]
    for bet_type in list_types:
        player_values = {}
        for r in results:
            entries = r.get("predictions", {}).get(bet_type, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                name = entry.get("player", "")
                val = entry.get("projected")
                if name and val is not None:
                    player_values.setdefault(name, []).append(float(val))
        if player_values and bet_type in preds:
            preds[bet_type] = [
                {"player": name, "projected": round(sum(vals) / len(vals), 1)}
                for name, vals in player_values.items()
            ]

    base["predictions"] = preds
    base["ensemble_runs"] = n
    return base
