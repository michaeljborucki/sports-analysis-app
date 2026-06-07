from scrapers.news import get_injuries

def test_get_injuries_returns_list():
    result = get_injuries(league="MLS")
    assert isinstance(result, list)

def test_get_injuries_no_teams():
    result = get_injuries(league="MLS", teams=None)
    assert result == []
