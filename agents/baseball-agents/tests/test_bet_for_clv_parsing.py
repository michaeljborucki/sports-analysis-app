"""Regression tests for tracker._parse_bet_for_clv.

Side-string parsing is a contract between bet logging and CLV lookup. Each
bet type has its own side format. Breaking parsing for any one type silently
loses CLV coverage on those bets.
"""
import pytest
from tracker import _parse_bet_for_clv


# ---------------------------------------------------------------------------
# Mainline bet types
# ---------------------------------------------------------------------------

class TestMoneyline:
    def test_home(self):
        market, side, line, player = _parse_bet_for_clv("moneyline", "home")
        assert (market, side, line, player) == ("moneyline", "home", None, "")

    def test_away(self):
        m, s, l, p = _parse_bet_for_clv("moneyline", "away")
        assert (m, s, l, p) == ("moneyline", "away", None, "")


class TestRunLine:
    def test_home_minus_15(self):
        m, s, l, p = _parse_bet_for_clv("run_line", "home -1.5")
        assert (m, s, l, p) == ("run_line", "home", -1.5, "")

    def test_away_plus_15(self):
        m, s, l, p = _parse_bet_for_clv("run_line", "away 1.5")
        assert (m, s, l, p) == ("run_line", "away", 1.5, "")


class TestTotal:
    def test_over(self):
        m, s, l, p = _parse_bet_for_clv("total", "over 8.5")
        assert (m, s, l, p) == ("total", "over", 8.5, "")

    def test_under(self):
        m, s, l, p = _parse_bet_for_clv("total", "under 7.0")
        assert (m, s, l, p) == ("total", "under", 7.0, "")


class TestTeamTotal:
    def test_home_under(self):
        m, s, l, p = _parse_bet_for_clv("team_total_home", "home under 3.5")
        assert (m, s, l, p) == ("team_total_home", "under", 3.5, "")

    def test_away_over(self):
        m, s, l, p = _parse_bet_for_clv("team_total_away", "away over 4.5")
        assert (m, s, l, p) == ("team_total_away", "over", 4.5, "")


class TestNRFI:
    def test_nrfi(self):
        m, s, l, p = _parse_bet_for_clv("nrfi", "NRFI")
        assert (m, s, l, p) == ("nrfi", "NRFI", None, "")

    def test_yrfi(self):
        m, s, l, p = _parse_bet_for_clv("nrfi", "YRFI")
        assert (m, s, l, p) == ("nrfi", "YRFI", None, "")


class TestFirstInningRunLine:
    def test_first_1_rl_home(self):
        m, s, l, p = _parse_bet_for_clv("first_1_rl", "home +0.0")
        assert (m, s, l, p) == ("first_1_rl", "home", 0.0, "")

    def test_first_5_rl_away(self):
        m, s, l, p = _parse_bet_for_clv("first_5_rl", "away -1.5")
        assert (m, s, l, p) == ("first_5_rl", "away", -1.5, "")


# ---------------------------------------------------------------------------
# Player props — must extract player_name correctly
# ---------------------------------------------------------------------------

class TestPropParsing:
    def test_simple_two_word_name(self):
        m, s, l, p = _parse_bet_for_clv("batter_hits", "Mike Trout over 1.5")
        assert m == "batter_hits"
        assert s == "over"
        assert l == 1.5
        assert p == "Mike Trout"

    def test_under_direction(self):
        m, s, l, p = _parse_bet_for_clv("batter_rbis", "Aaron Judge under 0.5")
        assert (s, l, p) == ("under", 0.5, "Aaron Judge")

    def test_three_word_name(self):
        m, s, l, p = _parse_bet_for_clv("batter_total_bases", "Vladimir Guerrero Jr. over 1.5")
        assert s == "over"
        assert l == 1.5
        assert p == "Vladimir Guerrero Jr."

    def test_pitcher_strikeouts(self):
        m, s, l, p = _parse_bet_for_clv("pitcher_strikeouts", "Cole Ragans under 6.5")
        assert (m, s, l, p) == ("pitcher_strikeouts", "under", 6.5, "Cole Ragans")

    def test_pitcher_outs_high_line(self):
        m, s, l, p = _parse_bet_for_clv("pitcher_outs", "Brandon Sproat over 14.5")
        assert l == 14.5
        assert p == "Brandon Sproat"

    def test_special_chars_in_name(self):
        # Apostrophes, accents, hyphens — all common in MLB rosters
        m, s, l, p = _parse_bet_for_clv("batter_hits", "Ke'Bryan Hayes over 0.5")
        assert p == "Ke'Bryan Hayes"

    def test_accented_name(self):
        m, s, l, p = _parse_bet_for_clv("batter_hits_runs_rbis", "Moisés Ballesteros under 1.5")
        assert p == "Moisés Ballesteros"


# ---------------------------------------------------------------------------
# Unsupported / unparseable inputs
# ---------------------------------------------------------------------------

class TestUnsupported:
    def test_unknown_bet_type(self):
        m, s, l, p = _parse_bet_for_clv("game_handicap", "home -2.5")
        assert m is None

    def test_malformed_total(self):
        m, s, l, p = _parse_bet_for_clv("total", "over")  # no line
        assert m is None

    def test_malformed_team_total(self):
        m, s, l, p = _parse_bet_for_clv("team_total_home", "home")  # missing direction+line
        assert m is None

    def test_malformed_run_line_non_numeric(self):
        m, s, l, p = _parse_bet_for_clv("run_line", "home foo")
        assert m is None

    def test_prop_missing_direction(self):
        m, s, l, p = _parse_bet_for_clv("batter_hits", "Mike Trout 1.5")
        assert m is None

    def test_prop_missing_line(self):
        m, s, l, p = _parse_bet_for_clv("batter_hits", "Mike Trout over")
        assert m is None

    def test_empty_side(self):
        m, s, l, p = _parse_bet_for_clv("moneyline", "")
        # moneyline returns ("moneyline", "", None, "") — empty side string
        # is the documented behavior; downstream lookup will just no-match
        assert m == "moneyline"
        assert s == ""
