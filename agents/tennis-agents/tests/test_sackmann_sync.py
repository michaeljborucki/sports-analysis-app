"""Tests for ``scrapers/sackmann_sync.py``.

Covers schema conformance, dedup idempotency, statistics aggregation,
player caching, graceful handling of missing stats, and score reconstruction.
All external HTTP calls are mocked.
"""
from unittest.mock import patch

import pytest

from scrapers import sackmann_sync as sync


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _test_cache():
    """Pre-populated player cache so _ensure_player doesn't make real API calls.

    Matches the player_keys used by ``_mk_fixture`` (100 = Alcaraz, 200 = Sinner).
    """
    return {
        "_loaded": True,
        100: {"player_id": 100, "name_first": "Carlos", "name_last": "Alcaraz",
              "hand": "R", "dob": "20030505", "ioc": "ESP"},
        200: {"player_id": 200, "name_first": "Jannik", "name_last": "Sinner",
              "hand": "R", "dob": "20010816", "ioc": "ITA"},
    }


def _mk_stat(player_key, stat_type, stat_name, stat_value, stat_period="match"):
    return {
        "player_key": player_key,
        "stat_period": stat_period,
        "stat_type": stat_type,
        "stat_name": stat_name,
        "stat_value": stat_value,
    }


def _mk_fixture(
    event_key="1001",
    tournament_key="T7",
    tournament_name="Madrid Open",
    tournament_round="Round of 32",
    event_type="Atp Singles",
    event_date="2026-04-22",
    event_status="Finished",
    first_player="C. Alcaraz",
    second_player="J. Sinner",
    first_key=100,
    second_key=200,
    event_winner="First Player",
    scores=None,
    statistics=None,
):
    return {
        "event_key": event_key,
        "tournament_key": tournament_key,
        "tournament_name": tournament_name,
        "tournament_round": tournament_round,
        "event_type_type": event_type,
        "event_date": event_date,
        "event_status": event_status,
        "event_first_player": first_player,
        "event_second_player": second_player,
        "first_player_key": first_key,
        "second_player_key": second_key,
        "event_winner": event_winner,
        "scores": scores if scores is not None else [
            {"score_first": "6", "score_second": "3", "score_set": "1"},
            {"score_first": "6", "score_second": "4", "score_set": "2"},
        ],
        "statistics": statistics if statistics is not None else [],
    }


# ---------------------------------------------------------------------------
# _parse_pct
# ---------------------------------------------------------------------------


class TestParsePct:
    def test_percentage_string(self):
        assert sync._parse_pct("51%") == 0.51

    def test_plain_percentage(self):
        assert sync._parse_pct("51") == 0.51

    def test_zero(self):
        assert sync._parse_pct("0%") == 0.0

    def test_one_hundred(self):
        assert sync._parse_pct("100%") == 1.0

    def test_already_fraction(self):
        # Values ≤ 1.0 are treated as already-normalized
        assert sync._parse_pct("0.8") == 0.8

    def test_empty(self):
        assert sync._parse_pct("") is None
        assert sync._parse_pct(None) is None

    def test_garbage(self):
        assert sync._parse_pct("abc") is None


# ---------------------------------------------------------------------------
# _aggregate_statistics
# ---------------------------------------------------------------------------


