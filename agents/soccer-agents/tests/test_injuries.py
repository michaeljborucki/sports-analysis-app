import pytest
from unittest.mock import patch, MagicMock
from scrapers.injuries import get_squad_injuries

MOCK_ESPN_INJURIES = {
    "sports": [{"leagues": [{"teams": [
        {
            "team": {
                "displayName": "Inter Miami CF",
                "injuries": [
                    {"athlete": {"displayName": "Lionel Messi"}, "status": "Out", "type": {"description": "Knee"}},
                    {"athlete": {"displayName": "Sergio Busquets"}, "status": "Doubtful", "type": {"description": "Hamstring"}},
                ],
            }
        }
    ]}]}],
}

@patch("scrapers.injuries.requests.get")
def test_get_squad_injuries(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_ESPN_INJURIES
    mock_resp.raise_for_status = MagicMock()
    mock_get.return_value = mock_resp

    injuries = get_squad_injuries("Inter Miami CF", league="MLS")
    assert len(injuries) == 2
    assert injuries[0]["player"] == "Lionel Messi"
    assert injuries[0]["status"] == "Out"
    assert injuries[0]["injury"] == "Knee"

def test_get_squad_injuries_handles_failure():
    injuries = get_squad_injuries("Nonexistent FC", league="MLS")
    assert injuries == []
