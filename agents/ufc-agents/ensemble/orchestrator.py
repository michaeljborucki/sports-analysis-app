"""Adaptive 3-phase ensemble orchestrator.

Phase 1: Quick pass — all panel models in parallel at default temp.
Phase 2: Temperature expansion — expand disagreeing, confirm agreeing.
Phase 3: Adversarial challenge — Claude Sonnet 4 reviews surviving bets.
"""
import copy
import logging
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from config import ENSEMBLE_MODELS, CONSENSUS_MIN_VOTES, MAX_CALLS_PER_GAME

logger = logging.getLogger("mirofish.ensemble")
from ensemble.models import get_panel_models
from ensemble.runner import run_single_model
from ensemble.weights import BET_SLOTS, load_weights
from ensemble.consensus import (
    extract_vote, count_votes, check_consensus,
    weighted_average_prob, apply_stability_bonus,
    majority_vote, BET_SLOT_FIELDS,
)
from ensemble.challenger import run_challenge
from ensemble.logger import log_model_prediction

# Temperature sweep for Phase 2 expansion
EXPANSION_TEMPS = [0.5, 0.7, 0.9]
EXPANSION_RUNS_PER_TEMP = 2
CONFIRM_RUNS = 2

# Probability field mappings per bet slot for weighted averaging
PROB_FIELDS = {
    "moneyline": ["fighter_a_win_prob", "fighter_b_win_prob"],
    "total_rounds": ["over_prob", "under_prob", "projected_rounds"],
    "method": ["ko_tko_prob", "submission_prob", "decision_prob"],
}

# Map bet slots to their prediction section key
SLOT_SECTION = {
    "moneyline": "moneyline",
    "total_rounds": "total_rounds",
    "method": "method",
}

# Primary probability field per slot (for stability bonus calculation)
PRIMARY_PROB_FIELD = {
    "moneyline": "fighter_a_win_prob",
    "total_rounds": "over_prob",
    "method": "ko_tko_prob",
}


def run_phase1(briefing: str) -> tuple[list[dict], float]:
    """Phase 1: Dispatch all panel models in parallel at default temperature.

    Returns (results_list, total_cost).
    """
    panel = get_panel_models()
    logger.info("Phase 1: dispatching %d models in parallel", len(panel))
    results = []
    total_cost = 0.0
    t0 = time.time()

    def _call(key, spec):
        call_start = time.time()
        logger.debug("  Phase 1: calling %s (model=%s, temp=%.1f)", key, spec["id"], spec["default_temp"])
        r = run_single_model(
            model_key=key,
            model_id=spec["id"],
            briefing=briefing,
            temperature=spec["default_temp"],
            max_tokens=spec["max_tokens"],
            timeout=spec["timeout"],
            input_price=spec["input_price"],
            output_price=spec["output_price"],
        )
        elapsed = time.time() - call_start
        if r:
            logger.debug("  Phase 1: %s succeeded in %.1fs (cost=$%.4f)", key, elapsed, r["cost"])
        else:
            logger.warning("  Phase 1: %s failed after %.1fs", key, elapsed)
        return r

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_call, k, s): k for k, s in panel}
        for future in as_completed(futures):
            result = future.result(timeout=120)
            if result:
                results.append(result)
                total_cost += result["cost"]

    succeeded = [r["model_key"] for r in results]
    failed = [k for k, _ in panel if k not in succeeded]
    logger.info("Phase 1 complete: %d/%d models succeeded in %.1fs (cost=$%.4f)",
                len(results), len(panel), time.time() - t0, total_cost)
    if failed:
        logger.warning("Phase 1 failures: %s", ", ".join(failed))

    return results, total_cost


