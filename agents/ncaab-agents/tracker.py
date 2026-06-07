"""Bet logging and P&L tracking via CSV."""
import os
import pandas as pd
from config import BETS_CSV, PREDICTIONS_CSV, DATA_DIR

COLUMNS = [
    "date", "game", "bet_type", "side", "odds", "sim_prob",
    "edge", "kelly_pct", "predicted_score", "result", "profit",
]

PRED_COLUMNS = [
    "date", "game", "game_time", "bet_type", "side", "odds",
    "sim_prob", "market_prob", "edge", "kelly_pct", "predicted_score",
    "has_edge", "challenger_flag", "challenger_reason", "result", "profit",
]


def _ensure_csv_with_columns(csv_path: str, columns: list) -> None:
    directory = os.path.dirname(csv_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        pd.DataFrame(columns=columns).to_csv(csv_path, index=False)


def _ensure_csv(csv_path: str) -> None:
    _ensure_csv_with_columns(csv_path, COLUMNS)


def log_bet(bet: dict, csv_path: str = None) -> None:
    """Append a bet to the CSV tracker. Skips duplicates (same date/game/bet_type/side)."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)

    row = {col: bet.get(col, "") for col in COLUMNS}
    row.setdefault("result", "")
    row.setdefault("profit", "")

    df = pd.read_csv(csv_path)

    # Dedup: skip if same date/game/bet_type/side already exists
    dup_keys = ["date", "game", "bet_type", "side"]
    if not df.empty:
        match = df
        for k in dup_keys:
            match = match[match[k].astype(str) == str(row[k])]
        if not match.empty:
            return

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(csv_path, index=False)


def log_prediction(pred: dict, csv_path: str = None) -> None:
    """Append a full prediction (all bet types) to the predictions CSV."""
    csv_path = csv_path or PREDICTIONS_CSV
    _ensure_csv_with_columns(csv_path, PRED_COLUMNS)

    row = {col: pred.get(col, "") for col in PRED_COLUMNS}

    df = pd.read_csv(csv_path)
    # Dedup: same date/game/bet_type
    dup_keys = ["date", "game", "bet_type"]
    if not df.empty:
        match = df
        for k in dup_keys:
            match = match[match[k].astype(str) == str(row[k])]
        if not match.empty:
            return

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(csv_path, index=False)


def load_predictions(csv_path: str = None) -> pd.DataFrame:
    """Load all predictions from CSV."""
    csv_path = csv_path or PREDICTIONS_CSV
    _ensure_csv_with_columns(csv_path, PRED_COLUMNS)
    try:
        return pd.read_csv(csv_path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=PRED_COLUMNS)


def update_prediction_result(index: int, result: str, csv_path: str = None) -> None:
    """Update a prediction's result (W/L/P) and calculate profit."""
    csv_path = csv_path or PREDICTIONS_CSV
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


def load_bets(csv_path: str = None) -> pd.DataFrame:
    """Load all bets from CSV."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)
    try:
        return pd.read_csv(csv_path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=COLUMNS)


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
