"""Regression tests for the abbreviated → full player name resolution path.

Fixes a silent data bug discovered 2026-04-24: api-tennis `get_fixtures`
returns abbreviated names ("A. Rublev") while the local Sackmann archive is
keyed by full names ("Andrey Rublev"). Without resolving the abbreviation,
``get_player_profile`` falls back to placeholder data (Elo 1500, 0-0 record,
999 days since last match), which the ensemble challenger correctly kills
as "missing player data" — producing the 0-bet pattern we were chasing.

The fix: ``scrapers/schedule.get_schedule`` carries ``player_a_key`` and
``player_b_key``, and ``main._resolve_full_name`` looks them up via
``sackmann_sync._ensure_player`` before briefing construction.
"""
from unittest.mock import patch


def test_resolve_full_name_uses_sackmann_sync_ensure_player():
    """_resolve_full_name calls _ensure_player with the player_key and
    returns the full name from the returned metadata."""
    from main import _resolve_full_name

    cache: dict = {}

    def _fake_ensure_player(pk, tour, c):
        assert pk == 2847 and tour == "atp"
        return {"name_first": "Andrey", "name_last": "Rublev"}

    with patch("scrapers.sackmann_sync._ensure_player", _fake_ensure_player):
        full = _resolve_full_name("A. Rublev", 2847, "atp", cache)
    assert full == "Andrey Rublev"


def test_resolve_full_name_falls_back_on_empty_metadata():
    """If api-tennis lookup returns no metadata, the abbreviated name is
    returned unchanged — the downstream profile will use placeholder data,
    but the pipeline still runs."""
    from main import _resolve_full_name

    cache: dict = {}
    with patch("scrapers.sackmann_sync._ensure_player", return_value={}):
        full = _resolve_full_name("A. Rublev", 2847, "atp", cache)
    assert full == "A. Rublev"


def test_resolve_full_name_skips_lookup_when_key_missing():
    """No player_key → return the abbreviation unchanged, don't call the API."""
    from main import _resolve_full_name

    cache: dict = {}
    called = []
    def _spy(pk, tour, c):
        called.append(pk)
        return {"name_first": "X", "name_last": "Y"}
    with patch("scrapers.sackmann_sync._ensure_player", _spy):
        full = _resolve_full_name("A. Rublev", "", "atp", cache)
    assert full == "A. Rublev"
    assert called == []  # lookup was skipped


def test_schedule_carries_player_keys():
    """``get_schedule`` must populate player_a_key / player_b_key so the
    downstream name resolver has what it needs."""
    from scrapers import schedule

    fake_response = {
        "result": [
            {
                "event_first_player": "A. Rublev",
                "event_second_player": "V. Kopriva",
                "first_player_key": 2847,
                "second_player_key": 1083,
                "tournament_name": "Madrid",
                "tournament_round": "1/32-finals",
                "event_type_type": "Atp Singles",
                "event_key": 999,
                "event_date": "2026-04-24",
                "event_time": "11:00",
            }
        ]
    }

    class _FakeResp:
        def __init__(self, data): self._data = data
        def raise_for_status(self): pass
        def json(self): return self._data

    with patch("scrapers.schedule.API_TENNIS_KEY", "fake"), \
         patch("scrapers.schedule.requests.get",
               return_value=_FakeResp(fake_response)):
        matches = schedule.get_schedule("atp", "2026-04-24")

    assert len(matches) == 1
    m = matches[0]
    assert m["player_a"] == "A. Rublev"
    assert m["player_a_key"] == 2847
    assert m["player_b_key"] == 1083


def test_screen_match_resolves_names_before_profile_lookup():
    """End-to-end: _screen_one_match passes the FULL name to get_player_profile.

    Mocks everything external; verifies the critical hand-off: an abbreviated
    name came in from the schedule, a full name went into the profile call.
    """
    from main import _screen_one_match

    match = {
        "player_a": "A. Rublev", "player_a_key": 2847,
        "player_b": "V. Kopriva", "player_b_key": 1083,
        "tournament": "Madrid", "round": "R32", "surface": "clay",
        "indoor_outdoor": "outdoor", "start_time": "2099-01-01 11:00",
        "match_id": 999,
    }

    # Stub _ensure_player to simulate successful api-tennis lookup
    def _fake_ensure(pk, tour, c):
        return {
            2847: {"name_first": "Andrey", "name_last": "Rublev"},
            1083: {"name_first": "Vit",    "name_last": "Kopriva"},
        }.get(pk, {})

    profile_calls: list[str] = []
    def _fake_profile(name, tour, surface):
        profile_calls.append(name)
        return {"name": name, "ranking": 10, "elo": 1750, "season_record": "15-8"}

    class _FakeOdds:
        moneyline = {"player_a": -140, "player_b": 120}
        game_handicap = {"player_a_point": -3.5, "player_a_odds": -110,
                         "player_b_point": 3.5, "player_b_odds": -110}
        total_games = {"line": 22.5, "over_odds": -110, "under_odds": -110}
        implied_probs = {"player_a": 0.583, "player_b": 0.417}

    with patch("scrapers.sackmann_sync._ensure_player", _fake_ensure), \
         patch("scrapers.players.get_player_profile", _fake_profile), \
         patch("scrapers.players.get_head_to_head", return_value={"overall": "0-0"}), \
         patch("scrapers.odds.find_odds_for_match", return_value=_FakeOdds()), \
         patch("scrapers.conditions.get_match_conditions", return_value={}), \
         patch("briefing.build_briefing", return_value="<briefing>"), \
         patch("simulate.run_plan_b", return_value={
             "predictions": {
                 "moneyline": {"player_a_win_prob": 0.6, "player_b_win_prob": 0.4},
                 "game_handicap": {"favorite_cover_prob": 0.55},
                 "total_games": {"over_prob": 0.5, "under_prob": 0.5,
                                 "projected_games": 22.0},
             }
         }):
        result = _screen_one_match(match, [], "atp", "2099-01-01", {})

    # Full names were used for profile lookup, not abbreviations
    assert "Andrey Rublev" in profile_calls
    assert "Vit Kopriva" in profile_calls
    assert "A. Rublev" not in profile_calls
    assert "V. Kopriva" not in profile_calls
    # match_key keeps abbreviations for Discord/tracker user-facing consistency
    assert result["match_key"] == "A. Rublev vs V. Kopriva"
