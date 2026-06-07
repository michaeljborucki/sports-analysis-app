"""Morning-after agent: pulls final scores, grades pending bets W/L/P."""
import click
from datetime import date, timedelta

from scrapers.scores import get_match_results
from tracker import load_bets, update_result, get_summary


def _match_score(game_key: str, scores: list[dict]) -> dict | None:
    """Match a bet's game key (PlayerA vs PlayerB) to a final score."""
    for s in scores:
        key = f"{s['player_a']} vs {s['player_b']}"
        if key == game_key:
            return s
        # Try reversed
        key_rev = f"{s['player_b']} vs {s['player_a']}"
        if key_rev == game_key:
            return s
    return None


def grade_bet(bet_row, score: dict) -> str:
    """Grade a single bet as W/L/P based on match result."""
    bet_type = bet_row["bet_type"]
    side = str(bet_row["side"])

    # Handle retirements — flag for manual review
    if score.get("retired", False):
        return "P"  # Push on retirements (most books void)

    winner = score["winner"]
    player_a = score["player_a"]
    player_b = score["player_b"]
    games_a = score["games_a"]
    games_b = score["games_b"]
    total_games = score["total_games"]

    if bet_type == "moneyline":
        if side == "player_a":
            return "W" if winner == player_a else "L"
        else:
            return "W" if winner == player_b else "L"

    elif bet_type == "game_handicap":
        # Parse side like "player_a -4.5" or "player_b 4.5"
        tokens = side.split()
        gh_side = tokens[0] if tokens else ""
        spread = float(tokens[1]) if len(tokens) > 1 else 0

        if "player_a" in gh_side:
            adjusted = games_a + spread
            return "W" if adjusted > games_b else ("P" if adjusted == games_b else "L")
        else:
            adjusted = games_b + spread
            return "W" if adjusted > games_a else ("P" if adjusted == games_a else "L")

    elif bet_type == "total_games":
        tokens = side.split()
        direction = tokens[0] if tokens else ""
        line = float(tokens[1]) if len(tokens) > 1 else 0

        if direction == "over":
            return "W" if total_games > line else ("P" if total_games == line else "L")
        else:
            return "W" if total_games < line else ("P" if total_games == line else "L")

    return "L"


def run_results_grader(game_date: str = None, tour: str = "atp"):
    """Grade all pending bets for a given date."""
    if game_date is None:
        yesterday = date.today() - timedelta(days=1)
        game_date = yesterday.isoformat()

    click.echo(f"\n=== Results Grader — {game_date} ({tour.upper()}) ===\n")

    scores = get_match_results(game_date, tour)
    click.echo(f"Found {len(scores)} completed matches")

    if not scores:
        click.echo("No match results available yet.")
        return

    df = load_bets()
    pending = df[(df["date"] == game_date) & (~df["result"].isin(["W", "L", "P"]))]

    if pending.empty:
        click.echo("No pending bets for this date.")
        return

    click.echo(f"Grading {len(pending)} pending bets...\n")

    graded = 0
    for idx, row in pending.iterrows():
        score = _match_score(row["game"], scores)
        if not score:
            click.echo(f"  {row['game']}: No score found, skipping")
            continue

        result = grade_bet(row, score)
        update_result(idx, result)
        graded += 1

        emoji = {"W": "+", "L": "-", "P": "="}[result]
        click.echo(
            f"  [{emoji}] {row['game']} | {row['bet_type']} {row['side']} "
            f"→ {result} (Score: {score['score']})"
        )

    click.echo(f"\nGraded {graded} bets.")
    summary = get_summary()
    click.echo(f"Season record: {summary['record']} | Profit: {summary['profit']} units | ROI: {summary['roi']}%")


@click.command()
@click.option("--date", "game_date", default=None)
@click.option("--tour", default="atp", type=click.Choice(["atp", "wta"]))
def main(game_date, tour):
    """Grade yesterday's bets against final scores."""
    run_results_grader(game_date, tour)


if __name__ == "__main__":
    main()
