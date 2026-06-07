"""Regression tests pinning the challenger system prompt's value-bet guidance.

Added 2026-04-24 after a pipeline run showed the challenger killing 7 of 9
bets with "mathematical inconsistency" reasoning that conflated two
legitimately-different fields:

  - predicted_result.winner (majority-vote pick for who wins)
  - the moneyline BET side (whichever side the market is underpricing)

When market overprices a favorite, the ensemble votes the favorite as winner
AND bets the dog for +EV — this is correct value-betting logic, not a
contradiction. The prompt now explicitly calls this out.

If these tests fail, the prompt has drifted in a way that may cause a
regression to the "kill all value bets" pattern.
"""
from ensemble.challenger import CHALLENGER_SYSTEM_PROMPT


def test_prompt_explains_winner_vote_vs_bet_side_distinction():
    """The prompt must teach the challenger that winner-vote and bet side
    can legitimately differ when the market overprices a favorite."""
    # The core distinction is explained (exact example match isn't required —
    # just the key concepts).
    lower = CHALLENGER_SYSTEM_PROMPT.lower()
    assert "predicted_result.winner" in CHALLENGER_SYSTEM_PROMPT
    assert "overprice" in lower or "overpric" in lower, (
        "Prompt must explain the 'market overprices favorite' concept"
    )
    assert "value" in lower and "bet" in lower


def test_prompt_forbids_killing_on_winner_vs_bet_mismatch():
    """Explicit instruction not to kill just because winner-vote ≠ bet side."""
    assert "DO NOT kill" in CHALLENGER_SYSTEM_PROMPT or "DO NOT KILL" in CHALLENGER_SYSTEM_PROMPT
    lower = CHALLENGER_SYSTEM_PROMPT.lower()
    # Must explicitly reference the winner-vs-bet disagreement as a
    # NON-reason to kill.
    assert "winner-vote" in lower or "winner vote" in lower or \
           "winner.*disagree" in lower or "predicted_result" in lower


def test_prompt_retains_mathematical_inconsistency_as_valid_kill_reason():
    """The challenger should still kill on TRUE arithmetic errors — we only
    narrowed the definition, we didn't remove it."""
    lower = CHALLENGER_SYSTEM_PROMPT.lower()
    assert "arithmetic" in lower or "mathematical" in lower
    # Specifically calls out the sim_prob-below-market case as a valid kill.
    assert "below market" in lower or "below implied" in lower or \
           "below the implied" in lower or "sum to 1" in lower


def test_prompt_retains_tennis_blind_spot_checklist():
    """Don't regress the existing tennis-specific blind spots that catch real
    flaws (surface form, fatigue, H2H, retirement, format, conditions)."""
    for concept in ["SURFACE", "FATIGUE", "HEAD-TO-HEAD", "RETIREMENT",
                    "BEST-OF", "WEATHER"]:
        assert concept in CHALLENGER_SYSTEM_PROMPT, f"Missing blind-spot: {concept}"


def test_prompt_retains_json_only_output_contract():
    """Output contract must remain JSON-only — no markdown, no backticks."""
    assert "JSON only" in CHALLENGER_SYSTEM_PROMPT
    assert '"challenges"' in CHALLENGER_SYSTEM_PROMPT
    assert '"verdict"' in CHALLENGER_SYSTEM_PROMPT


def test_prompt_includes_concrete_value_bet_example():
    """The Jodar/De Minaur-style example is what makes the abstract rule
    concrete. If someone strips it, the challenger starts losing the point."""
    lower = CHALLENGER_SYSTEM_PROMPT.lower()
    # The prompt includes a worked numerical example (55% model vs 69% market
    # or similar). Check for "Example" plus numeric probabilities to pin the
    # concrete-teaching-by-example structure without overfitting to exact names.
    assert "example" in lower
    # Two probability percentages in the body of the example section
    import re
    percents = re.findall(r"\d+%", CHALLENGER_SYSTEM_PROMPT)
    assert len(percents) >= 3, (
        f"Expected a worked example with ≥3 percentage values; found {percents}. "
        "Concrete numbers make the rule stick; abstract guidance doesn't."
    )
