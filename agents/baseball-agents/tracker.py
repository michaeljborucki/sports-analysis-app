"""Bet logging and P&L tracking via CSV."""
import fcntl
import logging
import os
import threading
from contextlib import contextmanager
import pandas as pd
from config import BETS_CSV, DATA_DIR


def _american_to_decimal(odds: int) -> float:
    if odds < 0:
        return 100 / abs(odds) + 1
    return odds / 100 + 1


COLUMNS = [
    "date", "game", "game_time", "bet_type", "side", "odds", "sim_prob",
    "market_prob", "edge", "kelly_pct", "result", "profit",
    "close_odds", "close_prob", "clv_cents", "clv_pct",
]

_csv_lock = threading.Lock()
_log = logging.getLogger("mirofish.tracker")


@contextmanager
def file_lock(csv_path: str):
    """Cross-process exclusive lock on a CSV via flock on a sidecar file.

    threading.Lock alone is insufficient: the pipeline logs bets while the
    grader runs as a separate process, and concurrent full-file rewrites
    tore/spliced records in bets.csv (see tests/test_tracker_concurrency.py).
    """
    lock_path = csv_path + ".lock"
    directory = os.path.dirname(lock_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def atomic_write_csv(df: pd.DataFrame, csv_path: str) -> None:
    """Write a CSV via temp file + os.replace so readers never see a
    truncated/partially-written file."""
    tmp_path = f"{csv_path}.tmp.{os.getpid()}"
    try:
        df.to_csv(tmp_path, index=False)
        os.replace(tmp_path, csv_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def compute_clv(bet_odds: int, close_odds: int) -> dict:
    """CLV in American-cents and percent of decimal value.

    clv_cents = bet_odds - close_odds (positive = beat the close on dog side)
                inverted on favorite side so positive always means we got a better price
    clv_pct = (our_decimal / close_decimal) - 1
    """
    bet_dec = _american_to_decimal(int(bet_odds))
    close_dec = _american_to_decimal(int(close_odds))
    clv_pct = round((bet_dec / close_dec) - 1.0, 4)
    # American-cents diff: positive means our price is better. For favorites
    # (negative odds), "better" is closer to 0 — so the sign flips.
    if bet_odds < 0 and close_odds < 0:
        cents = abs(close_odds) - abs(bet_odds)
    elif bet_odds > 0 and close_odds > 0:
        cents = bet_odds - close_odds
    else:
        # Mixed sign (line crossed from fav to dog or vice versa). Use decimal
        # diff scaled to ~American magnitude as a rough indicator.
        cents = int(round((bet_dec - close_dec) * 100))
    return {"clv_cents": int(cents), "clv_pct": clv_pct}


def lookup_clv(bet_row) -> dict | None:
    """Find the closing line for a bet row and compute CLV.

    Returns None if no closing line is available.
    """
    from scrapers.closing_lines import find_closing_line

    bet_type = bet_row["bet_type"]
    side = str(bet_row["side"])
    market, parsed_side, line, player_name = _parse_bet_for_clv(bet_type, side)
    if market is None:
        return None
    close = find_closing_line(
        bet_row["date"], bet_row["game"], market, parsed_side,
        line=line, player_name=player_name,
    )
    if not close:
        return None
    clv = compute_clv(int(bet_row["odds"]), int(close["close_odds"]))
    clv["close_odds"] = int(close["close_odds"])
    clv["close_prob"] = float(close["close_prob_devig"])
    return clv


PROP_BET_TYPES = {
    "pitcher_strikeouts", "pitcher_earned_runs", "pitcher_outs", "pitcher_hits_allowed",
    "batter_total_bases", "batter_rbis", "batter_hits", "batter_runs_scored",
    "batter_hits_runs_rbis", "batter_strikeouts",
}


def _parse_bet_for_clv(bet_type: str, side: str) -> tuple[str | None, str, float | None, str]:
    """Map a bet's (bet_type, side) to (closing_line_market, side, line, player_name).

    Returns (None, "", None, "") if the bet type is unsupported.
    """
    if bet_type in ("moneyline", "first_3_ml"):
        return bet_type, side.split()[0] if side else "", None, ""

    if bet_type == "first_5_ml":
        return "first_5_ml", side.split()[0] if side else "", None, ""

    if bet_type in ("total", "first_3_total", "first_5_total"):
        tokens = side.split()
        if len(tokens) >= 2:
            return bet_type, tokens[0], float(tokens[1]), ""
        return None, "", None, ""

    if bet_type in ("team_total_home", "team_total_away"):
        tokens = side.split()
        if len(tokens) >= 3:
            return bet_type, tokens[1], float(tokens[2]), ""
        return None, "", None, ""

    if bet_type in ("run_line", "first_1_rl", "first_3_rl", "first_5_rl"):
        tokens = side.split()
        if len(tokens) >= 2:
            try:
                line = float(tokens[1])
            except ValueError:
                return None, "", None, ""
            return bet_type, tokens[0], line, ""
        return None, "", None, ""

    if bet_type == "nrfi":
        return "nrfi", side, None, ""

    if bet_type in PROP_BET_TYPES:
        # side like "Player Name over 1.5" or "Player Name under 0.5"
        tokens = side.split()
        if len(tokens) < 3:
            return None, "", None, ""
        # Direction is the second-to-last "over"/"under" token; line is the last token
        direction = None
        line_val = None
        name_tokens = []
        for i, tok in enumerate(tokens):
            if tok.lower() in ("over", "under"):
                direction = tok.lower()
                if i + 1 < len(tokens):
                    try:
                        line_val = float(tokens[i + 1])
                    except ValueError:
                        line_val = None
                name_tokens = tokens[:i]
                break
        if direction is None or line_val is None or not name_tokens:
            return None, "", None, ""
        player = " ".join(name_tokens)
        return bet_type, direction, line_val, player

    return None, "", None, ""


def _ensure_csv(csv_path: str) -> None:
    directory = os.path.dirname(csv_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(csv_path):
        pd.DataFrame(columns=COLUMNS).to_csv(csv_path, index=False)


def log_bet(bet: dict, csv_path: str = None) -> bool:
    """Append a bet to the CSV tracker. Skips duplicates on date+game+bet_type+side.

    Returns True if logged, False if duplicate.
    """
    csv_path = csv_path or BETS_CSV
    row = {col: bet.get(col, "") for col in COLUMNS}
    row.setdefault("result", "")
    row.setdefault("profit", "")
    with _csv_lock, file_lock(csv_path):
        _ensure_csv(csv_path)
        df = pd.read_csv(csv_path)
        # Dedup: skip if same date+game+bet_type+side already exists
        if not df.empty:
            match = (
                (df["date"] == row["date"]) &
                (df["game"] == row["game"]) &
                (df["bet_type"] == row["bet_type"]) &
                (df["side"] == row["side"])
            )
            if match.any():
                return False
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        atomic_write_csv(df, csv_path)
        return True


def load_bets(csv_path: str = None) -> pd.DataFrame:
    """Load all bets from CSV."""
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)
    return pd.read_csv(csv_path)


def update_result(index: int, result: str, csv_path: str = None) -> None:
    """Update a bet's result (W/L/P) and calculate profit + CLV (if available)."""
    csv_path = csv_path or BETS_CSV
    with _csv_lock, file_lock(csv_path):
        df = pd.read_csv(csv_path, dtype={"result": str, "profit": float})
        df["result"] = df["result"].astype(object)
        # Ensure new CLV columns exist for backward compat
        for col in ("close_odds", "close_prob", "clv_cents", "clv_pct"):
            if col not in df.columns:
                df[col] = ""
        if index not in df.index:
            # .at with a missing label silently ENLARGES the frame, writing an
            # all-NaN orphan row (",,,,,,,,W,,,,,,,") — the bets.csv corruption
            # of 2026-06-03. Fail loudly instead.
            raise KeyError(
                f"bet index {index} not in {csv_path} ({len(df)} rows) — "
                "refusing to fabricate an orphan row"
            )
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

        try:
            clv = lookup_clv(df.loc[index])
        except Exception as e:
            _log.warning("CLV lookup failed for row %d: %s", index, e)
            clv = None
        if clv:
            df.at[index, "close_odds"] = clv["close_odds"]
            df.at[index, "close_prob"] = clv["close_prob"]
            df.at[index, "clv_cents"] = clv["clv_cents"]
            df.at[index, "clv_pct"] = clv["clv_pct"]

        atomic_write_csv(df, csv_path)


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
