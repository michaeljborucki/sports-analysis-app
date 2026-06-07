"""Formats daily picks into a clean bet card summary."""
import json
import math
from datetime import date, datetime
from pathlib import Path

import click

from tracker import load_bets
from scrapers.odds import prob_to_american, american_be_with_wiggle
from notify.format import _format_et_time

MAINLINE_BET_TYPES = {
    "moneyline", "run_line", "total",
    "team_total_home", "team_total_away",
    "first_5_ml", "first_5_rl", "first_5_total",
    "first_3_ml", "first_3_rl", "first_3_total",
    "first_1_rl", "nrfi",
}


def format_bet_card(game_date: str = None) -> str:
    """Generate a formatted bet card for a given date."""
    if game_date is None:
        game_date = date.today().isoformat()

    df = load_bets()
    day_bets = df[df["date"] == game_date]

    if day_bets.empty:
        return f"\n=== Bet Card — {game_date} ===\n\nNo picks for today.\n"

    lines = [
        f"\n{'='*60}",
        f"  BET CARD — {game_date}",
        f"  {len(day_bets)} picks across {day_bets['game'].nunique()} games",
        f"{'='*60}",
        "",
    ]

    for game_key in day_bets["game"].unique():
        game_bets = day_bets[day_bets["game"] == game_key]
        lines.append(f"  {game_key}")
        lines.append(f"  {'-'*40}")

        for _, bet in game_bets.iterrows():
            odds_val = int(bet['odds'])
            sim_prob = float(bet['sim_prob'])
            edge_pct = f"{float(bet['edge'])*100:.1f}%"
            kelly_pct = f"{float(bet['kelly_pct'])*100:.2f}%"
            if 0 < sim_prob < 1:
                be_str = f"{american_be_with_wiggle(prob_to_american(sim_prob)):+d}"
            else:
                be_str = "LOCK" if sim_prob >= 1 else "  --"

            # Use no-vig market_prob if available, fall back to raw odds
            mkt_raw = bet.get("market_prob")
            if mkt_raw is not None and str(mkt_raw).strip() not in ("", "nan"):
                mkt_prob = float(mkt_raw)
            else:
                if odds_val < 0:
                    mkt_prob = abs(odds_val) / (abs(odds_val) + 100)
                else:
                    mkt_prob = 100 / (odds_val + 100)

            result_str = ""
            if bet.get("result") in ("W", "L", "P"):
                result_str = f" \u2192 {bet['result']}"

            lines.append(
                f"    {bet['bet_type']:12s} | {str(bet['side']):20s} | "
                f"{odds_val:+4d} | Mkt: {mkt_prob*100:4.1f}% | "
                f"Model: {sim_prob*100:4.1f}% | Edge: {edge_pct:>5s} | "
                f"Kelly: {kelly_pct:>6s} | BE: {be_str:>5s}{result_str}"
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


def format_mainline_bet_card(game_date: str = None) -> str:
    """Generate a formatted bet card containing only mainline (non-prop) bets."""
    if game_date is None:
        game_date = date.today().isoformat()

    df = load_bets()
    day_bets = df[(df["date"] == game_date) & (df["bet_type"].isin(MAINLINE_BET_TYPES))]

    if day_bets.empty:
        return f"\n=== Mainline Bet Card — {game_date} ===\n\nNo mainline picks for today.\n"

    lines = [
        f"\n{'='*60}",
        f"  MAINLINE BET CARD — {game_date}",
        f"  {len(day_bets)} picks across {day_bets['game'].nunique()} games",
        f"{'='*60}",
        "",
    ]

    for game_key in day_bets["game"].unique():
        game_bets = day_bets[day_bets["game"] == game_key].sort_values("edge", ascending=False)
        time_et = _first_game_time_et(game_bets)
        header = f"  {game_key} \u2014 {time_et}" if time_et else f"  {game_key}"
        lines.append(header)
        lines.append(f"  {'-'*40}")

        for _, bet in game_bets.iterrows():
            odds_val = int(bet["odds"])
            sim_prob = float(bet["sim_prob"])
            edge_pct = f"{float(bet['edge'])*100:.1f}%"
            kelly_pct = f"{float(bet['kelly_pct'])*100:.2f}%"
            if 0 < sim_prob < 1:
                be_str = f"{american_be_with_wiggle(prob_to_american(sim_prob)):+d}"
            else:
                be_str = "LOCK" if sim_prob >= 1 else "  --"

            mkt_raw = bet.get("market_prob")
            if mkt_raw is not None and str(mkt_raw).strip() not in ("", "nan"):
                mkt_prob = float(mkt_raw)
            else:
                if odds_val < 0:
                    mkt_prob = abs(odds_val) / (abs(odds_val) + 100)
                else:
                    mkt_prob = 100 / (odds_val + 100)

            result_str = ""
            if bet.get("result") in ("W", "L", "P"):
                result_str = f" \u2192 {bet['result']}"

            lines.append(
                f"    {bet['bet_type']:18s} | {str(bet['side']):20s} | "
                f"{odds_val:+5d} | Mkt: {mkt_prob*100:4.1f}% | "
                f"Model: {sim_prob*100:4.1f}% | Edge: {edge_pct:>5s} | "
                f"Kelly: {kelly_pct:>6s} | BE: {be_str:>5s}{result_str}"
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


def _first_game_time_et(game_bets) -> str:
    """Return the first non-empty game_time from a game's rows, formatted as ET.

    Safe against missing column (old CSVs) and NaN values.
    """
    if "game_time" not in game_bets.columns:
        return ""
    for val in game_bets["game_time"]:
        formatted = _format_et_time(val)
        if formatted:
            return formatted
    return ""


def _mainline_bet_card_dict(game_date: str) -> dict:
    """Build a serializable dict of mainline picks for a given date."""
    df = load_bets()
    day_bets = df[(df["date"] == game_date) & (df["bet_type"].isin(MAINLINE_BET_TYPES))]

    games = []
    for game_key in day_bets["game"].unique():
        game_rows = day_bets[day_bets["game"] == game_key].sort_values("edge", ascending=False)
        time_et = _first_game_time_et(game_rows)
        picks = []
        for _, bet in game_rows.iterrows():
            odds_val = int(bet["odds"])
            sim_prob = float(bet["sim_prob"])

            mkt_raw = bet.get("market_prob")
            if mkt_raw is not None and str(mkt_raw).strip() not in ("", "nan"):
                mkt_prob = float(mkt_raw)
            else:
                mkt_prob = abs(odds_val) / (abs(odds_val) + 100) if odds_val < 0 else 100 / (odds_val + 100)

            if 0 < sim_prob < 1:
                be_odds = american_be_with_wiggle(prob_to_american(sim_prob))
            else:
                be_odds = None

            result = bet.get("result")
            if result is None or (isinstance(result, float) and math.isnan(result)) or str(result).strip() in ("", "nan"):
                result = None

            picks.append({
                "bet_type": bet["bet_type"],
                "side": str(bet["side"]),
                "odds": odds_val,
                "market_prob": round(mkt_prob, 4),
                "model_prob": round(sim_prob, 4),
                "edge": round(float(bet["edge"]), 4),
                "kelly_pct": round(float(bet["kelly_pct"]), 4),
                "be_odds": be_odds,
                "result": result,
            })
        games.append({"game": game_key, "game_time_et": time_et, "picks": picks})

    return {
        "date": game_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_picks": int(len(day_bets)),
        "games": games,
    }


def write_mainline_bet_card_files(game_date: str = None, out_dir: str = "data") -> tuple[Path, Path]:
    """Write the mainline bet card to data/bet_card_<date>.{txt,json}.

    Filename pattern matches the tennis-agents convention so each day's card
    is preserved in history rather than overwritten.
    """
    if game_date is None:
        game_date = date.today().isoformat()

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    txt_path = out_path / f"bet_card_{game_date}.txt"
    json_path = out_path / f"bet_card_{game_date}.json"

    txt_path.write_text(format_mainline_bet_card(game_date))
    json_path.write_text(json.dumps(_mainline_bet_card_dict(game_date), indent=2))

    return txt_path, json_path


@click.command()
@click.option("--date", "game_date", default=None, help="Date (YYYY-MM-DD)")
@click.option("--mainline", is_flag=True, help="Show only mainline (non-prop) picks")
@click.option("--write", is_flag=True, help="Write mainline card to data/bet_card_<date>.{txt,json}")
def main(game_date, mainline, write):
    """Display formatted bet card for today."""
    if mainline:
        click.echo(format_mainline_bet_card(game_date))
    else:
        click.echo(format_bet_card(game_date))
    if write:
        txt_path, json_path = write_mainline_bet_card_files(game_date)
        click.echo(f"Wrote {txt_path} and {json_path}")


if __name__ == "__main__":
    main()
