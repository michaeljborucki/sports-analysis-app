"""Tests for server/odds/normalize.py outcome-name collision logging (M7)."""
from datetime import datetime, timezone


def _row(**overrides) -> dict:
    base = {
        "event_id": "ev1", "sport_key": "nba",
        "home_team": "Boston Celtics", "away_team": "Miami Heat",
        "commence_time": datetime(2026, 6, 21, tzinfo=timezone.utc),
        "bookmaker_key": "draftkings",
        "market_key": "spreads", "outcome_name": "Boston Celtics",
        "outcome_point": -2.5,
        "price_american": -110,
        "fetched_at": datetime(2026, 6, 21, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def test_outcome_name_collision_emits_warning(caplog):
    """Two books emitting different outcome_names for the same
    (event, market, point) should produce one WARN."""
    from server.odds.normalize import rows_to_games, _reset_collision_log_for_tests
    _reset_collision_log_for_tests()
    rows = [
        _row(bookmaker_key="draftkings", outcome_name="BOS", outcome_point=-2.5),
        _row(bookmaker_key="fanduel",    outcome_name="Boston Celtics", outcome_point=-2.5),
    ]
    with caplog.at_level("WARNING", logger="server.odds.normalize"):
        rows_to_games(rows, now=datetime.now(timezone.utc))
    warnings = [r for r in caplog.records if "outcome-name collision" in r.getMessage()]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "ev1" in msg and "spreads" in msg and "-2.5" in msg
    assert "BOS" in msg and "Boston Celtics" in msg


def test_outcome_name_collision_is_dedupd_per_address(caplog):
    """Re-seeing the same collision should NOT emit a second WARN."""
    from server.odds.normalize import rows_to_games, _reset_collision_log_for_tests
    _reset_collision_log_for_tests()
    rows = [
        _row(bookmaker_key="draftkings", outcome_name="BOS", outcome_point=-2.5),
        _row(bookmaker_key="fanduel",    outcome_name="Boston Celtics", outcome_point=-2.5),
    ]
    with caplog.at_level("WARNING", logger="server.odds.normalize"):
        rows_to_games(rows, now=datetime.now(timezone.utc))
        rows_to_games(rows, now=datetime.now(timezone.utc))
    warnings = [r for r in caplog.records if "outcome-name collision" in r.getMessage()]
    assert len(warnings) == 1


def test_no_warning_when_outcome_names_match(caplog):
    from server.odds.normalize import rows_to_games, _reset_collision_log_for_tests
    _reset_collision_log_for_tests()
    rows = [
        _row(bookmaker_key="draftkings", outcome_name="Boston Celtics"),
        _row(bookmaker_key="fanduel",    outcome_name="Boston Celtics"),
    ]
    with caplog.at_level("WARNING", logger="server.odds.normalize"):
        rows_to_games(rows, now=datetime.now(timezone.utc))
    warnings = [r for r in caplog.records if "outcome-name collision" in r.getMessage()]
    assert len(warnings) == 0
