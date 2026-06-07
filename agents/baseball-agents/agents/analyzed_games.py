"""Track which games have been screened by the daily pipeline on which date.

This state file prevents the auto-analyzer from redoing games that were already
processed, and lets the scheduler decide when to re-run to catch late-lineup
games.

A game is "analyzed" if the pipeline reached Step 5 (screening) for it —
regardless of whether it produced bets, hit a no-odds block, or screened-out.
Games skipped for missing lineup are NOT recorded, so they'll be retried.

CSV: data/analyzed_games.csv with columns: date, game, status, analyzed_at.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

from config import DATA_DIR

_CSV = os.path.join(DATA_DIR, "analyzed_games.csv")
_COLUMNS = ["date", "game", "status", "analyzed_at"]
_lock = threading.Lock()

AnalyzedStatus = Literal["flagged", "no_edge", "no_odds", "screen_error", "screen_timeout"]


def _ensure_csv() -> None:
    if not os.path.exists(_CSV):
        os.makedirs(os.path.dirname(_CSV), exist_ok=True)
        pd.DataFrame(columns=_COLUMNS).to_csv(_CSV, index=False)


def load_analyzed(game_date: str) -> dict[str, str]:
    """Return {game_key: status} for all games analyzed on this date."""
    _ensure_csv()
    df = pd.read_csv(_CSV)
    if df.empty:
        return {}
    day = df[df["date"] == game_date]
    if day.empty:
        return {}
    # Keep latest status per game
    day = day.sort_values("analyzed_at").drop_duplicates(subset=["game"], keep="last")
    return dict(zip(day["game"], day["status"]))


def mark_analyzed(game_date: str, game: str, status: AnalyzedStatus) -> None:
    """Record that `game` on `game_date` was processed with the given outcome."""
    row = {
        "date": game_date,
        "game": game,
        "status": status,
        "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with _lock:
        _ensure_csv()
        df = pd.read_csv(_CSV)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(_CSV, index=False)
