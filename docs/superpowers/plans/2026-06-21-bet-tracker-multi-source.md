# Bet Tracker Multi-Source — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified bet-tracker page that pulls bets from Coral33 (mirror), Kalshi (auth'd fills), Polymarket (wallet trades), and CSV imports into one `bets` table; surface them on a new `/bets` page with rollup tiles, CLV trend chart, and breakdowns.

**Architecture:** One new SQLite table (`bets`) in `cache.db`. Four sync paths write into it: Coral33 wager-log mirror (runs inside existing 30min wager-log refresh tick), Kalshi/Polymarket periodic poll (5min cadence, wired into existing `clv_scheduler` APScheduler), and CSV import (synchronous endpoint). CLV is computed at query time against the existing `closing_lines` table — never persisted. New `/api/bets`, `/api/bets/rollups`, `/api/bets/import`, `/api/bets/import/template` endpoints. Frontend gets a new `/bets` page with rollup tiles + recharts trend + filter bar + bet history table.

**Tech Stack:** Python 3.11, FastAPI, sqlite3, APScheduler, pytest. Next.js 16, React 19, SWR, TanStack Table, recharts (new dep), Tailwind, lucide-react.

**Spec:** `docs/superpowers/specs/2026-06-21-bet-tracker-multi-source-design.md`

---

## Pre-flight

Confirm the worktree:

```bash
git status
# Should be clean (or only have unstaged user_settings.json)
git log --oneline -3
# Should show fd4b455 (spec corrections), a70a505 (spec), c4f0766 (SSE perf fix)
```

If anything else is staged, stash it before starting.

---

## Phase 1 — DB layer

### Task 1: Add `bets` table to schema

**Files:**
- Modify: `server/odds/cache.py` (extend `SCHEMA` constant + `_MIGRATIONS` list)
- Test: `server/tests/test_cache.py`

- [ ] **Step 1: Write the failing test**

Add to `server/tests/test_cache.py`:

```python
def test_bets_table_created(tmp_path):
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    with cache._conn() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(bets)")}
    assert {
        "source_book", "external_id", "customer_id", "accepted_at",
        "settled_at", "status",
        "wager_type", "total_picks", "sport_key", "event_id",
        "home_team", "away_team", "market_key", "outcome_name",
        "outcome_point", "odds_american", "stake", "to_win",
        "settled_amount", "is_free_play", "raw_description", "imported_at",
    }.issubset(cols)


def test_bets_indexes_created(tmp_path):
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    with cache._conn() as c:
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_bets_accepted", "idx_bets_event", "idx_bets_book", "idx_bets_status"}.issubset(names)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest server/tests/test_cache.py::test_bets_table_created -v
```

Expected: FAIL with "no such table: bets" (or similar).

- [ ] **Step 3: Implement — extend SCHEMA in `server/odds/cache.py`**

Append to the `SCHEMA` constant (after `balance_snapshots`):

```sql
-- Unified bet ledger across every source: coral33 mirror, kalshi
-- portfolio fills, polymarket trades, and CSV imports. One row per
-- ticket / fill / position / import row. CLV is computed at query
-- time against `closing_lines` — never persisted here.
CREATE TABLE IF NOT EXISTS bets (
  source_book      TEXT NOT NULL,
  external_id      TEXT NOT NULL,
  customer_id      TEXT,                  -- coral33 customer_id; null for other sources
  accepted_at      TEXT NOT NULL,
  settled_at       TEXT,
  status           TEXT NOT NULL,
  wager_type       TEXT NOT NULL,
  total_picks      INTEGER NOT NULL DEFAULT 1,
  sport_key        TEXT,
  event_id         TEXT,
  home_team        TEXT,
  away_team        TEXT,
  market_key       TEXT,
  outcome_name     TEXT,
  outcome_point    REAL NOT NULL DEFAULT 0.0,
  odds_american    INTEGER,
  stake            REAL NOT NULL,
  to_win           REAL,
  settled_amount   REAL,
  is_free_play     INTEGER NOT NULL DEFAULT 0,
  raw_description  TEXT,
  imported_at      TEXT,
  PRIMARY KEY (source_book, external_id)
);

CREATE INDEX IF NOT EXISTS idx_bets_accepted ON bets(accepted_at);
CREATE INDEX IF NOT EXISTS idx_bets_event    ON bets(event_id);
CREATE INDEX IF NOT EXISTS idx_bets_book     ON bets(source_book);
CREATE INDEX IF NOT EXISTS idx_bets_status   ON bets(status);
```