def classify_consensus(results: list[dict], odds: dict) -> dict:
    """Classify consensus level per bet slot from Phase 1 results.

    Returns {slot: {"level": "strong"|"soft"|"none", "count": int, "side": str|None, "votes": dict}}.
    """
    classification = {}
    for slot in BET_SLOTS:
        votes = {}
        for r in results:
            mk = r["model_key"]
            if mk not in votes:  # one vote per model in Phase 1
                votes[mk] = extract_vote(r["parsed"], slot, odds)
        side, count = count_votes(votes)
        if count >= 5:
            level = "strong"
        elif count >= 3:
            level = "soft"
        else:
            level = "none"
        classification[slot] = {
            "level": level,
            "count": count,
            "side": side,
            "votes": votes,
        }
        logger.debug("  Consensus %s: %s (%d/6 → %s) | votes: %s",
                      slot, side, count, level,
                      {k: v for k, v in votes.items()})

    summary = {info["level"]: [] for info in classification.values()}
    for slot, info in classification.items():
        summary[info["level"]].append(slot)
    logger.info("Consensus classification: strong=%s, soft=%s, none=%s",
                summary.get("strong", []), summary.get("soft", []), summary.get("none", []))
    return classification


def _get_model_majority_vote(model_key: str, results: list[dict],
                              slot: str, odds: dict) -> str | None:
    """Determine a model's vote from majority of its runs."""
    model_votes = []
    for r in results:
        if r["model_key"] == model_key:
            vote = extract_vote(r["parsed"], slot, odds)
            if vote is not None:
                model_votes.append(vote)
    if not model_votes:
        return None
    return majority_vote(model_votes, default=model_votes[0])


def _extract_prob_for_slot(parsed: dict, slot: str) -> float | None:
    """Extract the primary probability value for a bet slot."""
    field = PRIMARY_PROB_FIELD.get(slot)
    if not field:
        return None
    section_key = SLOT_SECTION[slot]
    section = parsed.get("predictions", {}).get(section_key, {})
    val = section.get(field)
    if val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            return None
    return None


def reclassify_consensus(results: list[dict], odds: dict) -> dict:
    """Re-classify consensus using per-model majority votes after Phase 2.

    Each model gets ONE vote based on the majority of its runs.
    """
    # Collect unique model keys
    model_keys = list(dict.fromkeys(r["model_key"] for r in results))

    classification = {}
    for slot in BET_SLOTS:
        votes = {}
        for mk in model_keys:
            votes[mk] = _get_model_majority_vote(mk, results, slot, odds)
        side, count = count_votes(votes)
        if count >= 5:
            level = "strong"
        elif count >= 3:
            level = "soft"
        else:
            level = "none"
        classification[slot] = {
            "level": level,
            "count": count,
            "side": side,
            "votes": votes,
        }
    return classification


def run_phase2(briefing: str, results: list[dict],
               classification: dict, odds: dict) -> tuple[list[dict], float]:
    """Phase 2: Temperature expansion for soft-consensus slots.

    Disagreeing models: 3 temps x 2 runs = 6 extra calls.
    Agreeing models: 2 more runs at default temp.

    Returns (all_results, additional_cost).
    """
    panel_dict = dict(get_panel_models())
    total_cost = 0.0
    new_results = []
    call_count = len(results)  # track total calls
    t0 = time.time()

    # Determine which models agree/disagree across any soft slot
    agreeing_models = set()
    disagreeing_models = set()

    for slot, info in classification.items():
        if info["level"] != "soft":
            continue
        for mk, vote in info["votes"].items():
            if vote == info["side"]:
                agreeing_models.add(mk)
            else:
                disagreeing_models.add(mk)

    # Models that disagree on any soft slot get full expansion
    # Models that only agree get confirmation runs
    # Remove from agreeing if also disagreeing
    agreeing_only = agreeing_models - disagreeing_models

    logger.info("Phase 2: expanding %d disagreeing models, confirming %d agreeing models",
                len(disagreeing_models), len(agreeing_only))
    logger.debug("  Disagreeing: %s", list(disagreeing_models))
    logger.debug("  Agreeing (confirm): %s", list(agreeing_only))

    def _call(key, temp):
        nonlocal call_count
        if call_count >= MAX_CALLS_PER_GAME:
            return None
        call_count += 1
        spec = panel_dict.get(key)
        if not spec:
            return None
        return run_single_model(
            model_key=key,
            model_id=spec["id"],
            briefing=briefing,
            temperature=temp,
            max_tokens=spec["max_tokens"],
            timeout=spec["timeout"],
            input_price=spec["input_price"],
            output_price=spec["output_price"],
        )

    tasks = []
    # Disagreeing models: 3 temps x 2 runs
    for mk in disagreeing_models:
        for temp in EXPANSION_TEMPS:
            for _ in range(EXPANSION_RUNS_PER_TEMP):
                tasks.append((mk, temp))

    # Agreeing models: 2 confirmation runs at default temp
    for mk in agreeing_only:
        spec = panel_dict.get(mk)
        default_temp = spec["default_temp"] if spec else 0.7
        for _ in range(CONFIRM_RUNS):
            tasks.append((mk, default_temp))

    logger.info("Phase 2: dispatching %d additional calls (budget remaining: %d)",
                len(tasks), MAX_CALLS_PER_GAME - call_count)

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_call, mk, temp): (mk, temp) for mk, temp in tasks}
        for future in as_completed(futures):
            result = future.result(timeout=120)
            if result:
                new_results.append(result)
                total_cost += result["cost"]

    logger.info("Phase 2 complete: %d new results in %.1fs (cost=$%.4f, total calls=%d)",
                len(new_results), time.time() - t0, total_cost, call_count)
    return results + new_results, total_cost