class TestAggregateStatistics:
    def test_takes_first_entry_per_stat(self):
        """First entry is the match total; subsequent entries are per-set.
        Verified against real 2026-04-21 ATP matches (e.g. Sakamoto aces
        [7, 4, 1, 2] where 4+1+2 = 7)."""
        stats = [
            _mk_stat(100, "Service", "Aces", "7"),  # match total
            _mk_stat(100, "Service", "Aces", "4"),  # set 1
            _mk_stat(100, "Service", "Aces", "1"),  # set 2
            _mk_stat(100, "Service", "Aces", "2"),  # set 3
        ]
        agg = sync._aggregate_statistics(stats)
        assert agg[100]["Service:Aces"] == "7"

    def test_multiple_players(self):
        stats = [
            _mk_stat(100, "Service", "Aces", "3"),
            _mk_stat(200, "Service", "Aces", "1"),
        ]
        agg = sync._aggregate_statistics(stats)
        assert agg[100]["Service:Aces"] == "3"
        assert agg[200]["Service:Aces"] == "1"

    def test_multiple_stat_types(self):
        stats = [
            _mk_stat(100, "Service", "Aces", "2"),
            _mk_stat(100, "Service", "Double Faults", "1"),
            _mk_stat(100, "Points", "Winners", "14"),
        ]
        agg = sync._aggregate_statistics(stats)
        assert agg[100]["Service:Aces"] == "2"
        assert agg[100]["Service:Double Faults"] == "1"
        assert agg[100]["Points:Winners"] == "14"

    def test_empty_list(self):
        assert sync._aggregate_statistics([]) == {}

    def test_none_input(self):
        assert sync._aggregate_statistics(None) == {}


# ---------------------------------------------------------------------------
# _extract_player_stats
# ---------------------------------------------------------------------------


class TestExtractPlayerStats:
    def test_full_stats(self):
        raw = {
            "Service:Aces": "5",
            "Service:Double Faults": "2",
            "Service:1st serve percentage": "62%",
            "Service:1st serve points won": "75%",
            "Service:2nd serve points won": "55%",
            "Service:Break Points Saved": "80%",
            "Points:Return Points Won": "38%",
            "Return:Break Points Converted": "40%",
        }
        out = sync._extract_player_stats(raw)
        assert out["ace"] == 5
        assert out["df"] == 2
        assert out["1stSvPct"] == 0.62
        assert out["1stWonPct"] == 0.75
        assert out["2ndWonPct"] == 0.55
        assert out["bpSavedPct"] == 0.80
        assert out["retPtsWonPct"] == 0.38
        assert out["bpConvPct"] == 0.40

    def test_missing_fields_return_empty_string(self):
        out = sync._extract_player_stats({})
        for k in ("ace", "df", "1stSvPct", "1stWonPct", "2ndWonPct",
                  "bpSavedPct", "retPtsWonPct", "bpConvPct"):
            assert out[k] == ""


# ---------------------------------------------------------------------------
# _build_score_string
# ---------------------------------------------------------------------------


class TestBuildScoreString:
    def test_winner_first(self):
        scores = [
            {"score_first": "6", "score_second": "3"},
            {"score_first": "6", "score_second": "4"},
        ]
        assert sync._build_score_string(scores, winner_first=True) == "6-3 6-4"

    def test_winner_second(self):
        """Second player won — winner's games listed first in Sackmann format."""
        scores = [
            {"score_first": "4", "score_second": "6"},
            {"score_first": "3", "score_second": "6"},
        ]
        assert sync._build_score_string(scores, winner_first=False) == "6-4 6-3"

    def test_three_sets(self):
        scores = [
            {"score_first": "6", "score_second": "3"},
            {"score_first": "4", "score_second": "6"},
            {"score_first": "6", "score_second": "2"},
        ]
        assert sync._build_score_string(scores, winner_first=True) == "6-3 4-6 6-2"

    def test_empty(self):
        assert sync._build_score_string([], winner_first=True) == ""

    def test_skips_blank_scores(self):
        scores = [
            {"score_first": "6", "score_second": "3"},
            {"score_first": "", "score_second": ""},
        ]
        assert sync._build_score_string(scores, winner_first=True) == "6-3"


# ---------------------------------------------------------------------------
# _infer_best_of
# ---------------------------------------------------------------------------


def test_infer_best_of_short():
    assert sync._infer_best_of([{}, {}]) == 3


def test_infer_best_of_long():
    assert sync._infer_best_of([{}, {}, {}]) == 5


def test_infer_best_of_empty():
    assert sync._infer_best_of([]) == 3


# ---------------------------------------------------------------------------
# _infer_tourney_level
# ---------------------------------------------------------------------------


