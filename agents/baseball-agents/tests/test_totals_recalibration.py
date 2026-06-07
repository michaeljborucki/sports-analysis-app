"""Regression tests for the 2026-04-21 totals-recalibration fix.

PARK_FACTORS still pinned. The two post-LLM bias corrections that were
originally part of this fix have been removed:
  - TEAM_TOTAL_HOME_OVER_BIAS_CORRECTION (removed 2026-05-04) — was producing
    100% LOCK home-under picks at hitters' parks.
  - TOTAL_UNDER_BIAS_CORRECTION (removed 2026-05-04) — once calibration + MC
    tune shipped, the constant nudge stopped flipping side calls (still 92%
    unders post-correction) while creating double-correction risk with the
    calibrator.

Bias is now handled by:
  - MC simulator advance-prob tuning (Phase A, 2026-04-27)
  - Per-(bet_type, side) isotonic calibration in `calibrate.py`
"""
import pytest

from config import PARK_FACTORS


# ---------------------------------------------------------------------------
# Removed bias corrections must NOT reappear
# ---------------------------------------------------------------------------

class TestTotalUnderBiasCorrectionRemoved:
    def test_constant_no_longer_in_config(self):
        """TOTAL_UNDER_BIAS_CORRECTION was removed 2026-05-04. Pin its absence
        so it isn't silently re-introduced."""
        import config
        assert not hasattr(config, "TOTAL_UNDER_BIAS_CORRECTION"), \
            "TOTAL_UNDER_BIAS_CORRECTION was removed 2026-05-04 — must not reappear in config.py"

    def test_no_post_llm_total_correction_logic(self):
        """`check_total_edge` must not contain a constant-nudge bias correction
        on over_prob / under_prob. Bias is handled by MC tuning + calibration."""
        import edge
        import inspect
        source = inspect.getsource(edge.check_total_edge)
        forbidden_patterns = [
            'over_prob + TOTAL_UNDER_BIAS_CORRECTION',
            'under_prob - TOTAL_UNDER_BIAS_CORRECTION',
        ]
        for pat in forbidden_patterns:
            assert pat not in source, \
                f"Removed bias-correction pattern '{pat}' reappeared in check_total_edge"


# ---------------------------------------------------------------------------
# team_total_home OVER-bias correction REMOVED 2026-05-04
#
# History: a 2026-04-22 home-side correction was added because home-team-total
# overs were losing in the pre-improvement era. After calibration + MC tune
# shipped, the bias flipped — home unders became overconfident, with the
# correction stacking ON TOP of an already-low MC distribution and producing
# 100% LOCK picks at parks like Coors (where it should never fire). The
# correction was removed and the code path is now symmetric for home/away.
# ---------------------------------------------------------------------------

class TestTeamTotalHomeBiasCorrectionRemoved:
    def test_constant_no_longer_in_config(self):
        """The constant must NOT exist in config.py — its removal is what
        prevents the home-only bias correction from being re-imported."""
        import config
        assert not hasattr(config, "TEAM_TOTAL_HOME_OVER_BIAS_CORRECTION"), \
            "TEAM_TOTAL_HOME_OVER_BIAS_CORRECTION was removed 2026-05-04 — must not reappear in config.py"

    def test_no_home_only_bias_correction_logic(self):
        """The check_team_total_edge function must NOT contain logic that
        modifies over_prob/under_prob conditionally on `side == "home"`.
        Park effects influence both teams equally — corrections must be
        symmetric across both sides or absent entirely."""
        import edge
        import inspect
        source = inspect.getsource(edge.check_team_total_edge)
        # The single legitimate `side == "home"` is the team_total selector
        # at the top of the function (`tt = odds.team_total_home if side == "home"`).
        # No assignment to over_prob or under_prob should be inside a
        # `side == "home"` conditional branch — that would be the bias-correction
        # pattern we removed.
        forbidden_patterns = [
            'over_prob = max',  # the old correction's over-side assignment
            'under_prob = min(1.0',  # the old correction's under-side assignment
        ]
        for pat in forbidden_patterns:
            assert pat not in source, \
                f"Removed bias-correction pattern '{pat}' reappeared in check_team_total_edge"


# ---------------------------------------------------------------------------
# PARK_FACTORS — pin key corrections that drove the bias fix
# ---------------------------------------------------------------------------

class TestParkFactorRecalibration:
    """Pin the 2026-04-21 corrections. If someone reverts these without
    intent, the under-bias reappears."""

    def test_sf_raised_from_severe_low(self):
        """SF was 0.85 (way below public consensus 0.92-0.98). Raised to 0.93."""
        assert PARK_FACTORS["SF"]["runs"] >= 0.92

    def test_sd_no_longer_at_0_90(self):
        assert PARK_FACTORS["SD"]["runs"] > 0.90

    def test_sea_no_longer_at_0_90(self):
        assert PARK_FACTORS["SEA"]["runs"] > 0.90

    def test_mia_no_longer_at_0_90(self):
        assert PARK_FACTORS["MIA"]["runs"] > 0.90

    def test_oak_no_longer_at_0_90(self):
        assert PARK_FACTORS["OAK"]["runs"] > 0.90

    def test_cin_reduced_from_overrated(self):
        """CIN was 1.15 (high vs public consensus 1.05-1.10). Reduced to 1.08."""
        assert PARK_FACTORS["CIN"]["runs"] <= 1.10

    def test_phi_reduced_from_overrated(self):
        assert PARK_FACTORS["PHI"]["runs"] <= 1.08

    def test_col_still_highest(self):
        """Coors must remain the most hitter-friendly park. Anchor sanity check."""
        col_runs = PARK_FACTORS["COL"]["runs"]
        for team, pf in PARK_FACTORS.items():
            if team == "COL":
                continue
            assert pf["runs"] < col_runs, \
                f"{team} runs={pf['runs']} should be < COL runs={col_runs}"

    def test_all_parks_in_sane_range(self):
        """No park should have runs factor outside [0.85, 1.35]."""
        for team, pf in PARK_FACTORS.items():
            assert 0.85 <= pf["runs"] <= 1.35, \
                f"{team}: runs={pf['runs']} out of sane range"
            assert 0.80 <= pf["hr"] <= 1.35, \
                f"{team}: hr={pf['hr']} out of sane range"

    def test_all_30_teams_present(self):
        """Team coverage is a contract — all 30 teams must have entries."""
        from config import TEAM_ABBREVS
        for team in TEAM_ABBREVS:
            assert team in PARK_FACTORS, f"{team} missing from PARK_FACTORS"
