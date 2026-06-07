from ensemble.models import MODEL_REGISTRY, get_model, get_panel_models, get_challenger_model

def test_registry_has_seven_models():
    assert len(MODEL_REGISTRY) == 7

def test_all_models_have_required_fields():
    required = {"id", "role", "default_temp", "max_tokens", "timeout", "input_price", "output_price"}
    for key, model in MODEL_REGISTRY.items():
        missing = required - set(model.keys())
        assert not missing, f"Model {key} missing fields: {missing}"

def test_get_model_valid():
    m = get_model("kimi")
    assert m["id"] == "moonshotai/kimi-k2.5"

def test_get_model_invalid():
    assert get_model("nonexistent") is None

def test_panel_models_returns_all_seven():
    panels = get_panel_models()
    assert len(panels) == 7

def test_challenger_model():
    c = get_challenger_model()
    assert c is not None
    assert "claude" in c["id"]
