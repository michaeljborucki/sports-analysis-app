from ensemble.weights import BET_SLOTS, default_weights, load_weights, save_weights
from config import ENSEMBLE_MODELS

def test_bet_slots_has_three():
    assert BET_SLOTS == ["moneyline", "game_handicap", "total_games"]

def test_default_weights_structure():
    w = default_weights()
    for model in ENSEMBLE_MODELS:
        assert model in w
        for slot in BET_SLOTS:
            assert w[model][slot] == 1.0

def test_load_save_weights(tmp_path):
    path = str(tmp_path / "weights.json")
    w = default_weights()
    w["kimi"]["moneyline"] = 1.5
    save_weights(w, path)
    loaded = load_weights(path)
    assert loaded["kimi"]["moneyline"] == 1.5
