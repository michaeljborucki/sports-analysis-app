"""Morning-after agent: pulls final scores, grades pending bets W/L/P."""
import click
import logging
from datetime import date, timedelta

from scrapers.scores import get_final_scores
from scrapers.player_stats import get_player_box_scores, find_player
from tracker import load_bets, update_result, get_summary, get_breakdown, format_breakdown
from agents.self_optimizer import apply_learnings

logger = logging.getLogger("mirofish.grader")


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
        h1_home = score["home_score_h1"]
        h1_away = score["away_score_h1"]
        if "home" in side:
            return "W" if h1_home > h1_away else ("P" if h1_home == h1_away else "L")
        else:
            return "W" if h1_away > h1_home else ("P" if h1_away == h1_home else "L")

    elif bet_type == "first_half_total":
        h1_total = score["total_points_h1"]
        tokens = side.split()
        direction = tokens[0]
        line = float(tokens[-1])
        if direction == "over":
            return "W" if h1_total > line else ("P" if h1_total == line else "L")
        else:
            return "W" if h1_total < line else ("P" if h1_total == line else "L")

    elif bet_type == "first_half_spread":
        h1_home = score["home_score_h1"]
        h1_away = score["away_score_h1"]
        tokens = side.split()
        rl_side = tokens[0]
        spread_val = float(tokens[1]) if len(tokens) > 1 else 0
        if rl_side == "home":
            adjusted = h1_home + spread_val
            return "W" if adjusted > h1_away else ("P" if adjusted == h1_away else "L")
        else:
            adjusted = h1_away + spread_val
            return "W" if adjusted > h1_home else ("P" if adjusted == h1_home else "L")

    elif bet_type.startswith("q") and "_" in bet_type:
        parts = bet_type.split("_", 1)
        quarter = int(parts[0][1])  # "q1" -> 1
        sub_type = parts[1]  # "ml", "spread", "total"
        q_home = score.get(f"home_score_q{quarter}", 0)
        q_away = score.get(f"away_score_q{quarter}", 0)
        q_total_pts = q_home + q_away

        if sub_type == "ml":
            if "home" in side:
                return "W" if q_home > q_away else ("P" if q_home == q_away else "L")
            else:
                return "W" if q_away > q_home else ("P" if q_away == q_home else "L")
        elif sub_type == "total":
            tokens = side.split()
            direction = tokens[0]
            line = float(tokens[-1])
            if direction == "over":
                return "W" if q_total_pts > line else ("P" if q_total_pts == line else "L")
            else:
                return "W" if q_total_pts < line else ("P" if q_total_pts == line else "L")
        elif sub_type == "spread":
            tokens = side.split()
            rl_side = tokens[0]
            spread_val = float(tokens[-1]) if len(tokens) > 1 else 0
            if rl_side == "home":
                adjusted = q_home + spread_val
                return "W" if adjusted > q_away else ("P" if adjusted == q_away else "L")
            else:
                adjusted = q_away + spread_val
                return "W" if adjusted > q_home else ("P" if adjusted == q_home else "L")

    elif bet_type.startswith("team_total_"):
        team_side = bet_type.split("_")[-1]
        team_score = score[f"{team_side}_score"]
        tokens = side.split()
        direction = tokens[0]
        line = float(tokens[-1])
        if direction == "over":
            return "W" if team_score > line else ("P" if team_score == line else "L")
        else:
            return "W" if team_score < line else ("P" if team_score == line else "L")

    elif bet_type.startswith("player_"):
        # Player props graded via box score data
        box_scores = score.get("_box_scores")
        if not box_scores:
            return None  # No box score data available

        player_name = str(bet_row.get("player", ""))
        if not player_name or player_name == "nan":
            return None

        # Fuzzy match player in box score
        player_stats = find_player(player_name, box_scores)
        if not player_stats:
            logger.warning("Player '%s' not found in box score (DNP) — grading as push", player_name)
            return "P"

        # Map bet_type to stat key
        prop_stat_map = {
            "player_points": "points",
            "player_rebounds": "rebounds",
            "player_assists": "assists",
            "player_threes": "threes",
            "player_pra": "pra",
        }
        stat_key = prop_stat_map.get(bet_type)
        if not stat_key:
            return None

        actual = player_stats.get(stat_key, 0)
        tokens = side.split()
        direction = tokens[0]  # "over" or "under"
        line = float(tokens[-1])

        if direction == "over":
            return "W" if actual > line else ("P" if actual == line else "L")
        else:
            return "W" if actual < line else ("P" if actual == line else "L")

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

    # Fetch box scores for player prop grading
    for score in scores:
        game_id = score.get("game_id")
        if game_id:
            box = get_player_box_scores(game_id)
            score["_box_scores"] = box
            if box:
                click.echo(f"  Fetched box score for {score['away']}@{score['home']} ({len(box)} players)")
        else:
            score["_box_scores"] = []

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
        if result is None:
            continue  # Cannot grade (e.g., player props without box scores)
        update_result(idx, result)
        graded += 1

        emoji = {"W": "+", "L": "-", "P": "="}[result]
        player_str = f" [{row.get('player', '')}]" if row.get("player") else ""
        click.echo(
            f"  [{emoji}] {row['game']} | {row['bet_type']}{player_str} {row['side']} "
            f"→ {result} (Score: {score['away_score']}-{score['home_score']})"
        )

    click.echo(f"\nGraded {graded} bets.")
    summary = get_summary()
    click.echo(f"Season record: {summary['record']} | Profit: {summary['profit']} units | ROI: {summary['roi']}%")
    breakdown = get_breakdown()
    if breakdown:
        click.echo(format_breakdown(breakdown))

    # Run learning loop to update weights and thresholds
    if graded > 0:
        apply_learnings()


@click.command()
@click.option("--date", "game_date", default=None, help="Date to grade (YYYY-MM-DD), defaults to yesterday")
def main(game_date):
    """Grade yesterday's bets against final scores."""
    run_results_grader(game_date)


if __name__ == "__main__":
    main()
