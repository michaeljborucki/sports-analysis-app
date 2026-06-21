# Tier 4 — Backend Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three Tier 4 backend audit fixes — A6 (single-pass best-price), A8 (distinct_events SQL pushdown), A5 (24h TTL on `_resolved_keys`).

**Architecture:** Three independent internal changes; no public API or scanner-output change. Order: A6 (smallest, pure refactor) → A8 (SQL pushdown, semantics-preserving via HAVING) → A5 (real behavior change, refresh + fallback).

**Tech Stack:** Python 3.11, sqlite3, pytest.

**Spec:** `docs/superpowers/specs/2026-06-21-tier4-backend-perf-design.md`

---

## Pre-flight

```bash
git status
# Should be clean (or only have unstaged user_settings.json)
git log --oneline -3
# Should show: 7c6248c (spec), 136599d (Tier 3 close-out), b4c1c6d (M3)
```

---

## Task 1: A6 — single-pass best-price selection

**Files:**
- Modify: `server/odds/best_odds.py` (add `best_price_dict`)
- Modify: `server/odds/normalize.py:237-245` (use it; remove 3-pass logic)
- Test: `server/tests/test_best_odds.py`

- [ ] **Step 1: Failing test**

Check if `server/tests/test_best_odds.py` exists; if so append, otherwise create. Add:

```python
def test_best_price_dict_picks_highest_payout():
    """Given 3 books at known American odds, returns the dict whose
    price gives the highest payout multiplier to the bettor."""
    from server.odds.best_odds import best_price_dict
    prices = [
        {"bookmaker_key": "draftkings", "price_american": -110},
        {"bookmaker_key": "fanduel",    "price_american": +120},  # best for bettor
        {"bookmaker_key": "betmgm",     "price_american": -120},
    ]
    result = best_price_dict(prices)
    assert result is not None
    assert result["bookmaker_key"] == "fanduel"
    assert result["price_american"] == 120


def test_best_price_dict_empty_returns_none():
    from server.odds.best_odds import best_price_dict
    assert best_price_dict([]) is None


def test_best_price_dict_preserves_full_dict():
    """The returned reference includes ALL keys from the original dict
    (point, fetched_at, etc.), not just bookmaker_key + price_american."""
    from server.odds.best_odds import best_price_dict
    prices = [
        {"bookmaker_key": "dk", "price_american": -110, "point": -2.5, "fetched_at": "ts1"},
        {"bookmaker_key": "fd", "price_american": +110, "point": -2.5, "fetched_at": "ts2"},
    ]
    result = best_price_dict(prices)
    assert result["point"] == -2.5
    assert result["fetched_at"] == "ts2"
```

- [ ] **Step 2: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_best_odds.py -v -k best_price_dict
```

Expected: ImportError on `best_price_dict`.

- [ ] **Step 3: Implement in `server/odds/best_odds.py`**

Append after `pick_best_price`:

```python
def best_price_dict(prices: list[dict]) -> dict | None:
    """Pick the dict from `prices` whose `price_american` gives the
    highest payout multiplier to the bettor. Returns None for an empty
    list.

    Coexists with `pick_best_price` (tuple API, retained for callers
    that work with (bookmaker_key, american_odds) tuples). This dict
    API saves the redundant linear scan in `rows_to_games` to recover
    the original dict from a (book, price) tuple match.
    """
    if not prices:
        return None
    return max(prices, key=lambda p: _american_to_payout_multiplier(p["price_american"]))
