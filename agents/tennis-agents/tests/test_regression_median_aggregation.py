"""Regression tests pinning the median-of-model-medians aggregation.

Before 2026-04-23, ``build_ensemble_result`` used ``weighted_average_prob``
(weighted arithmetic mean across model medians) to compute each probability
field. That produced two problems:

1. **Signal compression under disagreement**: with 4 models at 0.70 and 2 at
   0.30, the mean came out to 0.53 — insufficient to beat edge thresholds
   even though the majority clearly favored a bet.
2. **Internal inconsistency with ``predicted_result.winner``** (which uses
   majority vote): the mean could pull the aggregated moneyline probability
   to the opposite side of the winner-vote, creating the "model picks A to
   win but bet says A has negative edge" contradiction the challenger
   rightly killed (Lehecka vs Tabilo case, 2026-04-23).

Fix: switch to ``statistics.median(model_medians.values())`` in the final
aggregation step of ``build_ensemble_result``. Median preserves the 4-of-6
majority without averaging drag, and stays consistent with the winner vote.

These tests pin the behavior so it doesn't regress.
"""
import inspect

from ensemble import orchestrator


def _mk_run(model_key: str, prob_ml_a: float,
            prob_ml_b: float | None = None) -> dict:
    """Minimal fake ensemble run result for testing."""
    if prob_ml_b is None:
        prob_ml_b = round(1.0 - prob_ml_a, 4)
    return {
        "model_key": model_key,
        "temperature": 0.7,
        "parsed": {
            "predictions": {
                "moneyline": {
                    "player_a_win_prob": prob_ml_a,
                    "player_b_win_prob": prob_ml_b,
                    "confidence": "medium",
                },
                "game_handicap": {"favorite_cover_prob": 0.5, "confidence": "medium"},
                "total_games": {"over_prob": 0.5, "under_prob": 0.5,
                                "projected_games": 22.0, "confidence": "medium"},
                "predicted_result": {"winner": "A" if prob_ml_a > 0.5 else "B",
                                    "score": "6-4 6-3"},
            },
        },
    }


def _classification_strong_moneyline() -> dict:
    from ensemble.weights import BET_SLOTS
    return {
        slot: {"level": "strong" if slot == "moneyline" else "none",
               "count": 6 if slot == "moneyline" else 2,
               "side": "player_a" if slot == "moneyline" else None,
               "votes": {}}
        for slot in BET_SLOTS
    }


# ==========================================================================
#  Static analysis — source-level contracts
# ==========================================================================


def test_build_ensemble_result_uses_median_not_weighted_average():
    """``build_ensemble_result`` must call ``statistics.median`` on model_medians,
    not ``weighted_average_prob``. If the code drifts back to weighted mean,
    this test fires."""
    src = inspect.getsource(orchestrator.build_ensemble_result)
    assert "statistics.median(model_medians.values())" in src, (
        "build_ensemble_result must aggregate model medians using "
        "statistics.median(), not weighted_average_prob()"
    )
    # Weighted-average usage must be gone from this function
    assert "weighted_average_prob(" not in src, (
        "weighted_average_prob was found in build_ensemble_result — it was "
        "replaced by median aggregation to avoid signal compression under "
        "majority-minority disagreement."
    )


# ==========================================================================
#  Behavioral tests — what does build_ensemble_result actually produce?
# ==========================================================================


def test_median_preserves_four_of_six_majority():
    """4 models at 0.70 + 2 at 0.30 → aggregated = 0.70 (median), NOT 0.53 (mean).
    This is the core case mean aggregation was failing on."""
    results = [
        _mk_run("a", 0.70), _mk_run("b", 0.70), _mk_run("c", 0.70), _mk_run("d", 0.70),
        _mk_run("e", 0.30), _mk_run("f", 0.30),
    ]
    classification = _classification_strong_moneyline()
    result = orchestrator.build_ensemble_result(
        results, classification, weights={}, killed_by_challenger=[]
    )
    ml = result["predictions"]["moneyline"]
    # Median of [0.70, 0.70, 0.70, 0.70, 0.30, 0.30] = average of 3rd and 4th = 0.70
    assert ml["player_a_win_prob"] == 0.70, (
        f"Expected median 0.70 for 4-2 majority, got {ml['player_a_win_prob']} "
        f"(likely reverted to mean ≈ 0.53)"
    )


