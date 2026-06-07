from unittest.mock import patch, MagicMock
from scrapers.rankings import get_rankings, get_fighter_rank


@patch("scrapers.rankings.requests.get")
def test_get_rankings_returns_dict(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body></body></html>"
    mock_get.return_value = mock_resp

    result = get_rankings()
    assert isinstance(result, dict)


def test_rankings_empty_on_failure():
    with patch("scrapers.rankings.requests.get", side_effect=Exception("fail")):
        result = get_rankings()
        assert result == {}


def test_get_fighter_rank_found():
    rankings = {"Lightweight": [{"rank": 1, "name": "Islam Makhachev"}]}
    result = get_fighter_rank("Islam Makhachev", rankings)
    assert result == ("Lightweight", 1)


def test_get_fighter_rank_not_found():
    rankings = {"Lightweight": [{"rank": 1, "name": "Islam Makhachev"}]}
    result = get_fighter_rank("Unknown Fighter", rankings)
    assert result is None
