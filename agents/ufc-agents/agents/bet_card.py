"""Formats daily picks into a clean bet card summary."""
import click
from datetime import date
from tracker import load_bets


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
        lines.append(f"  {'-'*40}")

        for _, bet in game_bets.iterrows():
            edge_pct = f"{float(bet['edge'])*100:.1f}%"
            kelly_pct = f"{float(bet['kelly_pct'])*100:.2f}%"
            result_str = ""
            if bet.get("result") in ("W", "L", "P"):
                result_str = f" → {bet['result']}"

            lines.append(
                f"    {bet['bet_type']:12s} | {str(bet['side']):20s} | "
                f"{int(bet['odds']):+4d} | Edge: {edge_pct:>5s} | "
                f"Kelly: {kelly_pct:>6s}{result_str}"
            )

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
