"""Morning-after agent: pulls final scores, grades pending bets W/L/P."""
import click
from datetime import date, timedelta

from scrapers.scores import get_final_scores
from tracker import (load_bets, update_result, get_summary,
                     load_predictions, update_prediction_result)


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
    home_won = home_score > away_score
    margin = abs(home_score - away_score)
    total = score["total_points"]

    if bet_type == "moneyline":
        if side == "home":
            return "W" if home_won else "L"
        else:  # away
            return "W" if not home_won else "L"

    elif bet_type == "spread":
        # Parse side like "home -1.5" or "away 1.5"
        tokens = side.split()
        rl_side = tokens[0] if tokens else ""
        spread = float(tokens[1]) if len(tokens) > 1 else 0

        if rl_side == "home":
            adjusted = home_score + spread  # spread is negative for favorite
            return "W" if adjusted > away_score else ("P" if adjusted == away_score else "L")
        else:
            adjusted = away_score + spread
            return "W" if adjusted > home_score else ("P" if adjusted == home_score else "L")

    elif bet_type == "total":
        # Parse side like "over 8.5" or "under 8.5"
        tokens = side.split()
        direction = tokens[0] if tokens else ""
        line = float(tokens[1]) if len(tokens) > 1 else 0

        if direction == "over":
            return "W" if total > line else ("P" if total == line else "L")
        else:
            return "W" if total < line else ("P" if total == line else "L")

    elif bet_type == "first_half_ml":
        home_h1 = score["home_score_h1"]
        away_h1 = score["away_score_h1"]

        if "home" in side:
            return "W" if home_h1 > away_h1 else ("P" if home_h1 == away_h1 else "L")
        else:
            return "W" if away_h1 > home_h1 else ("P" if away_h1 == home_h1 else "L")

    elif bet_type == "first_half_spread":
        home_h1 = score["home_score_h1"]
        away_h1 = score["away_score_h1"]
        # Parse side like "home H1 -3.5" or "away H1 3.5"
        tokens = side.split()
        sp_side = tokens[0] if tokens else ""
        spread = float(tokens[-1]) if len(tokens) > 1 else 0

        if sp_side == "home":
            adjusted = home_h1 + spread
            return "W" if adjusted > away_h1 else ("P" if adjusted == away_h1 else "L")
        else:
            adjusted = away_h1 + spread
            return "W" if adjusted > home_h1 else ("P" if adjusted == home_h1 else "L")

    elif bet_type == "first_half_total":
        total_h1 = score["total_points_h1"]
        tokens = side.split()
        direction = tokens[0] if tokens else ""
        line = float(tokens[-1]) if len(tokens) > 1 else 0

        if direction == "over":
            return "W" if total_h1 > line else ("P" if total_h1 == line else "L")
        else:
            return "W" if total_h1 < line else ("P" if total_h1 == line else "L")

    return "L"  # unknown bet type defaults to loss


def run_results_grader(game_date: str = None):
    """Grade all pending bets for a given date."""
    if game_date is None:
        yesterday = date.today() - timedelta(days=1)
        game_date = yesterday.isoformat()

    click.echo(f"\n=== Results Grader — {game_date} ===\n")

    # Pull final scores
    scores = get_final_scores(game_date)
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

    # Also grade full predictions (predictions.csv)
    preds = load_predictions()
    if preds.empty:
        return
    pending_preds = preds[(preds["date"] == game_date) & (~preds["result"].isin(["W", "L", "P"]))]
    if pending_preds.empty:
        return

    pred_graded = 0
    for idx, row in pending_preds.iterrows():
        score = _match_score(row["game"], scores)
        if not score:
            continue
        result = grade_bet(row, score)
        update_prediction_result(idx, result)
        pred_graded += 1

    if pred_graded:
        click.echo(f"Also graded {pred_graded} predictions in full analysis.")


@click.command()
@click.option("--date", "game_date", default=None, help="Date to grade (YYYY-MM-DD), defaults to yesterday")
def main(game_date):
    """Grade yesterday's bets against final scores."""
    run_results_grader(game_date)


if __name__ == "__main__":
    main()
