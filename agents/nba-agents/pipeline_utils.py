"""Shared pipeline helpers."""
from scrapers.odds import OddsData


def format_prop_lines(odds: OddsData) -> str:
    """Format player prop lines for the Tier 2 LLM prompt."""
    lines = []
    for player, props in odds.player_props.items():
        parts = []
        for prop_type, data in props.items():
            parts.append(f"  {prop_type}: {data.get('line', '?')} "
                        f"(O {data.get('over_odds', '?')} / U {data.get('under_odds', '?')})")
        lines.append(f"{player}:\n" + "\n".join(parts))
    return "\n".join(lines) if lines else "No player props available"


def build_game_odds_dict(odds: OddsData) -> dict:
    """Build the full odds dict from OddsData for game_data['odds']."""
    return {
        "moneyline": odds.moneyline,
        "spread": odds.spread,
        "total": odds.total,
        "h1_moneyline": odds.h1_moneyline,
        "h1_total": odds.h1_total,
        "h1_spread": odds.h1_spread,
        "h2_moneyline": odds.h2_moneyline,
        "h2_total": odds.h2_total,
        "h2_spread": odds.h2_spread,
        "q1_moneyline": odds.q1_moneyline,
        "q1_spread": odds.q1_spread,
        "q1_total": odds.q1_total,
        "q2_total": odds.q2_total,
        "q3_total": odds.q3_total,
        "q4_total": odds.q4_total,
        "team_totals": odds.team_totals,
        "alt_spreads": odds.alt_spreads,
        "alt_totals": odds.alt_totals,
        "player_props": odds.player_props,
        "implied_probs": odds.implied_probs,
    }
