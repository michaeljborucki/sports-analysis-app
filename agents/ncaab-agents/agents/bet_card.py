"""Formats daily picks into a clean bet card summary."""
import click
from datetime import date, datetime, timezone
from tracker import load_bets, load_predictions


def _format_game_time(game_time_str: str) -> str:
    """Convert ISO game time to 'h:MM PM ET' display format."""
    if not game_time_str or str(game_time_str) == "nan":
        return "TBD"
    try:
        dt = datetime.fromisoformat(str(game_time_str).replace("Z", "+00:00"))
        # Convert UTC to ET (UTC-4 during EDT)
        from datetime import timedelta
        et = dt - timedelta(hours=4)
        return et.strftime("%-I:%M %p ET")
    except (ValueError, TypeError):
        return "TBD"


def _sort_key(game_time_str: str) -> str:
    """Return sortable string from game_time. Unknown times sort last."""
    if not game_time_str or str(game_time_str) == "nan":
        return "9999"
    return str(game_time_str)


def format_bet_card(game_date: str = None) -> str:
    """Generate a formatted bet card showing ALL predictions for every game.

    Reads from predictions.csv (full analysis) and bets.csv (edge-filtered).
    Games are ordered by tip-off time. Edge bets are marked with a star.
    """
    if game_date is None:
        game_date = date.today().isoformat()

    preds = load_predictions()
    day_preds = preds[preds["date"] == game_date] if not preds.empty else preds

    bets = load_bets()
    day_bets = bets[bets["date"] == game_date] if not bets.empty else bets

    # If no predictions yet, fall back to bets-only view
    if day_preds.empty and day_bets.empty:
        return f"\n=== MiroFish Bet Card -- {game_date} ===\n\nNo analysis for today.\n"

    # Use predictions if available, otherwise fall back to bets
    if day_preds.empty:
        return _format_bets_only(game_date, day_bets)

    # Count edge bets
    edge_count = int(day_preds["has_edge"].sum()) if "has_edge" in day_preds.columns else 0
    game_count = day_preds["game"].nunique()

    lines = [
        f"\n{'='*78}",
        f"  MIROFISH BET CARD -- {game_date}",
        f"  {game_count} games analyzed | {edge_count} recommended bets",
        f"{'='*78}",
        "",
    ]

    # Sort games by game_time
    game_times = {}
    for _, row in day_preds.iterrows():
        g = row["game"]
        if g not in game_times:
            game_times[g] = row.get("game_time", "")
    sorted_games = sorted(game_times.keys(), key=lambda g: _sort_key(game_times[g]))

    for game_key in sorted_games:
        game_preds = day_preds[day_preds["game"] == game_key]
        gt_display = _format_game_time(game_times[game_key])

        pred_score = str(game_preds.iloc[0].get("predicted_score", ""))
        score_suffix = f"  (Proj: {pred_score})" if pred_score and pred_score not in ("", "nan") else ""

        lines.append(f"  {gt_display} -- {game_key}{score_suffix}")
        lines.append(f"  {'─'*74}")

        for _, pred in game_preds.iterrows():
            sim_prob_pct = f"{float(pred['sim_prob'])*100:.1f}%"
            edge_val = float(pred['edge'])
            edge_pct = f"{edge_val*100:+.1f}%"
            kelly_val = float(pred['kelly_pct'])
            kelly_pct = f"{kelly_val*100:.2f}%" if kelly_val > 0 else "  --  "

            has_edge = bool(pred.get("has_edge", False))
            challenged = bool(pred.get("challenger_flag", False))
            result = str(pred.get("result", "")).strip()
            result_tag = ""
            if result in ("W", "L", "P"):
                result_tag = f"  {result}"

            marker = " >> " if has_edge else "    "

            lines.append(
                f"{marker}{pred['bet_type']:16s} | {str(pred['side']):20s} | "
                f"{int(pred['odds']):+4d} | Prob: {sim_prob_pct:>5s} | "
                f"Edge: {edge_pct:>6s} | Kelly: {kelly_pct:>6s}{result_tag}"
            )
            if challenged:
                reason = str(pred.get("challenger_reason", "")).strip()
                if reason and reason != "nan":
                    lines.append(f"         [!] {reason}")
                else:
                    lines.append(f"         [!] Challenger flagged — no specific reason given")

        lines.append("")

    # Summary footer
    settled_preds = day_preds[day_preds["result"].isin(["W", "L", "P"])] if "result" in day_preds.columns else day_preds.iloc[0:0]
    if not settled_preds.empty:
        wins = len(settled_preds[settled_preds["result"] == "W"])
        losses = len(settled_preds[settled_preds["result"] == "L"])
        pushes = len(settled_preds[settled_preds["result"] == "P"])
        total_p = len(settled_preds)
        # Edge bets record
        edge_settled = settled_preds[settled_preds["has_edge"] == True]
        if not edge_settled.empty:
            e_wins = len(edge_settled[edge_settled["result"] == "W"])
            e_losses = len(edge_settled[edge_settled["result"] == "L"])
            e_profit = edge_settled["profit"].sum() if "profit" in edge_settled.columns else 0
            lines.append(f"  All predictions: {wins}-{losses}-{pushes} ({total_p} total)")
            lines.append(f"  Edge bets only:  {e_wins}-{e_losses} | Profit: {e_profit:+.2f} units")
        else:
            lines.append(f"  All predictions: {wins}-{losses}-{pushes} ({total_p} total)")
    else:
        lines.append("  >> = recommended bet (edge >= 5%)  |  [!] = challenger flagged")
        lines.append("  Status: Pending")

    lines.append(f"{'='*78}\n")
    return "\n".join(lines)


def _format_bets_only(game_date: str, day_bets) -> str:
    """Fallback: format using bets.csv only (legacy format)."""
    if day_bets.empty:
        return f"\n=== MiroFish Bet Card -- {game_date} ===\n\nNo picks for today.\n"

    lines = [
        f"\n{'='*60}",
        f"  MIROFISH BET CARD -- {game_date}",
        f"  {len(day_bets)} picks across {day_bets['game'].nunique()} games",
        f"{'='*60}",
        "",
    ]

    for game_key in day_bets["game"].unique():
        game_bets = day_bets[day_bets["game"] == game_key]
        pred_score = str(game_bets.iloc[0].get("predicted_score", ""))
        score_suffix = f"  (Proj: {pred_score})" if pred_score and pred_score not in ("", "nan") else ""
        lines.append(f"  {game_key}{score_suffix}")
        lines.append(f"  {'-'*40}")

        for _, bet in game_bets.iterrows():
            sim_prob_pct = f"{float(bet['sim_prob'])*100:.1f}%"
            edge_pct = f"{float(bet['edge'])*100:.1f}%"
            kelly_pct = f"{float(bet['kelly_pct'])*100:.2f}%"
            result_str = ""
            if bet.get("result") in ("W", "L", "P"):
                result_str = f" -> {bet['result']}"

            lines.append(
                f"    {bet['bet_type']:12s} | {str(bet['side']):20s} | "
                f"{int(bet['odds']):+4d} | Prob: {sim_prob_pct:>5s} | "
                f"Edge: {edge_pct:>5s} | Kelly: {kelly_pct:>6s}{result_str}"
            )

        lines.append("")

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
