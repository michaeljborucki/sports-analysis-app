from datetime import datetime, timezone

from server.odds.normalize import normalize_odds_response


def test_normalize_soccer_event_preserves_provider_league_metadata():
    """Dropping the provider league fields would make soccer grouping impossible."""
    now = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
    fixture = [{
        "id": "epl-1",
        "sport_key": "soccer_epl",
        "sport_title": "EPL",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": "2026-08-22T18:00:00Z",
        "bookmakers": [{
            "key": "draftkings",
            "markets": [{
                "key": "spreads",
                "outcomes": [{"name": "Arsenal", "point": -0.5, "price": -110}],
            }],
        }],
    }]

    rows = normalize_odds_response(fixture, fetched_at=now, sport_key="soccer")

    assert rows[0]["sport_key"] == "soccer"
    assert rows[0]["league_key"] == "soccer_epl"
    assert rows[0]["league_title"] == "EPL"
