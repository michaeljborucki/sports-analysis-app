from server.systems.registry import PRIMARY_SYSTEMS, SUBSET_SYSTEMS


def test_registry_exposes_26_primary_systems_and_nested_football_2b():
    assert len(PRIMARY_SYSTEMS) == 26
    assert len({system.system_id for system in PRIMARY_SYSTEMS}) == 26
    assert {system.system_id for system in PRIMARY_SYSTEMS if not system.enabled} == {
        "FOOTBALL_8_CFB_MAC_BOWL_FADE_TBD",
        "FOOTBALL_11_NFL_EARLY_DIVISIONAL_DOG_TBD",
        "FOOTBALL_13_NFL_OVER_AFTER_BOTH_UNDER",
    }
    assert [system.system_id for system in SUBSET_SYSTEMS] == [
        "FOOTBALL_2B_CFB_LARGE_ROAD_FAVORITE_FADE"
    ]
    assert SUBSET_SYSTEMS[0].parent_system_id == (
        "FOOTBALL_2_CFB_ROAD_FAVORITE_FADE"
    )


def test_registry_keeps_source_claims_separate_from_verified_results():
    football_one = next(
        system for system in PRIMARY_SYSTEMS
        if system.system_id == "FOOTBALL_1_CFB_MASSIVE_HOME_FAVORITE"
    )
    assert football_one.source_claim == "18-5 ATS (78.3%) since 2013"
    assert football_one.verified_backtest is None
