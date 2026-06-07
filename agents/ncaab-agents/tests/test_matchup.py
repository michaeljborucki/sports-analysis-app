from scrapers.matchup import get_matchup_context


def test_projected_total_uses_defense():
    """Projected total should account for opposing defense, not just average offense."""
    away_stats = {"adj_oe": 120, "adj_de": 110, "adj_tempo": 68}
    home_stats = {"adj_oe": 95, "adj_de": 90, "adj_tempo": 68}
    result = get_matchup_context(away_stats, home_stats)

    naive = (120 + 95) / 2 * 68 / 100
    assert result["projected_total"] > naive


def test_projected_total_symmetric_teams():
    """Two identical teams should produce consistent total."""
    stats = {"adj_oe": 105, "adj_de": 100, "adj_tempo": 68}
    result = get_matchup_context(stats, stats)
    expected = 105 * 100 / 100 * 68 / 100 * 2  # = 142.8
    assert abs(result["projected_total"] - round(expected, 1)) < 1.0
