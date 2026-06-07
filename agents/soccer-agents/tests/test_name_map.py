from scrapers.name_map import normalize_team_name, build_league_name_map

def test_known_mapping():
    assert normalize_team_name("CF Montreal") == "CF Montréal"
    assert normalize_team_name("Columbus Crew SC") == "Columbus Crew"

def test_case_insensitive():
    assert normalize_team_name("cf montreal") == "CF Montréal"

def test_no_mapping_returns_original():
    assert normalize_team_name("Unknown FC") == "Unknown FC"

def test_build_league_map():
    odds = ["Arsenal", "CF Montreal", "Columbus Crew SC"]
    espn = ["Arsenal", "CF Montréal", "Columbus Crew"]
    mapping = build_league_name_map(odds, espn)
    assert mapping["Arsenal"] == "Arsenal"
    assert mapping["CF Montreal"] == "CF Montréal"
    assert mapping["Columbus Crew SC"] == "Columbus Crew"
