"""Regression tests for every BET_FILTERS rule key.

Seed config today only uses ``max_edge`` per type. But the filter function
supports ``disabled``, ``min_edge``, ``max_edge``, ``side_contains``,
``odds_min``, ``odds_max``, and ``line_in``. Each of those is code we could
silently break without noticing — there's no caller yet to trip the bug.
These tests exercise every rule key so future regressions land loudly.
"""
import pytest

from edge import apply_bet_filters


# A harmless bet used as the baseline for tests that monkeypatch a rule.
# bet_type intentionally chosen OUTSIDE the default BET_FILTERS dict so
# tests control the rules entirely through monkeypatch.
def _bet(**overrides):
    base = {
        "bet_type": "__test_market__",
        "side": "player_a",
        "odds": -110,
        "edge": 0.10,
        "kelly_pct": 0.01,
    }
    base.update(overrides)
    return base


def _install_rules(monkeypatch, rules: dict):
    """Install ``rules`` as the BET_FILTERS entry for our synthetic bet_type."""
    import config
    monkeypatch.setitem(config.BET_FILTERS, "__test_market__", rules)


# ==========================================================================
#  disabled
# ==========================================================================
def test_rule_disabled_drops_everything(monkeypatch):
    _install_rules(monkeypatch, {"disabled": True})
    assert apply_bet_filters([_bet(edge=0.10), _bet(edge=0.05)]) == []


def test_rule_disabled_false_is_noop(monkeypatch):
    _install_rules(monkeypatch, {"disabled": False})
    bets = [_bet(edge=0.10)]
    assert apply_bet_filters(bets) == bets


# ==========================================================================
#  min_edge
# ==========================================================================
def test_rule_min_edge_drops_below(monkeypatch):
    _install_rules(monkeypatch, {"min_edge": 0.08})
    assert apply_bet_filters([_bet(edge=0.05)]) == []


def test_rule_min_edge_keeps_above(monkeypatch):
    _install_rules(monkeypatch, {"min_edge": 0.08})
    bets = [_bet(edge=0.10)]
    assert apply_bet_filters(bets) == bets


def test_rule_min_edge_boundary_equal_keeps(monkeypatch):
    """Edge == min_edge should keep (check is ``edge < min_edge``)."""
    _install_rules(monkeypatch, {"min_edge": 0.10})
    bets = [_bet(edge=0.10)]
    assert apply_bet_filters(bets) == bets


# ==========================================================================
#  max_edge
# ==========================================================================
def test_rule_max_edge_drops_above(monkeypatch):
    _install_rules(monkeypatch, {"max_edge": 0.20})
    assert apply_bet_filters([_bet(edge=0.30)]) == []


def test_rule_max_edge_keeps_below(monkeypatch):
    _install_rules(monkeypatch, {"max_edge": 0.20})
    bets = [_bet(edge=0.15)]
    assert apply_bet_filters(bets) == bets


def test_rule_max_edge_boundary_equal_keeps(monkeypatch):
    """Edge == max_edge should keep (check is ``edge > max_edge``)."""
    _install_rules(monkeypatch, {"max_edge": 0.20})
    bets = [_bet(edge=0.20)]
    assert apply_bet_filters(bets) == bets


# ==========================================================================
#  side_contains
# ==========================================================================
def test_rule_side_contains_keeps_matching(monkeypatch):
    _install_rules(monkeypatch, {"side_contains": ["over"]})
    bets = [_bet(side="over 22.5")]
    assert apply_bet_filters(bets) == bets


def test_rule_side_contains_drops_non_matching(monkeypatch):
    _install_rules(monkeypatch, {"side_contains": ["over"]})
    assert apply_bet_filters([_bet(side="under 22.5")]) == []


def test_rule_side_contains_case_insensitive(monkeypatch):
    _install_rules(monkeypatch, {"side_contains": ["OVER"]})
    bets = [_bet(side="over 22.5")]
    assert apply_bet_filters(bets) == bets


