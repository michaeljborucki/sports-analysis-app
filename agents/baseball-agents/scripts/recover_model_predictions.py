"""One-shot recovery for the corrupted model_predictions.csv.

Both the live file (70-col shifted schema, plus merged/truncated rows)
and the .bak file (mostly clean, but ~147 rows merged by the same
concurrent-write bug) need the same treatment: scan each line, extract
every contiguous 10-field window that validates as a real prediction
row, then dedupe.

Run: PYTHONPATH=. python3 scripts/recover_model_predictions.py
"""
import csv
import re
from pathlib import Path

from ensemble.logger import PREDICTION_COLUMNS

ROOT = Path(__file__).resolve().parent.parent
BACKUP = ROOT / "data" / "model_predictions.csv.bak"
OUTPUT = ROOT / "data" / "model_predictions.csv"

# Prefer the most recent quarantined copy so a re-run never re-ingests
# an already-cleaned file.
_broken = sorted((ROOT / "data").glob("model_predictions.csv.broken-*"))
CORRUPT = _broken[-1] if _broken else OUTPUT

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def extract_payloads(row):
    """Yield every contiguous 10-field window of non-empty values."""
    i, n = 0, len(row)
    while i <= n - 10:
        window = row[i:i + 10]
        if all(v != "" for v in window):
            yield list(window)
            i += 10
        else:
            i += 1


def looks_like_data(p):
    """Valid row: date at [0], game non-empty at [1], numerics at [5:10].

    The numeric check is what rejects merged-line windows, because a
    merged window's position 5 lands on a bet_type string like
    'first_5_ml' rather than a sim_prob float.
    """
    if len(p) != 10 or not DATE_RE.match(p[0]) or not p[1]:
        return False
    try:
        for v in p[5:10]:
            float(v)
    except ValueError:
        return False
    return True


def process_file(path, patch_date_prefix=False):
    rows, patched, dropped = [], 0, 0
    with path.open(newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for lineno, raw in enumerate(reader, start=2):
            got = False
            for p in extract_payloads(raw):
                if patch_date_prefix and p[0] == "026-04-14":
                    p[0] = "2026-04-14"
                    patched += 1
                if looks_like_data(p):
                    rows.append(p)
                    got = True
            if not got:
                dropped += 1
                preview = ",".join(v for v in raw if v != "")[:110]
                print(f"  {path.name} line {lineno} unrecoverable: {preview}")
    return rows, patched, dropped


def recover():
    print(f"=== processing backup: {BACKUP.name} ===")
    backup_rows, _, b_drop = process_file(BACKUP)
    print(f"=== processing corrupt: {CORRUPT.name} ===")
    corrupt_rows, patched, c_drop = process_file(CORRUPT, patch_date_prefix=True)

    seen, merged = set(), []
    for r in backup_rows + corrupt_rows:
        key = tuple(r)
        if key in seen:
            continue
        seen.add(key)
        merged.append(r)

    merged.sort(key=lambda r: (r[0], r[1], r[2], int(float(r[9])), r[3], r[4]))

    with OUTPUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(PREDICTION_COLUMNS)
        w.writerows(merged)

    print()
    print(f"backup kept:    {len(backup_rows)} rows (unrecoverable lines: {b_drop})")
    print(f"corrupt kept:   {len(corrupt_rows)} rows (patched {patched}, unrecoverable lines: {c_drop})")
    print(f"after dedupe:   {len(merged)} rows")
    print(f"read corrupt:   {CORRUPT}")
    print(f"wrote clean:    {OUTPUT}")


if __name__ == "__main__":
    recover()
