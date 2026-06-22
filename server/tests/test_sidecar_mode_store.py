from pathlib import Path
from server.sidecar.mode_store import SidecarMode, SidecarModeStore


def test_default_is_off(tmp_path: Path):
    store = SidecarModeStore(tmp_path / "sidecar_mode.json")
    assert store.get() is SidecarMode.OFF


def test_round_trip_all_three_modes(tmp_path: Path):
    p = tmp_path / "sidecar_mode.json"
    store = SidecarModeStore(p)
    for mode in (SidecarMode.OFF, SidecarMode.DRY_RUN, SidecarMode.LIVE):
        store.set(mode)
        # Re-open from disk
        assert SidecarModeStore(p).get() is mode


def test_missing_file_defaults_to_off(tmp_path: Path):
    p = tmp_path / "sidecar_mode.json"
    # File never written
    assert SidecarModeStore(p).get() is SidecarMode.OFF


def test_rejects_bogus_mode(tmp_path: Path):
    import pytest
    store = SidecarModeStore(tmp_path / "sidecar_mode.json")
    with pytest.raises(ValueError):
        store.set("wild-mode")  # type: ignore