def _apply_stability_bonuses(results: list[dict], weights: dict, odds: dict) -> dict:
    """Apply stability bonus to weights for models with runs at 2+ distinct temps."""
    weights = copy.deepcopy(weights)
    model_keys = list(dict.fromkeys(r["model_key"] for r in results))

    for mk in model_keys:
        model_runs = [r for r in results if r["model_key"] == mk]
        temps = set(r["temperature"] for r in model_runs)
        if len(temps) < 2:
            continue
        for slot in BET_SLOTS:
            probs = []
            for r in model_runs:
                p = _extract_prob_for_slot(r["parsed"], slot)
                if p is not None:
                    probs.append(p)
            if len(probs) >= 2:
                std = statistics.stdev(probs)
                if mk in weights and slot in weights[mk]:
                    weights[mk][slot] = apply_stability_bonus(weights[mk][slot], std)
    return weights


def _log_all_predictions(results: list[dict], odds: dict, game_label: str) -> None:
    """Log each model's predictions per bet slot to CSV."""
    today = date.today().isoformat()
    # Track run indices per model
    model_run_idx = {}

    for r in results:
        mk = r["model_key"]
        model_run_idx[mk] = model_run_idx.get(mk, 0) + 1
        run_idx = model_run_idx[mk]

        for slot in BET_SLOTS:
            vote = extract_vote(r["parsed"], slot, odds)
            if vote is None:
                continue
            prob = _extract_prob_for_slot(r["parsed"], slot) or 0.0
            implied = odds.get("implied_probs", {})
            market_prob = implied.get("fighter_a", 0.5)  # rough fallback
            edge = prob - market_prob if prob else 0.0
            try:
                log_model_prediction(
                    date=today,
                    game=game_label,
                    model=mk,
                    bet_type=slot,
                    side=vote,
                    sim_prob=prob,
                    market_prob=market_prob,
                    edge=edge,
                    temperature=r["temperature"],
                    run_index=run_idx,
                )
            except Exception as e:
                print(f"[ensemble] Failed to log prediction for {mk}/{slot}: {e}")


