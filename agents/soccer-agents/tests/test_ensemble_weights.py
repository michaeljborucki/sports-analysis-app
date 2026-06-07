import json, os, tempfile
from ensemble.weights import load_weights, save_weights, default_weights, BET_SLOTS

def test_bet_slots():
    assert BET_SLOTS == ["asian_handicap", "total", "btts"]

def test_default_weights():
    w = default_weights()
    # 6 LLM panel models + 1 quant_poisson non-LLM voter
    assert len(w) == 7
    assert "quant_poisson" in w
    llm_models = {k: v for k, v in w.items() if k != "quant_poisson"}
    assert len(llm_models) == 6
    for model, slots in llm_models.items():
        assert len(slots) == 3
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
        w["kimi"]["asian_handicap"] = 1.5
        save_weights(w, path)
        loaded = load_weights(path)
        assert loaded["kimi"]["asian_handicap"] == 1.5

def test_load_weights_corrupt_file_returns_defaults():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        with open(path, "w") as f:
            f.write("not json")
        w = load_weights(path)
        assert w == default_weights()
