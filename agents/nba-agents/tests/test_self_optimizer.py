import json
import os
import tempfile
import pandas as pd
from unittest.mock import patch
from agents.self_optimizer import (
    analyze_by_bet_type,
    analyze_by_edge_bucket,
    analyze_by_odds_range,
    recommend_adjustments,
    compute_model_brier_scores,
    update_model_weights,
    compute_threshold_overrides,
)


SAMPLE_BETS = pd.DataFrame([
    {"date": "2026-04-01", "game": "MIA@BOS", "bet_type": "moneyline", "side": "home",
     "odds": -150, "sim_prob": 0.62, "edge": 0.06, "kelly_pct": 0.02, "result": "W", "profit": 0.67},
    {"date": "2026-04-01", "game": "MIA@BOS", "bet_type": "total", "side": "under 8.5",
     "odds": -110, "sim_prob": 0.58, "edge": 0.05, "kelly_pct": 0.01, "result": "L", "profit": -1.0},
    {"date": "2026-04-02", "game": "LAL@BOS", "bet_type": "moneyline", "side": "away",
     "odds": 120, "sim_prob": 0.55, "edge": 0.07, "kelly_pct": 0.03, "result": "W", "profit": 1.2},
    {"date": "2026-04-02", "game": "LAL@BOS", "bet_type": "spread", "side": "away 4.5",
     "odds": -110, "sim_prob": 0.65, "edge": 0.08, "kelly_pct": 0.02, "result": "L", "profit": -1.0},
])


def test_analyze_by_bet_type():
    result = analyze_by_bet_type(SAMPLE_BETS)
    assert "moneyline" in result
    assert result["moneyline"]["wins"] == 2
    assert result["moneyline"]["total"] == 2


def test_analyze_by_edge_bucket():
    result = analyze_by_edge_bucket(SAMPLE_BETS)
    assert isinstance(result, dict)
    # Edges 0.05, 0.06, 0.07 fall in 5-8% bucket; 0.08 falls in 8-12% bucket
    assert "5-8%" in result
    assert result["5-8%"]["total"] == 3
    assert "8-12%" in result
    assert result["8-12%"]["total"] == 1


def test_analyze_by_odds_range():
    result = analyze_by_odds_range(SAMPLE_BETS)
    assert isinstance(result, dict)
    assert len(result) > 0


def test_recommend_adjustments():
    by_type = {
        "moneyline": {"total": 25, "roi": 8.5, "win_rate": 0.55},
        "total": {"total": 25, "roi": -12.0, "win_rate": 0.42},
    }
    by_edge = {}
    recs = recommend_adjustments(by_type, by_edge)
    assert any("PROFITABLE" in r for r in recs)
    assert any("LOSING" in r for r in recs)


def test_compute_model_brier_scores():
    """Test Brier score computation with mock data files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a clean predictions CSV
        preds_path = os.path.join(tmpdir, "preds.csv")
        preds = pd.DataFrame([
            {"date": "2026-04-01", "game": "MIA@BOS", "model": "kimi", "bet_type": "moneyline",
             "side": "home", "sim_prob": 0.60, "market_prob": 0.50, "edge": 0.10, "temperature": 0.5, "run_index": 1},
        ] * 12)  # 12 rows to exceed min 10
        preds.to_csv(preds_path, index=False)

        # Create matching bets CSV
        bets_path = os.path.join(tmpdir, "bets.csv")
        bets = pd.DataFrame([{
            "date": "2026-04-01", "game": "MIA@BOS", "bet_type": "moneyline",
            "side": "home", "odds": -150, "sim_prob": 0.60, "market_prob": 0.50,
            "edge": 0.10, "kelly_pct": 0.02, "confidence": "high", "market": "",
            "player": "", "result": "W", "profit": 0.67, "projected": "",
        }])
        bets.to_csv(bets_path, index=False)

        with patch("agents.self_optimizer.MODEL_PREDICTIONS_CSV", preds_path), \
             patch("agents.self_optimizer.load_bets", return_value=bets):
            scores = compute_model_brier_scores()
            assert "kimi" in scores
            assert "moneyline" in scores["kimi"]
            # Brier for prob=0.60, outcome=1.0: (0.60 - 1.0)^2 = 0.16
            assert abs(scores["kimi"]["moneyline"] - 0.16) < 0.01


def test_compute_model_brier_scores_empty():
    """Test Brier scores return empty dict when no predictions file."""
    with patch("agents.self_optimizer.MODEL_PREDICTIONS_CSV", "/nonexistent/path.csv"):
        scores = compute_model_brier_scores()
        assert scores == {}


def test_update_model_weights():
    """Test that lower Brier score gives higher weight."""
    brier_scores = {
        "kimi": {"moneyline": 0.20, "spread": 0.25},
        "gpt4o": {"moneyline": 0.15, "spread": 0.30},
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        weights_path = os.path.join(tmpdir, "weights.json")
        with patch("ensemble.weights.default_weights",
                   return_value={"kimi": {"moneyline": 1.0, "spread": 1.0},
                                 "gpt4o": {"moneyline": 1.0, "spread": 1.0}}), \
             patch("ensemble.weights.MODEL_WEIGHTS_FILE", weights_path):
            weights = update_model_weights(brier_scores)
            # Lower brier score → higher weight
            assert weights["gpt4o"]["moneyline"] > weights["kimi"]["moneyline"]
            assert os.path.exists(weights_path)


def test_compute_threshold_overrides():
    """Test threshold override rules."""
    # Create bets with enough data to trigger rules
    losing_bets = [
        {"date": f"2026-04-{i:02d}", "game": "A@B", "bet_type": "q1_total",
         "side": "over 55", "odds": -110, "sim_prob": 0.55, "edge": 0.05,
         "kelly_pct": 0.01, "confidence": "med", "market": "", "player": "",
         "result": "L", "profit": -1.0, "projected": "", "market_prob": 0.50}
        for i in range(1, 32)
    ]
    df = pd.DataFrame(losing_bets)

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("agents.self_optimizer.load_bets", return_value=df), \
             patch("agents.self_optimizer.DATA_DIR", tmpdir):
            overrides = compute_threshold_overrides()
            # -100% ROI should disable q1_total
            assert "q1_total" in overrides
            assert overrides["q1_total"] is None
