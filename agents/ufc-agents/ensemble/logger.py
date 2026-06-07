"""Per-model prediction logging to CSV."""
import os
import pandas as pd
from config import MODEL_PREDICTIONS_CSV

PREDICTION_COLUMNS = [
    "date", "game", "model", "bet_type", "side",
    "sim_prob", "market_prob", "edge", "temperature", "run_index",
]

def _ensure_csv(path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    if not os.path.exists(path):
        pd.DataFrame(columns=PREDICTION_COLUMNS).to_csv(path, index=False)

def log_model_prediction(
    date: str, game: str, model: str, bet_type: str, side: str,
    sim_prob: float, market_prob: float, edge: float,
    temperature: float, run_index: int, csv_path: str = None,
) -> None:
    csv_path = csv_path or MODEL_PREDICTIONS_CSV
    _ensure_csv(csv_path)
    row = {
        "date": date, "game": game, "model": model,
        "bet_type": bet_type, "side": side,
        "sim_prob": round(sim_prob, 4), "market_prob": round(market_prob, 4),
        "edge": round(edge, 4), "temperature": temperature,
        "run_index": run_index,
    }
    df = pd.read_csv(csv_path)
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(csv_path, index=False)

def load_model_predictions(csv_path: str = None) -> pd.DataFrame:
    csv_path = csv_path or MODEL_PREDICTIONS_CSV
    _ensure_csv(csv_path)
    return pd.read_csv(csv_path)
