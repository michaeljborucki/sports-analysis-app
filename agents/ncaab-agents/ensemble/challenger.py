"""Adversarial challenge pass via Claude Sonnet 4."""
import json
import logging
from ensemble.models import get_challenger_model
from ensemble.runner import run_single_model

logger = logging.getLogger("mirofish.ensemble.challenger")

CHALLENGER_SYSTEM_PROMPT = """You are a final-check analyst reviewing an NCAAB basketball betting ensemble's output.

IMPORTANT CONTEXT: These bets already passed consensus from 3-6 independent models across
multiple temperature runs. The ensemble has already filtered aggressively. Your role is NOT
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

NCAAB-SPECIFIC BLIND SPOTS TO CHECK:
1. SMALL-CONFERENCE TRAPS: Mid-major inflated records against weak opponents
2. TRANSFER PORTAL CHEMISTRY: New rosters underperforming talent level (early season)
3. HOME COURT ADVANTAGE: Hostile venues can exceed the ~3.5 point average
4. PACE MISMATCH: Extreme tempo differences creating total uncertainty
5. REST AND SCHEDULING: Back-to-back games, travel, exam periods
6. SHARED BIAS CHECK: When 5-6/6 models unanimously agree on a total direction,
   consider whether this reflects genuine independent analysis or shared LLM
   training bias. LLMs systematically overestimate college basketball totals.
   Unanimous over picks deserve EXTRA scrutiny, not less. If the ensemble
   unanimously picks over and the projected total exceeds the line by less
   than 5 points, apply heightened skepticism.
   Also check: tournament experience, coaching records, and travel fatigue

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


def build_challenge_prompt(briefing: str, ensemble_predictions: dict,
                           model_agreement: dict) -> str:
    agreement_lines = "\n".join(
        f"- {slot}: {desc}" for slot, desc in model_agreement.items()
    )
    return f"""BRIEFING:
{briefing}

ENSEMBLE PREDICTION:
{json.dumps(ensemble_predictions, indent=2)}

MODEL AGREEMENT:
{agreement_lines}

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
                  surviving_slots: list[str]) -> tuple[dict, float]:
    """Run adversarial challenge. Returns (verdicts_dict, cost).
    On failure, all surviving slots are approved (challenger can't block).
    """
    model = get_challenger_model()
    if not model:
        logger.warning("No challenger model configured, approving all bets")
        return {slot: {"verdict": "approve", "reasoning": "", "flaw_found": None}
                for slot in surviving_slots}, 0

    logger.info("Challenger: reviewing %d slot(s) via %s", len(surviving_slots), model["id"])
    prompt = build_challenge_prompt(briefing, ensemble_predictions, model_agreement)

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

    return verdicts, result["cost"]