```

- [ ] **Step 4: Use it in `normalize.py`**

In `server/odds/normalize.py` around line 178, update the import:

```python
from .best_odds import best_price_dict, median_american_odds
```

(Replacing `pick_best_price` if it was imported.)

Then replace the 3-pass block at lines 237-245:

```python
            for out in outcomes.values():
                price_tuples = [(p["bookmaker_key"], p["price_american"]) for p in out["prices"]]
                best = pick_best_price(price_tuples)
                best_price = None
                if best is not None:
                    best_price = next(
                        p for p in out["prices"]
                        if p["bookmaker_key"] == best[0] and p["price_american"] == best[1]
                    )
                consensus = median_american_odds([p["price_american"] for p in out["prices"]])
                out_list.append({
                    "outcome_name": out["outcome_name"],
                    "prices": out["prices"],
                    "best_price": best_price,
                    "consensus_price_american": consensus,
                })
```

with:

```python
            for out in outcomes.values():
                best_price = best_price_dict(out["prices"])
                consensus = median_american_odds([p["price_american"] for p in out["prices"]])
                out_list.append({
                    "outcome_name": out["outcome_name"],
                    "prices": out["prices"],
                    "best_price": best_price,
                    "consensus_price_american": consensus,
                })
```

- [ ] **Step 5: Run tests + regression sweep**

```bash
.venv/bin/python -m pytest server/tests/test_best_odds.py -v
.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py
```

Expected: new tests pass; no regressions in the existing suite.

- [ ] **Step 6: Commit**

```bash
git add server/odds/best_odds.py server/odds/normalize.py server/tests/test_best_odds.py
git commit -m "$(cat <<'EOF'
perf(normalize): single-pass best-price selection in rows_to_games (A6)

Replaces the three-pass build-tuples / max / find-original-dict pattern
with one max() over the dicts directly. New best_price_dict helper in
best_odds.py coexists with the existing pick_best_price (tuple API
retained for callers/tests). Eliminates the redundant O(N) recovery
scan per outcome.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: A8 — `distinct_events` SQL pushdown via HAVING

**Files:**
- Modify: `server/odds/cache.py:670-702`
- Test: `server/tests/test_cache.py`

- [ ] **Step 1: Failing test**

Append to `server/tests/test_cache.py`:

```python
def test_distinct_events_no_filter_returns_all(tmp_path):
    from datetime import datetime, timezone, timedelta
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    rows = [
        {
            "event_id": f"ev_{i}", "sport_key": "nba",
            "home_team": "BOS", "away_team": "MIA",
            "commence_time": now + timedelta(hours=h),
            "bookmaker_key": "dk", "market_key": "h2h",
            "outcome_name": "BOS", "outcome_point": None,
            "price_american": -110, "fetched_at": now,
        }
        for i, h in enumerate([1, 10, 30, 50])
    ]
    cache.upsert(rows)
    result = cache.distinct_events()
    assert {r["event_id"] for r in result} == {"ev_0", "ev_1", "ev_2", "ev_3"}


def test_distinct_events_within_hours_ahead_filters(tmp_path):
    """SQL pushdown via HAVING returns only events with MAX(commence_time)
    in [now, now+24h]."""
    from datetime import datetime, timezone, timedelta
    from unittest.mock import patch
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    fixed_now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    rows = [
        # 1h ahead — within 24h window
        {"event_id": "ev_soon",  "sport_key": "nba", "home_team": "BOS",
         "away_team": "MIA", "commence_time": fixed_now + timedelta(hours=1),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "BOS",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now},
        # 30h ahead — outside 24h window
        {"event_id": "ev_far",   "sport_key": "nba", "home_team": "BOS",
         "away_team": "MIA", "commence_time": fixed_now + timedelta(hours=30),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "BOS",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now},
        # 5h ago — past
        {"event_id": "ev_past",  "sport_key": "nba", "home_team": "BOS",
         "away_team": "MIA", "commence_time": fixed_now - timedelta(hours=5),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "BOS",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now},
    ]
    cache.upsert(rows)
    with patch("server.odds.cache.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        # Important: timedelta is accessed off cache.py's `datetime` import
        # too in the function body; patch carefully so timedelta still works.
        from datetime import timedelta as _td
        mock_dt.fromisoformat = datetime.fromisoformat
        result = cache.distinct_events(within_hours_ahead=24)
    eids = {r["event_id"] for r in result}
    assert eids == {"ev_soon"}
    # Returned commence_time should be a datetime (per existing API)
    soon = next(r for r in result if r["event_id"] == "ev_soon")
    assert isinstance(soon["commence_time"], datetime)


def test_distinct_events_sport_filter_and_time_filter_combined(tmp_path):
    from datetime import datetime, timezone, timedelta
    from unittest.mock import patch
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    fixed_now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    rows = [
        {"event_id": "nba_soon", "sport_key": "nba", "home_team": "BOS",
         "away_team": "MIA", "commence_time": fixed_now + timedelta(hours=1),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "BOS",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now},
        {"event_id": "mlb_soon", "sport_key": "mlb", "home_team": "LAD",
         "away_team": "SF", "commence_time": fixed_now + timedelta(hours=1),
         "bookmaker_key": "dk", "market_key": "h2h", "outcome_name": "LAD",
         "outcome_point": None, "price_american": -110, "fetched_at": fixed_now},
    ]
    cache.upsert(rows)
    with patch("server.odds.cache.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat = datetime.fromisoformat
        result = cache.distinct_events(within_hours_ahead=24, sport_key="nba")
    assert {r["event_id"] for r in result} == {"nba_soon"}
```

