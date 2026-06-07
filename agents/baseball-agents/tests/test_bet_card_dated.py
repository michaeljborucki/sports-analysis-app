"""Regression tests for the dated mainline bet card output.

Pins:
- Filename pattern: data/bet_card_<date>.{txt,json}
- JSON schema: top-level keys + per-pick keys
- Mainline-only filter (props excluded)
- Two-sided tracking (overs AND unders both kept after we removed side filters)
"""
import json
from unittest.mock import patch
import pandas as pd
import pytest

from agents import bet_card as bc


@pytest.fixture
def fake_bets():
    """Mix of mainline + prop + filtered-out bet types."""
    return pd.DataFrame([
        # Mainlines — should appear in card
        {"date": "2026-04-20", "game": "BAL@KC", "bet_type": "moneyline",
         "side": "home", "odds": -150, "sim_prob": 0.62, "edge": 0.055,
         "kelly_pct": 0.02, "result": "", "profit": "", "market_prob": 0.6},
        {"date": "2026-04-20", "game": "BAL@KC", "bet_type": "total",
         "side": "under 9.0", "odds": -113, "sim_prob": 0.6, "edge": 0.12,
         "kelly_pct": 0.04, "result": "", "profit": "", "market_prob": 0.48},
        {"date": "2026-04-20", "game": "STL@MIA", "bet_type": "team_total_home",
         "side": "home over 4.5", "odds": 110, "sim_prob": 0.55, "edge": 0.08,
         "kelly_pct": 0.03, "result": "", "profit": "", "market_prob": 0.47},
        # Props — should be EXCLUDED from mainline card
        {"date": "2026-04-20", "game": "BAL@KC", "bet_type": "batter_hits",
         "side": "Aaron Judge over 0.5", "odds": -200, "sim_prob": 0.7,
         "edge": 0.03, "kelly_pct": 0.01, "result": "", "profit": "", "market_prob": 0.67},
        {"date": "2026-04-20", "game": "STL@MIA", "bet_type": "pitcher_strikeouts",
         "side": "Cole Ragans under 6.5", "odds": -110, "sim_prob": 0.6,
         "edge": 0.05, "kelly_pct": 0.02, "result": "", "profit": "", "market_prob": 0.55},
        # Different date — should not appear
        {"date": "2026-04-19", "game": "BAL@KC", "bet_type": "moneyline",
         "side": "away", "odds": +100, "sim_prob": 0.5, "edge": 0.0,
         "kelly_pct": 0.0, "result": "W", "profit": 1.0, "market_prob": 0.5},
    ])


# ---------------------------------------------------------------------------
# write_mainline_bet_card_files — file naming and structure
# ---------------------------------------------------------------------------

class TestFilenameDated:
    def test_filenames_use_date_suffix(self, tmp_path, fake_bets):
        with patch("agents.bet_card.load_bets", return_value=fake_bets):
            txt_path, json_path = bc.write_mainline_bet_card_files(
                "2026-04-20", out_dir=str(tmp_path))
        assert txt_path.name == "bet_card_2026-04-20.txt"
        assert json_path.name == "bet_card_2026-04-20.json"

    def test_files_actually_created(self, tmp_path, fake_bets):
        with patch("agents.bet_card.load_bets", return_value=fake_bets):
            txt_path, json_path = bc.write_mainline_bet_card_files(
                "2026-04-20", out_dir=str(tmp_path))
        assert txt_path.exists()
        assert json_path.exists()


# ---------------------------------------------------------------------------
# Mainline-only filter
# ---------------------------------------------------------------------------

