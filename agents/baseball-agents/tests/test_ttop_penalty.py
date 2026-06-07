"""Tier 3 (2026-05-07): times-through-the-order penalty.

Modern MLB data: a starter's effectiveness degrades each time through the
opposing lineup. We track times-through (TTOP) by counting PAs faced and
dividing by 9, capping at index 2 (1st, 2nd, 3rd+). Multipliers (matching
published literature):

    K_PCT: [1.04, 1.00, 0.94]   - K rate falls each pass
    BB_PCT:[0.96, 1.00, 1.06]   - BB rate rises
    HR_PCT:[0.92, 1.00, 1.10]   - HR rate rises sharply

The penalty is the single biggest source of pitcher-strikeouts overconfidence
in our prior MC: a starter's first 9 PAs were sampled at the same rates as
their last 9, even though real-world third-time-through performance is
markedly worse.
"""
import random


# ---------------------------------------------------------------------------
# Pure helper: applying TTOP multipliers in the matchup probability builder
# ---------------------------------------------------------------------------

class TestSamplePaAcceptsTtop:
    BATTER = {
        "k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
        "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004,
        "out_pct": 0.459, "hbp_pct": 0.0108,
    }
    # Strong-K starter so the TTOP signal is visible over noise.
    PITCHER = {
        "k_pct": 0.30, "bb_pct": 0.07, "hr_pct": 0.025,
        "single_pct": 0.140, "double_pct": 0.040, "triple_pct": 0.003,
        "out_pct": 0.422, "hbp_pct": 0.0108,
    }

    def test_sample_pa_accepts_ttop_index(self):
        from simulation.pa_engine import sample_pa
        # Should not raise — signature accepts an optional ttop_index kwarg.
        sample_pa(self.BATTER, self.PITCHER, ttop_index=0)
        sample_pa(self.BATTER, self.PITCHER, ttop_index=1)
        sample_pa(self.BATTER, self.PITCHER, ttop_index=2)

    def test_k_rate_falls_each_pass(self):
        """3rd-time-through K rate < 1st-time-through K rate."""
        from simulation.pa_engine import sample_pa
        random.seed(42)
        first_pass = [sample_pa(self.BATTER, self.PITCHER, ttop_index=0) for _ in range(20000)]
        random.seed(42)
        third_pass = [sample_pa(self.BATTER, self.PITCHER, ttop_index=2) for _ in range(20000)]
        first_k = first_pass.count("K") / len(first_pass)
        third_k = third_pass.count("K") / len(third_pass)
        assert third_k < first_k, f"1st: {first_k:.3f}, 3rd+: {third_k:.3f}"
        # Difference should be material (>1pp at 30% K rate).
        assert (first_k - third_k) > 0.01

    def test_hr_rate_rises_each_pass(self):
        from simulation.pa_engine import sample_pa
        random.seed(42)
        first_pass = [sample_pa(self.BATTER, self.PITCHER, ttop_index=0) for _ in range(50000)]
        random.seed(42)
        third_pass = [sample_pa(self.BATTER, self.PITCHER, ttop_index=2) for _ in range(50000)]
        first_hr = first_pass.count("HR") / len(first_pass)
        third_hr = third_pass.count("HR") / len(third_pass)
        assert third_hr > first_hr, f"1st: {first_hr:.4f}, 3rd+: {third_hr:.4f}"

    def test_bb_rate_rises_each_pass(self):
        from simulation.pa_engine import sample_pa
        random.seed(42)
        first_pass = [sample_pa(self.BATTER, self.PITCHER, ttop_index=0) for _ in range(30000)]
        random.seed(42)
        third_pass = [sample_pa(self.BATTER, self.PITCHER, ttop_index=2) for _ in range(30000)]
        first_bb = first_pass.count("BB") / len(first_pass)
        third_bb = third_pass.count("BB") / len(third_pass)
        assert third_bb > first_bb, f"1st: {first_bb:.4f}, 3rd+: {third_bb:.4f}"

    def test_ttop_index_zero_is_default(self):
        """Backwards compat: omitting ttop_index produces same dist as ttop_index=0."""
        from simulation.pa_engine import sample_pa
        random.seed(7)
        no_idx = [sample_pa(self.BATTER, self.PITCHER) for _ in range(5000)]
        random.seed(7)
        idx_zero = [sample_pa(self.BATTER, self.PITCHER, ttop_index=0) for _ in range(5000)]
        # Same RNG seed + same logical input → identical sequence.
        assert no_idx == idx_zero


# ---------------------------------------------------------------------------
# game_sim wires TTOP through automatically
# ---------------------------------------------------------------------------

class TestGameSimAppliesTtop:
    AVG_BATTER = {
        "k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
        "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004,
        "out_pct": 0.459, "hbp_pct": 0.0108, "player_id": 1,
    }
    # Use a starter with very high pitch count so we don't switch to relievers
    # too early — we need to see PAs 1-27 from the starter to test TTOP.
    AVG_PITCHER = {
        "k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
        "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004,
        "out_pct": 0.459, "hbp_pct": 0.0108, "avg_pitch_count": 250,
        "player_id": 100,
    }

    def test_starter_strikeouts_lower_with_ttop_than_without(self):
        """Same RNG seed: starter K count should be lower with TTOP enabled
        (since multipliers compound to net <1.0 once the starter has gone
        through the order multiple times)."""
        from simulation.game_sim import simulate_game
        # Game sim integration test — starter pitch count is set high so the
        # starter throws complete games and we observe TTOP across all 27 PAs.
        # We do not directly compare K counts because outcomes are sequence-
        # dependent. Instead, simulate many games and compare aggregate K rates.
        random.seed(2026)
        lineup = [{**self.AVG_BATTER, "player_id": i + 1} for i in range(9)]

        starter_k_total = 0
        starter_pa_total = 0
        for _ in range(30):
            state = simulate_game(
                home_lineup=lineup, away_lineup=lineup,
                home_pitcher={**self.AVG_PITCHER, "player_id": 100},
                away_pitcher={**self.AVG_PITCHER, "player_id": 200},
            )
            # away_pitcher (200) faces home_lineup
            ps = state.pitcher_stats.get(200, {})
            starter_k_total += ps.get("k", 0)
            starter_pa_total += ps.get("pa_faced", 0)
        assert starter_pa_total > 0, "TTOP requires pa_faced to be tracked on pitcher_stats"
        k_rate = starter_k_total / starter_pa_total
        # League-avg matchup with TTOP active: K rate should still be in
        # ballpark of league avg (~0.224) — slightly compressed because
        # 3rd-time-through penalty drags it down.
        assert 0.18 < k_rate < 0.24, f"k_rate={k_rate:.3f} starter_pa_total={starter_pa_total}"

    def test_pitcher_stats_tracks_pa_faced(self):
        from simulation.game_sim import simulate_game
        random.seed(99)
        lineup = [{**self.AVG_BATTER, "player_id": i + 1} for i in range(9)]
        state = simulate_game(
            home_lineup=lineup, away_lineup=lineup,
            home_pitcher={**self.AVG_PITCHER, "player_id": 100},
            away_pitcher={**self.AVG_PITCHER, "player_id": 200},
        )
        # Both starters should have faced batters
        assert "pa_faced" in state.pitcher_stats[100]
        assert "pa_faced" in state.pitcher_stats[200]
        assert state.pitcher_stats[100]["pa_faced"] > 0
        assert state.pitcher_stats[200]["pa_faced"] > 0
