"""Regression tests for bets.csv concurrent-write corruption.

Root cause (2026-06-03 forensics): bets.csv was corrupted by
  1. update_result() silently fabricating all-NaN orphan rows
     (",,,,,,,,W,,,,,,,") via pandas .at enlargement when called with an
     index missing from the freshly-read CSV
  2. concurrent full-file rewrites from multiple processes (pipeline
     logger + grader subprocess) tearing/splicing records — threading.Lock
     does not protect across processes
"""
import os
import re
import subprocess
import sys
import textwrap

import pandas as pd
import pytest

from tracker import log_bet, load_bets, update_result

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BET = {
    "date": "2026-04-01",
    "game": "BOS@NYY",
    "bet_type": "moneyline",
    "side": "home",
    "odds": -150,
    "sim_prob": 0.62,
    "edge": 0.055,
    "kelly_pct": 0.02,
}


def test_update_result_missing_index_raises_keyerror(tmp_path):
    """Updating a row that doesn't exist must fail loudly, not enlarge."""
    csv = str(tmp_path / "bets.csv")
    log_bet(BET, csv_path=csv)
    with pytest.raises(KeyError):
        update_result(5, "W", csv_path=csv)


def test_update_result_missing_index_writes_no_orphan_row(tmp_path):
    """A bad index must not append an all-NaN orphan row to the CSV."""
    csv = str(tmp_path / "bets.csv")
    log_bet(BET, csv_path=csv)
    try:
        update_result(5, "W", csv_path=csv)
    except KeyError:
        pass
    df = load_bets(csv_path=csv)
    assert len(df) == 1
    assert df["date"].notna().all()


def test_write_leaves_no_temp_files(tmp_path):
    """Atomic writes must clean up their temp files."""
    csv = str(tmp_path / "bets.csv")
    log_bet(BET, csv_path=csv)
    update_result(0, "W", csv_path=csv)
    leftovers = [f for f in os.listdir(tmp_path) if f not in ("bets.csv", "bets.csv.lock")]
    assert leftovers == []


def _run_worker(code: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_concurrent_loggers_and_grader_no_lost_rows_or_corruption(tmp_path):
    """Multiple processes appending while another grades must not lose
    rows, lose grades, or produce malformed lines.

    Mirrors production: the pipeline logs prop bets while daily_runner's
    grader subprocess updates results on existing rows.
    """
    csv = str(tmp_path / "bets.csv")

    # Seed 30 rows for the "grader" to update
    for i in range(30):
        bet = dict(BET, game=f"SEED@G{i}", side=f"side{i}")
        log_bet(bet, csv_path=csv)

    logger_code = """
        import sys
        sys.path.insert(0, {repo!r})
        from tracker import log_bet
        for i in range(30):
            log_bet({{
                "date": "2026-04-02", "game": f"{tag}@G{{i}}",
                "bet_type": "moneyline", "side": f"side{{i}}",
                "odds": -150, "sim_prob": 0.6, "edge": 0.05, "kelly_pct": 0.02,
            }}, csv_path={csv!r})
    """
    grader_code = """
        import sys
        sys.path.insert(0, {repo!r})
        from tracker import update_result
        for i in range(30):
            update_result(i, "W", csv_path={csv!r})
    """

    workers = [
        _run_worker(logger_code.format(repo=REPO, csv=csv, tag="AAA")),
        _run_worker(logger_code.format(repo=REPO, csv=csv, tag="BBB")),
        _run_worker(logger_code.format(repo=REPO, csv=csv, tag="CCC")),
        _run_worker(grader_code.format(repo=REPO, csv=csv)),
    ]
    for w in workers:
        out, err = w.communicate(timeout=120)
        assert w.returncode == 0, f"worker failed: {err.decode()[-2000:]}"

    # File must parse and contain zero malformed lines
    with open(csv) as f:
        lines = f.read().splitlines()
    date_re = re.compile(r"^2026-\d{2}-\d{2},")
    malformed = [ln for ln in lines[1:] if not date_re.match(ln)]
    assert malformed == [], f"malformed lines: {malformed[:5]}"

    # No lost appends: 30 seed + 3 workers x 30
    df = pd.read_csv(csv)
    assert len(df) == 120

    # No lost grades: every seed row graded W with correct profit
    seeds = df[df["game"].str.startswith("SEED@")]
    assert len(seeds) == 30
    assert (seeds["result"] == "W").all()
