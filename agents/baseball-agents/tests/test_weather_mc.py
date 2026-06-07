"""Tier 2 (2026-05-07): wire weather into the Monte Carlo simulator.

Weather data is fetched in `scrapers/ballpark.get_game_environment` and
threaded through `game_data["environment"]` (see main.py:80) but was
never used in the MC. This file pins the new behavior:

  - `simulation.weather.weather_hr_multiplier(weather, roof)` produces
    a single HR-rate multiplier with sensible bounds.
  - `run_monte_carlo` and `simulate_game` accept an optional
    `weather_hr_multiplier` parameter that compounds with `park_factor_hr`.
"""
import random


# ---------------------------------------------------------------------------
# Pure helper: weather → HR multiplier
# ---------------------------------------------------------------------------

class TestWeatherHrMultiplier:
    def test_closed_roof_neutralizes_weather(self):
        from simulation.weather import weather_hr_multiplier
        weather = {"temp_f": 95, "wind_mph": 25, "wind_direction": "out"}
        assert weather_hr_multiplier(weather, roof="closed") == 1.0

    def test_dome_neutralizes_weather(self):
        from simulation.weather import weather_hr_multiplier
        weather = {"temp_f": 95, "wind_mph": 25, "wind_direction": "out"}
        assert weather_hr_multiplier(weather, roof="dome") == 1.0

    def test_empty_weather_returns_neutral(self):
        from simulation.weather import weather_hr_multiplier
        assert weather_hr_multiplier(None) == 1.0
        assert weather_hr_multiplier({}) == 1.0

    def test_neutral_weather_returns_about_one(self):
        from simulation.weather import weather_hr_multiplier
        weather = {"temp_f": 70, "wind_mph": 0, "wind_direction": "calm"}
        assert abs(weather_hr_multiplier(weather) - 1.0) < 0.005

    def test_hot_weather_boosts_hr(self):
        """+1°F over 70°F adds ~0.5% to HR rate (Statcast carry data)."""
        from simulation.weather import weather_hr_multiplier
        hot = {"temp_f": 90, "wind_mph": 0, "wind_direction": "calm"}
        m = weather_hr_multiplier(hot)
        assert 1.05 < m < 1.15, f"hot weather HR multiplier: {m}"

    def test_cold_weather_suppresses_hr(self):
        from simulation.weather import weather_hr_multiplier
        cold = {"temp_f": 50, "wind_mph": 0, "wind_direction": "calm"}
        m = weather_hr_multiplier(cold)
        assert 0.85 < m < 0.95, f"cold weather HR multiplier: {m}"

    def test_wind_out_boosts_hr(self):
        """Wind blowing OUT 15+ mph notably boosts HR rate."""
        from simulation.weather import weather_hr_multiplier
        wind_out = {"temp_f": 70, "wind_mph": 20, "wind_direction": "out"}
        m = weather_hr_multiplier(wind_out)
        assert m > 1.08, f"strong wind-out HR multiplier: {m}"

    def test_wind_in_suppresses_hr(self):
        from simulation.weather import weather_hr_multiplier
        wind_in = {"temp_f": 70, "wind_mph": 20, "wind_direction": "in"}
        m = weather_hr_multiplier(wind_in)
        assert m < 0.92, f"strong wind-in HR multiplier: {m}"

    def test_cross_wind_neutral(self):
        from simulation.weather import weather_hr_multiplier
        cross = {"temp_f": 70, "wind_mph": 20, "wind_direction": "cross"}
        assert abs(weather_hr_multiplier(cross) - 1.0) < 0.005

    def test_light_wind_minimal_effect(self):
        """Wind under ~8mph is too weak to affect carry meaningfully."""
        from simulation.weather import weather_hr_multiplier
        light = {"temp_f": 70, "wind_mph": 5, "wind_direction": "out"}
        assert abs(weather_hr_multiplier(light) - 1.0) < 0.02

    def test_extreme_weather_clamped(self):
        """Even insane combined boosts cap somewhere reasonable."""
        from simulation.weather import weather_hr_multiplier
        extreme = {"temp_f": 105, "wind_mph": 40, "wind_direction": "out"}
        m = weather_hr_multiplier(extreme)
        assert 1.0 < m <= 1.30, f"extreme HR multiplier should cap: {m}"

        extreme_cold = {"temp_f": 30, "wind_mph": 40, "wind_direction": "in"}
        m2 = weather_hr_multiplier(extreme_cold)
        assert 0.70 <= m2 < 1.0, f"extreme cold/wind-in multiplier: {m2}"


# ---------------------------------------------------------------------------
# run_monte_carlo accepts weather_hr_multiplier and forwards it
# ---------------------------------------------------------------------------

class TestMcAcceptsWeather:
    AVG_BATTER = {
        "k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
        "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004,
        "out_pct": 0.459, "hbp_pct": 0.0108, "player_id": 1,
    }
    AVG_PITCHER = {
        "k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033,
        "single_pct": 0.152, "double_pct": 0.044, "triple_pct": 0.004,
        "out_pct": 0.459, "hbp_pct": 0.0108, "avg_pitch_count": 90,
        "player_id": 100,
    }

    def _run(self, weather_hr_multiplier=1.0, seed=42, n_sims=200):
        from simulation.monte_carlo import run_monte_carlo
        random.seed(seed)
        lineup = [{**self.AVG_BATTER, "player_id": i + 1} for i in range(9)]
        return run_monte_carlo(
            home_lineup=lineup, away_lineup=lineup,
            home_pitcher={**self.AVG_PITCHER, "player_id": 100},
            away_pitcher={**self.AVG_PITCHER, "player_id": 200},
            n_sims=n_sims,
            weather_hr_multiplier=weather_hr_multiplier,
        )

    def test_run_monte_carlo_accepts_multiplier(self):
        results = self._run(weather_hr_multiplier=1.0)
        assert "game_results" in results

    def test_high_hr_multiplier_increases_total_runs(self):
        """A 1.20x HR multiplier should noticeably raise mean total runs."""
        baseline = self._run(weather_hr_multiplier=1.0, seed=11, n_sims=400)
        boosted = self._run(weather_hr_multiplier=1.20, seed=11, n_sims=400)
        assert boosted["game_results"]["avg_total"] > baseline["game_results"]["avg_total"], \
            f"baseline={baseline['game_results']['avg_total']:.2f} " \
            f"boosted={boosted['game_results']['avg_total']:.2f}"

    def test_low_hr_multiplier_decreases_total_runs(self):
        """A 0.80x HR multiplier should noticeably lower mean total runs."""
        baseline = self._run(weather_hr_multiplier=1.0, seed=22, n_sims=400)
        suppressed = self._run(weather_hr_multiplier=0.80, seed=22, n_sims=400)
        assert suppressed["game_results"]["avg_total"] < baseline["game_results"]["avg_total"], \
            f"baseline={baseline['game_results']['avg_total']:.2f} " \
            f"suppressed={suppressed['game_results']['avg_total']:.2f}"
