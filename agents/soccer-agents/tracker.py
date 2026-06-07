"""Bet logging and P&L tracking via CSV.

Thread-safe (parallel screening/simulation writes log_bet concurrently).
Dedups on (date, game, bet_type, side) so re-runs of the pipeline don't
double-count picks. CLV is recorded when results are graded — it looks up
the matching row in closing_lines.csv, not bets.csv.
"""
import logging
import os
import threading
import pandas as pd

from config import BETS_CSV, DATA_DIR

COLUMNS = [
    "date", "game", "league", "bet_type", "side", "odds", "sim_prob",
    "market_prob", "close_market_prob", "clv",
    "edge", "kelly_pct", "result", "profit",
]

_csv_lock = threading.Lock()
logger = logging.getLogger("mirofish.tracker")


def _migrate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add any missing CLV/league columns to legacy CSVs in-place."""
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[COLUMNS]


def _ensure_csv(csv_path: str) -> None:
    directory = os.path.dirname(csv_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(csv_path):
        pd.DataFrame(columns=COLUMNS).to_csv(csv_path, index=False)


def log_bet(bet: dict, csv_path: str = None) -> bool:
    """Append a bet to the CSV tracker. Returns False on duplicate.

    Dedup key: (date, game, bet_type, side). Side includes the line for AH/total
    so different handicaps/lines are treated as distinct bets.
    """
    csv_path = csv_path or BETS_CSV
    row = {col: bet.get(col, "") for col in COLUMNS}
    row.setdefault("result", "")
    row.setdefault("profit", "")

    with _csv_lock:
        _ensure_csv(csv_path)
        df = pd.read_csv(csv_path)
        df = _migrate_columns(df)
        if not df.empty:
            dup = (
                (df["date"].astype(str) == str(row["date"]))
                & (df["game"].astype(str) == str(row["game"]))
                & (df["bet_type"].astype(str) == str(row["bet_type"]))
                & (df["side"].astype(str) == str(row["side"]))
            )
            if dup.any():
                logger.info("Skipping duplicate bet: %s | %s %s",
                            row["game"], row["bet_type"], row["side"])
                return False
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(csv_path, index=False)
        return True


def load_bets(csv_path: str = None) -> pd.DataFrame:
    """Load all bets from CSV."""
    csv_path = csv_path or BETS_CSV
    with _csv_lock:
        _ensure_csv(csv_path)
        df = pd.read_csv(csv_path)
    return _migrate_columns(df)


def update_close_prob(index: int, close_prob: float, csv_path: str = None) -> None:
    """Record closing market probability for a pending bet + compute CLV.

    Legacy path used by `agents.clv_snapshotter`. The preferred flow is
    `update_result` auto-looking up CLV from closing_lines.csv.
    """
    csv_path = csv_path or BETS_CSV
    with _csv_lock:
        df = pd.read_csv(csv_path)
        df = _migrate_columns(df)
        df.at[index, "close_market_prob"] = round(float(close_prob), 4)
        try:
            bet_prob = float(df.at[index, "market_prob"])
            df.at[index, "clv"] = round(float(close_prob) - bet_prob, 4)
        except (ValueError, TypeError):
            pass
        df.to_csv(csv_path, index=False)


def _lookup_clv_from_closing_lines(row) -> float | None:
    """Find the matching closing_lines.csv row and return CLV in prob terms.

    Returns close_market_prob - market_prob (positive = line moved toward our side).
    Returns None when no match exists or inputs are invalid.
    """
    try:
        from scrapers.closing_lines import find_closing_line
    except Exception:
        return None

    try:
        bet_prob = float(row.get("market_prob", ""))
    except (TypeError, ValueError):
        return None

    close = find_closing_line(
        game_date=str(row.get("date", "")),
        game=str(row.get("game", "")),
        bet_type=str(row.get("bet_type", "")),
        side=str(row.get("side", "")),
    )
    if not close:
        return None
    return float(close["close_prob_devig"]) - bet_prob, float(close["close_prob_devig"])


def update_result(index: int, result: str, csv_path: str = None) -> None:
    """Update a bet's result (W/L/P) + profit. Auto-fills CLV if a matching
    closing-lines capture exists for this bet.
    """
    csv_path = csv_path or BETS_CSV
    with _csv_lock:
        df = pd.read_csv(csv_path, dtype={"result": str, "profit": float})
        df["result"] = df["result"].astype(object)
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = ""
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

        # Auto-fill CLV from closing_lines.csv when available.
        try:
            maybe = _lookup_clv_from_closing_lines(df.loc[index])
        except Exception as e:
            logger.warning("CLV lookup failed for row %d: %s", index, e)
            maybe = None
        if maybe:
            clv_val, close_prob = maybe
            df.at[index, "clv"] = round(clv_val, 4)
            df.at[index, "close_market_prob"] = round(close_prob, 4)

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

    clv_rows = df[pd.to_numeric(df["clv"], errors="coerce").notna()]
    avg_clv = round(float(pd.to_numeric(clv_rows["clv"]).mean()), 4) if len(clv_rows) else None
    beat_close_pct = (
        round(float((pd.to_numeric(clv_rows["clv"]) > 0).mean()), 3) if len(clv_rows) else None
    )

    return {
        "total_bets": len(df),
        "settled": len(settled),
        "pending": len(df) - len(settled),
        "record": f"{wins}-{losses}-{pushes}",
        "win_rate": round(wins / max(len(settled), 1), 3),
        "profit": round(float(profit), 2),
        "roi": round(float(profit) / max(len(settled), 1) * 100, 1),
        "clv_samples": len(clv_rows),
        "avg_clv": avg_clv,
        "beat_close_pct": beat_close_pct,
    }
