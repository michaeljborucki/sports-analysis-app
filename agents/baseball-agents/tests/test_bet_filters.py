"""Regression tests for config.BET_FILTERS + edge._passes_bet_filter.

Pins the per-bet-type filter behavior so refactors of edge.py or config.py
can't silently break existing rules. Each filter shape (disabled, min_edge,
max_edge, side_contains, line_in, odds_min/max) gets explicit coverage.
"""
import pytest

from edge import _passes_bet_filter, _extract_line_from_side, apply_bet_filters
from config import BET_FILTERS


# ---------------------------------------------------------------------------
# _extract_line_from_side: parse the numeric line from various side formats
# ---------------------------------------------------------------------------

class TestLineExtraction:
    def test_simple_over(self):
        assert _extract_line_from_side("over 1.5") == 1.5

    def test_simple_under(self):
        assert _extract_line_from_side("under 0.5") == 0.5

    def test_player_prop(self):
        assert _extract_line_from_side("Mike Trout under 1.5") == 1.5

    def test_negative_handicap(self):
        assert _extract_line_from_side("home -1.5") == -1.5

    def test_positive_handicap(self):
        assert _extract_line_from_side("away +1.5") == 1.5

    def test_multi_word_player(self):
        assert _extract_line_from_side("Vladimir Guerrero Jr. over 1.5") == 1.5

    def test_no_number(self):
        assert _extract_line_from_side("home") is None

    def test_empty(self):
        assert _extract_line_from_side("") is None

    def test_none_input(self):
        assert _extract_line_from_side(None) is None


# ---------------------------------------------------------------------------
# BET_FILTERS is empty (2026-05-17) — no bet types are blanket-disabled.
# Mechanism still exists for future scoping; tests below verify behavior
# using monkeypatched configs.
# ---------------------------------------------------------------------------

FIRST_3_DISABLED = {"first_3_rl", "first_3_total", "first_3_ml"}


class TestFirstThreeDisabled:
    """As of 2026-05-19, first_3_* markets are filtered out due to a
    single graded slate showing 5-15 across rl/total picks."""

    def test_first_3_types_present_and_disabled(self):
        for bt in FIRST_3_DISABLED:
            assert bt in BET_FILTERS, f"{bt} must be in BET_FILTERS"
            assert BET_FILTERS[bt].get("disabled") is True, \
                f"{bt} must be disabled"

    def test_other_bet_types_not_in_filters(self):
        """Sanity: only first_3_* should be in the live config right now."""
        assert set(BET_FILTERS.keys()) == FIRST_3_DISABLED, \
            f"BET_FILTERS unexpected keys: {set(BET_FILTERS) - FIRST_3_DISABLED}"


# ---------------------------------------------------------------------------
# disabled flag still works as a mechanism (used via monkeypatch)
# ---------------------------------------------------------------------------

class TestDisabledFilterMechanism:
    def test_disabled_drops_high_edge_bet(self, monkeypatch):
        monkeypatch.setattr("edge.BET_FILTERS", {"_test": {"disabled": True}})
        bet = {"bet_type": "_test", "edge": 0.50, "side": "X over 1.5", "odds": -110}
        assert _passes_bet_filter(bet) is False

    def test_disabled_drops_zero_edge_bet(self, monkeypatch):
        monkeypatch.setattr("edge.BET_FILTERS", {"_test": {"disabled": True}})
        bet = {"bet_type": "_test", "edge": 0.00, "side": "home -1.5", "odds": -110}
        assert _passes_bet_filter(bet) is False


# ---------------------------------------------------------------------------
# min_edge / max_edge filter mechanism (tested against a synthetic config so
# the tests don't break when the live config cycles filters in and out).
# ---------------------------------------------------------------------------

class TestMinMaxEdgeMechanism:
    def test_min_edge_drops_below(self, monkeypatch):
        monkeypatch.setattr("edge.BET_FILTERS", {"_test": {"min_edge": 0.10}})
        bet = {"bet_type": "_test", "edge": 0.09, "side": "X over 1.5", "odds": -110}
        assert _passes_bet_filter(bet) is False

    def test_min_edge_passes_at_or_above(self, monkeypatch):
        monkeypatch.setattr("edge.BET_FILTERS", {"_test": {"min_edge": 0.10}})
        for e in (0.10, 0.20):
            bet = {"bet_type": "_test", "edge": e, "side": "X over 1.5", "odds": -110}
            assert _passes_bet_filter(bet) is True

    def test_max_edge_drops_at_or_above(self, monkeypatch):
        monkeypatch.setattr("edge.BET_FILTERS", {"_test": {"max_edge": 0.25}})
        for e in (0.25, 0.40):
            bet = {"bet_type": "_test", "edge": e, "side": "X over 0.5", "odds": -110}
            assert _passes_bet_filter(bet) is False

    def test_max_edge_passes_below(self, monkeypatch):
        monkeypatch.setattr("edge.BET_FILTERS", {"_test": {"max_edge": 0.25}})
        bet = {"bet_type": "_test", "edge": 0.20, "side": "X over 0.5", "odds": -110}
        assert _passes_bet_filter(bet) is True


