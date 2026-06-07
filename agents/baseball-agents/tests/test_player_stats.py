"""Tests for player stats scraper."""
import json
import threading
from unittest.mock import patch, MagicMock
from scrapers.player_stats import (
    resolve_player, get_batter_stats, get_pitcher_stats,
    _regress_to_mean, LEAGUE_AVERAGES, BATTER_REGRESS_PA,
)


def _expected(raw_rate, pa, key):
    """Regressed rate the scraper should produce for a given raw rate."""
    return _regress_to_mean(raw_rate, pa, LEAGUE_AVERAGES[key], BATTER_REGRESS_PA[key])


def test_resolve_player_returns_none_for_empty():
    assert resolve_player("") is None
    assert resolve_player(None) is None


def test_get_batter_stats_falls_back_to_league_avg():
    """When API fails, should return league averages."""
    with patch("scrapers.player_stats.requests.get", side_effect=Exception("API down")):
        stats = get_batter_stats(12345, 2025)
        assert stats["player_id"] == 12345
        assert stats["k_pct"] == LEAGUE_AVERAGES["k_pct"]
        assert stats["hr_pct"] == LEAGUE_AVERAGES["hr_pct"]


def test_get_pitcher_stats_falls_back_to_league_avg():
    with patch("scrapers.player_stats.requests.get", side_effect=Exception("API down")):
        stats = get_pitcher_stats(67890, 2025)
        assert stats["player_id"] == 67890
        assert stats["avg_pitch_count"] == 90
        assert stats["k_pct"] == LEAGUE_AVERAGES["k_pct"]


def test_get_batter_stats_parses_api_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "stats": [{
            "splits": [{
                "stat": {
                    "plateAppearances": 500,
                    "atBats": 450,
                    "hits": 120,
                    "doubles": 25,
                    "triples": 3,
                    "homeRuns": 20,
                    "baseOnBalls": 50,
                    "strikeOuts": 130,
                }
            }]
        }]
    }
    with patch("scrapers.player_stats.requests.get", return_value=mock_resp):
        stats = get_batter_stats(12345, 2025)
        # Raw rates (0.26, 0.04, 0.144) are regressed toward league average.
        assert stats["k_pct"] == _expected(130 / 500, 500, "k_pct")
        assert stats["hr_pct"] == _expected(20 / 500, 500, "hr_pct")
        assert stats["single_pct"] == _expected((120 - 25 - 3 - 20) / 500, 500, "single_pct")


def test_batter_rates_form_valid_distribution_no_strikeout_double_count():
    """The 7 mutually-exclusive per-PA outcomes (K, BB, 1B, 2B, 3B, HR, BIP-out)
    must sum to 1.0.

    The buggy out_pct = 1 - (hits + bb) / pa folds strikeouts into the out
    bucket even though K is its own outcome, so the rates sum to ~1 + k_pct and
    the PA engine's renormalization deflates every hit probability. A high-K
    slugger exposes it most. The sum-to-1 invariant is regression-invariant
    because LEAGUE_AVERAGES also sums to 1 and the blend weight is uniform.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "stats": [{
            "splits": [{
                "stat": {
                    "plateAppearances": 600,
                    "atBats": 540,
                    "hits": 130,
                    "doubles": 30,
                    "triples": 2,
                    "homeRuns": 35,
                    "baseOnBalls": 55,
                    "strikeOuts": 200,  # 33% K — high-strikeout slugger
                }
            }]
        }]
    }
    with patch("scrapers.player_stats.requests.get", return_value=mock_resp):
        s = get_batter_stats(12345, 2025)

    total = (
        s["k_pct"] + s["bb_pct"] + s["hbp_pct"] + s["single_pct"]
        + s["double_pct"] + s["triple_pct"] + s["hr_pct"] + s["out_pct"]
    )
    assert abs(total - 1.0) < 1e-9, (
        f"per-PA outcome rates sum to {total:.4f}, not 1.0 — "
        f"out_pct should be the residual of the 7 events"
    )


def test_per_stat_regression_retains_k_signal_and_regresses_power():
    """Per-stat regression constants (stabilization points): K% stabilizes fast
    (regress_n=60) so a high-K hitter keeps most of his signal, while XBH
    stabilizes slowly (regress_n=1610) so an inflated small-sample doubles rate
    is pulled almost all the way back to league average. A single uniform
    constant cannot do both.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "stats": [{
            "splits": [{
                "stat": {
                    "plateAppearances": 200,
                    "atBats": 180,
                    "hits": 60,
                    "doubles": 24,   # 12% doubles rate — extreme, on a small sample
                    "triples": 0,
                    "homeRuns": 6,
                    "baseOnBalls": 18,
                    "strikeOuts": 70,  # 35% K — extreme
                    "hitByPitch": 2,
                }
            }]
        }]
    }
    with patch("scrapers.player_stats.requests.get", return_value=mock_resp):
        s = get_batter_stats(123, 2025)
    # K signal retained (raw 0.35); uniform-200 would over-regress it to ~0.287.
    assert s["k_pct"] > 0.31
    # Doubles heavily regressed (raw 0.12 → near league 0.044); uniform-200 left ~0.082.
    assert s["double_pct"] < 0.06


def test_hbp_estimated_per_batter():
    """HBP is fetched and regressed per batter, not flattened to league average
    (Bug B). A hit-by-pitch magnet should read well above the ~1% league rate.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "stats": [{
            "splits": [{
                "stat": {
                    "plateAppearances": 400,
                    "atBats": 360,
                    "hits": 90,
                    "doubles": 18,
                    "triples": 1,
                    "homeRuns": 10,
                    "baseOnBalls": 35,
                    "strikeOuts": 95,
                    "hitByPitch": 20,  # 5% HBP — a notable magnet (~5x league)
                }
            }]
        }]
    }
    with patch("scrapers.player_stats.requests.get", return_value=mock_resp):
        s = get_batter_stats(123, 2025)
    assert s.get("hbp_pct", 0.0) > 0.02  # well above league ~0.011, below raw 0.05


def test_concurrent_resolve_player(tmp_path):
    """Verify no player IDs are lost when resolving concurrently."""
    map_file = str(tmp_path / "player_map.json")
    names = [f"Player {i}" for i in range(10)]

    def mock_api_search(url, params=None, timeout=None):
        """Return a unique player ID for each name."""
        name = params["names"]
        idx = int(name.split()[-1])
        mock_resp = type("Resp", (), {
            "status_code": 200,
            "json": lambda self: {"people": [{"id": 100000 + idx, "active": True}]}
        })()
        return mock_resp

    with patch("scrapers.player_stats.PLAYER_MAP_FILE", map_file), \
         patch("scrapers.player_stats.requests.get", side_effect=mock_api_search):
        threads = [threading.Thread(target=resolve_player, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    with open(map_file) as f:
        mapping = json.load(f)
    assert len(mapping) == 10, f"Expected 10 players cached, got {len(mapping)}"
