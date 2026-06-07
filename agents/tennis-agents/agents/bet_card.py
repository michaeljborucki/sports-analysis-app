"""Formats daily picks into a clean bet card summary."""
import json
import os
from datetime import date, datetime, timedelta

import click
import pandas as pd

from config import DATA_DIR
from tracker import load_bets


def _split_game(game: str) -> tuple[str, str]:
    """Split a game key like 'A. Rublev vs A. Fils' into (player_a_name, player_b_name)."""
    if not game or " vs " not in game:
        return "", ""
    left, right = game.split(" vs ", 1)
    return left.strip(), right.strip()


def _resolve_side(side: str, pa_name: str, pb_name: str) -> str:
    """Replace literal 'player_a'/'player_b' tokens in a side string with actual names."""
    if not side:
        return side
    out = side
    if pa_name:
        out = out.replace("player_a", pa_name)
    if pb_name:
        out = out.replace("player_b", pb_name)
    return out


def _render_card(bets_df, label: str) -> str:
    if bets_df.empty:
        return f"\n=== MiroFish Tennis Bet Card — {label} ===\n\nNo picks for this window.\n"

    lines = [
        f"\n{'='*60}",
        f"  MIROFISH TENNIS BET CARD — {label}",
        f"  {len(bets_df)} picks across {bets_df['game'].nunique()} matches",
        f"{'='*60}",
        "",
    ]

    for game_key in bets_df["game"].unique():
        game_bets = bets_df[bets_df["game"] == game_key]
        pa_name, pb_name = _split_game(str(game_key))
        # Show local start time when available — same formatter the Discord
        # picks/grades channels use, so operator sees consistent times.
        from notify.format import format_start_time_local
        first_start = ""
        for st in game_bets.get("start_time", []):
            if st and str(st).strip() not in ("", "nan", "NaN"):
                first_start = str(st)
                break
        time_str = format_start_time_local(first_start)
        header = f"  {game_key} — {time_str}" if time_str else f"  {game_key}"
        lines.append(header)
        lines.append(f"  {'-'*40}")

        for _, bet in game_bets.iterrows():
            edge_pct = f"{float(bet['edge'])*100:.1f}%"
            kelly_pct = f"{float(bet['kelly_pct'])*100:.2f}%"
            result_str = ""
            if bet.get("result") in ("W", "L", "P"):
                result_str = f" → {bet['result']}"
            side_display = _resolve_side(str(bet["side"]), pa_name, pb_name)
            lines.append(
                f"    {bet['bet_type']:15s} | {side_display:24s} | "
                f"{int(bet['odds']):+4d} | Edge: {edge_pct:>5s} | "
                f"Kelly: {kelly_pct:>6s}{result_str}"
            )
        lines.append("")

    settled = bets_df[bets_df["result"].isin(["W", "L", "P"])]
    if not settled.empty:
        wins = len(settled[settled["result"] == "W"])
        losses = len(settled[settled["result"] == "L"])
        profit = settled["profit"].sum()
        lines.append(f"  Record: {wins}-{losses} | Profit: {profit:+.2f} units")
    else:
        lines.append("  Status: Pending")

    lines.append(f"{'='*60}\n")
    return "\n".join(lines)


