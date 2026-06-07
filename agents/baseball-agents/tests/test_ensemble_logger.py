import csv
import glob
import os
import tempfile
import threading
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

def test_malformed_header_is_quarantined_and_rebuilt():
    """A file with a broken header must not compound corruption.

    Previously, log_model_prediction did read-modify-write with pandas,
    so any extra columns in the on-disk header survived every write.
    The logger must detect the bad header, move the file aside as
    .broken-<timestamp>, and start a clean file.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "preds.csv")
        with open(path, "w", newline="") as f:
            f.write("Unnamed: 0,Unnamed: 1,date,game,model,bet_type,side,sim_prob,market_prob,edge,temperature,run_index\n")
            f.write(",,2026-04-14,NYY@BOS,kimi,moneyline,home,0.58,0.52,0.06,0.7,1\n")

        log_model_prediction(
            date="2026-04-14", game="TB@CWS", model="claude",
            bet_type="total", side="over", sim_prob=0.55,
            market_prob=0.5, edge=0.05, temperature=0.7, run_index=1,
            csv_path=path,
        )

        with open(path, newline="") as f:
            header = next(csv.reader(f))
        assert header == PREDICTION_COLUMNS

        quarantined = glob.glob(path + ".broken-*")
        assert len(quarantined) == 1, f"expected one quarantined file, got {quarantined}"

        df = pd.read_csv(path)
        assert len(df) == 1
        assert df.iloc[0]["game"] == "TB@CWS"

def test_schema_cannot_grow_across_many_appends():
    """Repeated appends must never add columns to the file.

    This is the invariant the old read-modify-write implementation
    violated in production (row count stayed sane but column count
    ballooned to 70).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "preds.csv")
        for i in range(25):
            log_model_prediction(
                date="2026-04-14", game="NYY@BOS", model="kimi",
                bet_type="moneyline", side="home", sim_prob=0.58,
                market_prob=0.52, edge=0.06, temperature=0.7, run_index=i,
                csv_path=path,
            )
        with open(path, newline="") as f:
            rows = list(csv.reader(f))
        assert rows[0] == PREDICTION_COLUMNS
        assert all(len(r) == len(PREDICTION_COLUMNS) for r in rows), \
            "some row has wrong column count"
        assert len(rows) == 26

def test_concurrent_appends_do_not_corrupt():
    """The thread lock must serialize writes from parallel game workers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "preds.csv")

        def worker(idx):
            log_model_prediction(
                date="2026-04-14", game="NYY@BOS", model="kimi",
                bet_type="moneyline", side="home", sim_prob=0.58,
                market_prob=0.52, edge=0.06, temperature=0.7, run_index=idx,
                csv_path=path,
            )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads: t.start()
        for t in threads: t.join()

        with open(path, newline="") as f:
            rows = list(csv.reader(f))
        assert rows[0] == PREDICTION_COLUMNS
        assert len(rows) == 21
        assert all(len(r) == len(PREDICTION_COLUMNS) for r in rows)