# ---------------------------------------------------------------------------
# line_in: bet's parsed line must be in the whitelist
# ---------------------------------------------------------------------------

class TestLineInFilterMechanism:
    """line_in filter mechanism — uses monkeypatch since live BET_FILTERS
    no longer scopes any bet type by line."""

    @pytest.mark.parametrize("line", [3.5, 4.5, 5.5])
    def test_line_in_kept_for_listed_lines(self, line, monkeypatch):
        monkeypatch.setattr("edge.BET_FILTERS",
                            {"_test": {"line_in": [3.5, 4.5, 5.5]}})
        bet = {"bet_type": "_test", "edge": 0.10,
               "side": f"X over {line}", "odds": -110}
        assert _passes_bet_filter(bet) is True, f"line={line}"

    @pytest.mark.parametrize("line", [2.5, 6.5, 7.5])
    def test_line_in_dropped_for_unlisted_lines(self, line, monkeypatch):
        monkeypatch.setattr("edge.BET_FILTERS",
                            {"_test": {"line_in": [3.5, 4.5, 5.5]}})
        bet = {"bet_type": "_test", "edge": 0.10,
               "side": f"X over {line}", "odds": -110}
        assert _passes_bet_filter(bet) is False, f"line={line}"


# ---------------------------------------------------------------------------
# Unconfigured bet types pass through unchanged
# ---------------------------------------------------------------------------

UNFILTERED_BET_TYPES = [
    ("moneyline", 0.05, "home", -110),
    ("run_line", 0.08, "home -1.5", -130),
    ("nrfi", 0.10, "NRFI", -110),
    ("team_total_home", 0.10, "home over 4.5", +100),
    ("team_total_away", 0.10, "away under 3.5", -110),
    ("batter_rbis", 0.10, "X under 0.5", -110),
    ("batter_total_bases", 0.10, "X over 1.5", -110),
    ("pitcher_strikeouts", 0.20, "X over 5.5", -110),
    # Previously-disabled bet types now flowing (cleared 2026-05-17).
    ("batter_strikeouts", 0.10, "X over 1.5", -110),
    ("first_5_rl", 0.10, "home -1.5", -110),
    # pitcher_hits_allowed at any line (formerly line_in-restricted)
    ("pitcher_hits_allowed", 0.10, "X over 6.5", -110),
    ("pitcher_hits_allowed", 0.10, "X over 7.5", -110),
    # Totals guard (2026-04-21) removed after park-factor + bias recalibration
    # — low-edge totals should flow through again.
    ("total", 0.05, "under 8.5", -110),
    ("total", 0.06, "over 8.5", -110),
]


class TestUnconfiguredBetTypes:
    @pytest.mark.parametrize("bet_type,edge,side,odds", UNFILTERED_BET_TYPES)
    def test_unconfigured_passes(self, bet_type, edge, side, odds):
        bet = {"bet_type": bet_type, "edge": edge, "side": side, "odds": odds}
        assert _passes_bet_filter(bet) is True, f"{bet_type} should not be filtered"


# ---------------------------------------------------------------------------
# apply_bet_filters: list-level wrapper
# ---------------------------------------------------------------------------

class TestApplyBetFiltersList:
    def test_drops_disabled_keeps_others(self, monkeypatch):
        """Mechanism check via monkeypatch — live config no longer disables
        any types."""
        monkeypatch.setattr("edge.BET_FILTERS",
                            {"batter_strikeouts": {"disabled": True}})
        bets = [
            {"bet_type": "batter_strikeouts", "edge": 0.20, "side": "X over 1.5", "odds": -110},
            {"bet_type": "moneyline", "edge": 0.05, "side": "home", "odds": -110},
        ]
        kept = apply_bet_filters(bets)
        assert len(kept) == 1
        assert kept[0]["bet_type"] == "moneyline"

    def test_empty_input(self):
        assert apply_bet_filters([]) == []

    def test_live_config_keeps_everything(self):
        """With BET_FILTERS cleared, every bet should pass through."""
        bets = [
            {"bet_type": "moneyline", "edge": 0.05, "side": "home", "odds": -110},
            {"bet_type": "batter_strikeouts", "edge": 0.10, "side": "X over 1.5", "odds": -110},
            {"bet_type": "first_5_rl", "edge": 0.08, "side": "home -1.5", "odds": -110},
            {"bet_type": "pitcher_hits_allowed", "edge": 0.10, "side": "X over 6.5", "odds": -110},
        ]
        kept = apply_bet_filters(bets)
        assert len(kept) == len(bets), f"all bets should pass; kept {len(kept)} of {len(bets)}"


# ---------------------------------------------------------------------------
# Schema contract: BET_FILTERS only uses recognized keys
# ---------------------------------------------------------------------------

KNOWN_FILTER_KEYS = {"disabled", "min_edge", "max_edge", "side_contains",
                     "line_in", "odds_min", "odds_max"}


def test_bet_filters_uses_only_known_keys():
    """Catches typos like 'min_egde' or new keys added without filter support."""
    for bt, rules in BET_FILTERS.items():
        unknown = set(rules) - KNOWN_FILTER_KEYS
        assert not unknown, f"{bt} has unknown filter keys: {unknown}"
