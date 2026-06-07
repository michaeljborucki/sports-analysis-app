import json, os, tempfile
from ensemble.weights import load_weights, save_weights, default_weights, shrink_weights, BET_SLOTS

def test_bet_slots():
    assert BET_SLOTS == ["moneyline", "spread", "total", "first_half_ml", "first_half_spread", "first_half_total"]

def test_default_weights():
    w = default_weights()
    assert len(w) == 7
    for model, slots in w.items():
        assert len(slots) == 6
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


def test_shrink_weights_at_zero_bets():
    """With 0 settled bets, all weights should be exactly 1.0 (uniform)."""
    weights = {"kimi": {"moneyline": 1.5, "spread": 0.8}}
    shrunk = shrink_weights(weights, n_settled=0)
    assert shrunk["kimi"]["moneyline"] == 1.0
    assert shrunk["kimi"]["spread"] == 1.0


def test_shrink_weights_at_full_confidence():
    """With 100+ bets, original weights should be preserved."""
    weights = {"kimi": {"moneyline": 1.3, "spread": 0.7}}
    shrunk = shrink_weights(weights, n_settled=100)
    assert shrunk["kimi"]["moneyline"] == 1.3
    assert shrunk["kimi"]["spread"] == 0.7


def test_shrink_weights_partial_shrinkage():
    """At 50 bets, weights should be 50% shrunk toward uniform."""
    weights = {"kimi": {"moneyline": 1.4}}
    shrunk = shrink_weights(weights, n_settled=50)
    # effective = 1.0 + (1.4 - 1.0) * 0.5 = 1.2
    assert abs(shrunk["kimi"]["moneyline"] - 1.2) < 0.001


def test_shrink_weights_caps_at_max():
    """Weights above MAX_WEIGHT (1.5) should be capped."""
    weights = {"gemini": {"moneyline": 2.0}}
    shrunk = shrink_weights(weights, n_settled=200)
    assert shrunk["gemini"]["moneyline"] == 1.5
