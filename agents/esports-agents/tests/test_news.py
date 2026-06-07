from scrapers.news import fetch_match_context, get_injuries

def test_fetch_match_context_returns_required_keys():
    result = fetch_match_context("cs2", "NaVi", "FaZe")
    assert "roster_news" in result
    assert "tournament_context" in result
    assert "narrative" in result
    assert "online_lan" in result

def test_fetch_match_context_has_both_teams():
    result = fetch_match_context("cs2", "NaVi", "FaZe")
    assert "team_a" in result["roster_news"]
    assert "team_b" in result["roster_news"]

def test_roster_news_returns_lists():
    result = fetch_match_context("lol", "T1", "GenG")
    assert isinstance(result["roster_news"]["team_a"], list)
    assert isinstance(result["roster_news"]["team_b"], list)

def test_get_injuries_returns_list():
    result = get_injuries()
    assert isinstance(result, list)

def test_get_injuries_with_team():
    result = get_injuries(team="NaVi")
    assert isinstance(result, list)