def build_ensemble_result(results: list[dict], classification: dict,
                          weights: dict, killed_by_challenger: list[str]) -> dict:
    """Build final ensemble output dict.

    Starts from deepcopy of highest-weighted model's Phase 1 result.
    Applies weighted averages for probability fields.
    Removes killed slots.
    """
    if not results:
        return None

    # Find highest-weighted model (sum of weights across slots)
    model_keys = list(dict.fromkeys(r["model_key"] for r in results))
    weight_sums = {}
    for mk in model_keys:
        w = weights.get(mk, {})
        weight_sums[mk] = sum(w.get(s, 1.0) for s in BET_SLOTS)
    best_model = max(weight_sums, key=weight_sums.get)

    # Get Phase 1 result (first run) of best model
    base_result = None
    for r in results:
        if r["model_key"] == best_model:
            base_result = copy.deepcopy(r["parsed"])
            break
    if not base_result:
        return None

    predictions = base_result.get("predictions", {})

    # Weighted average for probability fields
    for slot, fields in PROB_FIELDS.items():
        section_key = SLOT_SECTION[slot]
        section = predictions.get(section_key, {})
        slot_weights = {mk: weights.get(mk, {}).get(slot, 1.0) for mk in model_keys}

        for field in fields:
            runs = []
            for r in results:
                mk = r["model_key"]
                sec = r["parsed"].get("predictions", {}).get(section_key, {})
                val = sec.get(field)
                if val is not None:
                    try:
                        runs.append({"model_key": mk, "prob": float(val)})
                    except (ValueError, TypeError):
                        continue
            if runs:
                avg = weighted_average_prob(runs, slot_weights)
                section[field] = avg

    # Predicted result: majority vote on winner/method, average round
    predicted_results = [
        r["parsed"].get("predictions", {}).get("predicted_result", {})
        for r in results if r.get("parsed")
    ]
    predicted_results = [pr for pr in predicted_results if pr]
    if predicted_results:
        winners = [pr.get("winner", "") for pr in predicted_results if pr.get("winner")]
        methods = [pr.get("method", "") for pr in predicted_results if pr.get("method")]
        rounds_list = [pr.get("round", 0) for pr in predicted_results if pr.get("round")]
        predictions["predicted_result"] = {
            "winner": majority_vote(winners, default=winners[0] if winners else ""),
            "method": majority_vote(methods, default=methods[0] if methods else ""),
            "round": round(sum(rounds_list) / len(rounds_list)) if rounds_list else 0,
        }

    # Confidence: majority vote across models
    confidence_values = []
    for r in results:
        preds = r["parsed"].get("predictions", {})
        ml_conf = preds.get("moneyline", {}).get("confidence")
        if ml_conf:
            confidence_values.append(ml_conf)
    if confidence_values:
        overall_confidence = majority_vote(confidence_values, default="medium")
        for section_key in ["moneyline", "total_rounds", "method"]:
            if section_key in predictions and isinstance(predictions[section_key], dict):
                predictions[section_key]["confidence"] = overall_confidence

    # Key factors + analyst assessments: from highest-weighted model (already in base)

    # Kill slots from challenger
    for slot in killed_by_challenger:
        section_key = SLOT_SECTION.get(slot)
        if section_key:
            predictions.pop(section_key, None)

    # Also remove slots with no consensus
    for slot, info in classification.items():
        if info["level"] == "none":
            section_key = SLOT_SECTION.get(slot)
            if section_key:
                predictions.pop(section_key, None)

    base_result["predictions"] = predictions
    return base_result


