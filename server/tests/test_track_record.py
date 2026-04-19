from datetime import date
from pathlib import Path

from server.picks.track_record import compute_30d_record


FIXTURE = Path(__file__).parent / "fixtures" / "bets_example.csv"


def test_compute_30d_record_returns_wins_losses_units():
    result = compute_30d_record(FIXTURE, reference_date=date(2026, 4, 1))
    assert "wins" in result
    assert "losses" in result
    assert "units" in result
    assert isinstance(result["wins"], int)


def test_compute_30d_record_formats_label():
    result = compute_30d_record(FIXTURE, reference_date=date(2026, 4, 1))
    assert "-" in result["label"]
    assert "u" in result["label"]


def test_compute_30d_record_missing_file_returns_zeros(tmp_path):
    result = compute_30d_record(tmp_path / "nope.csv", reference_date=date(2026, 4, 1))
    assert result["wins"] == 0
    assert result["losses"] == 0
    assert result["units"] == 0.0
