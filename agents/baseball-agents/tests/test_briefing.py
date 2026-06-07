from briefing import build_briefing


def test_build_briefing_produces_string():
    game_data = {
        "away_team": "BOS",
        "home_team": "NYY",
        "away_record": "40-35",
        "home_record": "45-30",
        "away_pitcher": {
            "name": "Brayan Bello",
            "season_stats": {"era": 3.50, "fip": 3.40, "xfip": 3.55,
                             "whip": 1.15, "k_per_9": 9.0, "bb_per_9": 2.5,
                             "hr_per_9": 1.0, "w": 8, "l": 5, "ip": 110, "starts": 18},
            "days_rest": 5,
            "last_5_starts": [],
        },
        "home_pitcher": {
            "name": "Gerrit Cole",
            "season_stats": {"era": 3.00, "fip": 2.90, "xfip": 3.10,
                             "whip": 1.00, "k_per_9": 11.0, "bb_per_9": 1.8,
                             "hr_per_9": 0.8, "w": 12, "l": 3, "ip": 140, "starts": 22},
            "days_rest": 4,
            "last_5_starts": [],
        },
        "odds": {
            "moneyline": {"home": -150, "away": 130},
            "run_line": {"home": -1.5, "home_odds": 140, "away": 1.5, "away_odds": -165},
            "total": {"line": 8.5, "over_odds": -110, "under_odds": -110},
            "implied_probs": {"ml_home": 0.585, "ml_away": 0.415},
        },
        "environment": {
            "ballpark": "Yankee Stadium",
            "park_factor_runs": 1.05,
            "weather": {"temp_f": 72, "wind_mph": 10, "wind_direction": "out"},
            "day_night": "night",
        },
        "away_bullpen": {"bullpen_freshness": "moderate", "closer": {"name": "Kenley Jansen"}},
        "home_bullpen": {"bullpen_freshness": "fresh", "closer": {"name": "Clay Holmes"}},
        "away_injuries": [],
        "home_injuries": [],
    }
    briefing = build_briefing(game_data)
    assert isinstance(briefing, str)
    assert "BOS" in briefing
    assert "NYY" in briefing
    assert "Gerrit Cole" in briefing
    assert "Brayan Bello" in briefing
    assert "Yankee Stadium" in briefing
    assert "PREDICTION TASK" in briefing


def _sample_batter(name, k=0.22, bb=0.08, hr=0.03, single=0.15, double=0.045, pa=400):
    """Synthetic batter record matching get_batter_stats output shape."""
    return {
        "player_id": hash(name) % 1000000,
        "full_name": name,
        "k_pct": k, "bb_pct": bb, "hr_pct": hr,
        "single_pct": single, "double_pct": double,
        "triple_pct": 0.005,
        "out_pct": 1.0 - (k + bb + hr + single + double + 0.005),
        "pa": pa,
    }


def test_briefing_includes_lineups_when_provided():
    """The brief must surface batting lineups so the LLM can reason about
    offense — the previous version had pitcher stats but zero hitting context,
    identified 2026-04-24 as a root cause of prop overconfidence."""
    game_data = {
        "away_team": "BOS", "home_team": "NYY",
        "away_record": "40-35", "home_record": "45-30",
        "away_pitcher": {"name": "Brayan Bello", "season_stats": {}},
        "home_pitcher": {"name": "Gerrit Cole", "season_stats": {}},
        "odds": {"moneyline": {"home": -150, "away": 130},
                 "run_line": {"home": -1.5, "home_odds": 140, "away": 1.5, "away_odds": -165},
                 "total": {"line": 8.5, "over_odds": -110, "under_odds": -110},
                 "implied_probs": {"ml_home": 0.585, "ml_away": 0.415}},
        "environment": {"ballpark": "Yankee Stadium", "park_factor_runs": 1.05,
                        "weather": {"temp_f": 72, "wind_mph": 10, "wind_direction": "out"},
                        "day_night": "night"},
        "away_bullpen": {}, "home_bullpen": {},
        "away_injuries": [], "home_injuries": [],
        "home_batters": [
            _sample_batter("Aaron Judge", k=0.28, bb=0.14, hr=0.08, pa=500),
            _sample_batter("Juan Soto", k=0.21, bb=0.17, hr=0.06, pa=480),
        ],
        "away_batters": [
            _sample_batter("Rafael Devers", k=0.25, bb=0.10, hr=0.05, pa=450),
        ],
    }
    brief = build_briefing(game_data)
    assert "LINEUP" in brief
    assert "Aaron Judge" in brief
    assert "Juan Soto" in brief
    assert "Rafael Devers" in brief


