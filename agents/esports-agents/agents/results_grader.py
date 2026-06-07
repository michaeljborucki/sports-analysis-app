"""Morning-after agent: pulls final scores, grades pending bets W/L/P."""
import click
from datetime import date, timedelta


def _match_score(game_key: str, scores: list[dict]) -> dict | None:
    """Match a bet's game key (TEAM_A@TEAM_B) to a final score."""
    parts = game_key.split("@")
    if len(parts) != 2:
        return None
    team_a, team_b = parts
    for s in scores:
        if s["team_a"] == team_a and s["team_b"] == team_b:
            return s
    return None


def grade_moneyline(bet_side: str, result: dict) -> str:
    """Grade moneyline bet. Straightforward winner comparison."""
    if result.get("winner") == bet_side:
        return "W"
    return "L"


def grade_map_handicap(bet_side: str, handicap: float, result: dict) -> str:
    """Grade map handicap bet.

    E.g., team_a -1.5 maps, actual 2-0 → adjusted = 0.5-0 → W
    E.g., team_a -1.5 maps, actual 2-1 → adjusted = 0.5-1 → L
    """
    score_parts = result["score"].split("-")
    team_a_maps = int(score_parts[0])
    team_b_maps = int(score_parts[1])

    if bet_side == "team_a":
        adjusted = team_a_maps + handicap
        return "W" if adjusted > team_b_maps else "L"
    else:  # team_b or underdog
        adjusted = team_b_maps + handicap
        return "W" if adjusted > team_a_maps else "L"


def grade_total_maps(bet_side: str, line: float, result: dict) -> str:
    """Grade total maps bet."""
    maps_played = result["maps_played"]
    if bet_side == "over":
        if maps_played > line:
            return "W"
        elif maps_played == line:
            return "P"
        return "L"
    else:  # under
        if maps_played < line:
            return "W"
        elif maps_played == line:
            return "P"
        return "L"


def grade_bet(bet_row, result: dict) -> str:
    """Grade a single bet as W/L/P based on final result.

    Dispatches to the appropriate esports grading function based on bet_type.
    Expected bet_types: moneyline, map_handicap, total_maps.
    """
    bet_type = bet_row["bet_type"]
    side = str(bet_row["side"])

    if bet_type == "moneyline":
        return grade_moneyline(side, result)

    elif bet_type == "map_handicap":
        # side format: "team_a -1.5" or "team_b +1.5"
        tokens = side.split()
        bet_side = tokens[0] if tokens else ""
        handicap = float(tokens[1]) if len(tokens) > 1 else 0.0
        return grade_map_handicap(bet_side, handicap, result)

    elif bet_type == "total_maps":
        # side format: "over 2.5" or "under 2.5"
        tokens = side.split()
        direction = tokens[0] if tokens else ""
        line = float(tokens[1]) if len(tokens) > 1 else 0.0
        return grade_total_maps(direction, line, result)

    return "L"  # unknown bet type defaults to loss


def run_results_grader(game_date: str = None):
    """Grade all pending bets for a given date."""
    from scrapers.scores import get_final_scores
    from tracker import load_bets, update_result, get_summary

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

        symbol = {"W": "+", "L": "-", "P": "="}[result]
        click.echo(
            f"  [{symbol}] {row['game']} | {row['bet_type']} {row['side']} "
            f"→ {result} (Score: {score['score']})"
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
