import json, os, tempfile
from ensemble.weights import load_weights, save_weights, default_weights, BET_SLOTS

def test_bet_slots():
    assert BET_SLOTS == [
        "moneyline", "run_line", "total", "first_5_ml", "first_5_total",
        "team_total_home", "team_total_away", "first_5_rl", "nrfi",
        "first_1_rl", "first_3_ml", "first_3_total", "first_3_rl",
    ]

def test_default_weights():
    w = default_weights()
    assert len(w) == 6
    for model, slots in w.items():
        assert len(slots) == 13
        for val in slots.values():
            assert val == 1.0

def test_load_weights_creates_file_if_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        w = load_weights(path)
        assert os.path.exists(path)
        assert w == default_weights()

def test_save_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        w = default_weights()
        w["kimi"]["moneyline"] = 1.5
        save_weights(w, path)
        loaded = load_weights(path)
        assert loaded["kimi"]["moneyline"] == 1.5

def test_load_weights_corrupt_file_returns_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        with open(path, "w") as f:
            f.write("not json")
        w = load_weights(path)
        assert w == default_weights()
