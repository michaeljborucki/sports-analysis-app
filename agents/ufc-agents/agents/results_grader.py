"""UFC fight result grader — grades pending bets W/L/P based on actual results."""
import logging
import re

logger = logging.getLogger("mirofish.results_grader")


def grade_bet(bet: dict, result: dict) -> str:
    """Grade a single bet against the actual fight result.

    Args:
        bet: dict with bet_type, side
        result: dict with winner, method, round

    Returns: "W", "L", or "P" (push)
    """
    bet_type = bet.get("bet_type", "")
    side = bet.get("side", "")

    if bet_type == "moneyline":
        return "W" if side == result.get("winner") else "L"

    elif bet_type == "total_rounds":
        actual_round = result.get("round", 0)
        method = result.get("method", "")

        match = re.match(r"(over|under)\s+([\d.]+)", side)
        if not match:
            logger.warning("Could not parse total_rounds side: %s", side)
            return "P"

        direction = match.group(1)
        line = float(match.group(2))

        if direction == "over":
            return "W" if actual_round > line else "L"
        else:
            return "W" if actual_round < line else "L"

    elif bet_type == "method":
        actual_method = result.get("method", "").lower()
        method_map = {
            "ko_tko": ["ko", "tko", "ko/tko"],
            "submission": ["submission", "sub"],
            "decision": ["decision", "unanimous", "split", "majority"],
        }
        matching_methods = method_map.get(side, [])
        for m in matching_methods:
            if m in actual_method:
                return "W"
        return "L"

    logger.warning("Unknown bet type: %s", bet_type)
    return "P"


def run_results_grader(fight_date: str = None):
    """Grade all pending bets for a given date.

    Placeholder — requires fight results data source.
    """
    import click
    from datetime import date as dt_date
    from tracker import load_bets

    if fight_date is None:
        fight_date = dt_date.today().isoformat()

    df = load_bets()
    pending = df[(df["date"] == fight_date) & (df["result"] == "")]

    if pending.empty:
        click.echo(f"No pending bets to grade for {fight_date}")
        return

    click.echo(f"Found {len(pending)} pending bet(s) for {fight_date}")
    click.echo("Results grading requires fight result data — not yet implemented.")
    logger.info("Results grader stub: %d pending bets for %s", len(pending), fight_date)
