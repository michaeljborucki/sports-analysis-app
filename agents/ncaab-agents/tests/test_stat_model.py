"""Tests for the statistical anchor model."""
import math
import pytest
from ensemble.stat_model import (
    _norm_cdf,
    project_total,
    project_spread,
    spread_to_win_prob,
    total_to_over_prob,
    run_stat_model,
    run_stat_model_as_ensemble_entry,
    MARGIN_SIGMA,
    TOTAL_SIGMA,
    H1_FRACTION,
    STAT_MODEL_KEY,
)


# ---------------------------------------------------------------------------
# Normal CDF tests
# ---------------------------------------------------------------------------

class TestNormCdf:
    def test_zero(self):
        assert abs(_norm_cdf(0) - 0.5) < 1e-6

    def test_positive(self):
        # Phi(1) ~ 0.8413
        assert abs(_norm_cdf(1.0) - 0.8413) < 0.001

    def test_negative(self):
        # Phi(-1) ~ 0.1587
        assert abs(_norm_cdf(-1.0) - 0.1587) < 0.001

    def test_large_positive(self):
        assert _norm_cdf(5.0) > 0.999

    def test_large_negative(self):
        assert _norm_cdf(-5.0) < 0.001

    def test_symmetry(self):
        assert abs(_norm_cdf(1.5) + _norm_cdf(-1.5) - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# Total projection tests
# ---------------------------------------------------------------------------

class TestProjectTotal:
    def test_average_teams(self):
        """Two perfectly average teams: 100 OE, 100 DE, 68 tempo."""
        total = project_total(100, 100, 100, 100, 68, 68)
        # (100*100/100 + 100*100/100) * 68/100 = 200 * 0.68 = 136
        assert abs(total - 136.0) < 0.1

    def test_good_offense_vs_bad_defense(self):
        """Good offense (110 OE) vs bad defense (105 DE) should score higher."""
        total_good = project_total(110, 100, 110, 100, 70, 70)
        total_avg = project_total(100, 100, 100, 100, 70, 70)
        assert total_good > total_avg

    def test_fast_tempo_increases_total(self):
        """Higher tempo = more possessions = more points."""
        total_fast = project_total(100, 100, 100, 100, 75, 75)
        total_slow = project_total(100, 100, 100, 100, 62, 62)
        assert total_fast > total_slow

    def test_cross_match_formula(self):
        """Verify cross-match: offense against opposing defense."""
        # Away: 110 OE vs Home DE of 95 -> away_pts = 110 * 95/100 = 104.5
        # Home: 105 OE vs Away DE of 100 -> home_pts = 105 * 100/100 = 105
        # Pace: (70+66)/2 = 68
        # Total = (104.5 + 105) * 68 / 100 = 142.46
        total = project_total(110, 100, 105, 95, 70, 66)
        expected = (110 * 95 / 100 + 105 * 100 / 100) * 68 / 100
        assert abs(total - round(expected, 1)) < 0.1

    def test_symmetric_teams(self):
        """Identical teams should produce a symmetric total."""
        total = project_total(105, 98, 105, 98, 70, 70)
        # Both sides: 105 * 98/100 = 102.9; total = 205.8 * 70/100 = 144.06
        expected = 2 * (105 * 98 / 100) * 70 / 100
        assert abs(total - round(expected, 1)) < 0.1


# ---------------------------------------------------------------------------
# Spread projection tests
# ---------------------------------------------------------------------------

class TestProjectSpread:
    def test_home_favored(self):
        """Home team with higher AdjEM should be favored (negative spread)."""
        spread = project_spread(away_em=5.0, home_em=15.0)
        assert spread < 0  # negative = home favored

    def test_away_favored(self):
        """Away team with higher AdjEM should be favored (positive spread)."""
        spread = project_spread(away_em=20.0, home_em=5.0)
        assert spread > 0  # positive = away favored

    def test_equal_teams_home_advantage(self):
        """Equal teams: home court should make home a slight favorite."""
        spread = project_spread(away_em=10.0, home_em=10.0)
        # HCA = 3.5, so spread = -(0 + 3.5) = -3.5
        assert abs(spread - (-3.5)) < 0.1

    def test_neutral_site(self):
        """Equal teams on neutral site: spread = 0."""
        spread = project_spread(away_em=10.0, home_em=10.0, neutral=True)
        assert abs(spread) < 0.1

    def test_magnitude_scales_with_gap(self):
        """Bigger AdjEM gap = bigger spread."""
        spread_small = project_spread(away_em=10.0, home_em=12.0)
        spread_large = project_spread(away_em=5.0, home_em=20.0)
        assert abs(spread_large) > abs(spread_small)


# ---------------------------------------------------------------------------
# Win probability tests
# ---------------------------------------------------------------------------

class TestSpreadToWinProb:
    def test_even_spread(self):
        """Spread of 0 -> 50% win probability."""
        prob = spread_to_win_prob(0.0)
        assert abs(prob - 0.5) < 0.01

    def test_home_favored(self):
        """Negative spread (home favored) -> home_win_prob > 0.5."""
        prob = spread_to_win_prob(-7.0)
        assert prob > 0.6

    def test_away_favored(self):
        """Positive spread (away favored) -> home_win_prob < 0.5."""
        prob = spread_to_win_prob(7.0)
        assert prob < 0.4

    def test_known_value(self):
        """Spread = -11 (one sigma) -> ~84.1% home win."""
        prob = spread_to_win_prob(-MARGIN_SIGMA)
        assert abs(prob - 0.8413) < 0.01

    def test_symmetry(self):
        """Spread symmetry: P(home, -X) + P(home, +X) = 1."""
        p_fav = spread_to_win_prob(-5.0)
        p_dog = spread_to_win_prob(5.0)
        assert abs(p_fav + p_dog - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Over/under probability tests
# ---------------------------------------------------------------------------

class TestTotalToOverProb:
    def test_projected_equals_line(self):
        """Projected total equals line -> 50%."""
        prob = total_to_over_prob(145.0, 145.0)
        assert abs(prob - 0.5) < 0.01

    def test_projected_above_line(self):
        """Projected above line -> over favored."""
        prob = total_to_over_prob(150.0, 140.0)
        assert prob > 0.7

    def test_projected_below_line(self):
        """Projected below line -> under favored."""
        prob = total_to_over_prob(130.0, 145.0)
        assert prob < 0.3

    def test_one_sigma_above(self):
        """One sigma above line -> ~84.1% over."""
        prob = total_to_over_prob(145.0 + TOTAL_SIGMA, 145.0)
        assert abs(prob - 0.8413) < 0.01


# ---------------------------------------------------------------------------
# Full model integration tests
# ---------------------------------------------------------------------------

def _make_game_data(away_oe=105, away_de=98, home_oe=108, home_de=95,
                    away_tempo=70, home_tempo=68, neutral=False,
                    spread_home=-6.5, total_line=145.0):
    """Build a minimal game_data dict for testing."""
    return {
        "away_team": "Team A",
        "home_team": "Team B",
        "away_stats": {
            "adj_oe": away_oe,
            "adj_de": away_de,
            "adj_tempo": away_tempo,
            "team": "Team A",
        },
        "home_stats": {
            "adj_oe": home_oe,
            "adj_de": home_de,
            "adj_tempo": home_tempo,
            "team": "Team B",
        },
        "odds": {
            "moneyline": {"home": -250, "away": 200},
            "spread": {
                "home": spread_home,
                "home_odds": -110,
                "away": -spread_home,
                "away_odds": -110,
            },
            "total": {"line": total_line, "over_odds": -110, "under_odds": -110},
            "h1_moneyline": {"home": -180, "away": 150},
            "h1_total": {"line": round(total_line * 0.48, 1), "over_odds": -110, "under_odds": -110},
            "h1_spread": {
                "home": round(spread_home * 0.48, 1),
                "home_odds": -110,
                "away": round(-spread_home * 0.48, 1),
                "away_odds": -110,
            },
            "implied_probs": {"ml_home": 0.71, "ml_away": 0.29},
        },
        "matchup": {"neutral_site": neutral},
    }


class TestRunStatModel:
    def test_returns_valid_structure(self):
        """Output must match the LLM prediction JSON schema."""
        gd = _make_game_data()
        result = run_stat_model(gd)
        assert result is not None
        assert "predictions" in result
        assert "analyst_assessments" in result

        preds = result["predictions"]
        assert "moneyline" in preds
        assert "spread" in preds
        assert "total" in preds
        assert "first_half" in preds
        assert "predicted_score" in preds
        assert "key_factors" in preds

    def test_moneyline_probs_sum_to_one(self):
        gd = _make_game_data()
        result = run_stat_model(gd)
        ml = result["predictions"]["moneyline"]
        total = ml["home_win_prob"] + ml["away_win_prob"]
        assert abs(total - 1.0) < 0.001

    def test_total_probs_sum_to_one(self):
        gd = _make_game_data()
        result = run_stat_model(gd)
        tot = result["predictions"]["total"]
        total = tot["over_prob"] + tot["under_prob"]
        assert abs(total - 1.0) < 0.001

    def test_h1_probs_sum_to_one(self):
        gd = _make_game_data()
        result = run_stat_model(gd)
        h1 = result["predictions"]["first_half"]
        total = h1["h1_home_win_prob"] + h1["h1_away_win_prob"]
        assert abs(total - 1.0) < 0.001

    def test_h1_over_under_sum_to_one(self):
        gd = _make_game_data()
        result = run_stat_model(gd)
        h1 = result["predictions"]["first_half"]
        total = h1["h1_over_prob"] + h1["h1_under_prob"]
        assert abs(total - 1.0) < 0.001

    def test_home_favorite_has_higher_win_prob(self):
        """When home has better stats, home_win_prob > 0.5."""
        gd = _make_game_data(home_oe=115, home_de=90, away_oe=100, away_de=100)
        result = run_stat_model(gd)
        ml = result["predictions"]["moneyline"]
        assert ml["home_win_prob"] > 0.5

    def test_returns_none_without_stats(self):
        """Missing efficiency data should return None."""
        gd = _make_game_data(away_oe=0, home_oe=0)
        result = run_stat_model(gd)
        assert result is None

    def test_neutral_site_no_hca(self):
        """Neutral site: equal teams should produce ~50/50."""
        gd = _make_game_data(
            away_oe=105, away_de=98, home_oe=105, home_de=98,
            away_tempo=68, home_tempo=68, neutral=True,
            spread_home=0.0,  # pick-em on neutral site
        )
        result = run_stat_model(gd)
        ml = result["predictions"]["moneyline"]
        assert abs(ml["home_win_prob"] - 0.5) < 0.05

    def test_confidence_labels_valid(self):
        gd = _make_game_data()
        result = run_stat_model(gd)
        valid = {"low", "medium", "high"}
        assert result["predictions"]["moneyline"]["confidence"] in valid
        assert result["predictions"]["spread"]["confidence"] in valid
        assert result["predictions"]["total"]["confidence"] in valid
        assert result["predictions"]["first_half"]["confidence"] in valid

    def test_value_sides_valid(self):
        gd = _make_game_data()
        result = run_stat_model(gd)
        assert result["predictions"]["moneyline"]["value_side"] in ("home", "away", "none")
        assert result["predictions"]["spread"]["value_side"] in ("favorite", "underdog", "none")
        assert result["predictions"]["total"]["value_side"] in ("over", "under", "none")

    def test_h1_total_is_fraction_of_full(self):
        """H1 projected total should be ~48% of full-game total."""
        gd = _make_game_data()
        result = run_stat_model(gd)
        full_total = result["predictions"]["total"]["projected_total"]
        h1_total = result["predictions"]["first_half"]["h1_projected_total"]
        ratio = h1_total / full_total
        assert abs(ratio - H1_FRACTION) < 0.02

    def test_predicted_score_reasonable(self):
        """Individual team scores should be positive and sum to ~total."""
        gd = _make_game_data()
        result = run_stat_model(gd)
        score = result["predictions"]["predicted_score"]
        assert score["home"] > 40
        assert score["away"] > 40
        total_score = score["home"] + score["away"]
        projected_total = result["predictions"]["total"]["projected_total"]
        assert abs(total_score - projected_total) < 15  # rough check

    def test_market_blending(self):
        """Model should blend toward market line (not purely model-driven)."""
        # Model projects a very different total than market
        gd = _make_game_data(
            away_oe=115, away_de=90, home_oe=115, home_de=90,
            away_tempo=75, home_tempo=75, total_line=130.0,
        )
        result = run_stat_model(gd)
        proj_total = result["predictions"]["total"]["projected_total"]
        # Should be between raw model total and market line
        raw_total = project_total(115, 90, 115, 90, 75, 75)
        assert proj_total < raw_total  # pulled toward 130
        assert proj_total > 130.0       # still above market


class TestEnsembleEntry:
    def test_wrapper_format(self):
        gd = _make_game_data()
        entry = run_stat_model_as_ensemble_entry(gd)
        assert entry is not None
        assert entry["model_key"] == STAT_MODEL_KEY
        assert entry["temperature"] == 0.0
        assert entry["cost"] == 0.0
        assert "predictions" in entry["parsed"]

    def test_wrapper_returns_none_on_missing_data(self):
        gd = _make_game_data(away_oe=0)
        entry = run_stat_model_as_ensemble_entry(gd)
        assert entry is None

    def test_passes_coherence_check(self):
        """Stat model output should pass the ensemble's coherence validator."""
        from ensemble.consensus import validate_prediction_coherence
        gd = _make_game_data()
        entry = run_stat_model_as_ensemble_entry(gd)
        assert validate_prediction_coherence(entry["parsed"])
