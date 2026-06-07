"""Tests for full game simulation."""
from simulation.game_sim import simulate_game, advance_runners, GameState

AVG_BATTER = {"k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
              "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004, "out_pct": 0.459,
              "player_id": 1}
AVG_PITCHER = {"k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
               "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004, "out_pct": 0.459,
               "avg_pitch_count": 90, "player_id": 100}


def test_advance_runners_single_empty():
    bases, scored, dp = advance_runners([0, 0, 0], "1B", 0, batter_id=1)
    assert bases[0] == 1  # batter on first
    assert len(scored) == 0
    assert dp is False


def test_advance_runners_hr_clears_bases():
    bases, scored, dp = advance_runners([10, 20, 30], "HR", 0, batter_id=99)
    assert bases == [0, 0, 0]
    assert len(scored) == 4  # 3 runners + batter
    assert set(scored) == {10, 20, 30, 99}


def test_advance_runners_single_scores_from_third():
    bases, scored, dp = advance_runners([0, 0, 50], "1B", 0, batter_id=99)
    assert len(scored) >= 1
    assert 50 in scored


def test_advance_runners_double_scores_from_second():
    bases, scored, dp = advance_runners([0, 50, 0], "2B", 0, batter_id=99)
    assert len(scored) >= 1
    assert 50 in scored


def test_advance_runners_bb_forced():
    bases, scored, dp = advance_runners([10, 20, 30], "BB", 0, batter_id=99)
    assert len(scored) == 1  # forced home
    assert scored[0] == 30  # R3B scored


def test_advance_runners_single_r2_sometimes_scores():
    """Runner on 2B should score on a single ~65% of the time (modern MLB)."""
    import random
    random.seed(42)
    score_count = 0
    n = 1000
    for _ in range(n):
        _, scored, _ = advance_runners([0, 50, 0], "1B", 0, batter_id=99)
        if 50 in scored:
            score_count += 1
    rate = score_count / n
    assert 0.55 < rate < 0.75, f"R2B scoring rate on single: {rate:.3f}"


def test_advance_runners_double_r1_sometimes_scores():
    """Runner on 1B should score on a double ~50% of the time."""
    import random
    random.seed(42)
    score_count = 0
    n = 1000
    for _ in range(n):
        _, scored, _ = advance_runners([50, 0, 0], "2B", 0, batter_id=99)
        if 50 in scored:
            score_count += 1
    rate = score_count / n
    assert 0.40 < rate < 0.60, f"R1B scoring rate on double: {rate:.3f}"


def test_rbi_credit_rules():
    """RBIs credited to the batter per MLB Rule 9.04."""
    from simulation.game_sim import _rbi_credit
    # Strikeout: never an RBI.
    assert _rbi_credit("K", 0, is_dp=False) == 0
    # Safe hit / sac fly / RBI groundout: one RBI per run that scored.
    assert _rbi_credit("1B", 2, is_dp=False) == 2
    assert _rbi_credit("OUT", 1, is_dp=False) == 1   # productive out (9.04(a)(1))
    # Home run: batter drives in himself plus every runner.
    assert _rbi_credit("HR", 3, is_dp=False) == 3
    # Ground-into-double-play: the run scores but NO RBI (Rule 9.04(b)(1)).
    assert _rbi_credit("OUT", 1, is_dp=True) == 0


def test_no_rbi_on_double_play_but_run_still_counts():
    """GIDP with a runner on 3B: the run scores (counts for the team) but the
    batter is credited no RBI — MLB Rule 9.04(b)(1)."""
    from unittest.mock import patch
    from simulation.game_sim import _rbi_credit
    # random.random() < 0.11 triggers the GIDP; < 0.50 scores R3.
    with patch("simulation.game_sim.random.random", return_value=0.0):
        new_bases, scored, is_dp = advance_runners([10, 0, 30], "OUT", 0, batter_id=99)
    assert is_dp is True
    assert 30 in scored, "runner from 3B should still score on the DP"
    assert _rbi_credit("OUT", len(scored), is_dp) == 0, "no RBI on a double-play run"


def test_simulate_game_completes():
    import random
    random.seed(42)
    lineup = [{**AVG_BATTER, "player_id": i + 1} for i in range(9)]
    state = simulate_game(
        home_lineup=lineup,
        away_lineup=lineup,
        home_pitcher={**AVG_PITCHER, "player_id": 100},
        away_pitcher={**AVG_PITCHER, "player_id": 200},
    )
    assert state.inning >= 9
    assert state.score["home"] >= 0
    assert state.score["away"] >= 0
    assert len(state.batter_stats) > 0
    assert len(state.pitcher_stats) > 0


def test_simulate_game_reasonable_scores():
    import random
    random.seed(123)
    lineup = [{**AVG_BATTER, "player_id": i + 1} for i in range(9)]
    pitcher = {**AVG_PITCHER, "player_id": 100}
    scores = []
    for _ in range(200):
        state = simulate_game(
            home_lineup=lineup, away_lineup=lineup,
            home_pitcher={**pitcher, "player_id": 100},
            away_pitcher={**pitcher, "player_id": 200},
        )
        scores.append(state.score["home"] + state.score["away"])
    avg = sum(scores) / len(scores)
    assert 6 < avg < 12


def test_simulate_game_tracks_pitcher_stats():
    import random
    random.seed(42)
    lineup = [{**AVG_BATTER, "player_id": i + 1} for i in range(9)]
    state = simulate_game(
        home_lineup=lineup, away_lineup=lineup,
        home_pitcher={**AVG_PITCHER, "player_id": 100},
        away_pitcher={**AVG_PITCHER, "player_id": 200},
    )
    # Away pitcher (id 200) faces home batters
    assert 200 in state.pitcher_stats
    ps = state.pitcher_stats[200]
    assert ps["outs"] > 0
    assert ps["k"] >= 0
    assert ps["h"] >= 0


def test_simulate_game_tracks_score_by_inning():
    import random
    random.seed(42)
    lineup = [{**AVG_BATTER, "player_id": i + 1} for i in range(9)]
    state = simulate_game(
        home_lineup=lineup, away_lineup=lineup,
        home_pitcher={**AVG_PITCHER, "player_id": 100},
        away_pitcher={**AVG_PITCHER, "player_id": 200},
    )
    assert len(state.score_by_inning["away"]) >= 9
    assert len(state.score_by_inning["home"]) >= 9
    assert sum(state.score_by_inning["away"]) == state.score["away"]
    assert sum(state.score_by_inning["home"]) == state.score["home"]
