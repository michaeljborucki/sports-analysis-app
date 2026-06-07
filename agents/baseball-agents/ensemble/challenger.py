"""Adversarial challenge pass via Claude Sonnet 4."""
import json
import logging
from ensemble.models import get_challenger_model
from ensemble.runner import run_single_model

logger = logging.getLogger("mirofish.ensemble.challenger")

CHALLENGER_SYSTEM_PROMPT = """You are a final-check analyst reviewing an MLB betting ensemble's output.

IMPORTANT CONTEXT: These bets already passed consensus from 3-6 independent models across
multiple temperature runs. They also passed a worst-case devig filter — meaning even if ALL
sportsbook vig were loaded onto the bettor's side, the model still shows positive edge.
The ensemble has already filtered aggressively. Your role is NOT to second-guess reasonable
predictions — it is to catch specific errors the ensemble missed.

ONLY KILL a bet if you identify a CONCRETE flaw such as:
- A factual error (wrong pitcher, misidentified stats, wrong team matchup)
- A specific blind spot the models overlooked (see checklist below)
- The probability estimate is mathematically inconsistent with the analysis
- A known factor not in the briefing (confirmed injury, weather, lineup change)

DO NOT KILL a bet just because:
- The game is "hard to predict" — all games are
- You feel general uncertainty — uncertainty is already priced in
- The edge is small — the ensemble already applied edge thresholds and worst-case filters
- You personally would pick the other side — the ensemble consensus outweighs one opinion
- The moneyline or side pick is in a close game — close games can still have edge

MLB-SPECIFIC BLIND SPOTS TO CHECK:
1. PITCHER MISMATCH: Starter's recent form vs season averages, bullpen availability
2. LINEUP CHANGES: Key hitters resting, platoon splits not accounted for
3. PARK FACTORS: Extreme parks (Coors, Oracle) creating misleading totals
4. WEATHER: Wind, temperature affecting ball carry (outdoor parks only)
5. REST AND TRAVEL: Cross-country travel, day games after night games
6. BULLPEN FATIGUE: Heavy recent usage creating late-game vulnerability

EDGE DATA is provided below. Use it to understand the mathematical basis — if a bet has
strong consensus AND survives worst-case devig, the bar for killing should be very high.

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
                           model_agreement: dict, odds: dict = None) -> str:
    agreement_lines = "\n".join(
        f"- {slot}: {desc}" for slot, desc in model_agreement.items()
    )

    # Build edge context from odds data
    edge_context = ""
    if odds:
        implied = odds.get("implied_probs", {})
        if implied:
            edge_lines = []
            for key, val in implied.items():
                if not key.endswith("_worst") and not key.endswith("_book_count"):
                    worst_key = f"{key}_worst"
                    worst_val = implied.get(worst_key)
                    if worst_val is not None:
                        edge_lines.append(f"  {key}: consensus={val:.4f}, worst_case={worst_val:.4f}")
                    else:
                        edge_lines.append(f"  {key}: consensus={val:.4f}")
            book_count = implied.get("ml_book_count", implied.get("rl_book_count", "?"))
            edge_lines.append(f"  book_count: {book_count}")
            edge_context = "\n\nMARKET EDGE DATA (multi-book consensus, power-devigged):\n" + "\n".join(edge_lines)

    return f"""BRIEFING:
{briefing}

ENSEMBLE PREDICTION:
{json.dumps(ensemble_predictions, indent=2)}

MODEL AGREEMENT:
{agreement_lines}{edge_context}

Review each bet that passed consensus. Only kill if you find a CONCRETE flaw — not general uncertainty."""


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
    prompt = build_challenge_prompt(briefing, ensemble_predictions, model_agreement, odds)

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

    # Log reasoning for killed bets
    for slot in killed:
        v = verdicts[slot]
        logger.info("  KILL %s: %s | flaw: %s", slot, v["reasoning"], v["flaw_found"])

    return verdicts, result["cost"]
