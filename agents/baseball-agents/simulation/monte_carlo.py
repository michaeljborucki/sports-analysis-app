"""Run N game simulations and aggregate per-player stat distributions."""
from collections import defaultdict
from simulation.game_sim import simulate_game


def _counts_to_distribution(counts: dict, max_val: int) -> list:
    """Convert {value: count} to probability distribution [P(0), P(1), ..., P(max_val)]."""
    total = sum(counts.values())
    if total == 0:
        return [1.0] + [0.0] * max_val
    return [counts.get(i, 0) / total for i in range(max_val + 1)]


def run_monte_carlo(
    home_lineup: list[dict],
    away_lineup: list[dict],
    home_pitcher: dict,
    away_pitcher: dict,
    park_factor_runs: float = 1.0,
    park_factor_hr: float = 1.0,
    n_sims: int = 5000,
    weather_hr_multiplier: float = 1.0,
) -> dict:
    """Run N game simulations and aggregate results.

    Returns dict with game_results, pitcher_distributions, batter_distributions.
    """
    # Accumulators
    home_wins = 0
    away_wins = 0
    total_runs = []
    home_scores = []
    away_scores = []
    tied_after = {1: 0, 3: 0, 5: 0}

    # Per-player stat counts: {player_id: {stat: {value: count}}}
    pitcher_counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    batter_counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    for _ in range(n_sims):
        state = simulate_game(
            home_lineup=home_lineup,
            away_lineup=away_lineup,
            home_pitcher=home_pitcher.copy(),
            away_pitcher=away_pitcher.copy(),
            park_factor_runs=park_factor_runs,
            park_factor_hr=park_factor_hr,
            weather_hr_multiplier=weather_hr_multiplier,
        )

        # Game results
        if state.score["home"] > state.score["away"]:
            home_wins += 1
        else:
            away_wins += 1
        total_runs.append(state.score["home"] + state.score["away"])
        home_scores.append(state.score["home"])
        away_scores.append(state.score["away"])

        # Tied after N innings
        for n in [1, 3, 5]:
            away_through_n = sum(state.score_by_inning["away"][:n])
            home_through_n = sum(state.score_by_inning["home"][:n])
            if away_through_n == home_through_n:
                tied_after[n] += 1

        # Pitcher stats
        for pid, ps in state.pitcher_stats.items():
            for stat in ["k", "bb", "h", "er", "outs"]:
                pitcher_counts[pid][stat][ps.get(stat, 0)] += 1

        # Batter stats
        for pid, bs in state.batter_stats.items():
            for stat in ["h", "hr", "rbi", "r", "k", "bb", "tb"]:
                batter_counts[pid][stat][bs.get(stat, 0)] += 1
            # Composite: h + r + rbi
            h_r_rbi = bs.get("h", 0) + bs.get("r", 0) + bs.get("rbi", 0)
            batter_counts[pid]["h_r_rbi"][h_r_rbi] += 1

    # Build distributions
    pitcher_distributions = {}
    for pid, stats in pitcher_counts.items():
        pitcher_distributions[pid] = {}
        for stat, counts in stats.items():
            max_val = max(counts.keys()) if counts else 0
            pitcher_distributions[pid][stat] = _counts_to_distribution(counts, max_val)

    batter_distributions = {}
    for pid, stats in batter_counts.items():
        batter_distributions[pid] = {}
        for stat, counts in stats.items():
            max_val = max(counts.keys()) if counts else 0
            batter_distributions[pid][stat] = _counts_to_distribution(counts, max_val)

    return {
        "n_sims": n_sims,
        "game_results": {
            "home_wins": home_wins,
            "away_wins": away_wins,
            "avg_total": sum(total_runs) / n_sims,
            "avg_home_score": sum(home_scores) / n_sims,
            "avg_away_score": sum(away_scores) / n_sims,
            "tied_after_1": tied_after[1] / n_sims,
            "tied_after_3": tied_after[3] / n_sims,
            "tied_after_5": tied_after[5] / n_sims,
        },
        "pitcher_distributions": pitcher_distributions,
        "batter_distributions": batter_distributions,
    }
