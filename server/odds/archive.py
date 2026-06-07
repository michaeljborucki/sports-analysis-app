"""Cold storage for the odds time-series — compressed Parquet lake.

The hot `odds_history` table (cache.py) keeps only a ~90-day window so API
reads stay fast. Before any row is deleted from that window, it's exported
here into a partitioned, zstd-compressed Parquet dataset that's retained
indefinitely. The result is an append-only lake you can point DuckDB /
pandas / pyarrow at to extract the full multi-season corpus later:

    archive/
      sport_key=mlb/
        year_month=2026-03/
          part-<uuid>.parquet
          part-<uuid>.parquet
        year_month=2026-04/
          ...

Design notes:
  * Hive-style partitioning (sport_key / year_month derived from a game's
    commence_time) gives cheap partition pruning for time/sport-scoped
    extraction without an external catalog.
  * Files are immutable, written atomically (temp file → os.replace) and
    never rewritten — each export appends new part files. A crash between
    "Parquet written" and "deleted from hot" only re-exports the same rows
    next sweep, so readers should dedup on the natural key
    (event_id, bookmaker_key, market_key, outcome_name, outcome_point,
    observed_at). That window is tiny and the lake tolerates it.
  * A tiny `_manifest.json` tracks running totals so stats() stays O(1)
    instead of scanning the whole lake. The export job is single-instance
    (one scheduler thread), so the read-modify-write is race-free.

pyarrow is imported lazily so importing this module never hard-fails an
environment that hasn't installed it; the caller decides what to do when
construction/typing raises ImportError.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a runtime import cycle / hard pyarrow coupling
    from .cache import OddsCache

logger = logging.getLogger(__name__)


# Stable column order / types for every Parquet file, so the dataset reads
# back with one consistent schema regardless of which sweep wrote a file.
# Timestamps are kept as ISO strings (lossless, tz-safe); cast on read.
_PARQUET_COLUMNS = (
    "event_id",
    "sport_key",
    "home_team",
    "away_team",
    "commence_time",
    "bookmaker_key",
    "market_key",
    "outcome_name",
    "outcome_point",
    "price_american",
    "observed_at",
)

_MANIFEST_NAME = "_manifest.json"


def _year_month(commence_time: str | None) -> str:
    """Partition bucket from an ISO commence_time → 'YYYY-MM'. Falls back to
    'unknown' for malformed/empty values so a bad row never blocks export."""
    s = str(commence_time or "")
    return s[:7] if len(s) >= 7 and s[4] == "-" else "unknown"


class HistoryArchive:
    def __init__(self, root: Path):
        self.root = Path(root)

    # ───────────────────────────── write ──────────────────────────────

    def export_rows(self, rows: list[dict]) -> dict:
        """Write `rows` into the partitioned Parquet lake. Groups by
        (sport_key, year_month) so each game's history lands under its own
        month partition. Returns {"rows_written", "files_written"}.

        Idempotency is the caller's concern: this only appends. The caller
        deletes from hot AFTER this returns, so a crash re-exports (dedup on
        read). No-op on empty input.
        """
        if not rows:
            return {"rows_written": 0, "files_written": 0}

        import pyarrow as pa
        import pyarrow.parquet as pq

        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for r in rows:
            sk = r.get("sport_key") or "unknown"
            groups[(sk, _year_month(r.get("commence_time")))].append(r)

        files_written = 0
        rows_written = 0
        per_sport: dict[str, int] = defaultdict(int)
        bytes_written = 0
        earliest = None
        latest = None

        for (sport_key, ym), grp in groups.items():
            part_dir = self.root / f"sport_key={sport_key}" / f"year_month={ym}"
            part_dir.mkdir(parents=True, exist_ok=True)
            table = pa.table(
                {col: [r.get(col) for r in grp] for col in _PARQUET_COLUMNS}
            )
            final = part_dir / f"part-{uuid.uuid4().hex}.parquet"
            tmp = final.with_suffix(".parquet.tmp")
            pq.write_table(table, tmp, compression="zstd")
            os.replace(tmp, final)  # atomic publish

            files_written += 1
            rows_written += len(grp)
            per_sport[sport_key] += len(grp)
            bytes_written += final.stat().st_size
            for r in grp:
                ct = str(r.get("commence_time") or "")
                if ct:
                    earliest = ct if earliest is None or ct < earliest else earliest
                    latest = ct if latest is None or ct > latest else latest

        self._bump_manifest(
            rows_written, files_written, bytes_written,
            per_sport, earliest, latest,
        )
        return {"rows_written": rows_written, "files_written": files_written}

    # ──────────────────────────── manifest ────────────────────────────

    @property
    def _manifest_path(self) -> Path:
        return self.root / _MANIFEST_NAME

    def _load_manifest(self) -> dict:
        try:
            return json.loads(self._manifest_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "row_count": 0, "file_count": 0, "total_bytes": 0,
                "earliest_commence": None, "latest_commence": None,
                "last_export_at": None, "sports": {},
            }

    def _bump_manifest(
        self, rows: int, files: int, nbytes: int,
        per_sport: dict[str, int], earliest, latest,
    ) -> None:
        from datetime import datetime, timezone
        m = self._load_manifest()
        m["row_count"] += rows
        m["file_count"] += files
        m["total_bytes"] += nbytes
        m["last_export_at"] = datetime.now(timezone.utc).isoformat()
        if earliest and (m["earliest_commence"] is None or earliest < m["earliest_commence"]):
            m["earliest_commence"] = earliest
        if latest and (m["latest_commence"] is None or latest > m["latest_commence"]):
            m["latest_commence"] = latest
        sports = m.setdefault("sports", {})
        for sk, n in per_sport.items():
            sports[sk] = sports.get(sk, 0) + n
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(m, indent=2))
        os.replace(tmp, self._manifest_path)

    def stats(self) -> dict:
        """O(1) inventory of the lake, read from the manifest. Returns zeros
        before the first export."""
        m = self._load_manifest()
        return {
            "row_count": m.get("row_count", 0),
            "file_count": m.get("file_count", 0),
            "total_bytes": m.get("total_bytes", 0),
            "earliest_commence": m.get("earliest_commence"),
            "latest_commence": m.get("latest_commence"),
            "last_export_at": m.get("last_export_at"),
            "sports": m.get("sports", {}),
            "root": str(self.root),
        }

    # ───────────────────────────── read ───────────────────────────────

    def read_event(self, event_id: str) -> list[dict]:
        """Archived history points for one event (on-demand extraction).
        Scans the lake with an event_id filter — no partition pruning on
        event_id, so this reads broadly; intended for occasional lookups,
        not the hot path. Returns [] when the lake is empty."""
        if not self.root.exists():
            return []
        import pyarrow.dataset as ds
        try:
            dataset = ds.dataset(
                self.root, format="parquet", partitioning="hive",
            )
        except (FileNotFoundError, ValueError):
            return []
        if dataset.count_rows() == 0:
            return []
        table = dataset.to_table(
            columns=list(_PARQUET_COLUMNS),
            filter=ds.field("event_id") == event_id,
        )
        return table.to_pylist()


def export_and_purge(
    cache: "OddsCache",
    archive: HistoryArchive,
    now: datetime,
    hot_days: int = 90,
) -> dict:
    """Move odds_history rows older than `hot_days` from the hot table into
    the cold Parquet lake, then delete them from hot.

    Order is export-then-delete so a crash never loses data — at worst the
    same rows re-export next sweep (readers dedup on the natural key). No-op
    (and no delete) when the export itself fails, so the hot rows survive to
    be retried.

    Returns {"exported", "files_written", "purged_hot"}.
    """
    rows = cache.history_rows_older_than(now, days=hot_days)
    if not rows:
        return {"exported": 0, "files_written": 0, "purged_hot": 0}
    res = archive.export_rows(rows)
    purged = cache.delete_history_ids([r["id"] for r in rows])
    return {
        "exported": res["rows_written"],
        "files_written": res["files_written"],
        "purged_hot": purged,
    }
