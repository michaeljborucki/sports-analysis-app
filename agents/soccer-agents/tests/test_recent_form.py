from unittest.mock import patch, MagicMock
from scrapers.team_stats import get_recent_form


@patch("scrapers.team_stats.requests.get")
def test_get_recent_form_default_on_failure(mock_get):
    mock_get.side_effect = Exception("API down")
    form = get_recent_form("Test FC", league="EPL")
    assert form["team"] == "Test FC"
    assert form["form"] == ""
    assert form["last_5_ppg"] == 0.0


def test_default_form_structure():
    from scrapers.team_stats import _default_form
    form = _default_form("Test FC")
    assert "form" in form
    assert "last_5_ppg" in form
    assert "home_record" in form
    assert "away_record" in form
