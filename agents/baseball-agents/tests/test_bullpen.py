from unittest.mock import patch, MagicMock
from scrapers.bullpen import get_bullpen_state, _classify_freshness


def test_classify_freshness():
    assert _classify_freshness(avg_pitches=10) == "fresh"
    assert _classify_freshness(avg_pitches=22) == "moderate"
    assert _classify_freshness(avg_pitches=32) == "tired"
    assert _classify_freshness(avg_pitches=45) == "gassed"


@patch("scrapers.bullpen.requests.get")
def test_get_bullpen_state_returns_shape(mock_get):
    # Mock roster response
    roster_resp = MagicMock()
    roster_resp.status_code = 200
    roster_resp.json.return_value = {
        "roster": [
            {"person": {"id": 1, "fullName": "Reliever A"},
             "status": {"code": "A"},
             "position": {"abbreviation": "RP"}},
            {"person": {"id": 2, "fullName": "Closer B"},
             "status": {"code": "A"},
             "position": {"abbreviation": "CL"}},
        ]
    }

    # Mock game log response (empty)
    log_resp = MagicMock()
    log_resp.status_code = 200
    log_resp.json.return_value = {"stats": []}

    mock_get.side_effect = [roster_resp, log_resp, log_resp]

    state = get_bullpen_state(147, "2026-04-01")
    assert "bullpen_freshness" in state
    assert "relievers" in state
