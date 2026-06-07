from scrapers.news import get_squad_updates, SquadUpdate


def test_get_squad_updates_returns_empty_list():
    result = get_squad_updates("ipl")
    assert isinstance(result, list)
    assert len(result) == 0


def test_get_squad_updates_any_league():
    for league in ["bbl", "cpl", "psl", "hundred"]:
        result = get_squad_updates(league)
        assert result == []


def test_squad_update_dataclass():
    update = SquadUpdate(team="MI", league="ipl", available=["Player A"], unavailable=["Player B"], notes="Test")
    assert update.team == "MI"
    assert update.league == "ipl"
    assert update.available == ["Player A"]
    assert update.unavailable == ["Player B"]
    assert update.notes == "Test"
