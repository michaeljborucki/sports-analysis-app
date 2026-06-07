"""Formats daily picks into a clean bet card summary."""
import click
from datetime import date
from tracker import load_bets


def _format_bet_line(bet, show_player=True, indent=6) -> str:
    """Format a single bet line."""
    edge_pct = f"{float(bet['edge'])*100:.1f}%"

    # Format projected value — could be numeric, a score string, or missing
    proj_raw = bet.get("projected", None)
    if proj_raw is None or str(proj_raw).strip() in ("", "nan"):
        proj_str = "\u2014"
    else:
        try:
            proj_str = f"{float(proj_raw):.1f}"
        except (ValueError, TypeError):
            proj_str = str(proj_raw)

    # Format market implied probability (prefer no-vig market_prob)
    mkt_raw = bet.get("market_prob", None)
    if mkt_raw is not None and str(mkt_raw).strip() not in ("", "nan"):
        mkt_str = f"{float(mkt_raw)*100:.0f}%"
    else:
        odds_raw = bet.get("odds", None)
        if odds_raw is not None and str(odds_raw).strip() not in ("", "nan"):
            odds_val = int(float(odds_raw))
            if odds_val < 0:
                mkt_prob = abs(odds_val) / (abs(odds_val) + 100)
            else:
                mkt_prob = 100 / (odds_val + 100)
            mkt_str = f"{mkt_prob*100:.0f}%"
        else:
            mkt_str = "\u2014"

    # Format sim probability
    prob_raw = bet.get("sim_prob", None)
    if prob_raw is None or str(prob_raw).strip() in ("", "nan"):
        prob_str = "\u2014"
    else:
        prob_str = f"{float(prob_raw)*100:.0f}%"

    result_str = ""
    if bet.get("result") in ("W", "L", "P"):
        result_str = f" \u2192 {bet['result']}"
    player_str = ""
    if show_player and str(bet.get('player', '')).strip() not in ('', 'nan'):
        player_str = f" ({bet['player']})"
    pad = " " * indent
    return (
        f"{pad}{bet['bet_type']:14s} | {str(bet['side']):20s} | "
        f"Proj: {proj_str:>7s} | Mkt: {mkt_str:>4s} | "
        f"Model: {prob_str:>4s} | Edge: {edge_pct:>5s}{player_str}{result_str}"
    )


def format_bet_card(game_date: str = None) -> str:
    """Generate a formatted bet card for a given date."""
    if game_date is None:
        game_date = date.today().isoformat()

    df = load_bets()
    day_bets = df[df["date"] == game_date]

    if day_bets.empty:
        return f"\n=== MiroFish Bet Card — {game_date} ===\n\nNo picks for today.\n"

    lines = [
        f"\n{'='*60}",
        f"  MIROFISH BET CARD — {game_date}",
        f"  {len(day_bets)} picks across {day_bets['game'].nunique()} games",
        f"{'='*60}",
        "",
    ]

    for game_key in day_bets["game"].unique():
        game_bets = day_bets[day_bets["game"] == game_key]
        lines.append(f"  {game_key}")
        lines.append(f"  {'-'*56}")

        # Split into groups
        game_level = game_bets[game_bets["bet_type"].isin(["moneyline", "spread", "total"])]
        half_bets = game_bets[game_bets["bet_type"].str.startswith("first_half")]
        quarter_bets = game_bets[game_bets["bet_type"].str.match(r"^q\d_")]
        team_total = game_bets[game_bets["bet_type"].str.startswith("team_total")]
        player_bets = game_bets[game_bets["bet_type"].str.startswith("player_")]

        sections = [
            ("Game", game_level),
            ("Half", half_bets),
            ("Quarter", quarter_bets),
            ("Team Total", team_total),
        ]

        for section_name, section_df in sections:
            if section_df.empty:
                continue
            lines.append(f"    {section_name}:")
            for _, bet in section_df.sort_values("bet_type").iterrows():
                lines.append(_format_bet_line(bet))

        # Player props grouped by player
        if not player_bets.empty:
            lines.append(f"    Player Props:")
            for player_name in player_bets["player"].unique():
                p_bets = player_bets[player_bets["player"] == player_name]
                lines.append(f"      {player_name}:")
                for _, bet in p_bets.sort_values("bet_type").iterrows():
                    lines.append(_format_bet_line(bet, show_player=False, indent=8))

        lines.append("")

    # Summary footer
    settled = day_bets[day_bets["result"].isin(["W", "L", "P"])]
    if not settled.empty:
        wins = len(settled[settled["result"] == "W"])
        losses = len(settled[settled["result"] == "L"])
        profit = settled["profit"].sum()
        lines.append(f"  Day Record: {wins}-{losses} | Profit: {profit:+.2f} units")
    else:
        lines.append("  Status: Pending")

    lines.append(f"{'='*60}\n")
    return "\n".join(lines)


@click.command()
@click.option("--date", "game_date", default=None, help="Date (YYYY-MM-DD)")
def main(game_date):
    """Display formatted bet card for today."""
    click.echo(format_bet_card(game_date))


if __name__ == "__main__":
    main()
