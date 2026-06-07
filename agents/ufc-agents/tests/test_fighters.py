from unittest.mock import patch, MagicMock
from scrapers.fighters import FighterProfile, get_fighter_profile


def test_fighter_profile_structure():
    fp = FighterProfile(
        name="Islam Makhachev",
        record="25-1-0",
        wins_ko=4, wins_sub=11, wins_dec=10,
        losses_ko=0, losses_sub=0, losses_dec=1,
        height="5'10\"",
        reach="70.5",
        stance="Orthodox",
        age=32,
        slpm=2.42,
        str_acc=0.592,
        str_def=0.645,
        td_avg=3.15,
        td_def=0.897,
        sub_avg=1.2,
        avg_fight_time="12:30",
        win_streak=3,
        last_5_fights=[],
    )
    assert fp.name == "Islam Makhachev"
    assert fp.record == "25-1-0"
    assert fp.wins_ko == 4


def test_fighter_profile_defaults():
    fp = FighterProfile(name="Unknown Fighter", record="0-0-0")
    assert fp.wins_ko == 0
    assert fp.stance == "Orthodox"
    assert fp.slpm == 0.0
    assert fp.last_5_fights == []


def test_fighter_profile_sapm():
    fp = FighterProfile(name="Test", record="10-0-0", slpm=3.5, sapm=2.1)
    assert fp.sapm == 2.1


@patch("scrapers.fighters.search_fighter")
def test_get_fighter_profile_not_found(mock_search):
    mock_search.return_value = None
    profile = get_fighter_profile("Nonexistent Fighter")
    assert profile is not None
    assert profile.name == "Nonexistent Fighter"
    assert profile.record == "0-0-0"
