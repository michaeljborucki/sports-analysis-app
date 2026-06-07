"""Capture and look up consensus closing lines for CLV tracking.

Ported from baseball-agents, adapted for soccer markets:
  - asian_handicap (home/away points)
  - total (over/under line)
  - btts (yes/no)

Captures are deterministic — only fetches odds and applies the existing
power-method devig. No LLM calls. Default window is T-15 to T-5 minutes
before kickoff; `force=True` bypasses the window for backfills.

CSV: data/closing_lines.csv with one row per
(date, game, bet_type, side, line).
"""
from __future__ import annotations
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from config import DATA_DIR, ACTIVE_LEAGUES
from scrapers.odds import (
    OddsData,
    american_to_implied_prob,
    power_devig,
    get_soccer_odds,
)

logger = logging.getLogger("mirofish.closing_lines")

CLOSING_LINES_CSV = os.path.join(DATA_DIR, "closing_lines.csv")
COLUMNS = [
    "date", "game", "league", "bet_type", "side", "line",
    "close_odds", "close_prob_devig", "captured_at",
]
_csv_lock = threading.Lock()

CAPTURE_WINDOW_MINUTES = (5, 15)  # capture if kickoff is between T-5 and T-15


def _ensure_csv() -> None:
    os.makedirs(os.path.dirname(CLOSING_LINES_CSV), exist_ok=True)
    if not os.path.exists(CLOSING_LINES_CSV):
        pd.DataFrame(columns=COLUMNS).to_csv(CLOSING_LINES_CSV, index=False)


def _two_sided_devig(odds_a: int, odds_b: int) -> tuple[float, float]:
    raw_a = american_to_implied_prob(odds_a)
    raw_b = american_to_implied_prob(odds_b)
    return power_devig(raw_a, raw_b)


def _rows_from_two_sided(bet_type: str, side_a: str, side_b: str,
                         odds_a: int, odds_b: int,
                         line_a: float | str = "", line_b: float | str = "") -> list[dict]:
    """Emit two CLV rows (both sides) for any two-sided soccer market."""
    p_a, p_b = _two_sided_devig(int(odds_a), int(odds_b))
    return [
        {"bet_type": bet_type, "side": side_a, "line": line_a,
         "close_odds": int(odds_a), "close_prob_devig": round(p_a, 6)},
        {"bet_type": bet_type, "side": side_b, "line": line_b,
         "close_odds": int(odds_b), "close_prob_devig": round(p_b, 6)},
    ]


def extract_closing_rows(odds: OddsData) -> list[dict]:
    """Convert an OddsData snapshot into a list of per-side CLV rows.

    Side strings are composed to match bets.csv `side` fields so lookups work
    without extra parsing:
      - asian_handicap:  "home -0.5" / "away +0.5"
      - total:           "over 2.5" / "under 2.5"
      - btts:            "yes" / "no"
    """
    rows: list[dict] = []

    ah = odds.asian_handicap or {}
    if "home_odds" in ah and "away_odds" in ah:
        home_pt = ah.get("home", -0.5)
        away_pt = ah.get("away", 0.5)
        rows += _rows_from_two_sided(
            "asian_handicap",
            f"home {home_pt}", f"away {away_pt}",
            ah["home_odds"], ah["away_odds"],
            line_a=home_pt, line_b=away_pt,
        )

    tot = odds.total or {}
    if "over_odds" in tot and "under_odds" in tot and "line" in tot:
        line = tot["line"]
        rows += _rows_from_two_sided(
            "total",
            f"over {line}", f"under {line}",
            tot["over_odds"], tot["under_odds"],
            line_a=line, line_b=line,
        )

    btts = odds.btts or {}
    if "yes_odds" in btts and "no_odds" in btts:
        rows += _rows_from_two_sided(
            "btts", "yes", "no",
            btts["yes_odds"], btts["no_odds"],
        )

    return rows


def _normalize_line(value) -> str:
    if value is None or value == "":
        return ""
    s = str(value)
    if s.lower() == "nan":
        return ""
    return s