def test_rule_side_contains_any_token_matches(monkeypatch):
    """List membership is OR — any matching substring keeps the bet."""
    _install_rules(monkeypatch, {"side_contains": ["over", "under"]})
    assert len(apply_bet_filters([_bet(side="over 22"), _bet(side="under 22")])) == 2


# ==========================================================================
#  odds_min / odds_max (American)
# ==========================================================================
def test_rule_odds_min_drops_below(monkeypatch):
    _install_rules(monkeypatch, {"odds_min": -150})
    # -200 is below -150 (more negative = farther from zero = below)
    assert apply_bet_filters([_bet(odds=-200)]) == []


def test_rule_odds_min_keeps_equal(monkeypatch):
    _install_rules(monkeypatch, {"odds_min": -150})
    bets = [_bet(odds=-150)]
    assert apply_bet_filters(bets) == bets


def test_rule_odds_max_drops_above(monkeypatch):
    _install_rules(monkeypatch, {"odds_max": +110})
    assert apply_bet_filters([_bet(odds=150)]) == []


def test_rule_odds_max_keeps_equal(monkeypatch):
    _install_rules(monkeypatch, {"odds_max": +110})
    bets = [_bet(odds=110)]
    assert apply_bet_filters(bets) == bets


def test_rule_odds_min_and_max_together_form_a_range(monkeypatch):
    _install_rules(monkeypatch, {"odds_min": -150, "odds_max": -110})
    kept = apply_bet_filters([
        _bet(odds=-200),  # below min → drop
        _bet(odds=-130),  # in range → keep
        _bet(odds=-100),  # above max → drop
    ])
    assert len(kept) == 1
    assert kept[0]["odds"] == -130


# ==========================================================================
#  line_in
# ==========================================================================
def test_rule_line_in_keeps_whitelisted(monkeypatch):
    _install_rules(monkeypatch, {"line_in": [22.5, 23.5]})
    bets = [_bet(side="over 22.5"), _bet(side="under 23.5")]
    assert apply_bet_filters(bets) == bets


def test_rule_line_in_drops_unlisted(monkeypatch):
    _install_rules(monkeypatch, {"line_in": [22.5, 23.5]})
    assert apply_bet_filters([_bet(side="over 24.5")]) == []


def test_rule_line_in_drops_when_side_lacks_numeric(monkeypatch):
    """A bet with no parseable line can't satisfy line_in — drop."""
    _install_rules(monkeypatch, {"line_in": [22.5]})
    assert apply_bet_filters([_bet(side="player_a")]) == []


# ==========================================================================
#  Rule composition — multiple rules must ALL pass
# ==========================================================================
def test_rule_composition_drops_on_first_failure(monkeypatch):
    _install_rules(monkeypatch, {"min_edge": 0.08, "max_edge": 0.25})
    assert apply_bet_filters([_bet(edge=0.05)]) == []  # fails min_edge
    assert apply_bet_filters([_bet(edge=0.30)]) == []  # fails max_edge
    assert apply_bet_filters([_bet(edge=0.15)]) == [_bet(edge=0.15)]


# ==========================================================================
#  Unknown bet_type: bypasses all rules (pass-through)
# ==========================================================================
def test_unknown_bet_type_bypasses_all_rules():
    """Framework contract: bet types not in BET_FILTERS pass through untouched."""
    bet = {
        "bet_type": "some_future_market",
        "side": "anything",
        "odds": 100,
        "edge": 0.99,  # huge edge; no rules to apply
    }
    assert apply_bet_filters([bet]) == [bet]


# ==========================================================================
#  Defensive: bad input types
# ==========================================================================
def test_apply_bet_filters_handles_missing_edge(monkeypatch):
    _install_rules(monkeypatch, {"min_edge": 0.05})
    # Missing edge should be treated as 0 → fails min_edge → dropped
    bet = {"bet_type": "__test_market__", "side": "x", "odds": -110}
    assert apply_bet_filters([bet]) == []


def test_apply_bet_filters_handles_non_numeric_edge(monkeypatch):
    _install_rules(monkeypatch, {"min_edge": 0.05})
    bet = {"bet_type": "__test_market__", "side": "x", "odds": -110, "edge": "garbage"}
    assert apply_bet_filters([bet]) == []
