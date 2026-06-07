"""Formats daily picks into a clean bet card summary for esports."""
import click
from datetime import date
from tracker import load_bets

# Display names for esports bet types
BET_TYPE_LABELS = {
    "moneyline": "Match Winner",
    "map_handicap": "Map Handicap",
    "total_maps": "Total Maps",
}


def format_bet_card(game_date: str = None) -> str:
    """Generate a formatted bet card for a given date."""
    if game_date is None:
        game_date = date.today().isoformat()

    df = load_bets()
    day_bets = df[df["date"] == game_date]

    if day_bets.empty:
        return f"\n=== MiroFish Bet Card — {game_date} ===\n\nNo picks for today.\n"

    # Count unique game titles if present, fall back to game column
    game_col = "game_title" if "game_title" in day_bets.columns else "game"
    unique_games = day_bets[game_col].nunique() if game_col in day_bets.columns else day_bets["game"].nunique()

    lines = [
        f"\n{'='*60}",
        f"  MIROFISH ESPORTS BET CARD — {game_date}",
        f"  {len(day_bets)} picks across {unique_games} games",
        f"{'='*60}",
        "",
    ]

    # Group by game_title (cs2, lol) if available, then by match
    if "game_title" in day_bets.columns:
        for game_title in sorted(day_bets["game_title"].unique()):
            title_bets = day_bets[day_bets["game_title"] == game_title]
            lines.append(f"  [{game_title.upper()}]")
            lines.append(f"  {'-'*40}")

            for match_key in title_bets["game"].unique():
                match_bets = title_bets[title_bets["game"] == match_key]
                lines.append(f"    {match_key}")

                for _, bet in match_bets.iterrows():
                    lines.append(_format_bet_line(bet))

                lines.append("")
    else:
        # Fallback: group by game column
        for game_key in day_bets["game"].unique():
            game_bets = day_bets[day_bets["game"] == game_key]
            lines.append(f"  {game_key}")
            lines.append(f"  {'-'*40}")

            for _, bet in game_bets.iterrows():
                lines.append(_format_bet_line(bet))

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


def _format_bet_line(bet) -> str:
    """Format a single bet line with esports-friendly labels."""
    bet_type = str(bet.get("bet_type", ""))
    label = BET_TYPE_LABELS.get(bet_type, bet_type)
    edge_pct = f"{float(bet['edge'])*100:.1f}%"
    kelly_pct = f"{float(bet['kelly_pct'])*100:.2f}%"
    result_str = ""
    if bet.get("result") in ("W", "L", "P"):
        result_str = f" -> {bet['result']}"

    return (
        f"      {label:14s} | {str(bet['side']):20s} | "
        f"{int(bet['odds']):+4d} | Edge: {edge_pct:>5s} | "
        f"Kelly: {kelly_pct:>6s}{result_str}"
    )


@click.command()
@click.option("--date", "game_date", default=None, help="Date (YYYY-MM-DD)")
def main(game_date):
    """Display formatted bet card."""
    click.echo(format_bet_card(game_date))


if __name__ == "__main__":
    main()