def _opt_float(val):
    if val is None:
        return None
    s = str(val).strip()
    if s in ("", "nan", "NaN"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _opt_int(val):
    f = _opt_float(val)
    return int(f) if f is not None else None


def _bets_to_records(bets_df) -> list:
    records = []
    for _, bet in bets_df.iterrows():
        result = bet.get("result")
        if result not in ("W", "L", "P"):
            result = None
        start_time = str(bet.get("start_time", "")).strip() or None
        game = str(bet.get("game", ""))
        pa_name, pb_name = _split_game(game)
        raw_side = str(bet.get("side", ""))
        records.append({
            "date": str(bet.get("date", "")),
            "start_time": start_time,
            "game": game,
            "player_a": pa_name or None,
            "player_b": pb_name or None,
            "bet_type": str(bet.get("bet_type", "")),
            "side": _resolve_side(raw_side, pa_name, pb_name),
            "side_raw": raw_side,
            "odds": _opt_int(bet.get("odds")),
            "sim_prob": _opt_float(bet.get("sim_prob")),
            "market_prob": _opt_float(bet.get("market_prob")),
            "edge": _opt_float(bet.get("edge")),
            "kelly_pct": _opt_float(bet.get("kelly_pct")),
            "result": result,
            "profit": _opt_float(bet.get("profit")),
        })
    return records


def _build_payload(bets_df, label: str) -> dict:
    if bets_df.empty:
        settled_count = wins = losses = pushes = 0
        profit = 0.0
    else:
        settled = bets_df[bets_df["result"].isin(["W", "L", "P"])]
        settled_count = len(settled)
        wins = int((settled["result"] == "W").sum()) if settled_count else 0
        losses = int((settled["result"] == "L").sum()) if settled_count else 0
        pushes = int((settled["result"] == "P").sum()) if settled_count else 0
        profit = (
            float(pd.to_numeric(settled["profit"], errors="coerce").fillna(0).sum())
            if settled_count else 0.0
        )

    return {
        "label": label,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_picks": int(len(bets_df)),
        "total_matches": int(bets_df["game"].nunique()) if not bets_df.empty else 0,
        "record": {
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "settled": settled_count,
            "pending": int(len(bets_df) - settled_count),
            "profit_units": round(profit, 2),
        },
        "picks": _bets_to_records(bets_df),
    }


def write_bet_card_files(label: str, bets_df, text: str, out_dir: str = None):
    """Write <out_dir>/bet_card_<label>.{txt,json}. Returns (txt_path, json_path)."""
    out_dir = out_dir or DATA_DIR
    os.makedirs(out_dir, exist_ok=True)
    txt_path = os.path.join(out_dir, f"bet_card_{label}.txt")
    json_path = os.path.join(out_dir, f"bet_card_{label}.json")
    with open(txt_path, "w") as f:
        f.write(text)
    with open(json_path, "w") as f:
        json.dump(_build_payload(bets_df, label), f, indent=2)
    return txt_path, json_path


def format_bet_card(game_date: str = None) -> str:
    if game_date is None:
        game_date = date.today().isoformat()
    df = load_bets()
    return _render_card(df[df["date"] == game_date], game_date)


def format_bet_card_window(start_date: str, end_date: str) -> str:
    df = load_bets()
    bets = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
    label = start_date if start_date == end_date else f"{start_date} → {end_date}"
    return _render_card(bets, label)


def save_bet_card(game_date: str = None):
    """Render and persist a single-day bet card. Returns (txt_path, json_path)."""
    if game_date is None:
        game_date = date.today().isoformat()
    df = load_bets()
    day_bets = df[df["date"] == game_date]
    text = _render_card(day_bets, game_date)
    return write_bet_card_files(game_date, day_bets, text)


def save_bet_card_window(start_date: str, end_date: str):
    """Render and persist a windowed bet card; filename uses start_date. Returns (txt_path, json_path)."""
    df = load_bets()
    bets = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
    display_label = start_date if start_date == end_date else f"{start_date} → {end_date}"
    text = _render_card(bets, display_label)
    return write_bet_card_files(start_date, bets, text)


@click.command()
@click.option("--date", "game_date", default=None)
def main(game_date):
    if game_date is None:
        game_date = date.today().isoformat()
    df = load_bets()
    day_bets = df[df["date"] == game_date]
    text = _render_card(day_bets, game_date)
    click.echo(text)
    txt_path, json_path = write_bet_card_files(game_date, day_bets, text)
    click.echo(f"Saved: {txt_path}")
    click.echo(f"Saved: {json_path}")


if __name__ == "__main__":
    main()