def run_ensemble(briefing: str, odds: dict = None) -> dict | None:
    """Main entry point: run the adaptive 3-phase ensemble.

    Returns complete prediction dict or None (never partial).
    Falls back to None if <3 models succeed or no surviving slots.
    """
    odds = odds or {}
    weights = load_weights()
    total_cost = 0.0
    total_calls = 0
    phase_reached = 0
    killed_list = []
    ensemble_start = time.time()
    logger.info("=" * 50)
    logger.info("Ensemble started")

    # --- Phase 1: Quick pass ---
    phase_reached = 1
    results, p1_cost = run_phase1(briefing)
    total_cost += p1_cost
    total_calls += len(results)

    unique_models = set(r["model_key"] for r in results)
    if len(unique_models) < 3:
        logger.error("Phase 1: only %d models succeeded (%s), need 3+ — aborting",
                      len(unique_models), list(unique_models))
        return None

    classification = classify_consensus(results, odds)

    # --- Phase 2: Temperature expansion (if any soft consensus) ---
    has_soft = any(info["level"] == "soft" for info in classification.values())
    if has_soft:
        phase_reached = 2
        results, p2_cost = run_phase2(briefing, results, classification, odds)
        total_cost += p2_cost
        total_calls = len(results)

        # Apply stability bonuses
        weights = _apply_stability_bonuses(results, weights, odds)

        # Reclassify with per-model majority votes
        classification = reclassify_consensus(results, odds)
        logger.info("Phase 2 reclassification complete")
        for slot, info in classification.items():
            logger.debug("  %s: %s (%d votes → %s)", slot, info["side"], info["count"], info["level"])
    else:
        logger.info("Phase 2 skipped: all slots have strong or no consensus")

    # --- Log predictions ---
    # Build a game label from briefing (first 50 chars)
    game_label = briefing[:50].replace("\n", " ").strip()
    try:
        _log_all_predictions(results, odds, game_label)
    except Exception as e:
        logger.error("Prediction logging failed: %s", e)

    # --- Determine surviving slots ---
    surviving_slots = [
        slot for slot, info in classification.items()
        if info["level"] in ("strong", "soft")
    ]

    if not surviving_slots:
        logger.warning("No surviving bet slots after consensus — returning None")
        return None

    logger.info("Surviving slots for challenger: %s", surviving_slots)

    # --- Phase 3: Adversarial challenge ---
    phase_reached = 3
    logger.info("Phase 3: adversarial challenge on %d slot(s)", len(surviving_slots))
    # Build preliminary result for challenger to review
    preliminary = build_ensemble_result(results, classification, weights, [])
    if not preliminary:
        return None

    model_agreement = {
        slot: f"{info['level']} ({info['count']}/6 agree on {info['side']})"
        for slot, info in classification.items()
        if info["level"] in ("strong", "soft")
    }

    challenge_start = time.time()
    verdicts, challenge_cost = run_challenge(
        briefing=briefing,
        ensemble_predictions=preliminary.get("predictions", {}),
        model_agreement=model_agreement,
        surviving_slots=surviving_slots,
        odds=odds,
    )
    total_cost += challenge_cost
    total_calls += 1  # challenger call
    logger.info("Phase 3 complete in %.1fs (cost=$%.4f)", time.time() - challenge_start, challenge_cost)

    for slot, info in verdicts.items():
        if info["verdict"] == "kill":
            logger.info("  Challenger verdict: %s → KILL (flaw: %s)", slot, info.get("flaw_found"))
        else:
            logger.info("  Challenger verdict: %s → %s", slot, info["verdict"])

    killed_list = [slot for slot, v in verdicts.items() if v["verdict"] == "kill"]
    surviving_after_challenge = [s for s in surviving_slots if s not in killed_list]

    if not surviving_after_challenge:
        logger.warning("All bets killed by challenger — returning None")
        return None

    logger.info("Surviving after challenge: %s (killed: %s)", surviving_after_challenge, killed_list)

    # --- Build final result ---
    final = build_ensemble_result(results, classification, weights, killed_list)
    if not final:
        return None

    # Compute model contributions
    model_keys = list(dict.fromkeys(r["model_key"] for r in results))
    model_contributions = {
        mk: {
            "runs": sum(1 for r in results if r["model_key"] == mk),
            "weight_sum": round(sum(weights.get(mk, {}).get(s, 1.0) for s in BET_SLOTS), 2),
        }
        for mk in model_keys
    }

    # Add ensemble metadata
    consensus_counts = {"strong": 0, "soft": 0, "none": 0}
    for info in classification.values():
        consensus_counts[info["level"]] = consensus_counts.get(info["level"], 0) + 1

    final["ensemble_meta"] = {
        "total_calls": total_calls,
        "phase_reached": phase_reached,
        "consensus": consensus_counts,
        "disagreement_flags": {
            slot: {
                "ratio": round((sum(1 for v in info["votes"].values() if v) - info["count"]) /
                               max(sum(1 for v in info["votes"].values() if v), 1), 2),
                "high_uncertainty": info["level"] == "soft" and info["count"] <= 3,
            }
            for slot, info in classification.items()
        },
        "killed": killed_list,
        "challenger_verdicts": verdicts,
        "model_contributions": model_contributions,
        "cost_usd": round(total_cost, 4),
    }
    final["ensemble_runs"] = 1

    ensemble_elapsed = time.time() - ensemble_start
    logger.info("Ensemble complete: phase=%d, calls=%d, cost=$%.4f, elapsed=%.1fs",
                phase_reached, total_calls, total_cost, ensemble_elapsed)
    logger.info("=" * 50)

    return final
