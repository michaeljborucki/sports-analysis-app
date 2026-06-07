"""Tests for scrapers/scores.py — cricket rewrite."""
from unittest.mock import patch, MagicMock
from scrapers.scores import get_final_scores, MatchResult


MOCK_CRICKET_SCORES_RESPONSE = {
    "status": "success",
    "data": [
        {
            "id": "match_001",
            "name": "Mumbai Indians vs Chennai Super Kings",
            "matchType": "t20",
            "status": "Mumbai Indians won by 15 runs",
            "venue": "Wankhede Stadium",
            "date": "2026-03-22",
            "teams": ["Mumbai Indians", "Chennai Super Kings"],
            "score": [
                {
                    "r": 185,
                    "w": 4,
                    "o": 20.0,
                    "inning": "Mumbai Indians Inning 1",
                },
                {
                    "r": 170,
                    "w": 8,
                    "o": 20.0,
                    "inning": "Chennai Super Kings Inning 1",
                },
            ],
            "tossWinner": "Mumbai Indians",
            "tossChoice": "bat",
        }
    ],
}


@patch("scrapers.scores.requests.get")
def test_get_final_scores_returns_match_result(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_SCORES_RESPONSE
    mock_get.return_value = mock_resp

    results = get_final_scores()
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, MatchResult)


@patch("scrapers.scores.requests.get")
def test_get_final_scores_winner(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_SCORES_RESPONSE
    mock_get.return_value = mock_resp

    results = get_final_scores()
    r = results[0]
    assert r.winner == "MI"


@patch("scrapers.scores.requests.get")
def test_get_final_scores_team_abbrevs(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_SCORES_RESPONSE
    mock_get.return_value = mock_resp

    results = get_final_scores()
    r = results[0]
    assert r.team_a == "MI"
    assert r.team_b == "CSK"
    assert r.team_a_full == "Mumbai Indians"
    assert r.team_b_full == "Chennai Super Kings"


@patch("scrapers.scores.requests.get")
def test_get_final_scores_scores(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_SCORES_RESPONSE
    mock_get.return_value = mock_resp

    results = get_final_scores()
    r = results[0]
    assert r.team_a_score == 185
    assert r.team_a_wickets == 4
    assert r.team_a_overs == 20.0
    assert r.team_b_score == 170
    assert r.team_b_wickets == 8
    assert r.team_b_overs == 20.0


@patch("scrapers.scores.requests.get")
def test_get_final_scores_total_runs(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_SCORES_RESPONSE
    mock_get.return_value = mock_resp

    results = get_final_scores()
    r = results[0]
    assert r.total_runs == 185 + 170


@patch("scrapers.scores.requests.get")
def test_get_final_scores_toss(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_SCORES_RESPONSE
    mock_get.return_value = mock_resp

    results = get_final_scores()
    r = results[0]
    assert r.toss_winner == "MI"
    assert r.toss_decision == "bat"


@patch("scrapers.scores.requests.get")
def test_get_final_scores_dls_detection(mock_get):
    dls_response = {
        "status": "success",
        "data": [
            {
                "id": "match_002",
                "name": "Kolkata Knight Riders vs Delhi Capitals",
                "matchType": "t20",
                "status": "Kolkata Knight Riders won by DLS method",
                "venue": "Eden Gardens",
                "date": "2026-03-22",
                "teams": ["Kolkata Knight Riders", "Delhi Capitals"],
                "score": [
                    {"r": 160, "w": 5, "o": 20.0, "inning": "Kolkata Knight Riders Inning 1"},
                    {"r": 95, "w": 3, "o": 12.0, "inning": "Delhi Capitals Inning 1"},
                ],
                "tossWinner": "Kolkata Knight Riders",
                "tossChoice": "field",
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = dls_response
    mock_get.return_value = mock_resp

    results = get_final_scores()
    r = results[0]
    assert r.dls_applied is True


@patch("scrapers.scores.requests.get")
def test_get_final_scores_no_dls(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = MOCK_CRICKET_SCORES_RESPONSE
    mock_get.return_value = mock_resp

    results = get_final_scores()
    r = results[0]
    assert r.dls_applied is False


@patch("scrapers.scores.requests.get")
def test_get_final_scores_empty_response(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "success", "data": []}
    mock_get.return_value = mock_resp

    results = get_final_scores()
    assert results == []


@patch("scrapers.scores.requests.get")
def test_get_final_scores_filters_non_t20(mock_get):
    """Only t20 matches should be returned."""
    odi_response = {
        "status": "success",
        "data": [
            {
                "id": "odi_001",
                "name": "India vs Australia",
                "matchType": "odi",
                "status": "India won by 50 runs",
                "venue": "Wankhede Stadium",
                "date": "2026-03-22",
                "teams": ["India", "Australia"],
                "score": [
                    {"r": 300, "w": 6, "o": 50.0, "inning": "India Inning 1"},
                    {"r": 250, "w": 10, "o": 48.0, "inning": "Australia Inning 1"},
                ],
                "tossWinner": "India",
                "tossChoice": "bat",
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = odi_response
    mock_get.return_value = mock_resp

    results = get_final_scores()
    assert results == []


@patch("scrapers.scores.requests.get")
def test_get_final_scores_tied_match(mock_get):
    """Tied matches should be included."""
    tied_response = {
        "status": "success",
        "data": [
            {
                "id": "match_003",
                "name": "Royal Challengers Bengaluru vs Rajasthan Royals",
                "matchType": "t20",
                "status": "Match tied",
                "venue": "M. Chinnaswamy Stadium",
                "date": "2026-03-22",
                "teams": ["Royal Challengers Bengaluru", "Rajasthan Royals"],
                "score": [
                    {"r": 175, "w": 6, "o": 20.0, "inning": "Royal Challengers Bengaluru Inning 1"},
                    {"r": 175, "w": 8, "o": 20.0, "inning": "Rajasthan Royals Inning 1"},
                ],
                "tossWinner": "Royal Challengers Bengaluru",
                "tossChoice": "field",
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = tied_response
    mock_get.return_value = mock_resp

    results = get_final_scores()
    assert len(results) == 1
    r = results[0]
    assert "tied" in r.status.lower()
