"""Tests for scrapers.players (restored from Sackmann-shaped local archive).

Covers:
  - Shape contract of get_player_profile and get_head_to_head
  - Stat helpers using both legacy (raw count) and new (pre-computed pct) columns
  - Elo + H2H logic via mocked _fetch_csv
"""
import pytest
from scrapers.players import (
    _calc_serve_stats,
    _calc_return_stats,
    _calc_record,
    _recent_form,
    _expected_score,
    _get_elo,
    _player_won,
    _safe_float,
    _safe_div,
    get_head_to_head,
    get_player_profile,
    _is_h2h,
    _winner_is,
    ELO_START,
)


# ---------------------------------------------------------------------------
# Legacy (raw-count) match fixture — Sackmann 2020-2024 shape
# ---------------------------------------------------------------------------


def _legacy_match(
    winner_name="Novak Djokovic",
    loser_name="Carlos Alcaraz",
    surface="Hard",
    tourney_name="Australian Open",
    tourney_date="20260115",
    score="6-3 6-4",
    round_name="F",
    w_svpt=80, w_1stIn=50, w_1stWon=40, w_2ndWon=15,
    w_ace=8, w_df=2, w_bpFaced=5, w_bpSaved=3,
    l_svpt=75, l_1stIn=45, l_1stWon=30, l_2ndWon=12,
    l_ace=4, l_df=3, l_bpFaced=8, l_bpSaved=4,
):
    """Legacy Sackmann row — raw counts only, no pre-computed percentages."""
    return {
        "winner_name": winner_name,
        "loser_name": loser_name,
        "surface": surface,
        "tourney_name": tourney_name,
        "tourney_date": tourney_date,
        "score": score,
        "round": round_name,
        "w_svpt": str(w_svpt), "w_1stIn": str(w_1stIn),
        "w_1stWon": str(w_1stWon), "w_2ndWon": str(w_2ndWon),
        "w_ace": str(w_ace), "w_df": str(w_df),
        "w_bpFaced": str(w_bpFaced), "w_bpSaved": str(w_bpSaved),
        "l_svpt": str(l_svpt), "l_1stIn": str(l_1stIn),
        "l_1stWon": str(l_1stWon), "l_2ndWon": str(l_2ndWon),
        "l_ace": str(l_ace), "l_df": str(l_df),
        "l_bpFaced": str(l_bpFaced), "l_bpSaved": str(l_bpSaved),
    }


def _pct_match(
    winner_name="Carlos Alcaraz",
    loser_name="Jannik Sinner",
    surface="Clay",
    tourney_name="Madrid Open",
    tourney_date="20260422",
    score="6-4 6-3",
    w_ace=5, w_df=2,
    w_1stSvPct=0.62, w_1stWonPct=0.75, w_2ndWonPct=0.55,
    w_bpSavedPct=0.80, w_retPtsWonPct=0.42, w_bpConvPct=0.45,
    l_ace=3, l_df=4,
    l_1stSvPct=0.58, l_1stWonPct=0.70, l_2ndWonPct=0.50,
    l_bpSavedPct=0.60, l_retPtsWonPct=0.30, l_bpConvPct=0.25,
):
    """New Sackmann row — pre-computed percentages from api-tennis."""
    return {
        "winner_name": winner_name, "loser_name": loser_name,
        "surface": surface, "tourney_name": tourney_name,
        "tourney_date": tourney_date, "score": score,
        "w_ace": str(w_ace), "w_df": str(w_df),
        "w_1stSvPct": str(w_1stSvPct), "w_1stWonPct": str(w_1stWonPct),
        "w_2ndWonPct": str(w_2ndWonPct), "w_bpSavedPct": str(w_bpSavedPct),
        "w_retPtsWonPct": str(w_retPtsWonPct), "w_bpConvPct": str(w_bpConvPct),
        "l_ace": str(l_ace), "l_df": str(l_df),
        "l_1stSvPct": str(l_1stSvPct), "l_1stWonPct": str(l_1stWonPct),
        "l_2ndWonPct": str(l_2ndWonPct), "l_bpSavedPct": str(l_bpSavedPct),
        "l_retPtsWonPct": str(l_retPtsWonPct), "l_bpConvPct": str(l_bpConvPct),
    }


MATCH_1 = _legacy_match()
MATCH_2_PCT = _pct_match()


# ---------------------------------------------------------------------------
# _safe_float / _safe_div
# ---------------------------------------------------------------------------

def test_safe_float_valid():
    assert _safe_float("3.5") == 3.5
    assert _safe_float(7) == 7.0
    assert _safe_float("0") == 0.0


