import json
import os
import tempfile
import pandas as pd
from agents.self_optimizer import (
    analyze_by_bet_type,
    analyze_by_edge_bucket,
    analyze_by_odds_range,
    recommend_adjustments,
    compute_model_brier_scores,
    update_model_weights,
)


SAMPLE_BETS = pd.DataFrame([
    {"date": "2026-04-01", "game": "LA Galaxy@Inter Miami CF", "bet_type": "asian_handicap", "side": "home -0.5",
     "odds": -110, "sim_prob": 0.58, "edge": 0.06, "kelly_pct": 0.02, "result": "W", "profit": 0.91},
    {"date": "2026-04-01", "game": "LA Galaxy@Inter Miami CF", "bet_type": "total", "side": "under 2.5",
     "odds": -105, "sim_prob": 0.58, "edge": 0.05, "kelly_pct": 0.01, "result": "L", "profit": -1.0},
    {"date": "2026-04-02", "game": "Ajax@PSV", "bet_type": "asian_handicap", "side": "away 0.5",
     "odds": -110, "sim_prob": 0.55, "edge": 0.07, "kelly_pct": 0.03, "result": "W", "profit": 0.91},
    {"date": "2026-04-02", "game": "Ajax@PSV", "bet_type": "btts", "side": "yes",
     "odds": -120, "sim_prob": 0.65, "edge": 0.08, "kelly_pct": 0.02, "result": "L", "profit": -1.0},
])


def test_analyze_by_bet_type():
    result = analyze_by_bet_type(SAMPLE_BETS)
    assert "asian_handicap" in result
    assert result["asian_handicap"]["wins"] == 2
    assert result["asian_handicap"]["total"] == 2


def test_analyze_by_edge_bucket():
    result = analyze_by_edge_bucket(SAMPLE_BETS)
    assert isinstance(result, dict)
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
        "asian_handicap": {"total": 25, "roi": 8.5, "win_rate": 0.55},
        "total": {"total": 25, "roi": -12.0, "win_rate": 0.42},
    }
    by_edge = {}
    recs = recommend_adjustments(by_type, by_edge)
    assert any("PROFITABLE" in r for r in recs)
    assert any("LOSING" in r for r in recs)


def test_compute_model_brier_scores():
    preds_df = pd.DataFrame([
        {"model": "kimi", "bet_type": "asian_handicap", "sim_prob": 0.60, "side": "home -0.5"},
        {"model": "kimi", "bet_type": "asian_handicap", "sim_prob": 0.55, "side": "home -0.5"},
        {"model": "gpt4o", "bet_type": "asian_handicap", "sim_prob": 0.70, "side": "home -0.5"},
    ])
    bets_df = pd.DataFrame([
        {"bet_type": "asian_handicap", "result": "W", "date": "2026-03-28", "game": "Ajax@PSV"},
        {"bet_type": "asian_handicap", "result": "L", "date": "2026-03-29", "game": "Inter@Milan"},
    ])
    scores = compute_model_brier_scores(preds_df, bets_df)
    assert "kimi" in scores
    assert "asian_handicap" in scores["kimi"]


def test_compute_model_brier_scores_empty():
    scores = compute_model_brier_scores(pd.DataFrame(), pd.DataFrame())
    assert scores == {}


def test_update_model_weights_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        weights_path = os.path.join(tmpdir, "weights.json")
        brier_scores = {
            "kimi": {"asian_handicap": 0.20, "total": 0.25},
            "gpt4o": {"asian_handicap": 0.15, "total": 0.30},
        }
        update_model_weights(brier_scores, weights_path)
        assert os.path.exists(weights_path)
        with open(weights_path) as f:
            weights = json.load(f)
        assert weights["gpt4o"]["asian_handicap"] > weights["kimi"]["asian_handicap"]
