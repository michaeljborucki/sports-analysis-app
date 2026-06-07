from unittest.mock import patch, MagicMock
from scrapers.news import get_injuries


MOCK_INJURIES = {
    "people": [
        {
            "id": 123,
            "fullName": "Mike Trout",
            "currentTeam": {"abbreviation": "LAA"},
            "injuries": [
                {"description": "Left knee", "status": "10-Day IL"}
            ],
        }
    ]
}


@patch("scrapers.news.requests.get")
def test_get_injuries(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_INJURIES
    mock_get.return_value = mock_resp

    injuries = get_injuries()
    assert len(injuries) >= 1
    assert injuries[0]["player"] == "Mike Trout"
    assert injuries[0]["team"] == "LAA"


@patch("scrapers.news.requests.get")
def test_get_injuries_for_team(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_INJURIES
    mock_get.return_value = mock_resp

    injuries = get_injuries(team="LAA")
    assert all(i["team"] == "LAA" for i in injuries)