def test_safe_float_empty_or_invalid():
    assert _safe_float("") is None
    assert _safe_float(None) is None
    assert _safe_float("nan") is None
    assert _safe_float("abc") is None


def test_safe_div_normal():
    assert _safe_div(10.0, 5.0) == 2.0


def test_safe_div_edge_cases():
    assert _safe_div(10.0, 0) is None
    assert _safe_div(None, 5.0) is None
    assert _safe_div(5.0, None) is None


# ---------------------------------------------------------------------------
# _player_won
# ---------------------------------------------------------------------------

def test_player_won_winner():
    assert _player_won("Novak Djokovic", MATCH_1) is True


def test_player_won_loser():
    assert _player_won("Carlos Alcaraz", MATCH_1) is False


def test_player_won_partial_name():
    assert _player_won("Djokovic", MATCH_1) is True


# ---------------------------------------------------------------------------
# _calc_serve_stats — legacy (count-derived) path
# ---------------------------------------------------------------------------

class TestCalcServeStatsLegacy:
    def test_winner(self):
        stats = _calc_serve_stats([MATCH_1], name="Novak Djokovic")
        assert stats["first_serve_pct"] == "62.5%"   # 50/80
        assert stats["first_serve_win_pct"] == "80.0%"  # 40/50
        assert stats["second_serve_win_pct"] == "50.0%"  # 15/30
        assert stats["ace_rate"] == "8.0"
        assert stats["df_rate"] == "2.0"

    def test_loser(self):
        stats = _calc_serve_stats([MATCH_1], name="Carlos Alcaraz")
        assert stats["first_serve_pct"] == "60.0%"   # 45/75
        assert stats["first_serve_win_pct"] == "66.7%"
        assert stats["ace_rate"] == "4.0"

    def test_empty(self):
        stats = _calc_serve_stats([], name="Nobody")
        assert stats["first_serve_pct"] == "N/A"
        assert stats["ace_rate"] == "N/A"


# ---------------------------------------------------------------------------
# _calc_serve_stats — new (pre-computed pct) path
# ---------------------------------------------------------------------------

class TestCalcServeStatsPrecomputed:
    def test_uses_precomputed_percentages(self):
        """When pct columns are present, they're used directly (no back-compute)."""
        stats = _calc_serve_stats([MATCH_2_PCT], name="Carlos Alcaraz")
        assert stats["first_serve_pct"] == "62.0%"
        assert stats["first_serve_win_pct"] == "75.0%"
        assert stats["second_serve_win_pct"] == "55.0%"
        assert stats["ace_rate"] == "5.0"
        assert stats["df_rate"] == "2.0"

    def test_uses_precomputed_for_loser(self):
        stats = _calc_serve_stats([MATCH_2_PCT], name="Jannik Sinner")
        assert stats["first_serve_pct"] == "58.0%"
        assert stats["first_serve_win_pct"] == "70.0%"
        assert stats["ace_rate"] == "3.0"

    def test_mixed_legacy_and_precomputed(self):
        """Averaging across both shapes works — legacy (62.5%) + pct (62%) → ~62.25%."""
        # Put same player in both matches so both contribute to the average.
        legacy = _legacy_match(winner_name="Djokovic Win", loser_name="Opp A",
                               w_svpt=80, w_1stIn=50)  # 62.5%
        pct = _pct_match(winner_name="Djokovic Win", loser_name="Opp B",
                         w_1stSvPct=0.62)  # 62.0%
        stats = _calc_serve_stats([legacy, pct], name="Djokovic Win")
        # Average of 0.625 and 0.62 = 0.6225 → "62.3%" (Python's %-format rounds up)
        assert stats["first_serve_pct"] == "62.3%"


# ---------------------------------------------------------------------------
# _calc_return_stats
# ---------------------------------------------------------------------------

class TestCalcReturnStatsLegacy:
    def test_winner(self):
        stats = _calc_return_stats([MATCH_1], name="Novak Djokovic")
        # opp_svpt=75, opp_1st_won=30, opp_2nd_won=12 → return_won=33 → 44.0%
        assert stats["return_pts_won_pct"] == "44.0%"
        # bp_conversion = (8-4)/8 = 50.0%
        assert stats["bp_conversion_pct"] == "50.0%"

    def test_loser(self):
        stats = _calc_return_stats([MATCH_1], name="Carlos Alcaraz")
        # opp = w_*: svpt=80, 1st_won=40, 2nd_won=15 → return_won=25 → 31.2%
        assert stats["return_pts_won_pct"] == "31.2%"


