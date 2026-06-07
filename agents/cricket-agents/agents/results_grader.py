"""Morning-after agent: pulls final scores, grades pending bets W/L/P."""
import click
from datetime import date, timedelta

from scrapers.scores import get_final_scores, MatchResult
from tracker import load_bets, update_result, get_summary


def _match_score(game_key: str, scores: list[MatchResult]) -> MatchResult | None:
    """Match a bet's game key (TEAM_A@TEAM_B) to a final score."""
    parts = game_key.split("@")
    if len(parts) != 2:
        return None
    team_a, team_b = parts
    for s in scores:
        if s.team_a == team_a and s.team_b == team_b:
            return s
    return None


def grade_bet(bet_row, score) -> str:
    """Grade a single bet as W/L/P based on final score.

    score may be a MatchResult dataclass or a dict (for tests).
    """
    bet_type = bet_row["bet_type"]
    side = str(bet_row["side"])

    # Support both MatchResult dataclass and plain dict (used in tests)
    if isinstance(score, dict):
        team_a_score = score["team_a_score"]
        team_b_score = score["team_b_score"]
        total_runs = score["total_runs"]
        dls_applied = score.get("dls_applied", False)
        winner = score.get("winner", "")
    else:
        team_a_score = score.team_a_score
        team_b_score = score.team_b_score
        total_runs = score.total_runs
        dls_applied = score.dls_applied
        winner = score.winner

    team_a_won = team_a_score > team_b_score

    if bet_type == "moneyline":
        if side == "team_a":
            return "W" if team_a_won else "L"
        else:  # team_b
            return "W" if not team_a_won else "L"

    elif bet_type == "total_runs":
        # Void (push) if DLS was applied — rain-affected totals are unreliable
        if dls_applied:
            return "P"

        # Parse side like "over 320.5" or "under 300.5"
        tokens = side.split()
        direction = tokens[0] if tokens else ""
        line = float(tokens[1]) if len(tokens) > 1 else 0

        if direction == "over":
            return "W" if total_runs > line else ("P" if total_runs == line else "L")
        else:
            return "W" if total_runs < line else ("P" if total_runs == line else "L")

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
            f"→ {result} (Score: {score.team_a_score}-{score.team_b_score})"
        )

    click.echo(f"\nGraded {graded} bets.")
    summary = get_summary()
    click.echo(f"Season record: {summary['record']} | Profit: {summary['profit']} units | ROI: {summary['roi']}%")


@click.command()
@click.option("--date", "game_date", default=None, help="Date to grade (YYYY-MM-DD), defaults to yesterday")
def main(game_date):
    """Grade yesterday's bets against final scores."""
    run_results_grader(game_date)


if __name__ == "__main__":
    main()