def test_briefing_marks_thin_sample_batters():
    """Batters with < 50 PA need a regress-to-league-average flag so the LLM
    doesn't overweight their noisy recent line."""
    game_data = {
        "away_team": "BOS", "home_team": "NYY",
        "away_record": "", "home_record": "",
        "away_pitcher": {"name": "X", "season_stats": {}},
        "home_pitcher": {"name": "Y", "season_stats": {}},
        "odds": {"moneyline": {}, "run_line": {}, "total": {},
                 "implied_probs": {"ml_home": 0.5, "ml_away": 0.5}},
        "environment": {"weather": {}},
        "away_bullpen": {}, "home_bullpen": {},
        "away_injuries": [], "home_injuries": [],
        "home_batters": [_sample_batter("Rookie Jones", pa=15)],
        "away_batters": [],
    }
    brief = build_briefing(game_data)
    assert "Rookie Jones" in brief
    assert any(marker in brief.lower() for marker in ["thin", "limited", "regress"])


def test_briefing_prediction_task_has_calibration_anchors():
    """The prediction task must include explicit confidence caps and anchoring
    instructions. Measured 2026-04-24: high-confidence predictions missed
    reality by 15-30pp."""
    game_data = {
        "away_team": "BOS", "home_team": "NYY", "away_record": "", "home_record": "",
        "away_pitcher": {"name": "X", "season_stats": {}},
        "home_pitcher": {"name": "Y", "season_stats": {}},
        "odds": {"moneyline": {}, "run_line": {}, "total": {},
                 "implied_probs": {"ml_home": 0.5, "ml_away": 0.5}},
        "environment": {"weather": {}},
        "away_bullpen": {}, "home_bullpen": {},
        "away_injuries": [], "home_injuries": [],
    }
    brief = build_briefing(game_data)
    lower = brief.lower()
    assert "market" in lower or "implied" in lower
    assert any(marker in lower for marker in ["cap", "rarely", "70%", "65%"])
    assert any(marker in lower for marker in ["variance", "uncertainty", "noise"])


def test_briefing_allows_higher_ml_confidence_than_other_markets():
    """ML confidence cap raised 70%→80% on 2026-04-28 (lopsided matchups
    can exceed 70% legitimately). Other markets (RL, totals, props) keep
    the 70% / 65% caps. The prompt must communicate both bars distinctly so
    the LLM doesn't blanket-cap everything at 70%."""
    game_data = {
        "away_team": "BOS", "home_team": "NYY", "away_record": "", "home_record": "",
        "away_pitcher": {"name": "X", "season_stats": {}},
        "home_pitcher": {"name": "Y", "season_stats": {}},
        "odds": {"moneyline": {}, "run_line": {}, "total": {},
                 "implied_probs": {"ml_home": 0.5, "ml_away": 0.5}},
        "environment": {"weather": {}},
        "away_bullpen": {}, "home_bullpen": {},
        "away_injuries": [], "home_injuries": [],
    }
    brief = build_briefing(game_data)
    # Both caps appear so the LLM treats ML differently from other markets.
    assert "80%" in brief, "ML cap (80%) missing — LLM will keep ML at 70% blanket"
    assert "70%" in brief, "general game-level cap (70%) missing"


def test_briefing_works_when_lineups_not_provided():
    """Backward compat: lineup data is optional; older call sites shouldn't break."""
    game_data = {
        "away_team": "BOS", "home_team": "NYY", "away_record": "", "home_record": "",
        "away_pitcher": {"name": "X", "season_stats": {}},
        "home_pitcher": {"name": "Y", "season_stats": {}},
        "odds": {"moneyline": {}, "run_line": {}, "total": {},
                 "implied_probs": {"ml_home": 0.5, "ml_away": 0.5}},
        "environment": {"weather": {}},
        "away_bullpen": {}, "home_bullpen": {},
        "away_injuries": [], "home_injuries": [],
    }
    brief = build_briefing(game_data)
    assert isinstance(brief, str)
    assert "PREDICTION TASK" in brief
