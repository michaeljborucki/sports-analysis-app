"""Bet logging and P&L tracking via CSV."""
import os
import pandas as pd
from config import BETS_CSV, DATA_DIR

COLUMNS = [
    "date", "game", "bet_type", "side", "projected", "odds",
    "sim_prob", "edge", "kelly_pct", "tier", "result", "profit",
]


def _ensure_csv(csv_path: str) -> None:
    directory = os.path.dirname(csv_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(csv_path):
        pd.DataFrame(columns=COLUMNS).to_csv(csv_path, index=False)


def log_bet(bet: dict, csv_path: str = None) -> None:
    """Append a bet to the CSV tracker."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)

    row = {col: bet.get(col, "") for col in COLUMNS}
    row.setdefault("result", "")
    row.setdefault("profit", "")

    df = pd.read_csv(csv_path)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(csv_path, index=False)


def load_bets(csv_path: str = None) -> pd.DataFrame:
    """Load all bets from CSV."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)
    return pd.read_csv(csv_path)


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
