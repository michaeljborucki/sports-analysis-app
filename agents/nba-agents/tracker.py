"""Bet logging and P&L tracking via CSV."""
import os
import pandas as pd
from config import BETS_CSV, DATA_DIR

COLUMNS = [
    "date", "game", "bet_type", "side", "odds", "sim_prob",
    "market_prob", "edge", "kelly_pct", "confidence", "market", "player",
    "projected", "result", "profit",
]


def _ensure_csv(csv_path: str) -> None:
    directory = os.path.dirname(csv_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(csv_path):
        pd.DataFrame(columns=COLUMNS).to_csv(csv_path, index=False)


DEDUP_KEYS = ["date", "game", "bet_type", "side", "player"]


def log_bet(bet: dict, csv_path: str = None) -> None:
    """Append or replace a bet in the CSV tracker (deduped by date/game/bet_type/side/player)."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)

    row = {col: bet.get(col, "") for col in COLUMNS}
    row.setdefault("result", "")
    row.setdefault("profit", "")

    df = pd.read_csv(csv_path)

    # Build mask matching all dedup keys — drop any existing duplicate
    mask = pd.Series(True, index=df.index)
    for key in DEDUP_KEYS:
        mask &= df[key].fillna("").astype(str) == str(row.get(key, ""))
    if mask.any():
        # Keep graded results — only replace if the existing bet is still pending
        settled = df.loc[mask, "result"].fillna("").isin(["W", "L", "P"])
        if settled.all():
            # All matching rows are already graded, don't replace
            return
        # Drop only the pending duplicates
        df = df[~(mask & ~df["result"].fillna("").isin(["W", "L", "P"]))]

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(csv_path, index=False)


def load_bets(csv_path: str = None) -> pd.DataFrame:
    """Load all bets from CSV."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)
    df = pd.read_csv(csv_path)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[COLUMNS]


def update_result(index: int, result: str, csv_path: str = None) -> None:
    """Update a bet's result (W/L/P) and calculate profit."""
    csv_path = csv_path or BETS_CSV
    df = pd.read_csv(csv_path, dtype={"result": str, "profit": float})
    df["result"] = df["result"].astype(object)
    df.at[index, "result"] = result

    odds = df.at[index, "odds"]
    if result == "W":
        if odds < 0:
            df.at[index, "profit"] = round(100 / abs(odds), 2)
        else:
            df.at[index, "profit"] = round(odds / 100, 2)
    elif result == "L":
        df.at[index, "profit"] = -1.0
    else:  # Push
        df.at[index, "profit"] = 0.0

    df.to_csv(csv_path, index=False)


BET_TYPE_GROUPS = {
    "Game": ["moneyline", "spread", "total"],
    "Half": ["first_half_ml", "first_half_total", "first_half_spread"],
    "Quarter": ["q1_ml", "q1_spread", "q1_total", "q2_total", "q3_total", "q4_total"],
    "Team Total": ["team_total_home", "team_total_away"],
    "Player Props": ["player_points", "player_rebounds", "player_assists", "player_threes", "player_pra"],
}


def get_breakdown(csv_path: str = None) -> list[dict]:
    """Generate P&L breakdown grouped by bet type category, sorted by ROI."""
    csv_path = csv_path or BETS_CSV
    df = load_bets(csv_path)
    if df.empty:
        return []

    settled = df[df["result"].isin(["W", "L", "P"])]
    if settled.empty:
        return []

    groups = []
    for group_name, bet_types in BET_TYPE_GROUPS.items():
        types_in_group = []
        for bt in bet_types:
            bt_df = settled[settled["bet_type"] == bt]
            if bt_df.empty:
                continue
            w = len(bt_df[bt_df["result"] == "W"])
            l = len(bt_df[bt_df["result"] == "L"])
            p = len(bt_df[bt_df["result"] == "P"])
            profit = round(float(bt_df["profit"].sum()), 2)
            n = len(bt_df)
            roi = round(profit / n * 100, 1)
            types_in_group.append({
                "bet_type": bt,
                "record": f"{w}-{l}-{p}",
                "profit": profit,
                "roi": roi,
                "count": n,
            })
        if types_in_group:
            types_in_group.sort(key=lambda x: x["roi"], reverse=True)
            groups.append({"group": group_name, "types": types_in_group})
    return groups


def format_breakdown(groups: list[dict]) -> str:
    """Format the bet type breakdown as a printable string."""
    if not groups:
        return ""
    lines = ["\n  Breakdown by bet type:"]
    for g in groups:
        lines.append(f"\n    {g['group']}:")
        for t in g["types"]:
            label = t["bet_type"].replace("_", " ").replace("first half", "H1")
            lines.append(
                f"      {label:<22s} {t['record']:>9s}  {t['profit']:>+8.2f}u  ({t['roi']:>+5.1f}%)"
            )
    return "\n".join(lines)


def get_summary(csv_path: str = None) -> dict:
    """Generate P&L summary."""
    csv_path = csv_path or BETS_CSV
    df = load_bets(csv_path)

    if df.empty:
        return {"total_bets": 0, "record": "0-0-0", "profit": 0, "roi": 0}

    settled = df[df["result"].isin(["W", "L", "P"])]
    wins = len(settled[settled["result"] == "W"])
    losses = len(settled[settled["result"] == "L"])
    pushes = len(settled[settled["result"] == "P"])
    profit = settled["profit"].sum() if not settled.empty else 0

    return {
        "total_bets": len(df),
        "settled": len(settled),
        "pending": len(df) - len(settled),
        "record": f"{wins}-{losses}-{pushes}",
        "win_rate": round(wins / max(len(settled), 1), 3),
        "profit": round(float(profit), 2),
        "roi": round(float(profit) / max(len(settled), 1) * 100, 1),
    }
