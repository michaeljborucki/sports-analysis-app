import io
import pytest
from server.odds.bets_csv import parse_csv_to_bet_rows


SAMPLE_OK = """date,book,sport,event,market,side,odds,stake,result
2026-06-19,DraftKings,nba,MIA @ BOS,h2h,BOS,-145,50,W
2026-06-20,FanDuel,mlb,LAD @ SF,spreads -1.5,LAD,+155,25,pending
2026-06-20,Pinnacle,tennis,Sinner vs Alcaraz,h2h,Alcaraz,+105,100,L
"""


def test_parses_happy_path():
    rows, errors = parse_csv_to_bet_rows(io.StringIO(SAMPLE_OK))
    assert len(rows) == 3
    assert errors == []
    assert rows[0].source_book == "imported"
    assert rows[0].raw_description == "MIA @ BOS"
    assert rows[0].odds_american == -145
    assert rows[0].stake == 50.0
    assert rows[0].status == "win"


def test_status_pending_when_result_pending():
    rows, errors = parse_csv_to_bet_rows(io.StringIO(SAMPLE_OK))
    assert rows[1].status == "pending"


def test_missing_required_column_returns_error():
    bad = "date,book,sport,market,side,odds,result\n2026-06-19,DK,nba,h2h,BOS,-145,W\n"
    rows, errors = parse_csv_to_bet_rows(io.StringIO(bad))
    assert rows == []
    assert any("stake" in e["reason"] for e in errors)


def test_bad_date_rejected_row_still_returns_good_rows():
    mixed = """date,book,sport,event,market,side,odds,stake,result
last tuesday,DK,nba,A @ B,h2h,A,-145,50,W
2026-06-19,DK,nba,C @ D,h2h,C,+110,25,L
"""
    rows, errors = parse_csv_to_bet_rows(io.StringIO(mixed))
    assert len(rows) == 1
    assert rows[0].raw_description == "C @ D"
    assert len(errors) == 1
    assert "date" in errors[0]["reason"] or "parse" in errors[0]["reason"]


def test_external_id_is_stable_hash():
    rows, _ = parse_csv_to_bet_rows(io.StringIO(SAMPLE_OK))
    rows2, _ = parse_csv_to_bet_rows(io.StringIO(SAMPLE_OK))
    assert [r.external_id for r in rows] == [r.external_id for r in rows2]
