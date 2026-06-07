import os, tempfile
import pandas as pd
from ensemble.logger import log_model_prediction, load_model_predictions, PREDICTION_COLUMNS

def test_log_creates_csv_if_missing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "preds.csv")
        log_model_prediction(
            date="2026-03-28", game="NYY@BOS", model="kimi",
            bet_type="moneyline", side="home", sim_prob=0.58,
            market_prob=0.52, edge=0.06, temperature=0.7, run_index=1,
            csv_path=path,
        )
        assert os.path.exists(path)
        df = pd.read_csv(path)
        assert len(df) == 1
        assert df.iloc[0]["model"] == "kimi"

def test_log_appends_to_existing():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "preds.csv")
        for i in range(3):
            log_model_prediction(
                date="2026-03-28", game="NYY@BOS", model="kimi",
                bet_type="moneyline", side="home", sim_prob=0.58,
                market_prob=0.52, edge=0.06, temperature=0.7, run_index=i,
                csv_path=path,
            )
        df = pd.read_csv(path)
        assert len(df) == 3

def test_load_predictions_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "preds.csv")
        df = load_model_predictions(path)
        assert len(df) == 0
        assert list(df.columns) == PREDICTION_COLUMNS
