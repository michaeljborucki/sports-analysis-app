"""Adversarial challenge pass via Claude Sonnet 4."""
import json
import logging
from ensemble.models import get_challenger_model
from ensemble.runner import run_single_model

logger = logging.getLogger("mirofish.ensemble.challenger")

CHALLENGER_SYSTEM_PROMPT = """You are a final-check analyst reviewing a soccer betting ensemble's output.

IMPORTANT CONTEXT: These bets already passed consensus from 3-6 independent models across
multiple temperature runs. They also passed a worst-case devig filter. Your role is NOT
to second-guess reasonable predictions — it is to catch specific errors the ensemble missed.

ONLY KILL a bet if you identify a CONCRETE flaw such as:
- A factual error (wrong team stats, misidentified favorite/underdog)
- A specific blind spot the models overlooked (see checklist below)
- The edge is entirely explained by a factor the models can't assess (e.g., a key injury
  not in the briefing, known scheduling trap)
- The probability estimate is mathematically inconsistent with the analysis

DO NOT KILL a bet just because:
- The game is "hard to predict" — all games are
- You feel general uncertainty — uncertainty is already priced in
- The edge is small — the ensemble already applied edge thresholds
- You personally would pick the other side — the ensemble consensus outweighs one opinion

SOCCER-SPECIFIC BLIND SPOTS TO CHECK:
1. LINEUP ROTATION: Cup/league fixture congestion, squad rotation
2. TRAVEL FATIGUE: Continental competition (Champions League) midweek travel
3. MOTIVATION: Teams with nothing to play for, relegated teams, dead rubbers
4. WEATHER: Rain/wind affecting open stadiums
5. REFEREE TENDENCY: Strict/lenient referees affecting card/foul counts
6. TACTICAL SETUP: Bus-parking teams creating lower-scoring matches

EDGE DATA is provided below — use it to verify the ensemble's edge is real.

For each bet, respond in valid JSON only:
{
  "challenges": [
    {
      "bet_type": "asian_handicap",
      "verdict": "approve" or "kill",
      "reasoning": "...",
      "flaw_found": null or "specific flaw description"
    }
  ]
}
No markdown, no backticks, no preamble. JSON only."""


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

    return f"""BRIEFING:
{briefing}

ENSEMBLE PREDICTION:
{json.dumps(ensemble_predictions, indent=2)}

MODEL AGREEMENT:
{agreement_lines}{edge_context}

Review each bet that passed consensus. Find the weakest reasoning. Should any bet be killed?"""


def parse_challenge_response(raw: str) -> dict | None:
    """Parse challenger response into {bet_type: {verdict, reasoning, flaw_found}} dict."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if "challenges" not in data:
        return None
    return {
        c["bet_type"]: {
            "verdict": c["verdict"],
            "reasoning": c.get("reasoning", ""),
            "flaw_found": c.get("flaw_found"),
        }
        for c in data["challenges"]
        if "bet_type" in c and "verdict" in c
    }


def run_challenge(briefing: str, ensemble_predictions: dict,
                  model_agreement: dict,
                  surviving_slots: list[str],
                  odds: dict = None) -> tuple[dict, float]:
    """Run adversarial challenge. Returns (verdicts_dict, cost).
    On failure, all surviving slots are approved (challenger can't block).
    """
    model = get_challenger_model()
    if not model:
        logger.warning("No challenger model configured, approving all bets")
        return {slot: {"verdict": "approve", "reasoning": "", "flaw_found": None}
                for slot in surviving_slots}, 0

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
        return {slot: {"verdict": "approve", "reasoning": "", "flaw_found": None}
                for slot in surviving_slots}, 0

    raw_content = json.dumps(result["parsed"]) if isinstance(result["parsed"], dict) else str(result["parsed"])
    verdicts = parse_challenge_response(raw_content)

    if not verdicts:
        logger.warning("Challenger response unparseable, approving all bets")
        default = {slot: {"verdict": "approve", "reasoning": "", "flaw_found": None}
                   for slot in surviving_slots}
        return default, result["cost"]

    for slot in surviving_slots:
        if slot not in verdicts:
            verdicts[slot] = {"verdict": "approve", "reasoning": "", "flaw_found": None}

    approved = [s for s, v in verdicts.items() if v["verdict"] == "approve"]
    killed = [s for s, v in verdicts.items() if v["verdict"] == "kill"]
    logger.info("Challenger results: approved=%s, killed=%s", approved, killed)

    for s, v in verdicts.items():
        if v["verdict"] == "kill":
            logger.info("  KILL %s: %s (flaw: %s)", s, v["reasoning"], v["flaw_found"])

    return verdicts, result["cost"]
