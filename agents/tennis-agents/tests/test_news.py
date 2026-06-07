from unittest.mock import patch, MagicMock
from scrapers.news import get_player_news


@patch("scrapers.news.API_TENNIS_KEY", "test-key")
@patch("scrapers.news.requests.get")
def test_get_player_news_returns_list(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"result": [
        {"player_name": "Djokovic", "type": "injury", "description": "Knee", "date": "2026-03-20"},
    ]}
    mock_get.return_value = mock_resp
    news = get_player_news("Djokovic")
    assert len(news) == 1
    assert news[0]["player"] == "Djokovic"


@patch("scrapers.news.API_TENNIS_KEY", "")
def test_get_player_news_no_key():
    news = get_player_news()
    assert news == []
