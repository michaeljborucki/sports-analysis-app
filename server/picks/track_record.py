from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path


def compute_30d_record(csv_path: Path, reference_date: date | None = None) -> dict:
    ref = reference_date or date.today()
    window_start = ref - timedelta(days=30)

    wins = losses = pushes = 0
    units = 0.0

    if not csv_path.exists():
        return {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0, "label": "0-0 (+0.0u)"}

    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                d = date.fromisoformat(row["date"])
            except (KeyError, ValueError):
                continue
            if d < window_start or d > ref:
                continue
            result = (row.get("result") or "").strip().upper()
            try:
                profit = float(row.get("profit") or 0)
            except ValueError:
                profit = 0.0
            if result == "W":
                wins += 1
                units += profit
            elif result == "L":
                losses += 1
                units += profit
            elif result == "P":
                pushes += 1

    sign = "+" if units >= 0 else ""
    label = f"{wins}-{losses} ({sign}{units:.1f}u)"
    return {
        "wins": wins, "losses": losses, "pushes": pushes,
        "units": round(units, 2), "label": label,
    }