class TestInferTourneyLevel:
    def test_grand_slam(self):
        assert sync._infer_tourney_level("Atp Singles", "Wimbledon") == "G"
        assert sync._infer_tourney_level("Wta Singles", "Australian Open") == "G"
        assert sync._infer_tourney_level("Atp Singles", "Roland Garros") == "G"
        assert sync._infer_tourney_level("Atp Singles", "US Open") == "G"

    def test_masters(self):
        assert sync._infer_tourney_level("Atp Singles", "Miami Masters") == "M"

    def test_challenger(self):
        assert sync._infer_tourney_level("Challenger Men Singles", "Phoenix") == "C"

    def test_itf(self):
        assert sync._infer_tourney_level("ITF Women", "Vina del Mar") == "S"

    def test_default(self):
        assert sync._infer_tourney_level("Atp Singles", "Madrid Open") == "A"


# ---------------------------------------------------------------------------
# _split_name, _parse_dob, _age_at
# ---------------------------------------------------------------------------


class TestNameHelpers:
    def test_split_comma(self):
        assert sync._split_name("Alcaraz, Carlos") == ("Carlos", "Alcaraz")

    def test_split_space(self):
        assert sync._split_name("Carlos Alcaraz") == ("Carlos", "Alcaraz")

    def test_split_multi_word_last(self):
        first, last = sync._split_name("Vladimir Guerrero Jr.")
        assert first == "Vladimir"
        assert last == "Guerrero Jr."

    def test_split_empty(self):
        assert sync._split_name("") == ("", "")


class TestParseDob:
    def test_iso(self):
        assert sync._parse_dob("2003-05-05") == "20030505"

    def test_european(self):
        assert sync._parse_dob("05.05.2003") == "20030505"

    def test_slash(self):
        assert sync._parse_dob("05/05/2003") == "20030505"

    def test_empty(self):
        assert sync._parse_dob("") == ""

    def test_garbage(self):
        assert sync._parse_dob("nope") == ""


class TestAgeAt:
    def test_before_birthday(self):
        # born 2003-05-05, tournament 2026-04-22 → age 22
        assert sync._age_at("20030505", "20260422") == "22"

    def test_after_birthday(self):
        # born 2003-05-05, tournament 2026-06-01 → age 23
        assert sync._age_at("20030505", "20260601") == "23"

    def test_missing_dob(self):
        assert sync._age_at("", "20260422") == ""

    def test_missing_date(self):
        assert sync._age_at("20030505", "") == ""


# ---------------------------------------------------------------------------
# _build_match_row
# ---------------------------------------------------------------------------


