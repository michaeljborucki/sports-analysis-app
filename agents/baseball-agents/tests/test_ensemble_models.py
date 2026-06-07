from ensemble.models import MODEL_REGISTRY, get_model, get_panel_models, get_challenger_model

def test_registry_has_seven_models():
    """Six panel + one dedicated challenger (Opus). Bumped from 6 on
    2026-05-07 when claude-opus-4.7 was added as the standalone challenger."""
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

def test_panel_models_returns_six():
    """Panel = ENSEMBLE_MODELS list, separate from the challenger."""
    panels = get_panel_models()
    assert len(panels) == 6

def test_gpt4o_slot_uses_gpt5_or_later():
    """The 'gpt4o' key is now mapped to the latest GPT model (the key name is
    legacy; the model ID was bumped 2026-05-07)."""
    m = get_model("gpt4o")
    assert m is not None
    assert m["id"].startswith("openai/gpt-5") or m["id"].startswith("openai/o3"), \
        f"gpt4o slot should point to a current GPT model, got {m['id']}"

def test_challenger_is_opus():
    """Challenger upgraded from Sonnet 4 → Opus 4.7 on 2026-05-07 to catch more
    data-quality issues (rookie pitchers, injury overrides, etc.)."""
    c = get_challenger_model()
    assert c is not None
    assert "opus" in c["id"], f"challenger should be Opus, got {c['id']}"

def test_panel_still_includes_sonnet():
    """Sonnet stays on the panel for diversity even though the challenger is now Opus."""
    panels = dict(get_panel_models())
    assert any("claude-sonnet" in m["id"] for m in panels.values())
