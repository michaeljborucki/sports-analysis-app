from unittest.mock import patch, MagicMock
from scrapers.lineups import get_confirmed_lineups


MOCK_SCHEDULE_LINEUPS = {
    "dates": [
        {
            "games": [
                {
                    "gamePk": 12345,
                    "teams": {
                        "away": {
                            "team": {"name": "Boston Red Sox"},
                        },
                        "home": {
                            "team": {"name": "New York Yankees"},
                        },
                    },
                    "lineups": {
                        "awayPlayers": [
                            {"id": 1, "fullName": "Player A", "primaryPosition": {"abbreviation": "CF"}, "batSide": {"code": "R"}},
                            {"id": 2, "fullName": "Player B", "primaryPosition": {"abbreviation": "SS"}, "batSide": {"code": "L"}},
                        ],
                        "homePlayers": [
                            {"id": 3, "fullName": "Player C", "primaryPosition": {"abbreviation": "RF"}, "batSide": {"code": "R"}},
                        ],
                    },
                }
            ]
        }
    ]
}


@patch("scrapers.lineups.requests.get")
def test_get_confirmed_lineups(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_SCHEDULE_LINEUPS
    mock_get.return_value = mock_resp

    result = get_confirmed_lineups("2026-04-01")
    assert "NYY" in result
    assert "BOS" in result
    assert result["BOS"]["confirmed"] is True
    assert len(result["BOS"]["lineup"]) == 2
    assert result["BOS"]["lineup"][0]["name"] == "Player A"


@patch("scrapers.lineups.requests.get")
def test_unconfirmed_lineup_when_no_lineups_key(mock_get):
    no_lineups = {
        "dates": [{"games": [{
            "gamePk": 99,
            "teams": {
                "away": {"team": {"name": "Boston Red Sox"}},
                "home": {"team": {"name": "New York Yankees"}},
            },
        }]}]
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = no_lineups
    mock_get.return_value = mock_resp

    result = get_confirmed_lineups("2026-04-01")
    assert result["NYY"]["confirmed"] is False
    assert result["NYY"]["lineup"] == []
