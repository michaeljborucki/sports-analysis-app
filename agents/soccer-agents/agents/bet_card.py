"""Formats daily picks into a clean bet card summary."""
import logging
import click
from datetime import date, datetime, timezone
from tracker import load_bets

logger = logging.getLogger("mirofish.bet_card")


def _kickoffs_by_game(leagues: list[str]) -> dict[str, datetime]:
    """Fetch today's kickoff times keyed by 'Away@Home' for each league.

    Names match bets.csv because both sides come from The Odds API.
    """
    from scrapers.odds import get_soccer_odds

    out: dict[str, datetime] = {}
    for lg in leagues:
        try:
            for o in get_soccer_odds(lg):
                if not o.commence_time:
                    continue
                try:
                    ts = datetime.fromisoformat(o.commence_time.replace("Z", "+00:00"))
                except ValueError:
                    continue
                out[f"{o.away}@{o.home}"] = ts
        except Exception as e:
            logger.warning("kickoff fetch failed for %s: %s", lg, e)
    return out


def format_bet_card(game_date: str = None, upcoming_only: bool = False) -> str:
    """Generate a formatted bet card for a given date.

    When upcoming_only is True, drops bets whose kickoff has already passed.
    Bets with no kickoff match are kept (fail-open).
    """
    if game_date is None:
        game_date = date.today().isoformat()

    df = load_bets()
    day_bets = df[df["date"] == game_date]

    suffix = " (upcoming)" if upcoming_only else ""
    if upcoming_only and not day_bets.empty:
        leagues = [lg for lg in day_bets["league"].dropna().unique().tolist() if lg]
        kickoffs = _kickoffs_by_game(leagues)
        now = datetime.now(timezone.utc)
        day_bets = day_bets[day_bets["game"].map(
            lambda g: g not in kickoffs or kickoffs[g] > now
        )]

    if day_bets.empty:
        return f"\n=== MiroFish Bet Card — {game_date}{suffix} ===\n\nNo picks for today.\n"

    header = f"  MIROFISH BET CARD — {game_date}" + (" (upcoming only)" if upcoming_only else "")
    lines = [
        f"\n{'='*60}",
        header,
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
@click.option("--upcoming", is_flag=True, help="Only show bets whose kickoff is in the future.")
def main(game_date, upcoming):
    """Display formatted bet card for today."""
    click.echo(format_bet_card(game_date, upcoming_only=upcoming))


if __name__ == "__main__":
    main()