No migration entries needed — `CREATE TABLE IF NOT EXISTS` handles both fresh and existing DBs.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest server/tests/test_cache.py -v
```

Expected: All pass, including the two new tests.

- [ ] **Step 5: Commit**

```bash
git add server/odds/cache.py server/tests/test_cache.py
git commit -m "$(cat <<'EOF'
feat(db): add bets table for unified bet tracker (#11)

Unified ledger across coral33/kalshi/polymarket/imports. PK is
(source_book, external_id) for idempotent re-syncs. CLV computed at
query time — never persisted.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Bets table query helpers

**Files:**
- Create: `server/odds/bets.py`
- Test: `server/tests/test_bets.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_bets.py`:

```python
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest
from server.odds.cache import OddsCache
from server.odds.bets import BetRow, upsert_bets, query_bets


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _row(**overrides) -> BetRow:
    base = BetRow(
        source_book="coral33", external_id="t1", customer_id="cust1",
        accepted_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        settled_at=None, status="open", wager_type="straight",
        total_picks=1, sport_key="mlb", event_id="ev1",
        home_team="LAD", away_team="SF", market_key="h2h",
        outcome_name="LAD", outcome_point=0.0, odds_american=-145,
        stake=50.0, to_win=34.5, settled_amount=None,
        is_free_play=False, raw_description=None, imported_at=None,
    )
    return base.replace(**overrides)


def test_upsert_inserts_new_row(cache):
    upsert_bets(cache, [_row()])
    rows = query_bets(cache)
    assert len(rows) == 1
    assert rows[0]["source_book"] == "coral33"
    assert rows[0]["external_id"] == "t1"


def test_upsert_is_idempotent(cache):
    upsert_bets(cache, [_row()])
    upsert_bets(cache, [_row()])
    rows = query_bets(cache)
    assert len(rows) == 1


def test_upsert_updates_status_on_repeat(cache):
    upsert_bets(cache, [_row(status="open")])
    upsert_bets(cache, [_row(status="win", settled_amount=84.5)])
    rows = query_bets(cache)
    assert len(rows) == 1
    assert rows[0]["status"] == "win"
    assert rows[0]["settled_amount"] == 84.5


def test_query_filters_by_book(cache):
    upsert_bets(cache, [
        _row(source_book="coral33", external_id="a"),
        _row(source_book="kalshi", external_id="b"),
    ])
    rows = query_bets(cache, book="kalshi")
    assert len(rows) == 1
    assert rows[0]["source_book"] == "kalshi"


def test_query_filters_by_status(cache):
    upsert_bets(cache, [
        _row(external_id="a", status="open"),
        _row(external_id="b", status="win"),
    ])
    rows = query_bets(cache, status="win")
    assert {r["external_id"] for r in rows} == {"b"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest server/tests/test_bets.py -v
```

Expected: FAIL with `ImportError: cannot import name 'BetRow'` or similar.

- [ ] **Step 3: Implement `server/odds/bets.py`**

```python
"""Unified bet ledger — DB layer.

One table, one row per (source_book, external_id). All four sync
paths (coral33 mirror, kalshi sync, polymarket sync, CSV import)
write rows in the same shape. CLV is NEVER stored here — it's
computed at query time by `lookup_clv_for_bet` against the existing
`closing_lines` table.
"""
from __future__ import annotations

from dataclasses import dataclass, replace as _replace
from datetime import datetime
from typing import Iterable

from .cache import OddsCache


@dataclass(frozen=True)
class BetRow:
    source_book: str
    external_id: str
    customer_id: str | None
    accepted_at: datetime
    settled_at: datetime | None
    status: str
    wager_type: str
    total_picks: int
    sport_key: str | None
    event_id: str | None
    home_team: str | None
    away_team: str | None
    market_key: str | None
    outcome_name: str | None
    outcome_point: float
    odds_american: int | None
    stake: float
    to_win: float | None
    settled_amount: float | None
    is_free_play: bool
    raw_description: str | None
    imported_at: datetime | None

    def replace(self, **kwargs) -> "BetRow":
        return _replace(self, **kwargs)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() if isinstance(dt, datetime) else str(dt)


def upsert_bets(cache: OddsCache, rows: Iterable[BetRow]) -> int:
    """Idempotent upsert on (source_book, external_id).

    On conflict, status / settled_at / settled_amount / odds_american /
    stake / to_win / total_picks update. accepted_at stays put.
    """
    rows = list(rows)
    if not rows:
        return 0
    prepared = [{
        "source_book": r.source_book,
        "external_id": r.external_id,
        "customer_id": r.customer_id,
        "accepted_at": _iso(r.accepted_at),
        "settled_at": _iso(r.settled_at),
        "status": r.status,
        "wager_type": r.wager_type,
        "total_picks": r.total_picks,
        "sport_key": r.sport_key,
        "event_id": r.event_id,
        "home_team": r.home_team,
        "away_team": r.away_team,
        "market_key": r.market_key,
        "outcome_name": r.outcome_name,
        "outcome_point": float(r.outcome_point),
        "odds_american": r.odds_american,
        "stake": float(r.stake),
        "to_win": r.to_win,
        "settled_amount": r.settled_amount,
        "is_free_play": 1 if r.is_free_play else 0,
        "raw_description": r.raw_description,
        "imported_at": _iso(r.imported_at),
    } for r in rows]
    with cache._conn() as c:
        c.executemany(
            """
            INSERT INTO bets (
              source_book, external_id, customer_id, accepted_at, settled_at, status,
              wager_type, total_picks, sport_key, event_id,
              home_team, away_team, market_key, outcome_name,
              outcome_point, odds_american, stake, to_win,
              settled_amount, is_free_play, raw_description, imported_at
            ) VALUES (
              :source_book, :external_id, :customer_id, :accepted_at, :settled_at, :status,
              :wager_type, :total_picks, :sport_key, :event_id,
              :home_team, :away_team, :market_key, :outcome_name,
              :outcome_point, :odds_american, :stake, :to_win,
              :settled_amount, :is_free_play, :raw_description, :imported_at
            )
            ON CONFLICT(source_book, external_id) DO UPDATE SET
              settled_at      = excluded.settled_at,
              status          = excluded.status,
              total_picks     = excluded.total_picks,
              odds_american   = excluded.odds_american,
              stake           = excluded.stake,
              to_win          = excluded.to_win,
              settled_amount  = excluded.settled_amount,
              market_key      = excluded.market_key,
              outcome_name    = excluded.outcome_name,
              outcome_point   = excluded.outcome_point,
              event_id        = excluded.event_id,
              sport_key       = excluded.sport_key,
              home_team       = excluded.home_team,
              away_team       = excluded.away_team
            """,
            prepared,
        )
    return len(prepared)


def query_bets(
    cache: OddsCache,
    *,
    book: str | None = None,
    sport: str | None = None,
    status: str | None = None,
    market_key: str | None = None,
    from_iso: str | None = None,
    to_iso: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Filtered bet list. All filters AND together. Sorted by
    accepted_at DESC."""
    q = "SELECT * FROM bets WHERE 1=1"
    args: list = []
    if book is not None:
        q += " AND source_book = ?"; args.append(book)
    if sport is not None:
        q += " AND sport_key = ?"; args.append(sport)
    if status is not None:
        q += " AND status = ?"; args.append(status)
    if market_key is not None:
        q += " AND market_key = ?"; args.append(market_key)
    if from_iso is not None:
        q += " AND accepted_at >= ?"; args.append(from_iso)
    if to_iso is not None:
        q += " AND accepted_at < ?"; args.append(to_iso)
    q += " ORDER BY accepted_at DESC"
    if limit is not None:
        q += " LIMIT ?"; args.append(int(limit))
    with cache._conn() as c:
        return [dict(r) for r in c.execute(q, args)]
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_bets.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/odds/bets.py server/tests/test_bets.py
git commit -m "$(cat <<'EOF'
feat(bets): BetRow dataclass + upsert/query helpers

Idempotent upserts on (source_book, external_id). On conflict,
settle-related fields update; accepted_at stays put. Sort and filter
helpers for the upcoming /api/bets endpoint.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Rollup SQL (30d / 90d / lifetime / by_book / by_sport / by_market)

**Files:**
- Modify: `server/odds/bets.py` (add `rollups()` function)
- Modify: `server/tests/test_bets.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_bets.py`:

```python
from datetime import timedelta


def test_rollups_lifetime_and_windows(cache):
    from server.odds.bets import rollups
    now = datetime(2026, 6, 21, tzinfo=timezone.utc)
    # 1 win at $100 stake / $200 payout, accepted 10 days ago
    upsert_bets(cache, [_row(
        external_id="recent_win", accepted_at=now - timedelta(days=10),
        settled_at=now - timedelta(days=9), status="win",
        stake=100.0, settled_amount=200.0,
    )])
    # 1 loss at $50 stake, accepted 100 days ago (outside 90d window)
    upsert_bets(cache, [_row(
        external_id="old_loss", accepted_at=now - timedelta(days=100),
        settled_at=now - timedelta(days=99), status="loss",
        stake=50.0, settled_amount=0.0,
    )])
    out = rollups(cache, now=now)
    # Lifetime: 2 bets, $150 wagered, $200 won, ROI = (200 - 150) / 150
    assert out["lifetime"]["count"] == 2
    assert out["lifetime"]["wagered"] == 150.0
    assert abs(out["lifetime"]["roi_pct"] - ((200 - 150) / 150 * 100)) < 0.01
    # 30d window: only the recent win
    assert out["window_30d"]["count"] == 1
    assert out["window_30d"]["wagered"] == 100.0
    # 90d window: also only the recent win
    assert out["window_90d"]["count"] == 1


def test_rollups_by_book(cache):
    from server.odds.bets import rollups
    now = datetime(2026, 6, 21, tzinfo=timezone.utc)
    upsert_bets(cache, [
        _row(source_book="coral33", external_id="a", stake=100,
             status="win", settled_amount=180,
             accepted_at=now - timedelta(days=5)),
        _row(source_book="kalshi", external_id="b", stake=100,
             status="loss", settled_amount=0,
             accepted_at=now - timedelta(days=5)),
    ])
    out = rollups(cache, now=now)
    by_book = {b["source_book"]: b for b in out["by_book"]}
    assert by_book["coral33"]["count"] == 1
    assert by_book["coral33"]["wagered"] == 100
    assert by_book["kalshi"]["count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest server/tests/test_bets.py::test_rollups_lifetime_and_windows -v
```

Expected: FAIL with `ImportError: cannot import name 'rollups'`.

- [ ] **Step 3: Implement `rollups()` in `server/odds/bets.py`**

Append to `server/odds/bets.py`:

```python
def _window_iso(now: datetime, days: int) -> str:
    from datetime import timedelta as _td
    return (now - _td(days=days)).isoformat()


def _rollup_for_window(cache: OddsCache, from_iso: str | None) -> dict:
    """Single-window rollup. from_iso=None means lifetime."""
    q = """
      SELECT
        COUNT(*) AS count,
        COALESCE(SUM(stake), 0) AS wagered,
        COALESCE(SUM(CASE WHEN status NOT IN ('open', 'pending') AND is_free_play = 0
                          THEN settled_amount - stake END), 0) AS net,
        COALESCE(SUM(CASE WHEN status NOT IN ('open', 'pending') AND is_free_play = 0
                          THEN stake END), 0) AS settled_wagered
      FROM bets
      WHERE 1=1
    """
    args: list = []
    if from_iso is not None:
        q += " AND accepted_at >= ?"
        args.append(from_iso)
    with cache._conn() as c:
        row = c.execute(q, args).fetchone()
    count = int(row["count"])
    wagered = float(row["wagered"] or 0)
    net = float(row["net"] or 0)
    settled_wagered = float(row["settled_wagered"] or 0)
    roi_pct = (net / settled_wagered * 100.0) if settled_wagered > 0 else 0.0
    return {
        "count": count,
        "wagered": round(wagered, 2),
        "net": round(net, 2),
        "roi_pct": round(roi_pct, 2),
    }


def _rollup_grouped(cache: OddsCache, group_col: str) -> list[dict]:
    """Lifetime rollup grouped by a column (source_book, sport_key,
    market_key). Returns one row per non-null group value."""
    q = f"""
      SELECT
        {group_col} AS grp,
        COUNT(*) AS count,
        COALESCE(SUM(stake), 0) AS wagered,
        COALESCE(SUM(CASE WHEN status NOT IN ('open', 'pending') AND is_free_play = 0
                          THEN settled_amount - stake END), 0) AS net,
        COALESCE(SUM(CASE WHEN status NOT IN ('open', 'pending') AND is_free_play = 0
                          THEN stake END), 0) AS settled_wagered
      FROM bets
      WHERE {group_col} IS NOT NULL
      GROUP BY {group_col}
      ORDER BY wagered DESC
    """
    out: list[dict] = []
    with cache._conn() as c:
        for r in c.execute(q):
            settled_wagered = float(r["settled_wagered"] or 0)
            net = float(r["net"] or 0)
            roi_pct = (net / settled_wagered * 100.0) if settled_wagered > 0 else 0.0
            out.append({
                group_col: r["grp"],
                "count": int(r["count"]),
                "wagered": round(float(r["wagered"] or 0), 2),
                "net": round(net, 2),
                "roi_pct": round(roi_pct, 2),
            })
    return out


def rollups(cache: OddsCache, now: datetime | None = None) -> dict:
    """One-pass rollup payload for the /bets dashboard.

    Returns: window_30d, window_90d, lifetime, by_book, by_sport,
    by_market. Each window has {count, wagered, net, roi_pct}.
    """
    if now is None:
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc)
    return {
        "window_30d": _rollup_for_window(cache, _window_iso(now, 30)),
        "window_90d": _rollup_for_window(cache, _window_iso(now, 90)),
        "lifetime": _rollup_for_window(cache, None),
        "by_book": _rollup_grouped(cache, "source_book"),
        "by_sport": _rollup_grouped(cache, "sport_key"),
        "by_market": _rollup_grouped(cache, "market_key"),
    }
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_bets.py -v
```

Expected: all tests pass (including the two new rollup tests).

- [ ] **Step 5: Commit**

```bash
git add server/odds/bets.py server/tests/test_bets.py
git commit -m "$(cat <<'EOF'
feat(bets): rollup SQL — 30d/90d/lifetime + by book/sport/market

Single-pass aggregations for the /bets dashboard tiles + breakdowns.
ROI computed on settled non-free-play rows only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2 — CLV generalization

### Task 4: `lookup_clv_for_bet`

**Files:**
- Modify: `server/odds/clv.py`
- Modify: `server/tests/test_clv.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_clv.py`:

```python
def test_lookup_clv_for_bet_returns_clv_when_event_resolved(tmp_path):
    from server.odds.cache import OddsCache
    from server.odds.clv import lookup_clv_for_bet
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    cache.upsert_closing_lines([{
        "event_id": "ev1", "sport_key": "mlb",
        "home_team": "LAD", "away_team": "SF",
        "market_key": "h2h", "outcome_name": "LAD", "outcome_point": 0.0,
        "close_odds": -120, "close_prob_devig": 0.545,
        "commence_time": "2026-06-19T19:00:00+00:00",
        "captured_at":    "2026-06-19T18:53:00+00:00",
        "source_books": "pinnacle",
    }])
    # Bettor took LAD at -145, line closed -120 → bettor's odds are worse
    bet = {
        "event_id": "ev1", "market_key": "h2h",
        "outcome_name": "LAD", "outcome_point": 0.0,
        "odds_american": -145,
    }
    result = lookup_clv_for_bet(bet, cache)
    assert result is not None
    assert result.close_odds == -120
    # bet_dec = 1 + 100/145 ≈ 1.6897, close_dec = 1 + 100/120 ≈ 1.8333
    # clv_pct ≈ 1.6897/1.8333 - 1 ≈ -0.0783
    assert result.clv_pct < 0  # negative — bettor got worse-than-close


def test_lookup_clv_for_bet_returns_none_when_event_missing(tmp_path):
    from server.odds.cache import OddsCache
    from server.odds.clv import lookup_clv_for_bet
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    bet = {
        "event_id": None, "market_key": "h2h",
        "outcome_name": "LAD", "outcome_point": 0.0,
        "odds_american": -145,
    }
    assert lookup_clv_for_bet(bet, cache) is None


def test_lookup_clv_for_bet_returns_none_when_no_closing_line(tmp_path):
    from server.odds.cache import OddsCache
    from server.odds.clv import lookup_clv_for_bet
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    bet = {
        "event_id": "ev_nonexistent", "market_key": "h2h",
        "outcome_name": "LAD", "outcome_point": 0.0,
        "odds_american": -145,
    }
    assert lookup_clv_for_bet(bet, cache) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest server/tests/test_clv.py -v -k for_bet
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement — add to `server/odds/clv.py`**

Append to `server/odds/clv.py`:

```python
def lookup_clv_for_bet(bet: dict, cache: OddsCache) -> CLVResult | None:
    """Compute CLV for a unified bet row.

    Requires the bet to carry a resolved outcome address:
      event_id + market_key + outcome_name + outcome_point.
    These are populated by each source's sync path using that book's
    `event_matcher.py`. CSV imports without an `event` match leave
    event_id=None and skip CLV — that's expected.

    Returns None when:
      - Any address field is missing
      - No closing line was captured for that outcome
      - bet.odds_american is None
    """
    if (
        bet.get("event_id") is None
        or bet.get("market_key") is None
        or bet.get("outcome_name") is None
        or bet.get("odds_american") is None
    ):
        return None
    close_row = cache.find_closing_line(
        event_id=bet["event_id"],
        market_key=bet["market_key"],
        outcome_name=bet["outcome_name"],
        outcome_point=float(bet.get("outcome_point") or 0.0),
    )
    if close_row is None:
        return None
    try:
        close_odds = int(close_row["close_odds"])
    except (KeyError, ValueError, TypeError):
        return None
    return compute_clv(int(bet["odds_american"]), close_odds)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_clv.py -v
```

Expected: all pass (including 3 new tests).

- [ ] **Step 5: Commit**

```bash
git add server/odds/clv.py server/tests/test_clv.py
git commit -m "$(cat <<'EOF'
feat(clv): lookup_clv_for_bet — sport-/book-agnostic CLV for bet rows

The bet's source-sync path is responsible for resolving the outcome
address; this function just looks up the closing line and runs the
math. CSV imports without a matched event surface CLV as None.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3 — Sync paths

### Task 5: Coral33 wager log → bets mirror

**Files:**
- Create: `server/odds/books/coral33/bets_mirror.py`
- Test: `server/tests/test_coral33_bets_mirror.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_coral33_bets_mirror.py`:

```python
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest
from server.odds.cache import OddsCache
from server.odds.bets import query_bets
from server.odds.books.coral33.wager_log import WagerLogEntry


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _wager(**overrides) -> WagerLogEntry:
    base = dict(
        customer_id="cust1",
        ticket_number=12345,
        accepted_at=datetime(2026, 6, 19, 18, 0, tzinfo=timezone.utc),
        settled_at=None, wager_status="O", wager_type="S",
        total_picks=1, amount_wagered=50.0, to_win_amount=34.5,
        amount_won=0.0, amount_lost=0.0, is_free_play=False,
        sport_type="Baseball", sport_sub_type="MLB",
        period=None, team1_id="Dodgers", team2_id="Giants",
        chosen_team_id="Dodgers", description="Dodgers ML",
        final_money=-145, adj_spread=0.0, adj_total_points=0.0,
    )
    base.update(overrides)
    return WagerLogEntry(**base)


def test_mirror_writes_one_row_per_ticket(cache):
    from server.odds.books.coral33.bets_mirror import (
        mirror_coral33_wager_log_to_bets,
    )
    wagers_by_cid = {
        "cust1": [_wager(ticket_number=1), _wager(ticket_number=2)],
    }
    n = mirror_coral33_wager_log_to_bets(cache, wagers_by_cid)
    assert n == 2
    rows = query_bets(cache, book="coral33")
    assert {r["external_id"] for r in rows} == {"1", "2"}


def test_mirror_is_idempotent_on_rerun(cache):
    from server.odds.books.coral33.bets_mirror import (
        mirror_coral33_wager_log_to_bets,
    )
    w = {"cust1": [_wager(ticket_number=1)]}
    mirror_coral33_wager_log_to_bets(cache, w)
    mirror_coral33_wager_log_to_bets(cache, w)
    assert len(query_bets(cache, book="coral33")) == 1


def test_mirror_updates_status_on_settlement(cache):
    from server.odds.books.coral33.bets_mirror import (
        mirror_coral33_wager_log_to_bets,
    )
    open_w = {"cust1": [_wager(ticket_number=1, wager_status="O")]}
    mirror_coral33_wager_log_to_bets(cache, open_w)
    settled_w = {"cust1": [_wager(
        ticket_number=1, wager_status="W",
        amount_won=84.5,
        settled_at=datetime(2026, 6, 19, 22, 0, tzinfo=timezone.utc),
    )]}
    mirror_coral33_wager_log_to_bets(cache, settled_w)
    rows = query_bets(cache, book="coral33")
    assert len(rows) == 1
    assert rows[0]["status"] == "win"
    assert rows[0]["settled_amount"] == 84.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest server/tests/test_coral33_bets_mirror.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `server/odds/books/coral33/bets_mirror.py`**

```python
"""Coral33 wager log → unified bets table mirror.

The wager log JSON files (per customer_id under server/data/
coral33_wager_log/) are the scrape cache — authoritative for what
Coral33 has reported. This module mirrors them into the unified
`bets` table so the /bets endpoint can return them alongside Kalshi,
Polymarket, and imported rows from a single source.

Called from the existing 30-min wager-log refresh tick in main.py.
No new HTTP traffic — purely a DB→DB copy.
"""
from __future__ import annotations

import logging
from typing import Iterable

from ...bets import BetRow, upsert_bets
from ...cache import OddsCache
from ...clv import get_coral33_config, wager_to_market_lookup
from .wager_log import WagerLogEntry


logger = logging.getLogger(__name__)


# Coral33 wager_status codes → unified status values.
_STATUS_MAP = {
    "O": "open",        # open / unsettled
    "W": "win",
    "L": "loss",
    "P": "push",
    "X": "void",
}


# Coral33 wager_type codes → unified wager_type values.
_WAGER_TYPE_MAP = {
    "S": "straight",
    "P": "parlay",
    "T": "teaser",
    "I": "if_bet",
    "R": "round_robin",
}


def _to_bet_row(w: WagerLogEntry, customer_id: str, cache: OddsCache) -> BetRow:
    """Translate a WagerLogEntry → BetRow. Resolves event_id /
    market_key / outcome address by reusing wager_to_market_lookup,
    so the resulting row carries the CLV-ready address."""
    status = _STATUS_MAP.get(w.wager_status, "open")
    settled_amount: float | None
    if status == "win":
        settled_amount = float(w.amount_wagered + w.amount_won)
    elif status == "loss":
        settled_amount = 0.0
    elif status == "push":
        settled_amount = float(w.amount_wagered)
    elif status == "void":
        settled_amount = float(w.amount_wagered)
    else:
        settled_amount = None

    sport_key: str | None = None
    event_id: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    market_key: str | None = None
    outcome_name: str | None = None
    outcome_point: float = 0.0
    try:
        config, reverse = get_coral33_config()
        lookup = wager_to_market_lookup(w, cache, config, reverse)
        if lookup is not None:
            sport_key = lookup.sport_key
            event_id = lookup.event_id
            home_team = lookup.canonical_home
            away_team = lookup.canonical_away
            market_key = lookup.market_key
            outcome_name = lookup.outcome_name
            outcome_point = lookup.outcome_point
    except Exception:
        logger.exception("coral33 mirror: market lookup failed for ticket %s", w.ticket_number)

    return BetRow(
        source_book="coral33",
        external_id=str(w.ticket_number),
        customer_id=customer_id,
        accepted_at=w.accepted_at,
        settled_at=w.settled_at,
        status=status,
        wager_type=_WAGER_TYPE_MAP.get(w.wager_type, "straight"),
        total_picks=w.total_picks,
        sport_key=sport_key,
        event_id=event_id,
        home_team=home_team,
        away_team=away_team,
        market_key=market_key,
        outcome_name=outcome_name,
        outcome_point=outcome_point,
        odds_american=w.final_money,
        stake=float(w.amount_wagered),
        to_win=float(w.to_win_amount),
        settled_amount=settled_amount,
        is_free_play=bool(w.is_free_play),
        raw_description=w.description,
        imported_at=None,
    )


def mirror_coral33_wager_log_to_bets(
    cache: OddsCache,
    wagers_by_cid: dict[str, Iterable[WagerLogEntry]],
) -> int:
    """Mirror every wager across all accounts into the bets table.

    Idempotent — re-runs produce the same end state. Status / settled
    fields update on re-mirror; accepted_at stays put.

    Returns total rows upserted.
    """
    rows: list[BetRow] = []
    for cid, wagers in wagers_by_cid.items():
        for w in wagers:
            rows.append(_to_bet_row(w, cid, cache))
    if not rows:
        return 0
    return upsert_bets(cache, rows)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_coral33_bets_mirror.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/coral33/bets_mirror.py server/tests/test_coral33_bets_mirror.py
git commit -m "$(cat <<'EOF'
feat(coral33): mirror wager log into unified bets table

Pure DB→DB copy — no new HTTP traffic. Wired into the existing 30min
wager-log refresh tick in a later task. Reuses wager_to_market_lookup
so each mirrored row carries the CLV-ready outcome address.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Kalshi portfolio sync

**Files:**
- Create: `server/odds/books/kalshi/portfolio_sync.py`
- Test: `server/tests/test_kalshi_portfolio_sync.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_kalshi_portfolio_sync.py`:

```python
from __future__ import annotations
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from server.odds.cache import OddsCache
from server.odds.bets import query_bets


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _fill(**overrides) -> dict:
    """A realistic Kalshi /portfolio/fills entry."""
    base = {
        "fill_id": "fill_abc",
        "ticker": "KXNBA-26JUN21BOSMIA-BOS",   # example
        "side": "yes",
        "price": 45,           # cents — 0.45 implied probability
        "count": 100,          # contracts
        "created_time": "2026-06-19T18:00:00Z",
        "is_taker": True,
    }
    base.update(overrides)
    return base


async def _run_sync(cache: OddsCache, fills: list[dict]):
    from server.odds.books.kalshi.portfolio_sync import sync_kalshi_fills
    client = MagicMock()
    client.get_portfolio_fills = AsyncMock(return_value=fills)
    return await sync_kalshi_fills(client=client, cache=cache)


def test_sync_inserts_one_bet_per_fill(cache):
    n = asyncio.run(_run_sync(cache, [_fill(fill_id="a"), _fill(fill_id="b")]))
    assert n == 2
    rows = query_bets(cache, book="kalshi")
    assert {r["external_id"] for r in rows} == {"a", "b"}


def test_sync_translates_price_to_american_odds(cache):
    # Kalshi YES at 45 cents → implied prob 0.45 → American odds +122
    asyncio.run(_run_sync(cache, [_fill(fill_id="a", price=45, side="yes")]))
    rows = query_bets(cache, book="kalshi")
    assert rows[0]["odds_american"] is not None
    # +122 is the rounded value of (1/0.45 - 1) * 100 / 0.45 ... use a loose check
    # because price→odds math for binary contracts is precise
    assert rows[0]["odds_american"] > 0  # 0.45 prob → underdog → positive odds


def test_sync_translates_stake_from_price_and_count(cache):
    asyncio.run(_run_sync(cache, [_fill(fill_id="a", price=45, count=100)]))
    rows = query_bets(cache, book="kalshi")
    # Stake on Kalshi YES at 45c × 100 contracts = $45
    assert rows[0]["stake"] == pytest.approx(45.0, abs=0.01)


def test_sync_is_idempotent(cache):
    fills = [_fill(fill_id="a")]
    asyncio.run(_run_sync(cache, fills))
    asyncio.run(_run_sync(cache, fills))
    assert len(query_bets(cache, book="kalshi")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_portfolio_sync.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `server/odds/books/kalshi/portfolio_sync.py`**

```python
"""Kalshi portfolio sync — fills → unified bets table.

Periodic 5-min task (wired into clv_scheduler in a later step).
Pulls /portfolio/fills via the existing KalshiClient (auth required),
translates each fill into a BetRow, upserts. Idempotent on
(source_book='kalshi', external_id=fill_id).

Outcome address (event_id / market_key / outcome_name) is resolved
via the existing kalshi/event_matcher.py — the same matcher used for
market-data ingest, so CLV lookup against `closing_lines` works
transparently.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from ...bets import BetRow, upsert_bets
from ...cache import OddsCache


logger = logging.getLogger(__name__)


def _price_to_american(price_cents: int, side: str) -> int | None:
    """Kalshi prices are in cents (0-99). YES at 45 → buyer pays 0.45,
    wins 1.00 if YES (implied prob 0.45). NO at 45 → buyer pays 0.45,
    wins 1.00 if NO (implied prob 0.45).
    Convert to American odds the bettor effectively took."""
    if not (0 < price_cents < 100):
        return None
    p = price_cents / 100.0
    # American odds: positive when prob < 0.5, negative when > 0.5
    if p < 0.5:
        return int(round((1 / p - 1) * 100))
    else:
        return int(round(-p / (1 - p) * 100))


def _fill_status(fill: dict) -> str:
    """Kalshi fills are events; the position resolves later. We mark
    new fills as 'open' here and the periodic resync upgrades them
    to win/loss once the market settles. (Settlement detection comes
    from /portfolio/positions where realized_pnl != 0.)
    """
    if fill.get("settled"):
        outcome = fill.get("settlement_outcome")
        if outcome == "win":
            return "win"
        elif outcome == "loss":
            return "loss"
    return "open"


async def sync_kalshi_fills(
    *, client, cache: OddsCache,
    settings_store=None,  # for future per-user wallet store; unused today
) -> int:
    """One sync cycle. Returns rows upserted (0 if no fills or unauthed).

    Tolerates auth being unconfigured — the wrapper task checks
    client.is_authenticated and skips this call if not."""
    try:
        fills = await client.get_portfolio_fills()
    except Exception:
        logger.exception("kalshi portfolio sync: get_portfolio_fills failed")
        return 0

    if not fills:
        return 0

    rows: list[BetRow] = []
    for f in fills:
        fill_id = f.get("fill_id") or f.get("trade_id")
        if not fill_id:
            continue
        price = f.get("price")
        count = f.get("count")
        side = (f.get("side") or "yes").lower()
        if price is None or count is None:
            continue
        odds = _price_to_american(int(price), side)
        stake = round(int(price) / 100.0 * int(count), 2)
        ts_raw = f.get("created_time") or f.get("trade_time") or f.get("ts")
        try:
            accepted_at = datetime.fromisoformat(
                str(ts_raw).replace("Z", "+00:00")
            ) if ts_raw else datetime.now(timezone.utc)
        except ValueError:
            accepted_at = datetime.now(timezone.utc)

        # Event-address resolution: deferred to a follow-up that wires
        # kalshi/event_matcher in. For now leave event_id=None so the
        # row appears in the table; CLV stays None.
        # TODO(#11-followup): resolve event_id via kalshi/event_matcher.py
        rows.append(BetRow(
            source_book="kalshi",
            external_id=str(fill_id),
            customer_id=None,
            accepted_at=accepted_at,
            settled_at=None,
            status=_fill_status(f),
            wager_type="straight",
            total_picks=1,
            sport_key=None,
            event_id=None,
            home_team=None,
            away_team=None,
            market_key="h2h",
            outcome_name=side.upper(),
            outcome_point=0.0,
            odds_american=odds,
            stake=stake,
            to_win=round(int(count) - stake, 2),
            settled_amount=None,
            is_free_play=False,
            raw_description=f.get("ticker"),
            imported_at=None,
        ))

    if not rows:
        return 0
    return upsert_bets(cache, rows)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_portfolio_sync.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/kalshi/portfolio_sync.py server/tests/test_kalshi_portfolio_sync.py
git commit -m "$(cat <<'EOF'
feat(kalshi): portfolio fills → unified bets table

Async sync function consuming KalshiClient.get_portfolio_fills().
Translates Kalshi binary-contract prices to American odds, stake =
price × count. Idempotent on fill_id. Event-address resolution is
left as a TODO follow-up — rows surface in the UI without CLV until
that lands.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Polymarket portfolio sync

**Files:**
- Create: `server/odds/books/polymarket/portfolio_sync.py`
- Test: `server/tests/test_polymarket_portfolio_sync.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_polymarket_portfolio_sync.py`:

```python
from __future__ import annotations
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from server.odds.cache import OddsCache
from server.odds.bets import query_bets


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "test.db")
    c.init()
    return c


def _trade(**overrides) -> dict:
    base = {
        "trade_id": "0xabc-1",
        "market": "celtics-vs-heat-2026-06-21",
        "outcome": "Celtics",
        "side": "BUY",
        "price": "0.62",
        "size": "100",            # USDC notional, NOT shares
        "timestamp": "2026-06-19T19:00:00Z",
    }
    base.update(overrides)
    return base


async def _run_sync(cache: OddsCache, trades: list[dict], wallet: str = "0xABC"):
    from server.odds.books.polymarket.portfolio_sync import sync_polymarket_trades
    client = MagicMock()
    client.get_user_trades = AsyncMock(return_value=trades)
    return await sync_polymarket_trades(
        client=client, cache=cache, wallet_address=wallet,
    )


def test_sync_inserts_one_bet_per_trade(cache):
    n = asyncio.run(_run_sync(cache, [
        _trade(trade_id="a"), _trade(trade_id="b"),
    ]))
    assert n == 2
    rows = query_bets(cache, book="polymarket")
    assert {r["external_id"] for r in rows} == {"a", "b"}


def test_sync_translates_price_to_american(cache):
    asyncio.run(_run_sync(cache, [_trade(trade_id="a", price="0.62")]))
    rows = query_bets(cache, book="polymarket")
    # 0.62 implied prob → favorite → negative American odds ≈ -163
    assert rows[0]["odds_american"] < 0


def test_sync_noop_when_wallet_empty(cache):
    n = asyncio.run(_run_sync(cache, [_trade()], wallet=""))
    assert n == 0


def test_sync_is_idempotent(cache):
    trades = [_trade(trade_id="a")]
    asyncio.run(_run_sync(cache, trades))
    asyncio.run(_run_sync(cache, trades))
    assert len(query_bets(cache, book="polymarket")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest server/tests/test_polymarket_portfolio_sync.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `server/odds/books/polymarket/portfolio_sync.py`**

```python
"""Polymarket portfolio sync — wallet trades → unified bets table.

Periodic 5-min task. Uses the public data-api.polymarket.com/trades
endpoint keyed by wallet address (no auth). Translates each trade
into a BetRow.

Polymarket fills are tied to on-chain wallets, so wallet_address is
required. If unconfigured in user_settings, the task no-ops.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ...bets import BetRow, upsert_bets
from ...cache import OddsCache


logger = logging.getLogger(__name__)


def _prob_to_american(p: float) -> int | None:
    """0 < p < 1 → American odds for the contract buyer."""
    if not (0 < p < 1):
        return None
    if p < 0.5:
        return int(round((1 / p - 1) * 100))
    return int(round(-p / (1 - p) * 100))


async def sync_polymarket_trades(
    *, client, cache: OddsCache, wallet_address: str,
) -> int:
    """One sync cycle. Returns rows upserted (0 if wallet empty)."""
    if not wallet_address:
        return 0

    try:
        trades = await client.get_user_trades(wallet_address)
    except Exception:
        logger.exception("polymarket sync: get_user_trades failed")
        return 0

    if not trades:
        return 0

    rows: list[BetRow] = []
    for t in trades:
        trade_id = t.get("trade_id") or t.get("transaction_hash")
        if not trade_id:
            continue
        try:
            price = float(t.get("price") or 0)
            size = float(t.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0 or size <= 0:
            continue

        ts_raw = t.get("timestamp") or t.get("created_at")
        try:
            accepted_at = datetime.fromisoformat(
                str(ts_raw).replace("Z", "+00:00")
            ) if ts_raw else datetime.now(timezone.utc)
        except ValueError:
            accepted_at = datetime.now(timezone.utc)

        side = (t.get("side") or "BUY").upper()
        if side == "SELL":
            # SELL closes a position. For now, ignore — we track buys
            # only; final settlement comes when the market resolves.
            # TODO(#11-followup): treat SELL as an early-exit settlement.
            continue

        odds = _prob_to_american(price)
        stake = round(price * size, 2)
        to_win = round(size - stake, 2)

        # TODO(#11-followup): resolve event_id via polymarket/event_matcher.py.
        rows.append(BetRow(
            source_book="polymarket",
            external_id=str(trade_id),
            customer_id=None,
            accepted_at=accepted_at,
            settled_at=None,
            status="open",
            wager_type="straight",
            total_picks=1,
            sport_key=None,
            event_id=None,
            home_team=None,
            away_team=None,
            market_key="h2h",
            outcome_name=t.get("outcome"),
            outcome_point=0.0,
            odds_american=odds,
            stake=stake,
            to_win=to_win,
            settled_amount=None,
            is_free_play=False,
            raw_description=t.get("market"),
            imported_at=None,
        ))

    if not rows:
        return 0
    return upsert_bets(cache, rows)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_polymarket_portfolio_sync.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/polymarket/portfolio_sync.py server/tests/test_polymarket_portfolio_sync.py
git commit -m "$(cat <<'EOF'
feat(polymarket): wallet trades → unified bets table

Wallet-keyed (no auth required) periodic sync. BUY-side trades only
in this pass; SELL (early exit) deferred to follow-up. Event-address
resolution also deferred — rows surface without CLV initially.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: CSV parser + import

**Files:**
- Create: `server/odds/bets_csv.py`
- Test: `server/tests/test_bets_csv.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_bets_csv.py`:

```python
import io
import pytest
from server.odds.bets_csv import parse_csv_to_bet_rows


SAMPLE_OK = """date,book,sport,event,market,side,odds,stake,result
2026-06-19,DraftKings,nba,MIA @ BOS,h2h,BOS,-145,50,W
2026-06-20,FanDuel,mlb,LAD @ SF,spreads -1.5,LAD,+155,25,pending
2026-06-20,Pinnacle,tennis,Sinner vs Alcaraz,h2h,Alcaraz,+105,100,L
"""


def test_parses_happy_path():
    rows, errors = parse_csv_to_bet_rows(io.StringIO(SAMPLE_OK))
    assert len(rows) == 3
    assert errors == []
    assert rows[0].source_book == "imported"
    assert rows[0].raw_description == "MIA @ BOS"
    assert rows[0].odds_american == -145
    assert rows[0].stake == 50.0
    assert rows[0].status == "win"


def test_status_pending_when_result_pending():
    rows, errors = parse_csv_to_bet_rows(io.StringIO(SAMPLE_OK))
    assert rows[1].status == "pending"


def test_missing_required_column_returns_error():
    bad = "date,book,sport,market,side,odds,result\n2026-06-19,DK,nba,h2h,BOS,-145,W\n"
    rows, errors = parse_csv_to_bet_rows(io.StringIO(bad))
    assert rows == []
    assert any("stake" in e["reason"] for e in errors)


def test_bad_date_rejected_row_still_returns_good_rows():
    mixed = """date,book,sport,event,market,side,odds,stake,result
last tuesday,DK,nba,A @ B,h2h,A,-145,50,W
2026-06-19,DK,nba,C @ D,h2h,C,+110,25,L
"""
    rows, errors = parse_csv_to_bet_rows(io.StringIO(mixed))
    assert len(rows) == 1
    assert rows[0].raw_description == "C @ D"
    assert len(errors) == 1
    assert "date" in errors[0]["reason"]


def test_external_id_is_stable_hash():
    rows, _ = parse_csv_to_bet_rows(io.StringIO(SAMPLE_OK))
    # Same CSV parsed twice → same external_ids
    rows2, _ = parse_csv_to_bet_rows(io.StringIO(SAMPLE_OK))
    assert [r.external_id for r in rows] == [r.external_id for r in rows2]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest server/tests/test_bets_csv.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `server/odds/bets_csv.py`**

```python
"""CSV → BetRow translator.

Format (header row required):
  date,book,sport,event,market,side,odds,stake,result

  date    YYYY-MM-DD or ISO datetime
  book    free text → source_book ('imported' for all CSV rows;
          the user's book text is stored in raw_description prefix)
  sport   our internal sport_key (mlb, nba, ...)
  event   free text matchup, optional
  market  market_key-ish ('h2h', 'spreads -1.5', 'totals 8.5', 'player_points')
  side    team name / Over / Under / player name + O/U
  odds    American odds, e.g. -145 or +155
  stake   dollars
  result  W | L | P | void | pending

Rows whose required fields are missing or unparseable are returned in
the `errors` list. Good rows are still returned.
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TextIO

from .bets import BetRow


REQUIRED_COLUMNS = ("date", "book", "sport", "market", "side", "odds", "stake", "result")

_RESULT_STATUS = {
    "W": "win", "L": "loss", "P": "push",
    "void": "void", "pending": "pending",
    "w": "win", "l": "loss", "p": "push",
}


@dataclass(frozen=True)
class CSVError:
    row: int
    reason: str


def _parse_odds(s: str) -> int:
    return int(s.strip().lstrip("+"))


def _parse_date(s: str) -> datetime:
    s = s.strip()
    # Try date-only first, then ISO
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    # Last resort
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _external_id(date_s: str, book: str, sport: str, event: str,
                 side: str, odds: str, stake: str) -> str:
    payload = "|".join((date_s, book, sport, event, side, odds, stake)).encode()
    return hashlib.sha1(payload).hexdigest()[:16]


def parse_csv_to_bet_rows(stream: TextIO) -> tuple[list[BetRow], list[dict]]:
    """Parse a CSV stream. Returns (good_rows, errors). Errors is a
    list of {row: int (1-indexed, header=row 1), reason: str}."""
    reader = csv.DictReader(stream)
    if reader.fieldnames is None or not set(REQUIRED_COLUMNS).issubset({c.strip() for c in reader.fieldnames}):
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        return [], [{"row": 1, "reason": f"missing required columns: {sorted(missing)}"}]

    good: list[BetRow] = []
    errors: list[dict] = []
    now = datetime.now(timezone.utc)

    for i, raw in enumerate(reader, start=2):  # row 2 is the first data row
        try:
            book = raw["book"].strip()
            sport = raw["sport"].strip()
            event = (raw.get("event") or "").strip()
            market = raw["market"].strip()
            side = raw["side"].strip()
            stake_s = raw["stake"].strip()
            odds_s = raw["odds"].strip()
            result_s = raw["result"].strip()
            date_s = raw["date"].strip()
            stake = float(stake_s)
            odds = _parse_odds(odds_s)
            accepted_at = _parse_date(date_s)
        except (KeyError, ValueError, AttributeError) as e:
            errors.append({"row": i, "reason": f"parse error: {e}"})
            continue

        status = _RESULT_STATUS.get(result_s)
        if status is None:
            errors.append({"row": i, "reason": f"invalid result '{result_s}'"})
            continue

        # Pull point off market string (e.g. "spreads -1.5" → market_key="spreads", point=-1.5)
        parts = market.split()
        market_key = parts[0] if parts else market
        outcome_point = 0.0
        if len(parts) > 1:
            try:
                outcome_point = float(parts[1])
            except ValueError:
                outcome_point = 0.0

        good.append(BetRow(
            source_book="imported",
            external_id=_external_id(date_s, book, sport, event, side, odds_s, stake_s),
            customer_id=None,
            accepted_at=accepted_at,
            settled_at=None,
            status=status,
            wager_type="straight",
            total_picks=1,
            sport_key=sport,
            event_id=None,
            home_team=None,
            away_team=None,
            market_key=market_key,
            outcome_name=side,
            outcome_point=outcome_point,
            odds_american=odds,
            stake=stake,
            to_win=None,
            settled_amount=None,
            is_free_play=False,
            raw_description=event or f"{book}: {market} {side}",
            imported_at=now,
        ))
    return good, errors
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_bets_csv.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/odds/bets_csv.py server/tests/test_bets_csv.py
git commit -m "$(cat <<'EOF'
feat(bets): CSV import parser + BetRow translator

Documented schema with sha1-keyed external_id for idempotent
re-imports. Bad rows surfaced in the errors list; good rows still
returned. CSV rows always import as source_book='imported' with the
user's book name preserved in raw_description.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — API endpoints

### Task 9: `GET /api/bets` and `GET /api/bets/rollups`

**Files:**
- Create: `server/api/bets.py`
- Modify: `server/main.py` (register router)
- Test: `server/tests/test_bets_api.py`

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_bets_api.py`:

```python
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.odds.cache import OddsCache
from server.odds.bets import BetRow, upsert_bets
from server.api.bets import build_router as bets_router


@pytest.fixture
def app_and_cache(tmp_path: Path):
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    app = FastAPI()
    app.include_router(bets_router(cache))
    upsert_bets(cache, [BetRow(
        source_book="coral33", external_id="t1", customer_id="cust1",
        accepted_at=datetime(2026, 6, 19, tzinfo=timezone.utc),
        settled_at=datetime(2026, 6, 19, 23, tzinfo=timezone.utc),
        status="win", wager_type="straight", total_picks=1,
        sport_key="mlb", event_id=None,
        home_team="LAD", away_team="SF",
        market_key="h2h", outcome_name="LAD", outcome_point=0.0,
        odds_american=-145, stake=50.0, to_win=34.5,
        settled_amount=84.5, is_free_play=False,
        raw_description="LAD ML", imported_at=None,
    )])
    return app, cache


def test_get_bets_returns_unified_rows(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    r = client.get("/api/bets")
    assert r.status_code == 200
    body = r.json()
    assert body["total_count"] == 1
    assert body["bets"][0]["source_book"] == "coral33"


def test_get_bets_filters_by_book(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    assert client.get("/api/bets?book=coral33").json()["total_count"] == 1
    assert client.get("/api/bets?book=kalshi").json()["total_count"] == 0


def test_get_rollups_returns_all_windows(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    r = client.get("/api/bets/rollups")
    assert r.status_code == 200
    body = r.json()
    for k in ("window_30d", "window_90d", "lifetime", "by_book", "by_sport", "by_market"):
        assert k in body
    assert body["lifetime"]["count"] == 1
    assert len(body["by_book"]) == 1
    assert body["by_book"][0]["source_book"] == "coral33"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest server/tests/test_bets_api.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `server/api/bets.py`**

```python
"""HTTP endpoints for the unified bet tracker.

  GET  /api/bets                  — list with filters + CLV per row
  GET  /api/bets/rollups          — 30d/90d/lifetime + by_book/sport/market
  POST /api/bets/import           — CSV upload (Task 10)
  GET  /api/bets/import/template  — example CSV download (Task 10)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..odds.bets import query_bets, rollups
from ..odds.cache import OddsCache
from ..odds.clv import lookup_clv_for_bet


logger = logging.getLogger(__name__)


class BetModel(BaseModel):
    source_book: str
    external_id: str
    customer_id: str | None = None
    accepted_at: datetime
    settled_at: datetime | None = None
    status: str
    wager_type: str
    total_picks: int
    sport_key: str | None = None
    event_id: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    market_key: str | None = None
    outcome_name: str | None = None
    outcome_point: float = 0.0
    odds_american: int | None = None
    stake: float
    to_win: float | None = None
    settled_amount: float | None = None
    is_free_play: bool = False
    raw_description: str | None = None
    clv_pct: float | None = None


class BetsResponse(BaseModel):
    bets: list[BetModel]
    total_count: int


class WindowRollup(BaseModel):
    count: int
    wagered: float
    net: float
    roi_pct: float


class GroupRollup(BaseModel):
    source_book: str | None = None
    sport_key: str | None = None
    market_key: str | None = None
    count: int
    wagered: float
    net: float
    roi_pct: float


class RollupsResponse(BaseModel):
    window_30d: WindowRollup
    window_90d: WindowRollup
    lifetime: WindowRollup
    by_book: list[GroupRollup]
    by_sport: list[GroupRollup]
    by_market: list[GroupRollup]


def _attach_clv(rows: list[dict], cache: OddsCache) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        clv_pct: float | None = None
        try:
            res = lookup_clv_for_bet(r, cache)
            if res is not None:
                clv_pct = round(res.clv_pct * 100.0, 2)
        except Exception:
            logger.exception("CLV lookup failed for bet %s:%s",
                             r.get("source_book"), r.get("external_id"))
        r = {**r, "is_free_play": bool(r.get("is_free_play")), "clv_pct": clv_pct}
        out.append(r)
    return out


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/bets", response_model=BetsResponse)
    def get_bets(
        status: Optional[str] = Query(default=None, description="open|win|loss|push|void|pending"),
        book: Optional[str] = Query(default=None),
        sport: Optional[str] = Query(default=None),
        market_key: Optional[str] = Query(default=None),
        from_: Optional[str] = Query(default=None, alias="from"),
        to: Optional[str] = Query(default=None),
        limit: Optional[int] = Query(default=None, ge=1, le=10000),
    ) -> BetsResponse:
        rows = query_bets(
            cache,
            book=book, sport=sport, status=status, market_key=market_key,
            from_iso=from_, to_iso=to, limit=limit,
        )
        rows = _attach_clv(rows, cache)
        return BetsResponse(
            bets=[BetModel.model_validate(r) for r in rows],
            total_count=len(rows),
        )

    @router.get("/api/bets/rollups", response_model=RollupsResponse)
    def get_rollups() -> RollupsResponse:
        return RollupsResponse.model_validate(rollups(cache))

    return router
```

- [ ] **Step 4: Wire router in `server/main.py`**

Find the section where routers are included (search for `app.include_router(` lines near the bottom of `create_app`) and add:

```python
from .api.bets import build_router as bets_router
app.include_router(bets_router(cache))
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_bets_api.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 6: Commit**

```bash
git add server/api/bets.py server/main.py server/tests/test_bets_api.py
git commit -m "$(cat <<'EOF'
feat(api): GET /api/bets + /api/bets/rollups

Filtered bet list with CLV computed at query time per row, plus
rollup payload powering the new /bets dashboard. Wired into the
FastAPI app router.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: `POST /api/bets/import` + template download

**Files:**
- Modify: `server/api/bets.py`
- Modify: `server/tests/test_bets_api.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_bets_api.py`:

```python
import io


def test_csv_import_round_trip(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    csv_body = (
        "date,book,sport,event,market,side,odds,stake,result\n"
        "2026-06-19,DraftKings,nba,MIA @ BOS,h2h,BOS,-145,50,W\n"
        "2026-06-20,FanDuel,mlb,LAD @ SF,spreads -1.5,LAD,+155,25,pending\n"
    )
    r = client.post(
        "/api/bets/import",
        files={"file": ("bets.csv", io.BytesIO(csv_body.encode()), "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 2
    assert body["rejected"] == []
    # And they're queryable
    list_r = client.get("/api/bets?book=imported")
    assert list_r.json()["total_count"] == 2


def test_csv_import_reports_bad_rows(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    csv_body = (
        "date,book,sport,event,market,side,odds,stake,result\n"
        "not-a-date,DK,nba,X @ Y,h2h,X,-110,50,W\n"
        "2026-06-19,DK,nba,A @ B,h2h,A,+110,25,L\n"
    )
    r = client.post(
        "/api/bets/import",
        files={"file": ("bets.csv", io.BytesIO(csv_body.encode()), "text/csv")},
    )
    body = r.json()
    assert body["accepted"] == 1
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["row"] == 2  # first data row


def test_template_endpoint_returns_csv(app_and_cache):
    app, _ = app_and_cache
    client = TestClient(app)
    r = client.get("/api/bets/import/template")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "date,book,sport" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest server/tests/test_bets_api.py -v -k "import or template"
```

Expected: 404 / not found.

- [ ] **Step 3: Implement — append to `server/api/bets.py`**

Add imports near the top:

```python
import io
from fastapi import UploadFile, File
from fastapi.responses import Response, PlainTextResponse

from ..odds.bets_csv import parse_csv_to_bet_rows
from ..odds.bets import upsert_bets
```

Add inside `build_router`:

```python
    class ImportResponse(BaseModel):
        accepted: int
        rejected: list[dict]

    @router.post("/api/bets/import", response_model=ImportResponse)
    async def post_import(file: UploadFile = File(...)) -> ImportResponse:
        body = (await file.read()).decode("utf-8", errors="replace")
        rows, errors = parse_csv_to_bet_rows(io.StringIO(body))
        # Reject any imported row that collides with a coral33 ticket
        # (the mirror is authoritative for coral33).
        filtered_errors = list(errors)
        coral33_ids = {
            r["external_id"] for r in query_bets(cache, book="coral33", limit=10000)
        }
        accepted: list = []
        for i, r in enumerate(rows, start=2):
            if r.external_id in coral33_ids:
                filtered_errors.append({
                    "row": i,
                    "reason": "external_id collides with an existing coral33 ticket",
                })
                continue
            accepted.append(r)
        if accepted:
            upsert_bets(cache, accepted)
        return ImportResponse(accepted=len(accepted), rejected=filtered_errors)

    _TEMPLATE_CSV = (
        "date,book,sport,event,market,side,odds,stake,result\n"
        "2026-06-19,DraftKings,nba,MIA @ BOS,h2h,BOS,-145,50,W\n"
        "2026-06-20,FanDuel,mlb,LAD @ SF,spreads -1.5,LAD,+155,25,pending\n"
        "2026-06-20,Pinnacle,tennis,Sinner vs Alcaraz,h2h,Alcaraz,+105,100,L\n"
    )

    @router.get("/api/bets/import/template")
    def get_template() -> Response:
        return PlainTextResponse(
            _TEMPLATE_CSV,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="bets-template.csv"'},
        )

    return router
```

(Note: replace the existing `return router` with the new block above so it's the final line of the function.)

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_bets_api.py -v
```

Expected: all 6 tests pass (3 original + 3 new).

- [ ] **Step 5: Commit**

```bash
git add server/api/bets.py server/tests/test_bets_api.py
git commit -m "$(cat <<'EOF'
feat(api): POST /api/bets/import + template download

Multipart CSV upload returning per-row accepted/rejected stats.
Coral33 ticket collisions are rejected so the wager-log mirror stays
authoritative.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5 — Wiring

### Task 11: Schedule sync jobs in lifespan

**Files:**
- Modify: `server/main.py` (extend `_wager_log_refresh_tick` and add new sync jobs to `clv_scheduler`)

- [ ] **Step 1: Locate the existing wager-log refresh tick in `server/main.py`** (currently lines 130-140, function `_wager_log_refresh_tick`).

- [ ] **Step 2: Extend the wager-log tick to capture-and-mirror in one pass**

Replace the body of `_wager_log_refresh_tick` with a capture-then-mirror pattern. **Don't** call `get_wager_log` twice — that would race the just-refreshed cache against the second read.

```python
async def _wager_log_refresh_tick():
    """Re-pull the wager log so newly-placed bets appear without the
    user having to hit ?force_wager_log=true. Coral33's wager-log
    endpoint costs ~14 calls per account per refresh; 8 accounts ×
    30-min cadence = 224 calls/hour, well under their rate limit.
    Settled wagers are immutable so re-pulling is cheap on the
    persistence side (JSON overwrite). After refreshing, mirror the
    log into the unified `bets` table so /api/bets is in sync.
    """
    try:
        wager_log = await accounts_scraper.get_wager_log(force=True)
    except Exception:
        logging.exception("wager-log refresh tick failed")
        return
    try:
        from .odds.books.coral33.bets_mirror import mirror_coral33_wager_log_to_bets
        mirror_coral33_wager_log_to_bets(cache, wager_log)
    except Exception:
        logging.exception("coral33 bets mirror tick failed")
```

- [ ] **Step 3: Add Kalshi + Polymarket sync jobs**

In the `lifespan` function, inside the `if initial_mode == CacheMode.LIVE:` block, after the `wager_log_refresh` job is added, add:

```python
# Kalshi portfolio sync — pulls auth'd fills into the bets table.
# 5-min cadence. No-op if Kalshi auth isn't configured.
async def _kalshi_portfolio_tick():
    try:
        if not kalshi_fetcher.client.is_authenticated:
            return
        from .odds.books.kalshi.portfolio_sync import sync_kalshi_fills
        await sync_kalshi_fills(client=kalshi_fetcher.client, cache=cache)
    except Exception:
        logging.exception("kalshi portfolio sync tick failed")

clv_scheduler.add_job(
    _kalshi_portfolio_tick,
    trigger="interval", minutes=5,
    id="kalshi_portfolio_sync", replace_existing=True, max_instances=1,
)

# Polymarket trade sync — wallet-keyed, no auth needed.
async def _polymarket_portfolio_tick():
    try:
        wallet = settings_store.get().get("polymarket_wallet_address", "")
        if not wallet:
            return
        from .odds.books.polymarket.portfolio_sync import sync_polymarket_trades
        await sync_polymarket_trades(
            client=polymarket_fetcher.client,
            cache=cache,
            wallet_address=wallet,
        )
    except Exception:
        logging.exception("polymarket portfolio sync tick failed")

clv_scheduler.add_job(
    _polymarket_portfolio_tick,
    trigger="interval", minutes=5,
    id="polymarket_portfolio_sync", replace_existing=True, max_instances=1,
)
```

(`kalshi_fetcher.client` and `polymarket_fetcher.client` are both already public attributes — verified at `server/odds/books/kalshi/fetcher.py:95` and `server/odds/books/polymarket/fetcher.py:79`.)

- [ ] **Step 4: Verify the server still starts**

```bash
# Stop any running uvicorn
lsof -ti :8000 | xargs -r kill
# Start fresh
.venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
sleep 4
curl -s http://127.0.0.1:8000/api/bets | head -c 200
```

Expected: 200 response with `{"bets": [], "total_count": 0}` (or any populated body, depending on whether wager-log mirror has run).

Tail the log for the new scheduler entries:

```bash
grep -E "kalshi_portfolio|polymarket_portfolio|wager_log_refresh" /tmp/uvicorn.log
```

- [ ] **Step 5: Commit**

```bash
git add server/main.py
git commit -m "$(cat <<'EOF'
feat(lifespan): schedule kalshi/polymarket portfolio sync + coral33 mirror

Kalshi (5min) + Polymarket (5min) jobs added to clv_scheduler.
Coral33 mirror folded into the existing 30min wager-log refresh tick.
Each task no-ops gracefully if its credentials/wallet aren't set.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Convert `/api/coral33/accounts/bets` into a wrapper

**Files:**
- Modify: `server/api/coral33_accounts.py`
- Test: existing `server/tests/test_api.py` (the existing /accounts/bets test should keep passing)

- [ ] **Step 1: Replace the `/api/coral33/accounts/bets` handler body**

Locate the existing handler in `server/api/coral33_accounts.py:292`. Replace its in-handler bet-construction logic with a call into `query_bets`:

```python
@router.get(
    "/api/coral33/accounts/bets",
    response_model=BetsResponse,
)
async def get_bets(
    status: str = Query(default="any"),
    force_wager_log: bool = Query(default=False),
) -> BetsResponse:
    """Backward-compat wrapper. Returns coral33-sourced bets from the
    unified `bets` table. The wager-log mirror tick populates the
    table; this endpoint just queries + filters.
    """
    from ..odds.books.coral33.wager_log import DEFAULT_BACKFILL_WEEKS
    from ..odds.bets import query_bets
    from ..odds.clv import lookup_clv_for_bet

    # Optional force-refresh path: kick the wager log + re-mirror.
    if force_wager_log:
        from ..odds.books.coral33.bets_mirror import mirror_coral33_wager_log_to_bets
        wager_log = await scraper.get_wager_log(force=True)
        if cache is not None:
            mirror_coral33_wager_log_to_bets(cache, wager_log)

    status_norm = status.lower().strip() if status else "any"
    db_status: str | None
    if status_norm == "open":
        db_status = "open"
    elif status_norm == "settled":
        db_status = None  # filter below
    else:
        db_status = None

    rows = query_bets(cache, book="coral33", status=db_status)
    if status_norm == "settled":
        rows = [r for r in rows if r["status"] not in ("open", "pending")]

    # Re-shape into the existing BetEntryModel surface for backward
    # compat. The wrapper preserves the v1 contract so the /accounts
    # page keeps working untouched.
    out: list[BetEntryModel] = []
    creds_by_id = {c.customer_id: c for c in scraper.credentials}
    for r in rows:
        clv_pct: float | None = None
        try:
            res = lookup_clv_for_bet(r, cache)
            if res is not None:
                clv_pct = round(res.clv_pct * 100.0, 2)
        except Exception:
            pass
        cid = r.get("customer_id") or ""
        cred = creds_by_id.get(cid)
        label = (cred.label if cred and cred.label else cid) if cid else "Coral33"
        out.append(BetEntryModel(
            customer_id=cid,
            account_label=label,
            ticket_number=int(r["external_id"]) if r["external_id"].isdigit() else 0,
            accepted_at=r["accepted_at"],
            settled_at=r.get("settled_at"),
            wager_status=r["status"][:1].upper(),
            wager_type=r["wager_type"][:1].upper(),
            total_picks=r["total_picks"],
            amount_wagered=r["stake"],
            to_win_amount=r.get("to_win") or 0.0,
            amount_won=(r.get("settled_amount") or 0) - r["stake"] if r["status"] == "win" else 0.0,
            amount_lost=r["stake"] if r["status"] == "loss" else 0.0,
            is_free_play=bool(r.get("is_free_play")),
            sport_type=None,
            sport_sub_type=r.get("sport_key"),
            period=None,
            team1_id=r.get("home_team"),
            team2_id=r.get("away_team"),
            chosen_team_id=r.get("outcome_name"),
            description=r.get("raw_description"),
            final_money=r.get("odds_american"),
            adj_spread=r.get("outcome_point") if (r.get("market_key") or "").startswith("spread") else None,
            adj_total_points=r.get("outcome_point") if (r.get("market_key") or "").startswith("total") else None,
            clv_pct=clv_pct,
        ))

    return BetsResponse(
        bets=out, total_count=len(out),
        backfill_weeks=DEFAULT_BACKFILL_WEEKS,
    )
```

(Note: the original handler's customer_id semantics are dropped here. If the existing test asserts on customer_id, this needs to round-trip through a join — see Step 2.)

- [ ] **Step 2: Check the existing tests still pass**

```bash
.venv/bin/python -m pytest server/tests/test_api.py -v -k "bets or accounts"
```

If any test fails because `customer_id` is wrong, that's expected — the original handler reads it from the wager log. The right fix is to add a `customer_id` column to the `bets` table (Phase 1 migration) and propagate it through the mirror. If failures appear, do that fix as a follow-up before continuing.

- [ ] **Step 3: Restart the server and smoke-test in browser**

```bash
lsof -ti :8000 | xargs -r kill
.venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
sleep 4
curl -s "http://127.0.0.1:8000/api/coral33/accounts/bets?status=any" | head -c 500
```

Expected: JSON with the same shape the /accounts page consumes today (`{bets: [...], total_count, backfill_weeks}`).

- [ ] **Step 4: Commit**

```bash
git add server/api/coral33_accounts.py
git commit -m "$(cat <<'EOF'
refactor(coral33): /accounts/bets reads from unified bets table

The handler now queries the unified bets table (populated by the
mirror tick) and reshapes into the BetEntryModel contract that the
existing /accounts UI consumes. Keeps the v1 surface stable while
the new /bets page is built against /api/bets.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6 — Frontend

### Task 13: Add recharts + scaffold `/bets` route

**Files:**
- Modify: `web/package.json`
- Create: `web/app/bets/page.tsx`
- Create: `web/app/bets/layout.tsx` (if needed for the section)

- [ ] **Step 1: Install recharts**

```bash
cd web && npm install recharts && cd ..
git add web/package.json web/package-lock.json
```

- [ ] **Step 2: Scaffold the page**

Create `web/app/bets/page.tsx`:

```tsx
"use client";

import useSWR from "swr";
import { fetchJson } from "@/lib/api";

// NOTE: fetchJson() in web/lib/api.ts already prepends
// NEXT_PUBLIC_API_BASE_URL — SWR keys must be relative paths.

export default function BetsPage() {
  const { data: rollups } = useSWR("/api/bets/rollups", fetchJson);
  const { data: bets } = useSWR("/api/bets", fetchJson);

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">Bets</h1>
      <pre className="text-xs bg-bg-1 p-3 rounded overflow-auto">
        rollups: {JSON.stringify(rollups, null, 2)}
      </pre>
      <pre className="text-xs bg-bg-1 p-3 rounded overflow-auto max-h-96">
        bets: {JSON.stringify(bets, null, 2)}
      </pre>
    </div>
  );
}
```

This is a working skeleton — the real components come in tasks 14-17 and replace the `<pre>` blocks one by one.

- [ ] **Step 3: Smoke-test in the browser**

```bash
# Dev server should already be running. Visit:
open http://localhost:3000/bets
```

Expected: the page renders with raw JSON dumps of rollups + bets.

- [ ] **Step 4: Commit**

```bash
git add web/package.json web/package-lock.json web/app/bets/page.tsx
git commit -m "$(cat <<'EOF'
feat(web): add recharts dep + scaffold /bets page

Working route consuming /api/bets and /api/bets/rollups via SWR. Real
components land in follow-up tasks; this commit just establishes the
route and dependency.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Rollup tiles + CLV trend chart

**Files:**
- Create: `web/app/bets/_components/RollupTiles.tsx`
- Create: `web/app/bets/_components/CLVChart.tsx`
- Modify: `web/app/bets/page.tsx`

- [ ] **Step 1: Implement `RollupTiles.tsx`**

```tsx
"use client";

interface Window {
  count: number;
  wagered: number;
  net: number;
  roi_pct: number;
}

interface Rollups {
  window_30d: Window;
  window_90d: Window;
  lifetime: Window;
}

const fmtPct = (v: number) =>
  `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const fmtUsd = (v: number) =>
  v.toLocaleString("en-US", { style: "currency", currency: "USD" });

export function RollupTiles({ data }: { data: Rollups | undefined }) {
  if (!data) {
    return <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {[0,1,2,3].map(i => (
        <div key={i} className="h-24 rounded bg-bg-1 animate-pulse" />
      ))}
    </div>;
  }
  const tile = (label: string, w: Window) => (
    <div className="rounded border border-border-subtle bg-bg-1 p-3">
      <div className="text-[10px] uppercase tracking-wider text-text-3">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular">
        ROI {fmtPct(w.roi_pct)}
      </div>
      <div className="text-xs text-text-2">{w.count} bets · {fmtUsd(w.wagered)}</div>
    </div>
  );
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {tile("30 DAY", data.window_30d)}
      {tile("90 DAY", data.window_90d)}
      {tile("LIFETIME", data.lifetime)}
      <div className="rounded border border-border-subtle bg-bg-1 p-3">
        <div className="text-[10px] uppercase tracking-wider text-text-3">NET LIFETIME</div>
        <div className="mt-1 text-lg font-semibold tabular">
          {fmtUsd(data.lifetime.net)}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement `CLVChart.tsx`**

```tsx
"use client";

import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from "recharts";

interface Bet {
  accepted_at: string;
  clv_pct: number | null;
}

export function CLVChart({ bets }: { bets: Bet[] | undefined }) {
  if (!bets) {
    return <div className="h-48 rounded bg-bg-1 animate-pulse" />;
  }
  // Bin by day, average CLV per day
  const byDay = new Map<string, { sum: number; count: number }>();
  for (const b of bets) {
    if (b.clv_pct == null) continue;
    const day = b.accepted_at.slice(0, 10);
    const cur = byDay.get(day) ?? { sum: 0, count: 0 };
    cur.sum += b.clv_pct;
    cur.count += 1;
    byDay.set(day, cur);
  }
  const series = [...byDay.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([day, s]) => ({ day, clv: s.sum / s.count }));

  return (
    <div className="h-48 rounded border border-border-subtle bg-bg-1 p-3">
      <div className="text-[10px] uppercase tracking-wider text-text-3 mb-2">
        CLV % over time
      </div>
      <ResponsiveContainer width="100%" height="85%">
        <LineChart data={series}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
          <XAxis dataKey="day" tick={{ fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip
            contentStyle={{ background: "var(--bg-1)", border: "1px solid var(--border-subtle)" }}
            formatter={(v: number) => `${v.toFixed(2)}%`}
          />
          <Line type="monotone" dataKey="clv" stroke="var(--accent)" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 3: Wire into `page.tsx`**

Replace `web/app/bets/page.tsx` body to use the new components:

```tsx
"use client";

import useSWR from "swr";
import { fetchJson } from "@/lib/api";
import { RollupTiles } from "./_components/RollupTiles";
import { CLVChart } from "./_components/CLVChart";

export default function BetsPage() {
  const { data: rollups } = useSWR("/api/bets/rollups", fetchJson);
  const { data: betsResp } = useSWR("/api/bets", fetchJson);

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">Bets</h1>
      <RollupTiles data={rollups} />
      <CLVChart bets={betsResp?.bets} />
    </div>
  );
}
```

- [ ] **Step 4: Smoke-test**

Visit http://localhost:3000/bets. Tiles + chart should render. Empty state if no bets yet.

- [ ] **Step 5: Commit**

```bash
git add web/app/bets/_components/RollupTiles.tsx web/app/bets/_components/CLVChart.tsx web/app/bets/page.tsx
git commit -m "$(cat <<'EOF'
feat(web): bets page rollup tiles + CLV trend chart

ROI tiles (30d/90d/lifetime/net) and per-day-binned CLV line chart
via recharts. Both subscribe to /api/bets/rollups and /api/bets,
auto-revalidated by the existing useLiveUpdates SSE hook.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: Filters + Breakdowns

**Files:**
- Create: `web/app/bets/_components/Filters.tsx`
- Create: `web/app/bets/_components/Breakdowns.tsx`
- Modify: `web/app/bets/page.tsx`

- [ ] **Step 1: Implement `Filters.tsx`**

```tsx
"use client";

import { useState } from "react";

export interface BetFilters {
  book: string;
  sport: string;
  status: string;
}

export function Filters({
  value, onChange,
}: { value: BetFilters; onChange: (next: BetFilters) => void }) {
  const sel = "rounded border border-border-subtle bg-bg-1 text-sm px-2 py-1";
  return (
    <div className="flex flex-wrap gap-2 items-center">
      <select className={sel} value={value.book}
              onChange={e => onChange({ ...value, book: e.target.value })}>
        <option value="">All books</option>
        <option value="coral33">Coral33</option>
        <option value="kalshi">Kalshi</option>
        <option value="polymarket">Polymarket</option>
        <option value="imported">Imported</option>
      </select>
      <select className={sel} value={value.sport}
              onChange={e => onChange({ ...value, sport: e.target.value })}>
        <option value="">All sports</option>
        <option value="mlb">MLB</option>
        <option value="nba">NBA</option>
        <option value="nfl">NFL</option>
        <option value="tennis">Tennis</option>
        <option value="soccer">Soccer</option>
        <option value="ufc">UFC</option>
      </select>
      <select className={sel} value={value.status}
              onChange={e => onChange({ ...value, status: e.target.value })}>
        <option value="">All statuses</option>
        <option value="open">Open</option>
        <option value="win">Win</option>
        <option value="loss">Loss</option>
        <option value="push">Push</option>
        <option value="pending">Pending</option>
      </select>
    </div>
  );
}
```

- [ ] **Step 2: Implement `Breakdowns.tsx`**

```tsx
"use client";

interface Group {
  source_book?: string;
  sport_key?: string;
  market_key?: string;
  count: number;
  wagered: number;
  net: number;
  roi_pct: number;
}

interface Rollups {
  by_book: Group[];
  by_sport: Group[];
  by_market: Group[];
}

const fmtPct = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;

function Table({ title, rows, keyCol }: {
  title: string;
  rows: Group[];
  keyCol: "source_book" | "sport_key" | "market_key";
}) {
  return (
    <div className="rounded border border-border-subtle bg-bg-1 p-3">
      <div className="text-[10px] uppercase tracking-wider text-text-3 mb-2">{title}</div>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-text-3">
            <th className="text-left font-normal">Group</th>
            <th className="text-right font-normal">Bets</th>
            <th className="text-right font-normal">ROI</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={3} className="py-2 text-text-3">No data</td></tr>
          ) : rows.map(r => (
            <tr key={r[keyCol] ?? "—"} className="border-t border-border-subtle">
              <td className="py-1">{r[keyCol] ?? "—"}</td>
              <td className="py-1 text-right tabular">{r.count}</td>
              <td className="py-1 text-right tabular">{fmtPct(r.roi_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Breakdowns({ data }: { data: Rollups | undefined }) {
  if (!data) return null;
  return (
    <div className="grid md:grid-cols-3 gap-3">
      <Table title="BY BOOK"   rows={data.by_book}   keyCol="source_book" />
      <Table title="BY SPORT"  rows={data.by_sport}  keyCol="sport_key"   />
      <Table title="BY MARKET" rows={data.by_market} keyCol="market_key"  />
    </div>
  );
}
```

- [ ] **Step 3: Wire filters + breakdowns into `page.tsx`**

```tsx
"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetchJson } from "@/lib/api";
import { RollupTiles } from "./_components/RollupTiles";
import { CLVChart } from "./_components/CLVChart";
import { Filters, BetFilters } from "./_components/Filters";
import { Breakdowns } from "./_components/Breakdowns";

export default function BetsPage() {
  const [filters, setFilters] = useState<BetFilters>({ book: "", sport: "", status: "" });
  const qs = new URLSearchParams(
    Object.entries(filters).filter(([_, v]) => v),
  ).toString();
  const { data: rollups } = useSWR("/api/bets/rollups", fetchJson);
  const { data: betsResp } = useSWR(
    `/api/bets${qs ? `?${qs}` : ""}`, fetchJson,
  );

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">Bets</h1>
      <RollupTiles data={rollups} />
      <CLVChart bets={betsResp?.bets} />
      <Breakdowns data={rollups} />
      <Filters value={filters} onChange={setFilters} />
    </div>
  );
}
```

- [ ] **Step 4: Smoke-test**

Visit http://localhost:3000/bets and confirm filters change the URL query and that the request fires (DevTools Network).

- [ ] **Step 5: Commit**

```bash
git add web/app/bets/_components/Filters.tsx web/app/bets/_components/Breakdowns.tsx web/app/bets/page.tsx
git commit -m "$(cat <<'EOF'
feat(web): bets page filters + breakdown tables

Three-up breakdown grid (by book / sport / market). Filter bar
controls the /api/bets request directly via useSWR key change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: Bet history table

**Files:**
- Create: `web/app/bets/_components/BetTable.tsx`
- Modify: `web/app/bets/page.tsx`

- [ ] **Step 1: Adapt the existing `/accounts` table**

The `/accounts` page already has a `BetRow` component (around `web/app/accounts/page.tsx:1504`). The new `/bets` table mirrors that styling but reads the unified shape (`source_book`, `sport_key`, etc. instead of the Coral33-specific fields).

Create `web/app/bets/_components/BetTable.tsx`:

```tsx
"use client";

import clsx from "clsx";

interface Bet {
  source_book: string;
  external_id: string;
  accepted_at: string;
  settled_at: string | null;
  status: string;
  wager_type: string;
  total_picks: number;
  sport_key: string | null;
  market_key: string | null;
  outcome_name: string | null;
  odds_american: number | null;
  stake: number;
  to_win: number | null;
  settled_amount: number | null;
  is_free_play: boolean;
  raw_description: string | null;
  clv_pct: number | null;
}

const fmtDate = (s: string) => s.slice(5, 10);  // MM-DD
const fmtOdds = (n: number | null) => n == null ? "—" : (n > 0 ? `+${n}` : `${n}`);
const fmtUsd = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD" });

const STATUS_TONE: Record<string, string> = {
  open:    "text-text-2 bg-bg-2",
  win:     "text-price-up bg-price-up/15",
  loss:    "text-price-down bg-price-down/15",
  push:    "text-text-2 bg-bg-2",
  void:    "text-text-3 bg-bg-2",
  pending: "text-text-2 bg-bg-2",
};

export function BetTable({ bets }: { bets: Bet[] | undefined }) {
  if (!bets) {
    return <div className="h-48 rounded bg-bg-1 animate-pulse" />;
  }
  if (bets.length === 0) {
    return (
      <div className="rounded border border-border-subtle bg-bg-1 p-6 text-center text-text-3">
        No bets yet. Place some on Coral33, configure Kalshi/Polymarket sync in Settings,
        or import a CSV.
      </div>
    );
  }
  return (
    <div className="rounded border border-border-subtle overflow-auto">
      <table className="w-full text-xs">
        <thead className="bg-bg-1 text-text-3">
          <tr>
            <th className="text-left px-2 py-1.5">Date</th>
            <th className="text-left px-2 py-1.5">Book</th>
            <th className="text-left px-2 py-1.5">Sport</th>
            <th className="text-left px-2 py-1.5">Pick</th>
            <th className="text-right px-2 py-1.5">Odds</th>
            <th className="text-right px-2 py-1.5">Stake</th>
            <th className="text-right px-2 py-1.5">Result</th>
            <th className="text-right px-2 py-1.5">CLV</th>
          </tr>
        </thead>
        <tbody>
          {bets.map(b => {
            const net = b.status === "win"
              ? (b.settled_amount ?? 0) - b.stake
              : b.status === "loss" ? -b.stake
              : 0;
            const tone = STATUS_TONE[b.status] ?? "text-text-3 bg-bg-2";
            return (
              <tr key={`${b.source_book}-${b.external_id}`} className="border-t border-border-subtle hover:bg-bg-1">
                <td className="px-2 py-1">{fmtDate(b.accepted_at)}</td>
                <td className="px-2 py-1">{b.source_book}</td>
                <td className="px-2 py-1">{b.sport_key ?? "—"}</td>
                <td className="px-2 py-1 truncate max-w-[260px]">{b.outcome_name ?? b.raw_description ?? "—"}</td>
                <td className="px-2 py-1 text-right tabular">{fmtOdds(b.odds_american)}</td>
                <td className="px-2 py-1 text-right tabular">{fmtUsd(b.stake)}</td>
                <td className={clsx("px-2 py-1 text-right whitespace-nowrap")}>
                  <span className={clsx("inline-flex items-center px-1.5 rounded-sm text-[10px] font-semibold tracking-wider", tone)}>
                    {b.status.toUpperCase()}
                  </span>
                  {b.status !== "open" && b.status !== "pending" && (
                    <span className={clsx("tabular ml-1.5",
                      net > 0 && "text-price-up", net < 0 && "text-price-down", net === 0 && "text-text-3")}>
                      {net > 0 ? "+" : ""}{fmtUsd(Math.abs(net))}
                    </span>
                  )}
                </td>
                <td className="px-2 py-1 text-right tabular">{b.clv_pct == null ? "—" : `${b.clv_pct.toFixed(2)}%`}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Wire into `page.tsx`**

Add `<BetTable bets={betsResp?.bets} />` after `<Filters>` in `page.tsx`. Don't forget the import.

- [ ] **Step 3: Smoke-test**

Reload `/bets`. Confirm the table renders, status pills look right, CLV column populates for matched bets.

- [ ] **Step 4: Commit**

```bash
git add web/app/bets/_components/BetTable.tsx web/app/bets/page.tsx
git commit -m "$(cat <<'EOF'
feat(web): unified bet history table on /bets

Single table rendering all sources (coral33/kalshi/polymarket/imported)
with the CLV column populated from /api/bets. Status chips + signed
net P&L mirror the /accounts table styling.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 17: CSV import drawer

**Files:**
- Create: `web/app/bets/_components/ImportDrawer.tsx`
- Modify: `web/app/bets/page.tsx`

- [ ] **Step 0: Export `BASE` from `web/lib/api.ts`**

`BASE` is module-private today. Make it exported so the ImportDrawer (which uses `fetch()` directly for the file POST, not `fetchJson`) can build absolute URLs:

```diff
-const BASE =
+export const BASE =
   process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
```

- [ ] **Step 1: Implement `ImportDrawer.tsx`**

```tsx
"use client";

import { useState } from "react";
import { useSWRConfig } from "swr";
import { BASE } from "@/lib/api";

interface ImportResult {
  accepted: number;
  rejected: { row: number; reason: string }[];
}

export function ImportDrawer() {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const { mutate } = useSWRConfig();

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true);
    setResult(null);
    try {
      const form = new FormData();
      form.append("file", f);
      const r = await fetch(`${BASE}/api/bets/import`, {
        method: "POST", body: form,
      });
      const body: ImportResult = await r.json();
      setResult(body);
      // Refresh the bets table + rollups
      mutate((k) => typeof k === "string" && k.includes("/api/bets"));
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="rounded border border-border-subtle bg-bg-1 hover:bg-bg-2 px-3 py-1.5 text-sm"
      >
        Import CSV ▾
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-80 rounded border border-border-subtle bg-bg-1 shadow-lg p-3 z-10">
          <p className="text-xs text-text-2 mb-2">
            Upload a CSV of bets from any book. Coral33/Kalshi/Polymarket
            sync automatically — use this for everything else.
          </p>
          <a
            href={`${BASE}/api/bets/import/template`}
            className="text-xs text-accent underline mb-2 inline-block"
          >
            Download template
          </a>
          <input
            type="file" accept=".csv,text/csv"
            onChange={handleFile} disabled={busy}
            className="block w-full text-xs"
          />
          {busy && <p className="text-xs text-text-3 mt-2">Uploading…</p>}
          {result && (
            <div className="mt-3 text-xs">
              <p className="text-price-up">Accepted: {result.accepted}</p>
              {result.rejected.length > 0 && (
                <>
                  <p className="text-price-down mt-1">Rejected: {result.rejected.length}</p>
                  <ul className="mt-1 space-y-0.5 max-h-32 overflow-auto">
                    {result.rejected.map((e, i) => (
                      <li key={i} className="text-text-3">Row {e.row}: {e.reason}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire into `page.tsx`**

Replace the page header:

```tsx
<div className="flex items-center justify-between">
  <h1 className="text-2xl font-semibold">Bets</h1>
  <ImportDrawer />
</div>
```

- [ ] **Step 3: Smoke-test the round trip**

Use the downloaded template, save it locally, upload it, confirm rows appear in the table.

- [ ] **Step 4: Commit**

```bash
git add web/app/bets/_components/ImportDrawer.tsx web/app/bets/page.tsx
git commit -m "$(cat <<'EOF'
feat(web): CSV import drawer on /bets

Header button opens a panel with template-download link + file
picker. POSTs to /api/bets/import, shows per-row accepted/rejected
summary inline, and revalidates the bets table after upload.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 7 — Polish

### Task 18: Remove bet history from `/accounts`, add `/bets` link in nav

**Files:**
- Modify: `web/app/accounts/page.tsx` (remove the bets table section, leave the bets-tab link)
- Modify: `web/components/` — find the sidebar / nav component and add `/bets`

- [ ] **Step 1: Find the nav component**

```bash
grep -rln "href=\"/edges\"\|href='/edges'" web/components web/app | head -5
```

The result is the file that lists sidebar/nav links — that's where the `/bets` entry gets added.

- [ ] **Step 2: Add `/bets` to the nav** with an appropriate lucide-react icon (e.g. `Receipt` or `Wallet`).

- [ ] **Step 3: On `/accounts`**, locate the section that renders the bet-history table (search for `BetRow` / `BetTable` in `web/app/accounts/page.tsx`). Replace it with a small banner:

```tsx
<div className="rounded border border-border-subtle bg-bg-1 p-4 flex items-center justify-between">
  <span className="text-sm text-text-2">Bet history moved to the new <a href="/bets" className="text-accent underline">/bets</a> page.</span>
  <a href="/bets" className="rounded border border-border-subtle bg-bg-2 px-3 py-1.5 text-sm">View bets →</a>
</div>
```

(Keep the pending-wager / balance sections intact — only the bet-history table moves.)

- [ ] **Step 4: Smoke-test both pages**

- `/accounts` shows balances + the redirect banner.
- `/bets` shows the new dashboard.

- [ ] **Step 5: Commit**

```bash
git add web/app/accounts/page.tsx web/components/
git commit -m "$(cat <<'EOF'
feat(web): move bet history from /accounts to /bets

/accounts keeps balance + pending-wager views. Bet history is now on
the dedicated /bets page. Added /bets to the sidebar nav.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verification — manual end-to-end

After all tasks complete:

- [ ] Run full server test suite: `.venv/bin/python -m pytest server/tests/ -q`. Expected: all pass, no new skips beyond the existing 1.
- [ ] Restart server + reload `/bets`. Confirm: tiles populate, chart renders, table shows Coral33 rows.
- [ ] Upload the template CSV (filled in). Confirm: imported rows appear, rollups update.
- [ ] If Kalshi auth + Polymarket wallet are configured, wait 5 min, confirm: Kalshi/Polymarket rows surface.
- [ ] CLV column shows values where `closing_lines` has a match.
- [ ] `/accounts` no longer shows the bet table; the redirect banner is in its place.

---

## Out of scope (deferred follow-ups)

These are intentionally not in this plan:

- Kalshi/Polymarket event-id resolution (rows currently have `event_id=NULL`; CLV is `—` for those). Both sync paths have TODOs at the resolution site. Follow-up: wire `kalshi/event_matcher.py` + `polymarket/event_matcher.py` into the sync paths.
- Polymarket SELL-side trades (early exits). Follow-up: treat SELL as a settle of the matching BUY.
- Manual one-bet entry form. Follow-up: thin form that posts to `/api/bets/import` with a single synthesized row.
- Bet tagging / notes column.