class TestBuildMatchRow:
    def test_all_columns_present(self):
        fx = _mk_fixture()
        row = sync._build_match_row(fx, "atp", _test_cache())
        # Every expected column must be in the row (may be blank)
        for col in sync.ALL_COLS:
            assert col in row, f"missing column {col}"

    def test_first_player_wins(self):
        fx = _mk_fixture(event_winner="First Player")
        row = sync._build_match_row(fx, "atp", _test_cache())
        # Full names from player metadata, not api-tennis abbreviations
        assert row["winner_name"] == "Carlos Alcaraz"
        assert row["loser_name"] == "Jannik Sinner"
        assert row["score"] == "6-3 6-4"

    def test_second_player_wins_score_flipped(self):
        fx = _mk_fixture(
            event_winner="Second Player",
            scores=[{"score_first": "3", "score_second": "6"},
                    {"score_first": "4", "score_second": "6"}],
        )
        row = sync._build_match_row(fx, "atp", _test_cache())
        assert row["winner_name"] == "Jannik Sinner"
        assert row["loser_name"] == "Carlos Alcaraz"
        assert row["score"] == "6-3 6-4"

    def test_falls_back_to_abbreviated_when_player_metadata_missing(self):
        """If _ensure_player returns {}, winner_name falls back to api-tennis abbrev."""
        fx = _mk_fixture()
        # Cache is loaded but has no entries for 100 / 200 — AND we patch
        # _api_call to return [] so lazy lookup also fails.
        empty_cache = {"_loaded": True}
        with patch.object(sync, "_api_call", return_value={"result": []}):
            row = sync._build_match_row(fx, "atp", empty_cache)
        assert row["winner_name"] == "C. Alcaraz"  # abbreviated fallback
        assert row["loser_name"] == "J. Sinner"

    def test_statistics_populate_pct_columns(self):
        # First entry per (player, stat) is match total; trailing entries
        # are per-set decoys that must be IGNORED.
        stats = [
            _mk_stat(100, "Service", "Aces", "5"),       # match total → kept
            _mk_stat(100, "Service", "Aces", "2"),       # set 1 → ignored
            _mk_stat(100, "Service", "Aces", "3"),       # set 2 → ignored
            _mk_stat(100, "Service", "1st serve percentage", "62%"),
            _mk_stat(100, "Service", "1st serve percentage", "58%"),  # ignored
            _mk_stat(100, "Service", "1st serve points won", "75%"),
            _mk_stat(200, "Service", "Aces", "2"),
            _mk_stat(200, "Service", "1st serve percentage", "58%"),
        ]
        fx = _mk_fixture(statistics=stats)
        row = sync._build_match_row(fx, "atp", _test_cache())
        assert row["w_ace"] == 5
        assert row["w_1stSvPct"] == 0.62
        assert row["w_1stWonPct"] == 0.75
        assert row["l_ace"] == 2
        assert row["l_1stSvPct"] == 0.58

    def test_no_statistics_row_still_valid(self):
        fx = _mk_fixture(statistics=[])
        row = sync._build_match_row(fx, "atp", _test_cache())
        assert row is not None
        assert row["winner_name"] == "Carlos Alcaraz"
        # Stat columns should be blank, not populated
        assert row["w_ace"] == ""
        assert row["w_1stSvPct"] == ""

    def test_missing_winner_returns_none(self):
        fx = _mk_fixture(event_winner="")
        assert sync._build_match_row(fx, "atp", _test_cache()) is None

    def test_missing_player_names_returns_none(self):
        fx = _mk_fixture(first_player="", second_player="")
        assert sync._build_match_row(fx, "atp", _test_cache()) is None

    def test_date_reformatted(self):
        fx = _mk_fixture(event_date="2026-04-22")
        row = sync._build_match_row(fx, "atp", _test_cache())
        assert row["tourney_date"] == "20260422"


# ---------------------------------------------------------------------------
# sync_matches_day — end-to-end with mocked API
# ---------------------------------------------------------------------------


