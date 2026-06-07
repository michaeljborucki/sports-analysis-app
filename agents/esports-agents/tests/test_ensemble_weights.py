import json, os, tempfile
from ensemble.weights import load_weights, save_weights, default_weights

# Use CS2 bet slots for testing
TEST_BET_SLOTS = ["moneyline", "map_handicap", "total_maps"]


def test_default_weights():
    w = default_weights(TEST_BET_SLOTS)
    assert len(w) == 6
    for model, slots in w.items():
        assert len(slots) == 3
        for val in slots.values():
            assert val == 1.0

def test_load_weights_creates_file_if_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        w = load_weights(TEST_BET_SLOTS, path)
        assert os.path.exists(path)
        assert w == default_weights(TEST_BET_SLOTS)

def test_save_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        w = default_weights(TEST_BET_SLOTS)
        w["kimi"]["moneyline"] = 1.5
        save_weights(w, path)
        loaded = load_weights(TEST_BET_SLOTS, path)
        assert loaded["kimi"]["moneyline"] == 1.5

def test_load_weights_corrupt_file_returns_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        with open(path, "w") as f:
            f.write("not json")
        w = load_weights(TEST_BET_SLOTS, path)
        assert w == default_weights(TEST_BET_SLOTS)
