"""The subprocess snapshot build must reproduce the in-process build exactly:
same rows (and order), games, non-prop games, system rows and overlay base.
The worker runs in a real spawned process, as in production."""
from __future__ import annotations

import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.odds import latest_snapshot as ls
from server.odds import normalize, snapshot_worker
from server.odds.cache import OddsCache


NOW = datetime.now(timezone.utc).replace(microsecond=0)

# Seeded through betting-db's own Store, as test_bettingdb_source does.
BETTING_DB_REPO = Path.home() / "personal_workspace/betting-db"
pytestmark = pytest.mark.skipif(
    not (BETTING_DB_REPO / "betting_db" / "store.py").exists(),
    reason="betting-db repo not present",
)
if str(BETTING_DB_REPO) not in sys.path:
    sys.path.insert(0, str(BETTING_DB_REPO))


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _seed_betting_db(path: Path) -> None:
    from betting_db.parse import EventRow, OddsRow
    from betting_db.store import Store

    def odds(eid, book, mk, name, point=None, price=-110, desc=None):
        return OddsRow(event_id=eid, bookmaker_key=book, market_key=mk,
                       outcome_name=name, outcome_description=desc,
                       outcome_point=point, price_american=price, price_decimal=2.0)

    rows = []
    for eid, home, away in (("evt_1", "New York Yankees", "Boston Red Sox"),
                            ("evt_2", "Chicago Cubs", "New York Mets")):
        for book, (hp, ap) in {"draftkings": (-120, 100), "fanduel": (-118, 102),
                               "pinnacle": (-115, 105), "novig": (-112, 108)}.items():
            rows += [odds(eid, book, "h2h", home, price=hp), odds(eid, book, "h2h", away, price=ap)]
            rows += [odds(eid, book, "totals", "Over", 8.5, -105), odds(eid, book, "totals", "Under", 8.5, -115)]
        rows += [odds(eid, "draftkings", "batter_hits", "Over", 0.5, -150, desc="Aaron Judge"),
                 odds(eid, "fanduel", "batter_hits", "Over", 0.5, -140, desc="Aaron Judge")]
    store = Store(str(path))
    store.init_db()
    store.apply_snapshot(
        events=[
            EventRow(event_id="evt_1", sport_key="baseball_mlb", league_key="mlb",
                     home_team="New York Yankees", away_team="Boston Red Sox",
                     commence_time=_z(NOW + timedelta(hours=3))),
            EventRow(event_id="evt_2", sport_key="baseball_mlb", league_key="mlb",
                     home_team="Chicago Cubs", away_team="New York Mets",
                     commence_time=_z(NOW + timedelta(hours=2))),
        ],
        rows=rows, fetched_at=_z(NOW),
    )
    store.close()


def _direct(eid, home, away, mk, name, point, price, book="novig", hours=3):
    return {
        "event_id": eid, "sport_key": "mlb", "league_key": "mlb", "league_title": None,
        "home_team": home, "away_team": away,
        "commence_time": NOW + timedelta(hours=hours),
        "bookmaker_key": book, "market_key": mk, "outcome_name": name,
        "outcome_point": point, "price_american": price, "fetched_at": NOW,
        "wager_type": None, "max_stake_dollars": 250.0 if book == "kalshi" else None,
    }


@pytest.fixture
def dbs(tmp_path: Path, monkeypatch):
    from server.odds import bettingdb_source
    bettingdb_source._reset_memo_for_tests()
    normalize._reset_collision_log_for_tests()
    bdb_path = tmp_path / "odds.db"
    _seed_betting_db(bdb_path)
    monkeypatch.setenv("BETTING_DB_PATH", str(bdb_path))
    monkeypatch.setenv("ODDS_SOURCE", "betting_db")
    cache = OddsCache(tmp_path / "cache.db")
    cache.init()
    cache.upsert([
        # Displace two betting-db novig rows (one per event) -> exercises the
        # excluded-position rebuild of `base`.
        _direct("evt_1", "New York Yankees", "Boston Red Sox", "h2h", "New York Yankees", None, -125),
        _direct("evt_2", "Chicago Cubs", "New York Mets", "totals", "Over", 8.5, -101, hours=2),
        _direct("evt_2", "Chicago Cubs", "New York Mets", "h2h", "Chicago Cubs", None, -119,
                book="kalshi", hours=2),
    ])
    yield cache
    bettingdb_source._reset_memo_for_tests()


