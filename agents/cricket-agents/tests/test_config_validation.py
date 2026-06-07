from config import BET_TYPES, ACTIVE_TIERS


def test_bet_types_has_16_entries():
    assert len(BET_TYPES) == 16


def test_all_linear_multipliers_match_std_dev():
    for key, cfg in BET_TYPES.items():
        if cfg["engine"] == "linear":
            expected = round(1 / (2 * cfg["std_dev"]), 3)
            assert abs(cfg["multiplier"] - expected) < 0.001, (
                f"{key}: multiplier {cfg['multiplier']} != 1/(2*{cfg['std_dev']}) = {expected}"
            )


def test_all_bet_types_have_required_fields():
    for key, cfg in BET_TYPES.items():
        assert "engine" in cfg, f"{key} missing engine"
        assert "threshold" in cfg, f"{key} missing threshold"
        assert "tier" in cfg, f"{key} missing tier"
        if cfg["engine"] == "linear":
            assert "std_dev" in cfg, f"{key} (linear) missing std_dev"
            assert "multiplier" in cfg, f"{key} (linear) missing multiplier"


def test_active_tiers_valid():
    assert all(t in [1, 2, 3, 4] for t in ACTIVE_TIERS)


def test_tier_thresholds():
    """Tier 1 = 0.06, Tier 2 = 0.05, Tier 3 = 0.04, Tier 4 = 0.05."""
    tier_thresholds = {1: 0.06, 2: 0.05, 3: 0.04, 4: 0.05}
    for key, cfg in BET_TYPES.items():
        expected = tier_thresholds[cfg["tier"]]
        assert cfg["threshold"] == expected, (
            f"{key}: threshold {cfg['threshold']} != expected {expected} for tier {cfg['tier']}"
        )
