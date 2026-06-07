"""Per-model prediction logging to CSV."""
import csv
import logging
import os
import threading
from datetime import datetime
import pandas as pd
from config import MODEL_PREDICTIONS_CSV

log = logging.getLogger(__name__)

_log_lock = threading.Lock()

PREDICTION_COLUMNS = [
    "date", "game", "model", "bet_type", "side",
    "sim_prob", "market_prob", "edge", "temperature", "run_index",
]

def _read_header(path: str):
    with open(path, newline="") as f:
        reader = csv.reader(f)
        try:
            return next(reader)
        except StopIteration:
            return None

def _write_header(path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", newline="") as f:
        csv.writer(f).writerow(PREDICTION_COLUMNS)

def _ensure_valid_csv(path: str) -> None:
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        _write_header(path)
        return
    header = _read_header(path)
    if header == PREDICTION_COLUMNS:
        return
    # Quarantine: preserve the bad file for forensics, start fresh.
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    broken = f"{path}.broken-{ts}"
    os.rename(path, broken)
    log.warning("model_predictions CSV had bad header; quarantined to %s", broken)
    _write_header(path)

def log_model_prediction(
    date: str, game: str, model: str, bet_type: str, side: str,
    sim_prob: float, market_prob: float, edge: float,
    temperature: float, run_index: int, csv_path: str = None,
) -> None:
    csv_path = csv_path or MODEL_PREDICTIONS_CSV
    row = {
        "date": date, "game": game, "model": model,
        "bet_type": bet_type, "side": side,
        "sim_prob": round(sim_prob, 4), "market_prob": round(market_prob, 4),
        "edge": round(edge, 4), "temperature": temperature,
        "run_index": run_index,
    }
    with _log_lock:
        _ensure_valid_csv(csv_path)
        with open(csv_path, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=PREDICTION_COLUMNS).writerow(row)

def load_model_predictions(csv_path: str = None) -> pd.DataFrame:
    csv_path = csv_path or MODEL_PREDICTIONS_CSV
    with _log_lock:
        _ensure_valid_csv(csv_path)
    return pd.read_csv(csv_path)