def _in_process(cache: OddsCache, built_at: datetime) -> ls._BuildResult:
    merged, base, direct = ls.merge_betting_db(cache)
    games, non_prop = normalize.rows_to_games_with_non_prop(tuple(merged), now=built_at)
    overlay = ls._OverlayBase(base_by_event=ls._group_by_event(base),
                              direct_sig=ls.direct_signatures(direct))
    return ls.finish_build(tuple(merged), games, non_prop, built_at, overlay)


def _subprocess(cache: OddsCache) -> tuple[ls._BuildResult, dict]:
    with ProcessPoolExecutor(1, mp_context=multiprocessing.get_context("spawn")) as pool:
        payload = pool.submit(snapshot_worker.build_payload, str(cache.path)).result(timeout=120)
    timings = payload["child_timings_ms"]
    return ls.LatestOddsSnapshotService._assemble_payload(payload), timings


def test_subprocess_build_matches_in_process_build(dbs):
    sub, timings = _subprocess(dbs)
    ref = _in_process(dbs, built_at=sub[5])          # same clock -> same stale_seconds
    rows, games, non_prop, by_sport, system_rows, built_at, overlay = sub
    assert len(ref[0]) == len(rows) > 20
    assert list(rows) == list(ref[0])                 # same rows, same order
    assert list(games) == list(ref[1])
    assert list(non_prop) == list(ref[2])
    assert dict(by_sport) == dict(ref[3])
    assert list(system_rows) == list(ref[4])
    assert overlay.base_by_event == ref[6].base_by_event
    assert overlay.direct_sig == ref[6].direct_sig
    # the displaced betting-db novig rows are in base but not in rows
    novig_base = [r for rs in overlay.base_by_event.values() for r in rs if r["bookmaker_key"] == "novig"]
    novig_rows = [r for r in rows if r["bookmaker_key"] == "novig"]
    assert len(novig_base) == 8 and len(novig_rows) == 8   # 2 displaced + 2 direct replacements
    assert set(timings) == {"read", "games", "pack"}


def test_chunk_boundaries_preserve_order(dbs, monkeypatch):
    """Tiny chunks: many boundaries, same result."""
    monkeypatch.setattr(snapshot_worker, "ROWS_PER_CHUNK", 3)
    monkeypatch.setattr(snapshot_worker, "SIGS_PER_CHUNK", 1)
    payload = snapshot_worker.build_payload(str(dbs.path))   # in-process call is fine here
    assert len(payload["row_chunks"]) > 5
    sub = ls.LatestOddsSnapshotService._assemble_payload(payload)
    ref = _in_process(dbs, built_at=sub[5])
    assert list(sub[0]) == list(ref[0]) and list(sub[1]) == list(ref[1])
    assert sub[6].base_by_event == ref[6].base_by_event


def test_service_falls_back_in_process_when_subprocess_fails(dbs, monkeypatch):
    import asyncio

    async def boom(self):
        raise RuntimeError("child died")

    monkeypatch.setattr(ls.LatestOddsSnapshotService, "_build_via_subprocess", boom)
    svc = ls.LatestOddsSnapshotService(dbs, build_in_subprocess=True)
    snap = asyncio.run(svc.get())
    assert snap.rows and svc.last_build["mode"] == "in_process"


def test_service_builds_via_subprocess_end_to_end(dbs):
    import asyncio

    async def run():
        svc = ls.LatestOddsSnapshotService(dbs, build_in_subprocess=True)
        try:
            return await svc.get(), svc.last_build
        finally:
            svc._shutdown_pool()

    snap, last = asyncio.run(run())
    assert last["mode"] == "subprocess", last
    assert set(last["child_ms"]) == {"read", "games", "pack"} and last["chunks"] > 0
    ref = _in_process(dbs, built_at=snap.built_at)
    assert list(snap.rows) == list(ref[0]) and list(snap.games) == list(ref[1])