(Note: patching `datetime` is fiddly because `cache.py` also imports `timedelta`. Simpler alternative — accept a `now` kwarg on `distinct_events` for testability. Re-spec to add `now: datetime | None = None` and use that. See implementation step.)

- [ ] **Step 2: Run to verify the no-filter test passes already (sanity baseline) and the time-filter test fails**

```bash
.venv/bin/python -m pytest server/tests/test_cache.py -v -k distinct_events
```

The no-filter test should pass (it doesn't depend on the new logic). The time-filter tests may fail due to `patch` complications OR pass because the existing Python-filter path produces the same answer. Either way, proceed.

If patching is too fiddly, simplify: accept a `now` kwarg on the function and pass `fixed_now` explicitly in tests.

- [ ] **Step 3: Implement**

Replace `distinct_events` in `server/odds/cache.py:670-702` with:

```python
    def distinct_events(
        self,
        within_hours_ahead: int | None = None,
        sport_key: str | None = None,
        now: datetime | None = None,
    ) -> list[dict]:
        """List distinct (event_id, sport_key, commence_time, home, away)
        known to the cache, optionally filtering by sport + time window.

        When `within_hours_ahead` is set, the time filter is applied as
        `HAVING MAX(commence_time) BETWEEN ? AND ?` on the GROUP BY —
        preserves the historical Python-filter semantics (filter on the
        per-event MAX, not on raw rows that may disagree on
        commence_time).

        `now` is injected for testability; production callers omit it
        (default = `datetime.now(timezone.utc)`).
        """
        from datetime import datetime as _dt, timezone as _tz
        q_parts = ["""
            SELECT event_id, MAX(sport_key) AS sport_key,
                   MAX(commence_time) AS commence_time,
                   MAX(home_team) AS home_team, MAX(away_team) AS away_team
            FROM odds_snapshot
        """]
        args: list = []
        where: list[str] = []
        if sport_key:
            where.append("sport_key = ?")
            args.append(sport_key)
        if where:
            q_parts.append("WHERE " + " AND ".join(where))
        q_parts.append("GROUP BY event_id")
        if within_hours_ahead is not None:
            ts_now = now if now is not None else _dt.now(_tz.utc)
            horizon = ts_now + timedelta(hours=within_hours_ahead)
            q_parts.append(
                "HAVING MAX(commence_time) >= ? AND MAX(commence_time) <= ?"
            )
            args.extend([ts_now.isoformat(), horizon.isoformat()])
        q = " ".join(q_parts)
        with self._conn() as c:
            rows = [dict(r) for r in c.execute(q, args)]
        if within_hours_ahead is None:
            return rows
        # Parse commence_time → datetime for callers (preserves the v1
        # API: returned commence_time is datetime when within_hours_ahead
        # is set, raw string otherwise).
        out: list[dict] = []
        for r in rows:
            ct = _dt.fromisoformat(r["commence_time"])
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=_tz.utc)
            out.append({**r, "commence_time": ct})
        return out
```

(Note that I'm adding a `now` parameter for testability. Production callers don't pass it; tests can.)

- [ ] **Step 4: Simplify the test to use the new `now` kwarg**

Replace the `with patch("server.odds.cache.datetime")` blocks in the tests with `now=fixed_now`:

```python
result = cache.distinct_events(within_hours_ahead=24, now=fixed_now)
```

(Remove the `from unittest.mock import patch` imports if no other test in the file uses them.)

- [ ] **Step 5: Run tests + regression**

```bash
.venv/bin/python -m pytest server/tests/test_cache.py -v -k distinct_events
.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py
```

Expected: all distinct_events tests pass; no regressions.

- [ ] **Step 6: Commit**

```bash
git add server/odds/cache.py server/tests/test_cache.py
git commit -m "$(cat <<'EOF'
perf(cache): distinct_events SQL pushdown via HAVING (A8)

Push commence_time time-window filter into SQL via HAVING
MAX(commence_time) BETWEEN ? AND ? instead of materializing all
events and filtering in Python. Preserves per-event MAX semantics
(rows for one event can disagree on commence_time; HAVING filters on
the aggregate, matching the Python-filter behavior bit-for-bit).
Adds a `now` kwarg for testability.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: A5 — TTL on `_resolved_keys`

**Files:**
- Modify: `server/odds/fetcher.py` (signature of `_resolve_keys`, type of `_resolved_keys`)
- Create: `server/tests/test_fetcher.py`

- [ ] **Step 1: Failing test**

Create `server/tests/test_fetcher.py`:

```python
"""Tests for FetcherRegistry._resolve_keys (A5 — 24h TTL)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.odds.fetcher import FetcherRegistry, _RESOLVED_KEYS_TTL
from server.sports import Sport


def _make_registry(resolve_return=None, resolve_raises: Exception | None = None):
    """Build a FetcherRegistry with a mock OddsAPIClient."""
    client = MagicMock()
    if resolve_raises is not None:
        client.resolve_sport_keys = AsyncMock(side_effect=resolve_raises)
    else:
        client.resolve_sport_keys = AsyncMock(return_value=resolve_return or [])
    # FetcherRegistry constructor expects (config, sports, cache, client, settings_store).
    # Minimal valid setup: pass MagicMocks for everything except client.
    return FetcherRegistry(
        config=MagicMock(),
        sports=[],
        cache=MagicMock(),
        client=client,
        settings_store=MagicMock(),
    ), client


def _sport(key: str = "tennis", odds_api_keys: list[str] | None = None) -> Sport:
    """Build a minimal Sport object for the resolve test."""
    return Sport(
        key=key,
        label=key.upper(),
        odds_api_sport_keys=odds_api_keys or [f"{key}_atp_*"],
        # Fill in other required fields with sane defaults — the exact
        # shape depends on Sport's dataclass; consult `server/sports.py`.
        # If Sport has more required fields, add them here.
        markets_config="",
    )


@pytest.mark.asyncio
async def test_first_call_resolves_and_caches():
    reg, client = _make_registry(resolve_return=["tennis_atp_french_open"])
    sp = _sport()
    now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    keys = await reg._resolve_keys(sp, now=now)
    assert keys == ["tennis_atp_french_open"]
    assert client.resolve_sport_keys.await_count == 1


@pytest.mark.asyncio
async def test_within_ttl_returns_cached_no_second_call():
    reg, client = _make_registry(resolve_return=["tennis_atp_french_open"])
    sp = _sport()
    now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    await reg._resolve_keys(sp, now=now)
    # 23 hours later — still within 24h TTL
    keys = await reg._resolve_keys(sp, now=now + timedelta(hours=23))
    assert keys == ["tennis_atp_french_open"]
    assert client.resolve_sport_keys.await_count == 1  # not re-called


@pytest.mark.asyncio
async def test_after_ttl_re_resolves():
    reg, client = _make_registry(resolve_return=["tennis_atp_french_open"])
    sp = _sport()
    now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    await reg._resolve_keys(sp, now=now)
    # 25 hours later — past TTL
    client.resolve_sport_keys.return_value = ["tennis_atp_wimbledon"]
    keys = await reg._resolve_keys(sp, now=now + timedelta(hours=25))
    assert keys == ["tennis_atp_wimbledon"]
    assert client.resolve_sport_keys.await_count == 2


@pytest.mark.asyncio
async def test_refresh_failure_preserves_cached_keys():
    """A transient refresh failure should NOT overwrite a previously-good
    cached set. The timestamp also stays put so next call retries."""
    reg, client = _make_registry(resolve_return=["tennis_atp_french_open"])
    sp = _sport()
    now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    await reg._resolve_keys(sp, now=now)
    # 25h later: refresh fails
    client.resolve_sport_keys.side_effect = Exception("network error")
    keys = await reg._resolve_keys(sp, now=now + timedelta(hours=25))
    assert keys == ["tennis_atp_french_open"]
    # Timestamp NOT updated — next call should retry, not wait another 24h
    client.resolve_sport_keys.side_effect = None
    client.resolve_sport_keys.return_value = ["tennis_atp_wimbledon"]
    keys2 = await reg._resolve_keys(sp, now=now + timedelta(hours=25, minutes=1))
    assert keys2 == ["tennis_atp_wimbledon"]


@pytest.mark.asyncio
async def test_first_call_failure_falls_back_to_static_keys():
    """First-time resolve failure caches the static-key fallback (strips
    pattern entries) so we don't retry-storm on every tier tick."""
    reg, client = _make_registry(resolve_raises=Exception("network error"))
    # Mix of static and pattern keys
    sp = _sport(odds_api_keys=["baseball_mlb", "tennis_atp_*"])
    now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    keys = await reg._resolve_keys(sp, now=now)
    assert keys == ["baseball_mlb"]  # static keys retained; pattern stripped
    # Repeat within TTL: still cached, no second call
    keys2 = await reg._resolve_keys(sp, now=now + timedelta(hours=1))
    assert keys2 == ["baseball_mlb"]
    assert client.resolve_sport_keys.await_count == 1
```

(The exact Sport dataclass fields may differ — read `server/sports.py` first and add any missing required fields to `_sport()`. If Sport requires `kind`, `default_markets_config`, etc., add sane defaults.)

- [ ] **Step 2: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_fetcher.py -v
```

Expected: ImportError on `_RESOLVED_KEYS_TTL`. (Or, if Sport's required fields differ, fix the fixture first.)

- [ ] **Step 3: Implement in `server/odds/fetcher.py`**

Near the top of the file (after the imports, before the class), add:

```python
# A5: re-resolve sport→Odds-API key mappings every 24h so tournament
# rotations (ATP draws, soccer matchdays) get picked up without a
# server restart. On refresh failure, the previously-cached set stays
# in place and the timestamp does NOT update — next caller retries.
_RESOLVED_KEYS_TTL = timedelta(hours=24)
```

Change the `_resolved_keys` field type at line 67 from:
```python
self._resolved_keys: dict[str, list[str]] = {}
```
to:
```python
self._resolved_keys: dict[str, tuple[list[str], datetime]] = {}
```

Replace `_resolve_keys` (lines 246-257) with:

```python
    async def _resolve_keys(
        self, sport: Sport, now: datetime | None = None,
    ) -> list[str]:
        """Resolve a sport's Odds-API key set, cached with 24h TTL.

        On refresh failure (cached entry exists, TTL expired, resolve
        raises), returns the previously-cached keys unchanged AND does
        not update the timestamp — next call retries on whatever
        cadence the caller runs.

        On first-time failure (no cached entry, resolve raises), falls
        back to the static-key subset (strips pattern entries) and
        caches that with the current timestamp to avoid retry-storming.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        cached = self._resolved_keys.get(sport.key)
        if cached is not None:
            keys, cached_at = cached
            if now - cached_at < _RESOLVED_KEYS_TTL:
                return keys
        # Resolve fresh (first-time OR TTL expired).
        try:
            keys = await self.client.resolve_sport_keys(sport.odds_api_sport_keys)
        except Exception:
            logger.exception("resolve_sport_keys failed for %s", sport.key)
            if cached is not None:
                # Refresh failure with a prior good cache → keep it,
                # don't update timestamp. Next call retries.
                return cached[0]
            # First-time failure → fall back to static keys, cache to
            # avoid retry-storm on every tier tick.
            keys = [k for k in sport.odds_api_sport_keys if not k.endswith("*")]
        # Log when refresh changed the resolved set (new tournaments
        # rotated in, old ones out).
        if cached is not None and keys != cached[0]:
            logger.info(
                "sport %s key set changed: %s → %s",
                sport.key, cached[0], keys,
            )
        else:
            logger.info("sport %s resolves to Odds API keys: %s", sport.key, keys)
        self._resolved_keys[sport.key] = (keys, now)
        return keys
```

(If `datetime` isn't already imported at module level for the type annotation, add it. Same for `timedelta` and `timezone`.)

- [ ] **Step 4: Run tests + regression**

```bash
.venv/bin/python -m pytest server/tests/test_fetcher.py -v
.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py
```

Expected: all 5 new fetcher tests pass; no regressions.

- [ ] **Step 5: Server-boot smoke test**

```bash
lsof -ti :8000 | xargs -r kill 2>/dev/null
sleep 1
nohup .venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 8000 > /tmp/uvicorn.log 2>&1 &
disown
sleep 5
echo "--- boot ---"
curl -s http://127.0.0.1:8000/api/health | head -c 150
echo
echo "--- _resolve_keys log lines ---"
grep "resolves to Odds API keys" /tmp/uvicorn.log | head -5
```

Expected: server boots; `resolves to Odds API keys` log line appears for each sport on startup (unchanged behavior on first call).

- [ ] **Step 6: Commit**

```bash
git add server/odds/fetcher.py server/tests/test_fetcher.py
git commit -m "$(cat <<'EOF'
feat(fetcher): 24h TTL on _resolved_keys (A5)

Re-resolve sport→Odds-API key mappings every 24 hours so tournament
rotations get picked up without a server restart. On refresh failure
with a prior good cache, keep the cached set AND don't update the
timestamp — next caller retries naturally. On first-time failure,
fall back to static keys to avoid retry-storming on every tier tick.
Logs when the resolved set changes across refreshes.

Adds a `now` kwarg to _resolve_keys for testability; production
callers omit it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verification — end-to-end

```bash
.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py
```

Expected: all pass. The 15 pre-existing failures in the ignored test files remain (unrelated; out of scope for Tier 4).

Restart the server, hit `/api/dashboard` and `/api/edges`, confirm no errors and no regressions vs pre-Tier-4 baseline.

---

## Deferred follow-ups

- `_event_sport_map` memory cleanup: it grows monotonically as new events stream in (Tier 4 audit lumped this with A5 but it's a memory-leak issue, not a staleness issue). Mitigation could prune entries for event_ids the cache has purged. Defer to a separate Tier-X item.
- Add a manual "refresh now" endpoint that drops the `_resolved_keys` cache for an immediate re-resolve on tournament-start day. Defer.
