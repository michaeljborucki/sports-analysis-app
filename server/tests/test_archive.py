from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.odds.archive import HistoryArchive, export_and_purge, _year_month
from server.odds.cache import OddsCache


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "cache.db")
    c.init()
    return c


@pytest.fixture
def archive(tmp_path: Path) -> HistoryArchive:
    return HistoryArchive(tmp_path / "archive")


def _row(**over):
    now = datetime.now(timezone.utc)
    base = {
        "event_id": "evt_1",
        "sport_key": "mlb",
        "home_team": "Yankees", "away_team": "Red Sox",
        "commence_time": now + timedelta(hours=2),
        "bookmaker_key": "pinnacle",
        "market_key": "h2h",
        "outcome_name": "Yankees",
        "outcome_point": None,
        "price_american": -138,
        "fetched_at": now,
    }
    base.update(over)
    return base


def test_year_month_partition():
    assert _year_month("2026-03-15T19:05:00+00:00") == "2026-03"
    assert _year_month("") == "unknown"
    assert _year_month(None) == "unknown"


def test_export_rows_roundtrip(archive: HistoryArchive):
    rows = [
        {"event_id": "e1", "sport_key": "mlb", "home_team": "Yankees",
         "away_team": "Red Sox", "commence_time": "2026-03-01T18:00:00+00:00",
         "bookmaker_key": "pinnacle", "market_key": "h2h",
         "outcome_name": "Yankees", "outcome_point": 0.0,
         "price_american": -138, "observed_at": "2026-03-01T12:00:00+00:00"},
    ]
    res = archive.export_rows(rows)
    assert res == {"rows_written": 1, "files_written": 1}
    # Partitioned path exists.
    parts = list((archive.root / "sport_key=mlb" / "year_month=2026-03").glob("*.parquet"))
    assert len(parts) == 1
    # Read back via the dataset filter.
    back = archive.read_event("e1")
    assert len(back) == 1
    assert back[0]["price_american"] == -138
    assert back[0]["bookmaker_key"] == "pinnacle"


def test_export_empty_is_noop(archive: HistoryArchive):
    assert archive.export_rows([]) == {"rows_written": 0, "files_written": 0}
    assert archive.stats()["row_count"] == 0
    assert archive.read_event("anything") == []


def test_manifest_accumulates(archive: HistoryArchive):
    def mk(eid, ct):
        return {"event_id": eid, "sport_key": "nba", "home_team": "A",
                "away_team": "B", "commence_time": ct, "bookmaker_key": "pinnacle",
                "market_key": "h2h", "outcome_name": "A", "outcome_point": 0.0,
                "price_american": -110, "observed_at": ct}
    archive.export_rows([mk("e1", "2026-01-05T00:00:00+00:00")])
    archive.export_rows([mk("e2", "2026-02-05T00:00:00+00:00"),
                         mk("e3", "2026-02-06T00:00:00+00:00")])
    s = archive.stats()
    assert s["row_count"] == 3
    assert s["file_count"] == 2  # two months → two part files
    assert s["earliest_commence"] == "2026-01-05T00:00:00+00:00"
    assert s["latest_commence"] == "2026-02-06T00:00:00+00:00"
    assert s["sports"] == {"nba": 3}
    assert s["total_bytes"] > 0


def test_export_and_purge_moves_old_rows(cache: OddsCache, archive: HistoryArchive):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=120)
    cache.upsert([_row(event_id="old_evt", commence_time=old, fetched_at=old,
                       price_american=-110)])
    cache.upsert([_row(event_id="new_evt", price_american=-105)])

    res = export_and_purge(cache, archive, now, hot_days=90)
    assert res["exported"] == 1
    assert res["files_written"] == 1
    assert res["purged_hot"] == 1

    # Old row gone from hot, present in cold storage; recent row untouched.
    assert cache.history_for_event("old_evt") == []
    assert len(cache.history_for_event("new_evt")) == 1
    archived = archive.read_event("old_evt")
    assert len(archived) == 1
    assert archived[0]["price_american"] == -110


def test_export_and_purge_noop_when_nothing_old(cache: OddsCache, archive: HistoryArchive):
    cache.upsert([_row(event_id="new_evt", price_american=-105)])
    res = export_and_purge(cache, archive, datetime.now(timezone.utc), hot_days=90)
    assert res == {"exported": 0, "files_written": 0, "purged_hot": 0}
    assert len(cache.history_for_event("new_evt")) == 1


def test_read_event_missing_lake(archive: HistoryArchive):
    # No export has happened yet → root doesn't exist.
    assert archive.read_event("e1") == []
