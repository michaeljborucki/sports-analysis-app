"""Adversarial challenge pass via Claude Sonnet 4."""
import json
import logging
from ensemble.models import get_challenger_model
from ensemble.runner import run_single_model

logger = logging.getLogger("mirofish.ensemble.challenger")

CHALLENGER_SYSTEM_PROMPT = """You are a final-check analyst reviewing a tennis betting ensemble's output.

IMPORTANT CONTEXT: These bets already passed consensus from 3-6 independent models across
multiple temperature runs. They also passed a worst-case devig filter. Your role is NOT
to second-guess reasonable predictions — it is to catch specific errors the ensemble missed.

HOW TO READ THE ENSEMBLE OUTPUT (CRITICAL):

A "bet" is surfaced when the ensemble's probability for ONE side EXCEEDS the market's implied
probability for that side. This is the definition of positive expected value — it has nothing
to do with who the ensemble thinks will win. Two fields can legitimately disagree:

  - ``predicted_result.winner`` is who the majority of models vote to win (a categorical pick).
  - The moneyline BET side is whichever side the market is UNDERPRICING versus the ensemble's
    own probability.

These fields INTENTIONALLY differ when the market overprices a favorite. Example:

  Ensemble says Jodar wins 55% of the time. Market implies Jodar at 69%.
  → The ensemble's winner vote is Jodar (he's still more likely to win than not).
  → But the +EV bet is on De Minaur, because the market is paying more on De Minaur (31%)
    than the ensemble's own probability for him (45%).
  This is CORRECT value-betting logic, not a mathematical inconsistency.

DO NOT kill a bet solely because the winner-vote disagrees with the bet side. That disagreement
is the most common signature of a value bet on an overpriced favorite — precisely the kind of
bet we want to keep. Only invoke "mathematical inconsistency" when the ensemble's own numbers
literally cannot both be true (e.g. over_prob = 0.42 AND under_prob = 0.42, sim_prob below the
implied prob on the bet side, Kelly > 1.0).

ONLY KILL a bet if you identify a CONCRETE flaw such as:
- A factual error (wrong player stats, misidentified favorite/underdog)
- A specific blind spot the models overlooked (see checklist below)
- The edge is entirely explained by a factor the models can't assess (e.g., a key injury
  not in the briefing, known scheduling trap)
- An arithmetic error — e.g. sim_prob for the BET side is actually below market implied
  (negative expected value), or probabilities that must sum to 1 don't

DO NOT KILL a bet just because:
- The match is "hard to predict" — all matches are
- You feel general uncertainty — uncertainty is already priced in
- The edge is small — the ensemble already applied edge thresholds
- You personally would pick the other side — the ensemble consensus outweighs one opinion
- ``predicted_result.winner`` disagrees with the bet side (see above — this is normal)

TENNIS-SPECIFIC BLIND SPOTS TO CHECK:
1. SURFACE FORM: Hard/clay/grass specialist playing on weak surface
2. FATIGUE: Long tournament runs, consecutive week tournaments
3. HEAD-TO-HEAD: Style matchups that override ranking differences
4. RETIREMENT RISK: Known injury concerns mid-match
5. BEST-OF FORMAT: Bo3 vs Bo5 creating upset variance differences
6. WEATHER/CONDITIONS: Indoor vs outdoor, altitude, humidity

EDGE DATA is provided below — use it to verify the ensemble's edge is real.

For each bet, respond in valid JSON only:
{
  "challenges": [
    {
      "bet_type": "moneyline",
      "verdict": "approve" or "kill",
      "reasoning": "...",
      "flaw_found": null or "specific flaw description"
    }
  ]
}
No markdown, no backticks, no preamble. JSON only."""


def _strip_internal_fields(predictions: dict) -> dict:
    """Remove leading-underscore keys before sending predictions to the LLM.

    Fields like ``_per_model_medians`` are internal metadata for Python-side
    fallback logic — they bloat the prompt and have no analytic value for the
    challenger. Returns a shallow copy; does not mutate input.
    """
    cleaned = {}
    for slot, section in predictions.items():
        if isinstance(section, dict):
            cleaned[slot] = {k: v for k, v in section.items() if not str(k).startswith("_")}
        else:
            cleaned[slot] = section
    return cleaned


def build_challenge_prompt(briefing: str, ensemble_predictions: dict,
                           model_agreement: dict, odds: dict = None) -> str:
    agreement_lines = "\n".join(
        f"- {slot}: {desc}" for slot, desc in model_agreement.items()
    )

    edge_context = ""
    if odds:
        implied = odds.get("implied_probs", {})
        if implied:
            edge_lines = "\n".join(f"  {k}: {v:.4f}" for k, v in implied.items())
            edge_context = f"\n\nEDGE DATA (devigged implied probabilities):\n{edge_lines}"

    cleaned_predictions = _strip_internal_fields(ensemble_predictions)

    return f"""BRIEFING:
{briefing}

ENSEMBLE PREDICTION:
{json.dumps(cleaned_predictions, indent=2)}

MODEL AGREEMENT:
{agreement_lines}{edge_context}

Review each bet that passed consensus. Find the weakest reasoning. Should any bet be killed?"""


def parse_challenge_response(raw: str) -> dict | None:
    """Parse challenger response into {bet_type: verdict_string} dict."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if "challenges" not in data:
        return None
    verdicts = {}
    for c in data["challenges"]:
        if "bet_type" not in c or "verdict" not in c:
            continue
        verdicts[c["bet_type"]] = c["verdict"]
        if c["verdict"] == "kill":
            logger.info("  KILL %s: %s (flaw: %s)",
                        c["bet_type"], c.get("reasoning", ""), c.get("flaw_found"))
    return verdicts


def run_challenge(briefing: str, ensemble_predictions: dict,
                  model_agreement: dict,
                  surviving_slots: list[str],
                  odds: dict = None) -> tuple[dict, float]:
    """Run adversarial challenge. Returns ({bet_type: verdict_string}, cost).
    On failure, all surviving slots are approved (challenger can't block).
    """
    model = get_challenger_model()
    if not model:
        logger.warning("No challenger model configured, approving all bets")
        return {slot: "approve" for slot in surviving_slots}, 0

    logger.info("Challenger: reviewing %d slot(s) via %s", len(surviving_slots), model["id"])
    prompt = build_challenge_prompt(briefing, ensemble_predictions, model_agreement, odds=odds)

    result = run_single_model(
        model_key="claude_challenger",
        model_id=model["id"],
        briefing=prompt,
        temperature=model["default_temp"],
        max_tokens=model["max_tokens"],
        timeout=model["timeout"],
        input_price=model["input_price"],
        output_price=model["output_price"],
        system_prompt=CHALLENGER_SYSTEM_PROMPT,
    )

    if not result:
        logger.warning("Challenger call failed, approving all bets by default")
        return {slot: "approve" for slot in surviving_slots}, 0

    raw_content = json.dumps(result["parsed"]) if isinstance(result["parsed"], dict) else str(result["parsed"])
    verdicts = parse_challenge_response(raw_content)

    if not verdicts:
        logger.warning("Challenger response unparseable, approving all bets")
        return {slot: "approve" for slot in surviving_slots}, result["cost"]

    for slot in surviving_slots:
        if slot not in verdicts:
            verdicts[slot] = "approve"

    approved = [s for s, v in verdicts.items() if v == "approve"]
    killed = [s for s, v in verdicts.items() if v == "kill"]
    logger.info("Challenger results: approved=%s, killed=%s", approved, killed)

    return verdicts, result["cost"]
