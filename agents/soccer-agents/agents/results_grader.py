"""Morning-after agent: pulls final scores, grades pending bets W/L/P."""
import click
from datetime import date, timedelta

from scrapers.scores import get_final_scores
from tracker import load_bets, update_result, get_summary
from config import ACTIVE_LEAGUES


def _match_score(game_key: str, scores: list[dict]) -> dict | None:
    """Match a bet's game key (AWAY@HOME) to a final score."""
    parts = game_key.split("@")
    if len(parts) != 2:
        return None
    away, home = parts
    for s in scores:
        if s["away"] == away and s["home"] == home:
            return s
    return None


def grade_bet(bet_row, score: dict) -> str:
    """Grade a single bet as W/L/P based on final score."""
    bet_type = bet_row["bet_type"]
    side = str(bet_row["side"])

    home_score = score["home_score"]
    away_score = score["away_score"]
    total_goals = score.get("total_goals", home_score + away_score)
    both_scored = score.get("both_scored", home_score > 0 and away_score > 0)

    if bet_type == "asian_handicap":
        tokens = side.split()
        ah_side = tokens[0] if tokens else ""
        handicap = float(tokens[1]) if len(tokens) > 1 else 0

        if ah_side == "home":
            adjusted = home_score + handicap
            return "W" if adjusted > away_score else ("P" if adjusted == away_score else "L")
        else:
            adjusted = away_score + handicap
            return "W" if adjusted > home_score else ("P" if adjusted == home_score else "L")

    elif bet_type == "total":
        tokens = side.split()
        direction = tokens[0] if tokens else ""
        line = float(tokens[1]) if len(tokens) > 1 else 0

        if direction == "over":
            return "W" if total_goals > line else ("P" if total_goals == line else "L")
        else:
            return "W" if total_goals < line else ("P" if total_goals == line else "L")

    elif bet_type == "btts":
        if side == "yes":
            return "W" if both_scored else "L"
        else:
            return "W" if not both_scored else "L"

    return "L"  # unknown bet type


def run_results_grader(game_date: str = None, league: str = None):
    """Grade all pending bets for a given date."""
    if game_date is None:
        yesterday = date.today() - timedelta(days=1)
        game_date = yesterday.isoformat()

    click.echo(f"\n=== Results Grader — {game_date} ===\n")

    # Pull final scores — iterate over all active leagues if none specified
    leagues_to_check = [league] if league else ACTIVE_LEAGUES
    scores = []
    for lg in leagues_to_check:
        scores.extend(get_final_scores(game_date, lg))
    click.echo(f"Found {len(scores)} final scores")

    if not scores:
        click.echo("No final scores available yet.")
        return

    # Load pending bets
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
            f"→ {result} (Score: {score['away_score']}-{score['home_score']})"
        )

    click.echo(f"\nGraded {graded} bets.")
    summary = get_summary()
    click.echo(f"Season record: {summary['record']} | Profit: {summary['profit']} units | ROI: {summary['roi']}%")


@click.command()
@click.option("--date", "game_date", default=None, help="Date to grade (YYYY-MM-DD), defaults to yesterday")
@click.option("--league", "league", default=None, help="League to grade (e.g. MLS), defaults to all active leagues")
def main(game_date, league):
    """Grade yesterday's bets against final scores."""
    run_results_grader(game_date, league)


if __name__ == "__main__":
    main()