class TestMainlineOnly:
    def test_props_excluded_from_text(self, tmp_path, fake_bets):
        with patch("agents.bet_card.load_bets", return_value=fake_bets):
            txt_path, _ = bc.write_mainline_bet_card_files("2026-04-20", out_dir=str(tmp_path))
        text = txt_path.read_text()
        assert "Aaron Judge" not in text
        assert "Cole Ragans" not in text
        assert "batter_hits" not in text
        assert "pitcher_strikeouts" not in text

    def test_mainlines_present_in_text(self, tmp_path, fake_bets):
        with patch("agents.bet_card.load_bets", return_value=fake_bets):
            txt_path, _ = bc.write_mainline_bet_card_files("2026-04-20", out_dir=str(tmp_path))
        text = txt_path.read_text()
        assert "BAL@KC" in text
        assert "STL@MIA" in text
        assert "moneyline" in text
        assert "total" in text
        assert "team_total_home" in text


class TestMainlineBetTypesConstant:
    def test_constant_includes_canonical_mainlines(self):
        """The MAINLINE_BET_TYPES constant is the contract for what counts
        as 'mainline' across the whole codebase."""
        canonical = {"moneyline", "run_line", "total", "team_total_home",
                     "team_total_away", "first_5_ml", "first_5_rl",
                     "first_5_total", "first_3_ml", "first_3_rl",
                     "first_3_total", "first_1_rl", "nrfi"}
        assert canonical == bc.MAINLINE_BET_TYPES

    def test_constant_excludes_props(self):
        prop_types = {"batter_hits", "batter_rbis", "pitcher_strikeouts",
                      "pitcher_outs", "batter_hits_runs_rbis"}
        assert prop_types.isdisjoint(bc.MAINLINE_BET_TYPES)


# ---------------------------------------------------------------------------
# JSON output schema
# ---------------------------------------------------------------------------

class TestJsonSchema:
    def test_top_level_keys(self, tmp_path, fake_bets):
        with patch("agents.bet_card.load_bets", return_value=fake_bets):
            _, json_path = bc.write_mainline_bet_card_files(
                "2026-04-20", out_dir=str(tmp_path))
        data = json.loads(json_path.read_text())
        assert set(data.keys()) == {"date", "generated_at", "total_picks", "games"}
        assert data["date"] == "2026-04-20"
        assert isinstance(data["total_picks"], int)
        assert isinstance(data["games"], list)

    def test_per_pick_keys(self, tmp_path, fake_bets):
        with patch("agents.bet_card.load_bets", return_value=fake_bets):
            _, json_path = bc.write_mainline_bet_card_files(
                "2026-04-20", out_dir=str(tmp_path))
        data = json.loads(json_path.read_text())
        assert data["games"], "must have at least one game"
        assert data["games"][0]["picks"], "must have at least one pick"
        pick = data["games"][0]["picks"][0]
        expected_keys = {"bet_type", "side", "odds", "market_prob",
                         "model_prob", "edge", "kelly_pct", "be_odds", "result"}
        assert set(pick.keys()) == expected_keys

    def test_total_picks_matches_games(self, tmp_path, fake_bets):
        with patch("agents.bet_card.load_bets", return_value=fake_bets):
            _, json_path = bc.write_mainline_bet_card_files(
                "2026-04-20", out_dir=str(tmp_path))
        data = json.loads(json_path.read_text())
        actual = sum(len(g["picks"]) for g in data["games"])
        assert data["total_picks"] == actual

    def test_only_target_date_appears(self, tmp_path, fake_bets):
        with patch("agents.bet_card.load_bets", return_value=fake_bets):
            _, json_path = bc.write_mainline_bet_card_files(
                "2026-04-20", out_dir=str(tmp_path))
        data = json.loads(json_path.read_text())
        assert data["date"] == "2026-04-20"
        # 2026-04-19 row should not be in the count
        assert data["total_picks"] == 3  # 3 mainlines for 04-20

    def test_no_picks_when_date_empty(self, tmp_path, fake_bets):
        with patch("agents.bet_card.load_bets", return_value=fake_bets):
            _, json_path = bc.write_mainline_bet_card_files(
                "2026-04-25", out_dir=str(tmp_path))  # no bets this date
        data = json.loads(json_path.read_text())
        assert data["total_picks"] == 0
        assert data["games"] == []