def test_median_tolerates_single_outlier():
    """5 models at 0.75 + 1 at 0.25 → aggregated = 0.75 (median), NOT 0.67 (mean).
    A single dissenter shouldn't drag the aggregate."""
    results = [
        _mk_run("a", 0.75), _mk_run("b", 0.75), _mk_run("c", 0.75),
        _mk_run("d", 0.75), _mk_run("e", 0.75), _mk_run("f", 0.25),
    ]
    classification = _classification_strong_moneyline()
    result = orchestrator.build_ensemble_result(
        results, classification, weights={}, killed_by_challenger=[]
    )
    assert result["predictions"]["moneyline"]["player_a_win_prob"] == 0.75


def test_median_unanimous_passes_through():
    """All 6 models at 0.65 → aggregated = 0.65 (no movement)."""
    results = [_mk_run(m, 0.65) for m in "abcdef"]
    classification = _classification_strong_moneyline()
    result = orchestrator.build_ensemble_result(
        results, classification, weights={}, killed_by_challenger=[]
    )
    assert result["predictions"]["moneyline"]["player_a_win_prob"] == 0.65


def test_median_split_tie_compromises():
    """3 at 0.70 + 3 at 0.30 → median = avg of 3rd and 4th sorted = 0.50.
    When no majority exists, median lands at the boundary — the ensemble
    correctly produces a 'no edge' output in the tied case."""
    results = [
        _mk_run("a", 0.70), _mk_run("b", 0.70), _mk_run("c", 0.70),
        _mk_run("d", 0.30), _mk_run("e", 0.30), _mk_run("f", 0.30),
    ]
    classification = _classification_strong_moneyline()
    result = orchestrator.build_ensemble_result(
        results, classification, weights={}, killed_by_challenger=[]
    )
    # Sorted: [0.30, 0.30, 0.30, 0.70, 0.70, 0.70] → median = (0.30+0.70)/2 = 0.50
    assert result["predictions"]["moneyline"]["player_a_win_prob"] == 0.50


def test_median_aggregates_per_model_medians_not_raw_runs():
    """Each model's multiple runs still collapse to that model's median FIRST.
    Then the outer median is taken across those per-model medians — not across
    raw runs. This keeps per-model noise from inflating any single opinion."""
    # Model A has one outlier run; its median should be the middle value, not the mean
    results = [
        _mk_run("a", 0.80), _mk_run("a", 0.70), _mk_run("a", 0.10),  # median of A = 0.70
        _mk_run("b", 0.70), _mk_run("c", 0.70), _mk_run("d", 0.70),
        _mk_run("e", 0.30), _mk_run("f", 0.30),
    ]
    classification = _classification_strong_moneyline()
    result = orchestrator.build_ensemble_result(
        results, classification, weights={}, killed_by_challenger=[]
    )
    # Per-model medians: A=0.70, B=0.70, C=0.70, D=0.70, E=0.30, F=0.30
    # Outer median of [0.30, 0.30, 0.70, 0.70, 0.70, 0.70] = 0.70
    assert result["predictions"]["moneyline"]["player_a_win_prob"] == 0.70


def test_median_consistent_with_majority_winner():
    """The aggregated prob and the majority-vote winner must point the same
    way. This was the Lehecka vs Tabilo bug — mean pulled the moneyline prob
    to 'Tabilo has edge' while the winner vote said 'Lehecka wins'. Median
    eliminates that class of inconsistency."""
    results = [
        _mk_run("a", 0.65),  # winner=A
        _mk_run("b", 0.65),  # winner=A
        _mk_run("c", 0.62),  # winner=A
        _mk_run("d", 0.60),  # winner=A
        _mk_run("e", 0.35),  # winner=B
        _mk_run("f", 0.35),  # winner=B
    ]
    classification = _classification_strong_moneyline()
    result = orchestrator.build_ensemble_result(
        results, classification, weights={}, killed_by_challenger=[]
    )
    # 4 of 6 predict A wins. Median prob of [0.35, 0.35, 0.60, 0.62, 0.65, 0.65] = 0.61
    assert result["predictions"]["moneyline"]["player_a_win_prob"] > 0.5, (
        "Aggregated probability must agree with the majority-vote winner "
        "direction. This is what median-of-model-medians guarantees (and "
        "mean aggregation historically violated)."
    )
    assert result["predictions"]["predicted_result"]["winner"] == "A"
