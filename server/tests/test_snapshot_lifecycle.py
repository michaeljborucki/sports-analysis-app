from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_app_starts_and_stops_one_snapshot_service(monkeypatch, tmp_path: Path):
    import server.config as config_mod
    import server.main as main_mod
    import server.user_settings as settings_mod

    calls: list[str] = []

    class FakeSnapshotService:
        def __init__(self, cache):
            self.cache = cache

        async def start(self):
            calls.append("start")

        async def stop(self):
            calls.append("stop")

    original_from_env = config_mod.Config.from_env

    def test_config():
        config = original_from_env()
        config.cache_db = tmp_path / "cache.db"
        config.coral33_enabled = False
        config.odds_api_fetcher_enabled = False
        return config

    monkeypatch.setattr(config_mod.Config, "from_env", staticmethod(test_config))
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(main_mod, "LatestOddsSnapshotService", FakeSnapshotService)
    monkeypatch.setattr(main_mod.KalshiFetcher, "start_all", lambda self: None)
    monkeypatch.setattr(main_mod.PolymarketFetcher, "start_all", lambda self: None)

    with TestClient(main_mod.create_app()) as client:
        assert client.get("/api/health").status_code == 200
        assert calls == ["start"]

    assert calls == ["start", "stop"]