class TestCalcReturnStatsPrecomputed:
    def test_uses_precomputed_percentages(self):
        stats = _calc_return_stats([MATCH_2_PCT], name="Carlos Alcaraz")
        assert stats["return_pts_won_pct"] == "42.0%"
        assert stats["bp_conversion_pct"] == "45.0%"


# ---------------------------------------------------------------------------
# _calc_record / _recent_form
# ---------------------------------------------------------------------------

class TestCalcRecord:
    def test_basic(self):
        matches = [MATCH_1, _legacy_match(winner_name="Alcaraz", loser_name="Djokovic")]
        assert _calc_record(matches, name="Djokovic") == "1-1"

    def test_surface_filter(self):
        matches = [
            MATCH_1,  # Hard
            _legacy_match(surface="Clay", winner_name="Alcaraz", loser_name="Djokovic"),
        ]
        assert _calc_record(matches, surface="Hard", name="Djokovic") == "1-0"
        assert _calc_record(matches, surface="Clay", name="Djokovic") == "0-1"


class TestRecentForm:
    def test_entries(self):
        form = _recent_form([MATCH_1], name="Djokovic", n=10)
        assert len(form) == 1
        assert form[0]["result"] == "W"
        assert form[0]["opponent"] == "Carlos Alcaraz"


# ---------------------------------------------------------------------------
# Elo helpers
# ---------------------------------------------------------------------------

class TestElo:
    def test_expected_score_equal(self):
        assert _expected_score(1500, 1500) == pytest.approx(0.5)

    def test_expected_score_stronger_player(self):
        exp = _expected_score(1600, 1400)
        assert exp == pytest.approx(0.7597, abs=0.001)

    def test_get_elo_unknown(self):
        elo, surf_elo = _get_elo("Unknown Player", "Hard", {}, {})
        assert elo == ELO_START
        assert surf_elo == ELO_START

    def test_get_elo_known(self):
        overall = {"Novak Djokovic": 1700.0}
        surface = {"Novak Djokovic": {"hard": 1650.0}}
        elo, surf_elo = _get_elo("Djokovic", "Hard", overall, surface)
        assert elo == 1700
        assert surf_elo == 1675  # 50/50 blend


# ---------------------------------------------------------------------------
# H2H helpers
# ---------------------------------------------------------------------------

class TestH2H:
    def test_is_h2h_true(self):
        assert _is_h2h("Djokovic", "Alcaraz", MATCH_1) is True

    def test_is_h2h_false(self):
        assert _is_h2h("Djokovic", "Federer", MATCH_1) is False

    def test_winner_is(self):
        assert _winner_is("Djokovic", MATCH_1) is True
        assert _winner_is("Alcaraz", MATCH_1) is False

    def test_get_head_to_head_with_surface(self, monkeypatch):
        monkeypatch.setattr("scrapers.players._fetch_csv",
                            lambda tour, fn: [MATCH_1])
        result = get_head_to_head("Djokovic", "Alcaraz", surface="Hard")
        assert "overall" in result
        assert "surface" in result
        assert "last_3" in result

    def test_get_head_to_head_empty(self, monkeypatch):
        monkeypatch.setattr("scrapers.players._fetch_csv", lambda tour, fn: [])
        result = get_head_to_head("Djokovic", "Federer")
        assert result["overall"] == "0-0"
        assert result["last_3"] == []


# ---------------------------------------------------------------------------
# get_player_profile — shape contract
# ---------------------------------------------------------------------------

REQUIRED_PROFILE_KEYS = {
    "name", "ranking", "ranking_points", "hand", "backhand", "height", "age",
    "season_record", "surface_record", "serve_stats", "return_stats",
    "recent_form", "days_since_last_match", "elo", "surface_elo",
}


class TestGetPlayerProfile:
    def test_shape_with_empty_archive(self, monkeypatch):
        """With no archive files, the profile still returns the expected shape."""
        monkeypatch.setattr("scrapers.players._fetch_csv", lambda tour, fn: [])
        p = get_player_profile("Unknown", tour="atp", surface="clay")
        assert REQUIRED_PROFILE_KEYS.issubset(p.keys())
        assert p["name"] == "Unknown"
        assert p["ranking"] == "N/A"
        assert p["elo"] == ELO_START

    def test_populates_serve_stats_from_archive(self, monkeypatch):
        """When archive has matches, serve stats are populated."""
        def fake_fetch(tour, fn):
            if "matches" in fn:
                return [MATCH_1]
            return []
        monkeypatch.setattr("scrapers.players._fetch_csv", fake_fetch)
        p = get_player_profile("Djokovic", tour="atp")
        assert p["serve_stats"]["first_serve_pct"] == "62.5%"
        assert p["season_record"] == "1-0"
