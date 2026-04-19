from datetime import date
from pathlib import Path

from server.picks.reader import PicksReader


FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_picks_reader_returns_ok_when_card_exists():
    reader = PicksReader(
        bet_card_dir=FIXTURE_DIR,
        bets_csv=FIXTURE_DIR / "bets_example.csv",
    )
    response = reader.get_picks_for_date(date(2026, 4, 1))
    assert response["status"] == "ok"
    assert len(response["picks"]) > 0


def test_picks_reader_tier_values_valid():
    reader = PicksReader(
        bet_card_dir=FIXTURE_DIR,
        bets_csv=FIXTURE_DIR / "bets_example.csv",
    )
    response = reader.get_picks_for_date(date(2026, 4, 1))
    tiers = {p["tier"] for p in response["picks"]}
    assert tiers <= {"high", "sweet", "lean"}


def test_picks_reader_sorted_by_edge_desc():
    reader = PicksReader(
        bet_card_dir=FIXTURE_DIR,
        bets_csv=FIXTURE_DIR / "bets_example.csv",
    )
    response = reader.get_picks_for_date(date(2026, 4, 1))
    edges = [p["edge_pct"] for p in response["picks"]]
    assert edges == sorted(edges, reverse=True)


def test_picks_reader_no_file_returns_empty(tmp_path: Path):
    reader = PicksReader(bet_card_dir=tmp_path, bets_csv=tmp_path / "missing.csv")
    response = reader.get_picks_for_date(date(2026, 4, 1))
    assert response["status"] == "no_picks_today"
    assert response["picks"] == []


def test_picks_reader_get_todays_event_ids_empty_stub(tmp_path: Path):
    reader = PicksReader(bet_card_dir=tmp_path, bets_csv=tmp_path / "missing.csv")
    assert reader.get_todays_event_ids(date(2026, 4, 1)) == set()