def _existing_capture_keys(game_date: str) -> set[tuple[str, str, str, str]]:
    """Dedup: what (game, bet_type, side, line) rows already exist for this date."""
    if not os.path.exists(CLOSING_LINES_CSV):
        return set()
    df = pd.read_csv(CLOSING_LINES_CSV, dtype={"line": str}, keep_default_na=False)
    if df.empty:
        return set()
    today = df[df["date"] == game_date]
    return {
        (str(r["game"]), str(r["bet_type"]), str(r["side"]), _normalize_line(r["line"]))
        for _, r in today.iterrows()
    }


def capture_closing_lines(game_date: str | None = None,
                          now_utc: datetime | None = None,
                          force: bool = False,
                          leagues: list[str] | None = None) -> dict:
    """Snapshot consensus closing lines for in-window matches.

    A match is in-window if kickoff is between T-5 and T-15 from `now_utc`.
    Set `force=True` to bypass the window (manual/backfill).

    Returns {captured_games, captured_rows, skipped_games}.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    if game_date is None:
        game_date = now_utc.date().isoformat()
    leagues = leagues or ACTIVE_LEAGUES

    all_odds: list[tuple[str, OddsData]] = []
    for lg in leagues:
        try:
            for o in get_soccer_odds(league=lg) or []:
                all_odds.append((lg, o))
        except Exception as e:
            logger.error("close-capture: fetch failed for %s: %s", lg, e)

    in_window: list[tuple[str, OddsData]] = []
    skipped = 0
    for lg, o in all_odds:
        if not o.commence_time:
            continue
        try:
            ct = datetime.fromisoformat(o.commence_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        delta_min = (ct - now_utc).total_seconds() / 60.0
        if force or (CAPTURE_WINDOW_MINUTES[0] <= delta_min <= CAPTURE_WINDOW_MINUTES[1]):
            in_window.append((lg, o))
        else:
            skipped += 1

    if not in_window:
        logger.info("close-capture: no matches in window (skipped %d)", skipped)
        return {"captured_games": 0, "captured_rows": 0, "skipped_games": skipped}

    existing = _existing_capture_keys(game_date)
    captured_at = now_utc.isoformat()
    new_rows = []
    captured_games = 0

    for lg, o in in_window:
        game_key = f"{o.away}@{o.home}"
        rows = extract_closing_rows(o)
        rows_added = 0
        for r in rows:
            ek = (game_key, r["bet_type"], r["side"], _normalize_line(r.get("line", "")))
            if ek in existing:
                continue
            new_rows.append({
                "date": game_date,
                "game": game_key,
                "league": lg,
                "bet_type": r["bet_type"],
                "side": r["side"],
                "line": r.get("line", ""),
                "close_odds": r["close_odds"],
                "close_prob_devig": r["close_prob_devig"],
                "captured_at": captured_at,
            })
            existing.add(ek)
            rows_added += 1
        if rows_added:
            captured_games += 1
            logger.info("close-capture: %s → %d new rows", game_key, rows_added)

    if new_rows:
        with _csv_lock:
            _ensure_csv()
            df = pd.read_csv(CLOSING_LINES_CSV)
            df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
            df.to_csv(CLOSING_LINES_CSV, index=False)

    return {
        "captured_games": captured_games,
        "captured_rows": len(new_rows),
        "skipped_games": skipped,
    }


def load_closing_lines(game_date: str | None = None) -> pd.DataFrame:
    if not os.path.exists(CLOSING_LINES_CSV):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(CLOSING_LINES_CSV)
    if game_date is not None:
        df = df[df["date"] == game_date]
    return df


def find_closing_line(game_date: str, game: str, bet_type: str,
                      side: str, line: float | None = None) -> dict | None:
    """Return the matching closing-line row for this bet, or None.

    Matches exactly on (date, game, bet_type, side). `line` is optional —
    for AH/total we recommend not passing it since `side` already contains
    the line ("over 2.5").

    If multiple captures exist (e.g., per-league backfill + window capture),
    returns the latest by captured_at.
    """
    df = load_closing_lines(game_date)
    if df.empty:
        return None
    mask = (
        (df["game"] == game)
        & (df["bet_type"] == bet_type)
        & (df["side"].astype(str) == str(side))
    )
    if line is not None:
        mask &= (df["line"].astype(str) == str(line))
    matches = df[mask]
    if matches.empty:
        return None
    matches = matches.sort_values("captured_at")
    return matches.iloc[-1].to_dict()