class TestSyncMatchesDay:
    def test_writes_finished_singles_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        mocked = {
            "result": [
                _mk_fixture(event_key="1", event_status="Finished", event_type="Atp Singles"),
                _mk_fixture(event_key="2", event_status="Finished", event_type="Atp Doubles"),  # skip
                _mk_fixture(event_key="3", event_status="In Progress", event_type="Atp Singles"),  # skip
                _mk_fixture(event_key="4", event_status="Finished", event_type="Wta Singles"),  # wrong tour
            ]
        }
        with patch.object(sync, "_api_call", return_value=mocked):
            new_rows = sync.sync_matches_day("2026-04-22", "atp")
        assert new_rows == 1

    def test_idempotent_second_call(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        fx = _mk_fixture()
        with patch.object(sync, "_api_call", return_value={"result": [fx]}):
            first = sync.sync_matches_day("2026-04-22", "atp")
            second = sync.sync_matches_day("2026-04-22", "atp")
        assert first == 1
        assert second == 0  # dedup kicked in

    def test_empty_day(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        with patch.object(sync, "_api_call", return_value={"result": []}):
            assert sync.sync_matches_day("2026-04-22", "atp") == 0

    def test_writes_to_correct_year_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        fx_2025 = _mk_fixture(event_key="99", event_date="2025-07-15")
        with patch.object(sync, "_api_call", return_value={"result": [fx_2025]}):
            sync.sync_matches_day("2025-07-15", "atp")
        expected = tmp_path / "atp" / "atp_matches_2025.csv"
        assert expected.exists()

    def test_new_file_has_extended_columns_in_header(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        fx = _mk_fixture()
        with patch.object(sync, "_api_call", return_value={"result": [fx]}):
            sync.sync_matches_day("2026-04-22", "atp")
        path = tmp_path / "atp" / "atp_matches_2026.csv"
        with open(path) as f:
            header = f.readline().strip().split(",")
        # Core + extended columns present
        assert "w_ace" in header
        assert "w_1stSvPct" in header
        assert "l_bpConvPct" in header


# ---------------------------------------------------------------------------
# sync_rankings
# ---------------------------------------------------------------------------


class TestSyncRankings:
    def test_writes_rows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        mocked = {
            "result": [
                {"player_key": 100, "place": 1, "points": 11500},
                {"player_key": 200, "place": 2, "points": 9800},
            ]
        }
        with patch.object(sync, "_api_call", return_value=mocked):
            count = sync.sync_rankings("atp")
        assert count == 2

        path = tmp_path / "atp" / "atp_rankings_current.csv"
        assert path.exists()
        with open(path) as f:
            lines = f.read().splitlines()
        assert lines[0] == "ranking_date,rank,player,points"
        assert "100,11500" in lines[1]

    def test_empty_standings(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        with patch.object(sync, "_api_call", return_value={"result": []}):
            assert sync.sync_rankings("atp") == 0


# ---------------------------------------------------------------------------
# _ensure_player
# ---------------------------------------------------------------------------


class TestEnsurePlayer:
    def test_known_player_no_fetch(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        path = tmp_path / "atp" / "atp_players.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "player_id,name_first,name_last,hand,dob,ioc,height,wikidata_id\n"
            "100,Carlos,Alcaraz,R,20030505,ESP,183,Q123\n"
        )
        cache: dict = {}
        with patch.object(sync, "_api_call") as call:
            out = sync._ensure_player(100, "atp", cache)
        assert call.call_count == 0
        assert out["name_last"] == "Alcaraz"

    def test_unknown_triggers_lookup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        mocked = {
            "result": [{
                "player_name": "J. Sinner",           # abbreviated
                "player_full_name": "Jannik Sinner",  # full — preferred
                "player_hand": "R",
                "player_bday": "2001-08-16",
                "player_country": "ITA",
            }]
        }
        cache: dict = {}
        with patch.object(sync, "_api_call", return_value=mocked):
            out = sync._ensure_player(200, "atp", cache)
        # player_full_name is preferred — "Jannik Sinner" not "J. Sinner"
        assert out["name_first"] == "Jannik"
        assert out["name_last"] == "Sinner"
        assert out["hand"] == "R"
        assert out["dob"] == "20010816"
        assert out["ioc"] == "ITA"
        path = tmp_path / "atp" / "atp_players.csv"
        assert path.exists()

    def test_prefers_full_name_over_abbreviated(self, tmp_path, monkeypatch):
        """Regression: if only ``player_name`` is present we still work;
        if both are present we use ``player_full_name``."""
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        mocked = {"result": [{
            "player_name": "T. Korpatsch",
            "player_full_name": "Tamara Korpatsch",
            "player_hand": "R",
            "player_bday": "1995-04-06",
            "player_country": "GER",
        }]}
        with patch.object(sync, "_api_call", return_value=mocked):
            out = sync._ensure_player(501, "atp", {})
        assert out["name_first"] == "Tamara"
        assert out["name_last"] == "Korpatsch"

    def test_lookup_is_cached(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        mocked = {
            "result": [{"player_name": "Test Player", "player_hand": "R",
                        "player_bday": "2000-01-01", "player_country": "USA"}]
        }
        cache: dict = {}
        with patch.object(sync, "_api_call", return_value=mocked) as call:
            sync._ensure_player(300, "atp", cache)
            sync._ensure_player(300, "atp", cache)  # second call hits cache
        assert call.call_count == 1

    def test_failed_lookup_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync, "SACKMANN_LOCAL_DIR", str(tmp_path))
        cache: dict = {}
        with patch.object(sync, "_api_call", return_value={"result": []}):
            out = sync._ensure_player(999, "atp", cache)
        assert out == {}
