import json

from server.sidecar.settings import (
    get_bankroll,
    get_default_kelly,
    KellyFraction,
    _settings_path,
)


def _write(tmp_path, payload):
    p = tmp_path / "user_settings.json"
    p.write_text(json.dumps(payload))
    return p


def test_bankroll_default_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "server.sidecar.settings._settings_path",
        lambda: tmp_path / "user_settings.json",
    )
    assert get_bankroll() == 10000


def test_default_kelly_default_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "server.sidecar.settings._settings_path",
        lambda: tmp_path / "user_settings.json",
    )
    assert get_default_kelly() is KellyFraction.HALF


def test_bankroll_from_user_settings(tmp_path, monkeypatch):
    p = _write(tmp_path, {"sidecar_bankroll": 7500})
    monkeypatch.setattr(
        "server.sidecar.settings._settings_path",
        lambda: p,
    )
    assert get_bankroll() == 7500


def test_invalid_kelly_falls_back_to_half(tmp_path, monkeypatch):
    p = _write(tmp_path, {"sidecar_default_kelly": "wild"})
    monkeypatch.setattr(
        "server.sidecar.settings._settings_path",
        lambda: p,
    )
    assert get_default_kelly() is KellyFraction.HALF


def test_sidecar_keys_dont_break_existing_user_settings_load(tmp_path):
    """Verify the existing UserSettingsStore tolerates the new keys."""
    from server.user_settings import UserSettingsStore
    p = _write(tmp_path, {
        "disabled_sports": [],
        "sidecar_bankroll": 7500,
        "sidecar_default_kelly": "quarter",
    })
    # If UserSettingsStore strictly validates keys, this will throw.
    store = UserSettingsStore(p)
    settings = store.get()
    assert settings is not None
