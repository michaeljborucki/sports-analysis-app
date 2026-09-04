from datetime import datetime, timezone

from server.systems.models import SystemSignal
from server.systems.store import SystemSignalStore


def test_record_is_idempotent_and_updates_latest_line(tmp_path):
    store = SystemSignalStore(tmp_path / "signals.db")
    signal = SystemSignal(
        system_id="MLB_10_ROAD_FAVORITE_AFTER_SHUTOUT_LOSS",
        system_name="Road Favorite After Shutout Loss", sport="mlb",
        event_id="e1", home_team="Home", away_team="Away",
        commence_time=datetime(2026, 8, 30, tzinfo=timezone.utc),
        bet_type="moneyline", selection="Away", price_american=-125,
        best_book="pinnacle", qualification_reason="qualified",
        data_timestamp=datetime(2026, 8, 29, 16, tzinfo=timezone.utc),
        evaluated_at=datetime(2026, 8, 29, 16, tzinfo=timezone.utc),
    )
    store.record([signal])
    signal.price_american = -120
    signal.evaluated_at = datetime(2026, 8, 29, 17, tzinfo=timezone.utc)
    store.record([signal])
    rows = store.list_all()
    assert len(rows) == 1
    assert rows[0]["price_american"] == -120
    assert rows[0]["last_seen_at"] == "2026-08-29T17:00:00+00:00"
