"""Import historical balance snapshots from a text dump into the
balance_snapshots SQLite table.

The user has a long-running terminal script that prints account
balances at irregular intervals. The output format is a block per
poll:

    YYYY-MM-DD HH:MM:SS.ffffff
    User: <player_name> , Current Balance: <n>, Pending: <n>, Available Balance: <n>, Free Play: <n>
    User: ...
    User: ...

We:
  1. Parse each block — timestamp header + 1 line per user.
  2. Resolve `player_name` → `customer_id` via the live
     /api/coral33/accounts response (or AccountsScraper.credentials).
  3. Upsert into balance_snapshots with `local_date` derived from the
     header timestamp's calendar date.
  4. Skip lines that look like Python tracebacks / mid-script errors.

Usage:
  .venv/bin/python -m server.scripts.import_balance_snapshots \\
      server/data/balance_dump_2026-05-15.txt

Idempotent — re-running on the same dump is a no-op (PK collision →
overwrite with same values).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from server.config import Config
from server.odds.books.coral33.accounts import AccountsScraper
from server.odds.cache import OddsCache


# Header line: timestamp at the start of a block. Format
# `2026-04-18 23:30:10.404537` (microseconds may be absent).
_HEADER_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2}(?:\.\d+)?)$"
)

# Per-user line. Tolerant of trailing-space oddities and integer values
# in fields the dump occasionally emits as ints (e.g. Available
# Balance: 21 vs 21.0).
_USER_RE = re.compile(
    r"^User:\s*(?P<name>.+?)\s*,"
    r"\s*Current Balance:\s*(?P<cur>-?\d+(?:\.\d+)?)\s*,"
    r"\s*Pending:\s*(?P<pend>-?\d+(?:\.\d+)?)\s*,"
    r"\s*Available Balance:\s*(?P<avail>-?\d+(?:\.\d+)?)\s*,"
    r"\s*Free Play:\s*(?P<fp>-?\d+(?:\.\d+)?)\s*$"
)


@dataclass
class Snapshot:
    player_name: str
    captured_at: datetime
    local_date: str
    current_balance: float
    pending: float
    available: float
    free_play: float


def parse_dump(text: str) -> list[Snapshot]:
    """Parse the terminal dump into a flat list of Snapshot records.

    Blocks are delimited by header timestamp lines. Lines that don't
    match the header or user pattern (blank, shell prompts, tracebacks)
    are silently skipped.
    """
    out: list[Snapshot] = []
    current_ts: datetime | None = None
    current_date: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        m = _HEADER_RE.match(line)
        if m:
            date_str, time_str = m.group(1), m.group(2)
            try:
                current_ts = datetime.fromisoformat(f"{date_str}T{time_str}")
            except ValueError:
                current_ts = None
                current_date = None
                continue
            current_date = date_str
            continue
        m = _USER_RE.match(line)
        if not m or current_ts is None or current_date is None:
            continue
        out.append(Snapshot(
            player_name=m.group("name").strip(),
            captured_at=current_ts,
            local_date=current_date,
            current_balance=float(m.group("cur")),
            pending=float(m.group("pend")),
            available=float(m.group("avail")),
            free_play=float(m.group("fp")),
        ))
    return out


def build_name_to_id_map(
    scraper: AccountsScraper,
    backend_url: str | None = None,
) -> dict[str, str]:
    """Build {player_name → customer_id}.

    `player_name` (e.g. "Jimmy Dixon") isn't on AccountCredential — it's
    discovered at scrape time and surfaced via the live API. So we
    prefer hitting the running backend's
    /api/coral33/accounts endpoint to read the resolved names.

    Falls back to label-based matching (e.g. "Dixon") when no backend
    URL is provided or the request fails. Label matches are rarer in
    practice because the dump uses full player names.
    """
    out: dict[str, str] = {}
    if backend_url:
        try:
            with urllib.request.urlopen(
                f"{backend_url.rstrip('/')}/api/coral33/accounts",
                timeout=5,
            ) as r:
                data = json.load(r)
            for s in data.get("snapshots") or []:
                cid = s.get("customer_id")
                if not cid:
                    continue
                name = (s.get("player_name") or "").strip()
                if name:
                    out[name] = cid
                lbl = (s.get("label") or "").strip()
                if lbl:
                    out.setdefault(lbl, cid)
        except Exception as e:
            print(f"warning: backend lookup failed ({e}); "
                  f"falling back to credentials labels",
                  file=sys.stderr)
    # Fallback: label-based (works only when dump uses short forms).
    for cred in scraper.credentials:
        if cred.label:
            out.setdefault(cred.label.strip(), cred.customer_id)
    return out


def import_dump(
    dump_path: Path,
    cache: OddsCache,
    scraper: AccountsScraper,
    source_tag: str = "manual_import",
    backend_url: str | None = None,
) -> dict:
    """Parse + upsert. Returns counts for the caller to log."""
    text = dump_path.read_text()
    snapshots = parse_dump(text)
    name_to_id = build_name_to_id_map(scraper, backend_url)

    rows = []
    unresolved: dict[str, int] = {}
    for s in snapshots:
        cid = name_to_id.get(s.player_name)
        if cid is None:
            unresolved[s.player_name] = unresolved.get(s.player_name, 0) + 1
            continue
        rows.append({
            "customer_id":     cid,
            "captured_at":     s.captured_at.isoformat(),
            "local_date":      s.local_date,
            "current_balance": s.current_balance,
            "pending":         s.pending,
            "available":       s.available,
            "free_play":       s.free_play,
            "source":          source_tag,
        })

    written = cache.upsert_balance_snapshots(rows)
    return {
        "parsed_records": len(snapshots),
        "resolved_records": len(rows),
        "written": written,
        "unresolved_names": unresolved,
        "distinct_dates": sorted({r["local_date"] for r in rows}),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump_path", type=Path,
                    help="Path to the balance-dump text file")
    ap.add_argument("--source", default="manual_import",
                    help="Tag stored in balance_snapshots.source")
    ap.add_argument("--backend-url", default="http://127.0.0.1:8000",
                    help="Running backend URL for player_name lookup "
                         "(defaults to local). Pass empty string to skip.")
    args = ap.parse_args()

    if not args.dump_path.exists():
        print(f"dump not found: {args.dump_path}", file=sys.stderr)
        return 1

    config = Config.from_env()
    cache = OddsCache(config.cache_db)
    cache.init()
    scraper = AccountsScraper()

    result = import_dump(
        args.dump_path, cache, scraper, args.source,
        backend_url=args.backend_url or None,
    )
    print(f"parsed {result['parsed_records']} records, "
          f"resolved {result['resolved_records']}, wrote {result['written']}")
    if result["unresolved_names"]:
        print("unresolved player names (no matching credential):")
        for name, count in result["unresolved_names"].items():
            print(f"  {name!r}: {count} records")
    print(f"covered dates ({len(result['distinct_dates'])}): "
          f"{result['distinct_dates'][0]} .. {result['distinct_dates'][-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
