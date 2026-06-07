"""Bet logging and P&L tracking via CSV."""
import os
import pandas as pd
from config import BETS_CSV, DATA_DIR

COLUMNS = [
    "date", "start_time", "game", "bet_type", "side", "odds",
    "sim_prob", "sim_prob_raw", "market_prob",
    "edge", "kelly_pct", "result", "profit",
    "close_odds", "close_prob", "clv_cents", "clv_pct",
    # Empty for primary edge bets, "individual_conviction" for Option B
    # fallbacks. Lets CLV analysis compare per-source win rates later.
    "source",
]
CLV_COLUMNS = ("close_odds", "close_prob", "clv_cents", "clv_pct")


def _ensure_csv(csv_path: str) -> None:
    directory = os.path.dirname(csv_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(csv_path):
        pd.DataFrame(columns=COLUMNS).to_csv(csv_path, index=False)
        return
    # Migrate legacy files lacking any current column (CLV, calibration raw, etc.).
    df = pd.read_csv(csv_path)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        for c in missing:
            df[c] = ""
        df.to_csv(csv_path, index=False)


def lookup_clv(bet: dict) -> dict | None:
    """Look up the closing line for a bet and compute CLV. Returns None if no close found."""
    from scrapers.closing_lines import find_closing_line
    from scrapers.odds import compute_clv

    line_val: float | str | None = None
    bet_type = str(bet.get("bet_type", ""))
    side = str(bet.get("side", ""))
    if bet_type == "game_handicap":
        tokens = side.split()
        if len(tokens) >= 2:
            side = tokens[0]
            try:
                line_val = float(tokens[1])
            except ValueError:
                line_val = None
    elif bet_type == "total_games":
        tokens = side.split()
        if len(tokens) >= 2:
            side = tokens[0]
            try:
                line_val = float(tokens[1])
            except ValueError:
                line_val = None

    close = find_closing_line(
        game_date=str(bet.get("date", "")),
        game=str(bet.get("game", "")),
        market=bet_type,
        side=side,
        line=line_val,
    )
    if not close:
        return None
    try:
        bet_odds = int(bet.get("odds"))
        close_odds = int(close["close_odds"])
    except (TypeError, ValueError):
        return None
    clv = compute_clv(bet_odds, close_odds)
    return {
        "close_odds": close_odds,
        "close_prob": float(close.get("close_prob_devig", 0)),
        "clv_cents": clv["clv_cents"],
        "clv_pct": clv["clv_pct"],
    }


def log_bet(bet: dict, csv_path: str = None) -> None:
    """Upsert a bet into the CSV tracker, keyed by (date, game, bet_type, side).

    If an unsettled row with the same key exists, it is overwritten. If a settled row
    exists, the new bet is skipped to preserve graded history.
    """
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)

    row = {col: bet.get(col, "") for col in COLUMNS}
    row.setdefault("result", "")
    row.setdefault("profit", "")

    df = pd.read_csv(csv_path)
    if not df.empty:
        match = (
            (df["date"].astype(str) == str(row["date"]))
            & (df["game"].astype(str) == str(row["game"]))
            & (df["bet_type"].astype(str) == str(row["bet_type"]))
            & (df["side"].astype(str) == str(row["side"]))
        )
        if match.any():
            if df.loc[match, "result"].isin(["W", "L", "P"]).any():
                return
            df = df[~match]

    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(csv_path, index=False)


def load_bets(csv_path: str = None) -> pd.DataFrame:
    """Load all bets from CSV."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)
    return pd.read_csv(csv_path)


def _stake_units(odds: float) -> float:
    """Units risked per bet: favorites risk |odds|/100 to win 1, dogs risk 1 to win odds/100."""
    return abs(odds) / 100 if odds < 0 else 1.0


def _profit_units(odds: float, result: str) -> float:
    if result == "P":
        return 0.0
    if result == "W":
        return 1.0 if odds < 0 else odds / 100
    return -(abs(odds) / 100) if odds < 0 else -1.0


def update_result(index: int, result: str, csv_path: str = None) -> None:
    """Update a bet's result (W/L/P) and calculate profit; back-apply CLV if a close exists."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)
    df = pd.read_csv(csv_path, dtype={"result": str, "profit": float})
    df["result"] = df["result"].astype(object)
    df.at[index, "result"] = result
    df.at[index, "profit"] = round(_profit_units(df.at[index, "odds"], result), 2)

    for col in CLV_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    try:
        bet_row = df.iloc[index].to_dict()
        clv = lookup_clv(bet_row)
    except Exception:
        clv = None
    if clv:
        df.at[index, "close_odds"] = clv["close_odds"]
        df.at[index, "close_prob"] = clv["close_prob"]
        df.at[index, "clv_cents"] = clv["clv_cents"]
        df.at[index, "clv_pct"] = clv["clv_pct"]

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
    staked = sum(_stake_units(o) for o in settled["odds"]) if not settled.empty else 0

    return {
        "total_bets": len(df),
        "settled": len(settled),
        "pending": len(df) - len(settled),
        "record": f"{wins}-{losses}-{pushes}",
        "win_rate": round(wins / max(len(settled), 1), 3),
        "profit": round(float(profit), 2),
        "roi": round(float(profit) / max(staked, 1e-9) * 100, 1),
    }
