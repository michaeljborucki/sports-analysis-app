"""Tune-down of PITCHER_REGRESS_BF (2026-05-17).

Diagnosis: 10-day grading showed pitcher_strikeouts was -30.9% ROI on 56
graded picks, with model probabilities clustering at exactly 59.5% across
wildly different pitchers (rookies + Ohtani both rated identically).

Root cause: PITCHER_REGRESS_BF=150 over-regressed elite pitchers toward
the league-average K rate. At 100 BF an elite pitcher (k_pct≈0.33) was
getting blended to ~0.26, then TTOP + platoon cuts collapsed everyone to
~0.22-0.23 effective K rate → near-constant under probabilities.

Fix: drop PITCHER_REGRESS_BF from 150 → 50. Pitchers in the 50-200 BF
range now retain substantially more of their own K-rate signal; rookies
with <30 BF still get league-mean regression.
"""
import importlib

from scrapers import player_stats


def test_pitcher_regress_bf_is_fifty():
    assert player_stats.PITCHER_REGRESS_BF == 50, \
        f"PITCHER_REGRESS_BF should be 50 (was 150 pre-fix), got {player_stats.PITCHER_REGRESS_BF}"


def test_elite_pitcher_at_100bf_retains_most_of_true_rate():
    """An elite K pitcher (true k=0.33) with 100 BF should regress to a
    rate ABOVE 0.29 after blending — i.e., the elite signal survives."""
    league = 0.224
    regressed = player_stats._regress_to_mean(0.33, 100, league, player_stats.PITCHER_REGRESS_BF)
    assert regressed > 0.29, \
        f"Elite pitcher (0.33 K rate, 100 BF) should stay above 0.29 — got {regressed:.3f}"


def test_rookie_with_low_bf_still_heavily_regressed():
    """A rookie with 20 BF should still get meaningfully regressed toward
    the league mean — we don't want small-sample noise dominating."""
    league = 0.224
    regressed = player_stats._regress_to_mean(0.40, 20, league, player_stats.PITCHER_REGRESS_BF)
    # At 20 BF with PITCHER_REGRESS_BF=50, weight = 20/70 ≈ 0.286.
    # Expected: 0.286 * 0.40 + 0.714 * 0.224 ≈ 0.271
    assert 0.25 < regressed < 0.30, \
        f"Rookie regression should land in 0.25-0.30 band — got {regressed:.3f}"


def test_veteran_with_200bf_nearly_own_rate():
    """A veteran with 200 BF should be very close to his observed rate."""
    league = 0.224
    regressed = player_stats._regress_to_mean(0.31, 200, league, player_stats.PITCHER_REGRESS_BF)
    # weight = 200/250 = 0.80. 0.80*0.31 + 0.20*0.224 = 0.289
    assert 0.28 < regressed < 0.30, \
        f"Veteran regression should land in 0.28-0.30 band — got {regressed:.3f}"


def test_elite_more_differentiated_from_average_post_fix():
    """The whole point: elite pitchers should now look meaningfully
    different from average pitchers in the model, where before they
    looked similar after regression."""
    league = 0.224
    elite_100 = player_stats._regress_to_mean(0.33, 100, league, player_stats.PITCHER_REGRESS_BF)
    avg_100 = player_stats._regress_to_mean(0.224, 100, league, player_stats.PITCHER_REGRESS_BF)
    gap = elite_100 - avg_100
    assert gap > 0.06, \
        f"Elite minus average gap after regression should exceed 0.06 — got {gap:.3f}"
