from datetime import datetime, timezone

from server.odds.cache import OddsCache
from server.odds.normalize import normalize_odds_response
from server.odds.raw import decode_outcome_name, rows_to_odds_api_events


def test_decode_outcome_name_plain_markets():
    # Moneylines / spreads / totals keep their raw name and carry no desc.
    assert decode_outcome_name("h2h", "New York Yankees") == (None, "New York Yankees")
    assert decode_outcome_name("spreads", "Boston Red Sox") == (None, "Boston Red Sox")
    assert decode_outcome_name("totals", "Over") == (None, "Over")


def test_decode_outcome_name_player_props():
    assert decode_outcome_name("pitcher_strikeouts", "Drew Rasmussen Over") == (
        "Drew Rasmussen", "Over",
    )
    assert decode_outcome_name("batter_hits", "Aaron Judge Under") == (
        "Aaron Judge", "Under",
    )
    # Yes/No props (e.g. batter_first_home_run).
    assert decode_outcome_name("batter_first_home_run", "Mookie Betts Yes") == (
        "Mookie Betts", "Yes",
    )


def test_decode_outcome_name_team_totals():
    assert decode_outcome_name("team_totals", "New York Yankees Over") == (
        "New York Yankees", "Over",
    )
    assert decode_outcome_name("alternate_team_totals", "Boston Red Sox Under") == (
        "Boston Red Sox", "Under",
    )


# A single Odds API event spanning a moneyline, a totals line, a team total
# and a player prop — every outcome shape the encoder/decoder must round-trip.
SAMPLE_EVENT = {
    "id": "evt1",
    "sport_key": "baseball_mlb",
    "commence_time": "2026-06-07T23:05:00Z",
    "home_team": "New York Yankees",
    "away_team": "Boston Red Sox",
    "bookmakers": [
        {
            "key": "fanduel",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "New York Yankees", "price": -150},
                    {"name": "Boston Red Sox", "price": 130},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": -110, "point": 8.5},
                    {"name": "Under", "price": -110, "point": 8.5},
                ]},
                {"key": "team_totals", "outcomes": [
                    {"name": "Over", "price": -115, "point": 4.5,
                     "description": "New York Yankees"},
                    {"name": "Under", "price": -105, "point": 4.5,
                     "description": "New York Yankees"},
                ]},
                {"key": "pitcher_strikeouts", "outcomes": [
                    {"name": "Over", "price": -120, "point": 5.5,
                     "description": "Drew Rasmussen"},
                    {"name": "Under", "price": 100, "point": 5.5,
                     "description": "Drew Rasmussen"},
                ]},
            ],
        },
        # A non-Odds-API book must be dropped from the reconstruction.
        {
            "key": "polymarket",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "New York Yankees", "price": -160},
                    {"name": "Boston Red Sox", "price": 140},
                ]},
            ],
        },
    ],
}


def _market(event: dict, bookmaker_key: str, market_key: str) -> dict:
    book = next(b for b in event["bookmakers"] if b["key"] == bookmaker_key)
    return next(m for m in book["markets"] if m["key"] == market_key)


def test_round_trip_through_cache(tmp_path):
    """normalize -> cache -> all_current -> raw reconstruction is faithful."""
    cache = OddsCache(tmp_path / "cache.db")
    cache.init()
    fetched = datetime(2026, 6, 7, 22, 0, tzinfo=timezone.utc)
    rows = normalize_odds_response([SAMPLE_EVENT], fetched_at=fetched, sport_key="mlb")
    cache.upsert(rows)

    events = rows_to_odds_api_events(cache.all_current(sport_key="mlb"))
    assert len(events) == 1
    event = events[0]
    assert event["id"] == "evt1"
    assert event["home_team"] == "New York Yankees"
    assert event["away_team"] == "Boston Red Sox"

    # polymarket dropped; only the Odds API book survives.
    assert [b["key"] for b in event["bookmakers"]] == ["fanduel"]

    # h2h carries no point (cache nulls the sentinel for h2h).
    h2h = _market(event, "fanduel", "h2h")
    names = {o["name"]: o for o in h2h["outcomes"]}
    assert names["New York Yankees"]["price"] == -150
    assert "point" not in names["New York Yankees"]

    # totals keep their point.
    totals = {o["name"]: o for o in _market(event, "fanduel", "totals")["outcomes"]}
    assert totals["Over"]["point"] == 8.5

    # team totals + props decode the description back out of outcome_name.
    tt = _market(event, "fanduel", "team_totals")["outcomes"]
    assert all(o["description"] == "New York Yankees" for o in tt)
    assert {o["name"] for o in tt} == {"Over", "Under"}

    props = {o["name"]: o for o in _market(event, "fanduel", "pitcher_strikeouts")["outcomes"]}
    assert props["Over"]["description"] == "Drew Rasmussen"
    assert props["Over"]["point"] == 5.5


def test_nrfi_bridge_rows_excluded(tmp_path):
    """Synthetic nrfi rows must not appear as a market in the feed."""
    cache = OddsCache(tmp_path / "cache.db")
    cache.init()
    fetched = datetime(2026, 6, 7, 22, 0, tzinfo=timezone.utc)
    event = {
        "id": "evt2",
        "sport_key": "baseball_mlb",
        "commence_time": "2026-06-07T23:05:00Z",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "bookmakers": [{
            "key": "fanduel",
            "markets": [{"key": "totals_1st_1_innings", "outcomes": [
                {"name": "Over", "price": 120, "point": 0.5},
                {"name": "Under", "price": -140, "point": 0.5},
            ]}],
        }],
    }
    rows = normalize_odds_response([event], fetched_at=fetched, sport_key="mlb")
    # normalize synthesizes nrfi rows alongside totals_1st_1_innings.
    assert any(r["market_key"] == "nrfi" for r in rows)

    events = rows_to_odds_api_events(cache_seed(cache, rows))
    market_keys = {m["key"] for m in events[0]["bookmakers"][0]["markets"]}
    assert "nrfi" not in market_keys
    assert "totals_1st_1_innings" in market_keys


def cache_seed(cache: OddsCache, rows: list[dict]) -> list[dict]:
    cache.upsert(rows)
    return cache.all_current(sport_key="mlb")
