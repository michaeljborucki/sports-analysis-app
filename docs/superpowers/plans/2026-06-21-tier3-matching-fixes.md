# Tier 3 — Odds-Matching Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the six Tier 3 odds-matching correctness/observability fixes (M3-M8) from the 2026-06-21 audit.

**Architecture:** Six independent fixes batched as one shippable unit. Five touch only the venue-specific normalizer / event-matcher modules; one (M7) touches the shared `normalize.py` outcome grouping. No schema changes, no scanner output changes. Easiest items first so the riskier `match`-layer edits land last.

**Tech Stack:** Python 3.11, sqlite3 (cache), pytest.

**Spec:** `docs/superpowers/specs/2026-06-21-tier3-matching-fixes-design.md`

---

## Pre-flight

```bash
git status
# Should be clean (or only have unstaged user_settings.json)
git log --oneline -3
# Should show: 7f08535 (spec fix), 70b4eeb (spec), a6dad0a (roadmap close-out)
```

---

## Task 1: M5 — Kalshi code_map prefix validation

**Files:**
- Modify: `server/odds/books/kalshi/mapping.py`
- Test: `server/tests/test_kalshi_normalizer.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_kalshi_normalizer.py`:

```python
def test_validate_code_map_unique_prefixes_passes_real_map():
    """The actual TEAM_CODE_TO_CANONICAL map (loaded by the module) must
    not have any prefix collisions today. This pins it as a regression."""
    from server.odds.books.kalshi.mapping import (
        TEAM_CODE_TO_CANONICAL,
        validate_code_map_unique_prefixes,
    )
    # Should not raise — passes silently
    validate_code_map_unique_prefixes(TEAM_CODE_TO_CANONICAL)


def test_validate_code_map_unique_prefixes_catches_collision():
    from server.odds.books.kalshi.mapping import validate_code_map_unique_prefixes
    bad = {"BOS": "Boston Celtics", "BOSEN": "Hypothetical New Team"}
    with pytest.raises(ValueError) as exc:
        validate_code_map_unique_prefixes(bad)
    msg = str(exc.value)
    assert "BOS" in msg and "BOSEN" in msg


def test_validate_code_map_ignores_same_length_codes():
    """Two codes of the same length cannot be prefix-overlapping (one
    can't be a prefix of the other unless they're equal). Verify the
    common case where all codes are 3-letter abbreviations passes."""
    from server.odds.books.kalshi.mapping import validate_code_map_unique_prefixes
    fine = {"BOS": "Boston", "MIA": "Miami", "OKC": "Oklahoma City"}
    validate_code_map_unique_prefixes(fine)  # no raise
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_normalizer.py -v -k validate_code_map
```

Expected: ImportError on `validate_code_map_unique_prefixes`.

- [ ] **Step 3: Implement**

Locate `TEAM_CODE_TO_CANONICAL` in `server/odds/books/kalshi/mapping.py`. Add at module scope (after the dict):

```python
def validate_code_map_unique_prefixes(code_map: dict[str, str]) -> None:
    """Raise if any code is a prefix of another. Called once at load
    time — fail loud so adding a future team rebrand doesn't silently
    break `_split_team_pair` event resolution.

    Codes of equal length can never be prefix-overlapping (unless
    equal), so we only check unequal-length pairs.
    """
    codes = sorted(code_map.keys(), key=len)
    for i, short in enumerate(codes):
        for longer in codes[i + 1:]:
            if len(longer) == len(short):
                continue
            if longer.startswith(short):
                raise ValueError(
                    f"Kalshi code_map has prefix collision: "
                    f"'{short}' is a prefix of '{longer}' — "
                    f"_split_team_pair would silently fail on tickers "
                    f"containing both."
                )


# Validate on module load.
validate_code_map_unique_prefixes(TEAM_CODE_TO_CANONICAL)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_normalizer.py -v -k validate_code_map
```

Expected: all 3 pass. Run the full kalshi test file too:

```bash
.venv/bin/python -m pytest server/tests/test_kalshi_normalizer.py -q
```

Expected: no regressions.

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/kalshi/mapping.py server/tests/test_kalshi_normalizer.py
git commit -m "$(cat <<'EOF'
feat(kalshi): validate code_map has no prefix collisions (M5)

_split_team_pair walks every split point of a team-pair string and
accepts the unique split where both halves are valid codes. If a
future team rebrand introduced a code that's a prefix of another
(e.g. BOS + BOSEN), tickers containing both would split two valid
ways and silently return None. New validate_code_map_unique_prefixes
runs at module load — fail loud over fail silent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: M7 — Outcome-name collision WARN logging

**Files:**
- Modify: `server/odds/normalize.py`
- Test: `server/tests/test_normalize.py` (create)

- [ ] **Step 1: Inspect the outcome grouping site**

```bash
grep -n "outcome_name\|outcome_point\|def rows_to_games" server/odds/normalize.py | head -10
```

Confirm where prices get bucketed by `(outcome_name, outcome_point)`. This is where the M7 collision check goes.

- [ ] **Step 2: Write the failing test**

Create `server/tests/test_normalize.py`:

```python
"""Tests for server/odds/normalize.py outcome-name collision logging (M7)."""
from datetime import datetime, timezone

import pytest


def _row(**overrides) -> dict:
    base = {
        "event_id": "ev1", "sport_key": "nba",
        "home_team": "Boston Celtics", "away_team": "Miami Heat",
        "commence_time": datetime(2026, 6, 21, tzinfo=timezone.utc),
        "bookmaker_key": "draftkings",
        "market_key": "spreads", "outcome_name": "Boston Celtics",
        "outcome_point": -2.5,
        "price_american": -110,
        "fetched_at": datetime(2026, 6, 21, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def test_outcome_name_collision_emits_warning(caplog):
    """Two books emitting different outcome_names for the same
    (event, market, point) should produce one WARN."""
    from server.odds.normalize import rows_to_games, _reset_collision_log_for_tests
    _reset_collision_log_for_tests()
    rows = [
        _row(bookmaker_key="draftkings", outcome_name="BOS", outcome_point=-2.5),
        _row(bookmaker_key="fanduel",    outcome_name="Boston Celtics", outcome_point=-2.5),
    ]
    with caplog.at_level("WARNING", logger="server.odds.normalize"):
        rows_to_games(rows, now=datetime.now(timezone.utc))
    warnings = [r for r in caplog.records if "outcome-name collision" in r.getMessage()]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "ev1" in msg and "spreads" in msg and "-2.5" in msg
    assert "BOS" in msg and "Boston Celtics" in msg


def test_outcome_name_collision_is_dedupd_per_address(caplog):
    """Re-seeing the same collision should NOT emit a second WARN."""
    from server.odds.normalize import rows_to_games, _reset_collision_log_for_tests
    _reset_collision_log_for_tests()
    rows = [
        _row(bookmaker_key="draftkings", outcome_name="BOS", outcome_point=-2.5),
        _row(bookmaker_key="fanduel",    outcome_name="Boston Celtics", outcome_point=-2.5),
    ]
    with caplog.at_level("WARNING", logger="server.odds.normalize"):
        rows_to_games(rows, now=datetime.now(timezone.utc))
        rows_to_games(rows, now=datetime.now(timezone.utc))
    warnings = [r for r in caplog.records if "outcome-name collision" in r.getMessage()]
    assert len(warnings) == 1


def test_no_warning_when_outcome_names_match(caplog):
    from server.odds.normalize import rows_to_games, _reset_collision_log_for_tests
    _reset_collision_log_for_tests()
    rows = [
        _row(bookmaker_key="draftkings", outcome_name="Boston Celtics"),
        _row(bookmaker_key="fanduel",    outcome_name="Boston Celtics"),
    ]
    with caplog.at_level("WARNING", logger="server.odds.normalize"):
        rows_to_games(rows, now=datetime.now(timezone.utc))
    warnings = [r for r in caplog.records if "outcome-name collision" in r.getMessage()]
    assert len(warnings) == 0
```

- [ ] **Step 3: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_normalize.py -v
```

Expected: ImportError on `_reset_collision_log_for_tests`.

- [ ] **Step 4: Implement in `server/odds/normalize.py`**

Near the top of the file (after imports), add the module-level dedup set + reset helper:

```python
# M7: Outcome-name collision dedup. Records (event_id, market_key,
# outcome_point) addresses we've already warned about. Process-lifetime;
# bounded by distinct addresses × server uptime (realistic worst case
# ~few thousand entries).
_COLLISION_WARNED: set[tuple[str, str, float]] = set()


def _reset_collision_log_for_tests() -> None:
    """Clear the dedup set. Tests only."""
    _COLLISION_WARNED.clear()
```

Inside `rows_to_games`, after the rows have been grouped by their normal outcome key and before the per-outcome processing, add a pass that groups by `(event_id, market_key, outcome_point)` and checks for distinct outcome_names. Find the loop that builds `ev["markets"]` or the outcome dictionary and add:

```python
    # M7: outcome-name collision detection — group prices by their
    # (event_id, market_key, outcome_point) address. If two distinct
    # outcome_name values share an address, two books are describing
    # the same line with different labels and they'll never pair.
    # Log once per address per process.
    _check_outcome_name_collisions(rows)
```

Add the helper:

```python
def _check_outcome_name_collisions(rows: list[dict]) -> None:
    """Walk the raw rows once, building (address → set[outcome_name]).
    For any address where the set has >1 distinct name, emit a
    WARNING (deduplicated via _COLLISION_WARNED). Pure observability —
    never mutates rows or raises."""
    seen: dict[tuple[str, str, float], set[str]] = {}
    for r in rows:
        try:
            point = float(r.get("outcome_point") or 0.0)
        except (TypeError, ValueError):
            point = 0.0
        addr = (
            str(r.get("event_id") or ""),
            str(r.get("market_key") or ""),
            point,
        )
        name = str(r.get("outcome_name") or "")
        if not addr[0] or not addr[1] or not name:
            continue
        seen.setdefault(addr, set()).add(name)
    for addr, names in seen.items():
        if len(names) <= 1:
            continue
        if addr in _COLLISION_WARNED:
            continue
        _COLLISION_WARNED.add(addr)
        logger.warning(
            "outcome-name collision in %s/%s/%s: %s",
            addr[0], addr[1], addr[2], ", ".join(sorted(names)),
        )
```

(Verify there's already a module-level `logger = logging.getLogger(__name__)`; if not, add it.)

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_normalize.py -v
.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py
```

Expected: 3 new tests pass; no regressions.

- [ ] **Step 6: Commit**

```bash
git add server/odds/normalize.py server/tests/test_normalize.py
git commit -m "$(cat <<'EOF'
feat(normalize): WARN on outcome-name collisions across books (M7)

When two books emit different outcome_name strings for the same
(event_id, market_key, outcome_point) address, their prices hash to
distinct outcome groups and never pair. Pure observability fix — log
one WARN per address per process lifetime so silent splits are
debuggable before they become unrecoverable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: M8 — Coral33 in-play purge grace window

**Files:**
- Modify: `server/odds/cache.py` (`purge_live_rows_for_book` signature + body)
- Modify: `server/odds/books/coral33/fetcher.py` (pass `grace_seconds=1800`)
- Test: `server/tests/test_cache.py`

- [ ] **Step 1: Failing test**

Append to `server/tests/test_cache.py`:

```python
def test_purge_live_rows_grace_window_preserves_recent(tmp_path):
    """Rows whose commence_time is within `grace_seconds` of now should
    NOT be purged — they may be delayed / soft-start games."""
    from datetime import datetime, timezone, timedelta
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    # Row that started 10 minutes ago (within 30-min grace)
    recent = {
        "event_id": "ev_recent", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now - timedelta(minutes=10),
        "bookmaker_key": "coral33",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None, "price_american": -145,
        "fetched_at": now,
    }
    # Row that started 45 minutes ago (outside 30-min grace)
    old = {**recent, "event_id": "ev_old",
           "commence_time": now - timedelta(minutes=45)}
    cache.upsert([recent, old])
    removed = cache.purge_live_rows_for_book("coral33", now, grace_seconds=1800)
    assert removed == 1
    remaining = {r["event_id"] for r in cache.all_current()}
    assert "ev_recent" in remaining
    assert "ev_old" not in remaining


def test_purge_live_rows_default_grace_is_zero(tmp_path):
    """Without grace_seconds (existing call sites), behavior is
    unchanged — anything with commence_time <= now is purged."""
    from datetime import datetime, timezone, timedelta
    from server.odds.cache import OddsCache
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    now = datetime(2026, 6, 21, 20, 0, tzinfo=timezone.utc)
    row = {
        "event_id": "ev_at_kickoff", "sport_key": "nba",
        "home_team": "BOS", "away_team": "MIA",
        "commence_time": now - timedelta(seconds=1),
        "bookmaker_key": "coral33",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None, "price_american": -145,
        "fetched_at": now,
    }
    cache.upsert([row])
    removed = cache.purge_live_rows_for_book("coral33", now)  # default grace=0
    assert removed == 1
```

- [ ] **Step 2: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_cache.py -v -k purge_live_rows_grace
```

Expected: `TypeError: purge_live_rows_for_book() got an unexpected keyword argument 'grace_seconds'`.

- [ ] **Step 3: Implement in `server/odds/cache.py`**

Find `def purge_live_rows_for_book` (around line 345). Change signature + body:

```python
    def purge_live_rows_for_book(
        self, bookmaker_key: str, now: datetime,
        grace_seconds: int = 0,
    ) -> int:
        """Delete rows from a specific book whose game has been live
        for more than `grace_seconds` seconds. Default 0 — any row
        whose commence_time <= now gets purged. Used for coral33 with
        grace_seconds=1800 (30 minutes) so delayed / soft-start games
        don't lose their pre-game lines while the actual kickoff is
        still pending.
        """
        # Guard against clock skew or negative input — never expand
        # the purge window past now.
        grace = max(int(grace_seconds), 0)
        cutoff_dt = now - timedelta(seconds=grace)
        cutoff = cutoff_dt.isoformat()
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM odds_snapshot WHERE bookmaker_key = ? AND commence_time <= ?",
                (bookmaker_key, cutoff),
            )
            removed = cur.rowcount
        if removed:
            self._bump_version()
        return removed
```

- [ ] **Step 4: Wire Coral33 caller**

In `server/odds/books/coral33/fetcher.py`, find the call at ~line 276:

```python
        purged = self.cache.purge_live_rows_for_book("coral33", now)
```

Change to:

```python
        # 30-minute grace window: don't purge a row whose commence_time is
        # within the last 30 minutes. Catches the common rain-delay /
        # soft-start case without polling Coral33 for live game status.
        purged = self.cache.purge_live_rows_for_book(
            "coral33", now, grace_seconds=1800,
        )
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_cache.py -v -k purge_live_rows
```

Expected: both new tests pass + existing `test_purge_live_rows_for_book` (if any) still passes.

```bash
.venv/bin/python -m pytest server/tests/test_cache.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add server/odds/cache.py server/odds/books/coral33/fetcher.py server/tests/test_cache.py
git commit -m "$(cat <<'EOF'
feat(cache): grace_seconds on purge_live_rows_for_book (M8)

Optional `grace_seconds` parameter (default 0 = existing behavior).
Coral33 fetcher now passes 1800 (30 minutes) so delayed games and
soft starts don't lose their pre-game lines while actual kickoff is
still pending. Cheaper than polling Coral33 for live game status
(audit's preferred fix, deferred).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: M6 — Polymarket soccer partial-market emission

**Files:**
- Modify: `server/odds/books/polymarket/normalizer.py` (around line 565-613)
- Test: `server/tests/test_polymarket_normalizer.py` (extend or create)

- [ ] **Step 1: Read the existing soccer 3-way aggregation**

```bash
grep -n "Soccer 3-way\|by_segment\|early-return\|all 3\|home.*draw.*away" server/odds/books/polymarket/normalizer.py | head -10
sed -n '560,620p' server/odds/books/polymarket/normalizer.py
```

Locate the exact line that returns `[]` when fewer than 3 outcomes are present (per spec around line 612-613).

- [ ] **Step 2: Failing test**

In `server/tests/test_polymarket_normalizer.py`, find an existing test for 3-way soccer or create a new file. Add:

```python
def test_soccer_3way_emits_partial_when_draw_missing():
    """When only home + away are present (no draw yet), Polymarket
    should still emit those 2 outcomes — cross-book aggregation will
    complete the 3-way picture when paired with another book that has
    all 3."""
    from server.odds.books.polymarket.normalizer import _aggregate_soccer_3way
    # Construct a by_segment dict with only home + away (no draw)
    by_segment = {
        "cry": _make_outcome_segment(team="Crystal Palace", yes_ask=0.45),
        "ars": _make_outcome_segment(team="Arsenal",        yes_ask=0.40),
        # "draw" intentionally missing
    }
    rows = _aggregate_soccer_3way("soccer", by_segment, event_metadata=_event_meta())
    # 2 outcomes expected (no synthesized draw)
    outcome_names = {r["outcome_name"] for r in rows}
    assert "Crystal Palace" in outcome_names
    assert "Arsenal" in outcome_names
    assert "Draw" not in outcome_names
    assert len(rows) == 2


def test_soccer_3way_full_set_still_emits_3():
    """The 3-of-3 happy path is unchanged."""
    from server.odds.books.polymarket.normalizer import _aggregate_soccer_3way
    by_segment = {
        "cry":  _make_outcome_segment(team="Crystal Palace", yes_ask=0.40),
        "ars":  _make_outcome_segment(team="Arsenal",        yes_ask=0.35),
        "draw": _make_outcome_segment(team=None,             yes_ask=0.25),
    }
    rows = _aggregate_soccer_3way("soccer", by_segment, event_metadata=_event_meta())
    assert len(rows) == 3
```

(Adjust `_make_outcome_segment` and `_event_meta` to match the actual data shapes the aggregator expects. Read the function signature from the source to align.)

- [ ] **Step 3: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_polymarket_normalizer.py -v -k soccer_3way
```

Expected: the partial test fails (returns `[]` instead of 2 rows).

- [ ] **Step 4: Implement**

In `server/odds/books/polymarket/normalizer.py`, find the early-return on line ~612:

```python
        if not (code_a in by_segment and code_b in by_segment and "draw" in by_segment):
            return []
```

Replace with:

```python
        # Allow partials: emit whatever outcomes ARE present (2-of-3
        # or 1-of-3). The cross-book devig still gates the full 3-way
        # downstream; surfacing partials lets another book with all 3
        # complete the picture. Single-leg sets are unusual but
        # harmless — they pair against the same outcome from another
        # book in `rows_to_games`.
        present_count = sum(
            1 for k in (code_a, code_b, "draw") if k in by_segment
        )
        if present_count == 0:
            return []
        # When all 3 are present, the existing overround sanity check
        # still applies below. When only 2 (or 1), skip the overround
        # gate — it requires all 3 YES probs to sum sensibly.
```

Then update the existing overround sanity check (further down in the function — find the `overround_sum` computation) so it only applies when all 3 outcomes are present. The simplest shape:

```python
        if present_count == 3:
            # Existing 3-way overround sanity check
            overround_sum = sum(...)
            if overround_sum > MAX_3WAY_OVERROUND:
                return []
```

Then the emission loop simply iterates over whichever of `code_a`, `code_b`, `"draw"` are in `by_segment` and emits one row each.

(The exact edit depends on the existing code shape — read it carefully and apply the partial-emission pattern.)

- [ ] **Step 5: Run tests + verify scanner still works**

```bash
.venv/bin/python -m pytest server/tests/test_polymarket_normalizer.py -v
.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py
```

Expected: new tests pass, no scanner regressions.

- [ ] **Step 6: Commit**

```bash
git add server/odds/books/polymarket/normalizer.py server/tests/test_polymarket_normalizer.py
git commit -m "$(cat <<'EOF'
feat(polymarket): emit soccer 2-of-3 partials instead of dropping (M6)

When fewer than 3 outcomes are present (typically draw not yet
listed), emit whichever outcomes ARE available. The cross-book devig
downstream still gates the full 3-way; surfacing partials lets
another book with all 3 complete the picture. The 3-of-3 overround
sanity check is unchanged. Catches ~2-5% of early-tournament
Polymarket soccer events previously dropped silently.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: M4a — `canonicalize_spread_outcome` helper

**Files:**
- Create: `server/odds/books/spread_orientation.py`
- Test: `server/tests/test_spread_orientation.py`

- [ ] **Step 1: Failing test**

Create `server/tests/test_spread_orientation.py`:

```python
"""Tests for canonicalize_spread_outcome (M4)."""
import pytest


def test_negative_point_passes_through_unchanged():
    """The favored team's view (negative point) is already canonical."""
    from server.odds.books.spread_orientation import canonicalize_spread_outcome
    name, point = canonicalize_spread_outcome(
        "Boston Celtics", -2.5, "Boston Celtics", "Miami Heat",
    )
    assert name == "Boston Celtics"
    assert point == -2.5


def test_positive_point_flips_to_other_team_negated():
    """The underdog's view (positive point) gets canonicalized: the
    outcome becomes the OTHER team with the point negated."""
    from server.odds.books.spread_orientation import canonicalize_spread_outcome
    # Heat +2.5 → Celtics -2.5
    name, point = canonicalize_spread_outcome(
        "Miami Heat", 2.5, "Boston Celtics", "Miami Heat",
    )
    assert name == "Boston Celtics"
    assert point == -2.5


def test_pickem_zero_passes_through_unchanged():
    """Pick'em (point = 0) has no orientation; pass through."""
    from server.odds.books.spread_orientation import canonicalize_spread_outcome
    name, point = canonicalize_spread_outcome(
        "Miami Heat", 0.0, "Boston Celtics", "Miami Heat",
    )
    # Point=0 isn't really a spread; no flip
    assert name == "Miami Heat"
    assert point == 0.0


def test_idempotent_on_re_application():
    """Re-applying canonicalize_spread_outcome produces the same result."""
    from server.odds.books.spread_orientation import canonicalize_spread_outcome
    first = canonicalize_spread_outcome(
        "Miami Heat", 2.5, "Boston Celtics", "Miami Heat",
    )
    second = canonicalize_spread_outcome(
        first[0], first[1], "Boston Celtics", "Miami Heat",
    )
    assert second == first


def test_unknown_team_passes_through():
    """If outcome_name matches neither home nor away (e.g., a typo or
    unresolved alias), pass through unchanged — never silently swap to
    the wrong team."""
    from server.odds.books.spread_orientation import canonicalize_spread_outcome
    name, point = canonicalize_spread_outcome(
        "Unknown Team", 2.5, "Boston Celtics", "Miami Heat",
    )
    assert name == "Unknown Team"
    assert point == 2.5


def test_is_spread_market_helper():
    """The market_key dispatcher recognizes all spread-family keys."""
    from server.odds.books.spread_orientation import is_spread_market
    assert is_spread_market("spreads") is True
    assert is_spread_market("alternate_spreads") is True
    assert is_spread_market("spreads_h1") is True
    assert is_spread_market("alternate_spreads_1st_5_innings") is True
    assert is_spread_market("h2h") is False
    assert is_spread_market("totals") is False
    assert is_spread_market("alternate_totals") is False
```

- [ ] **Step 2: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_spread_orientation.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Create `server/odds/books/spread_orientation.py`:

```python
"""Canonicalize spread-market outcome orientation (M4).

Some books emit `(outcome_name="Boston Celtics", outcome_point=-2.5)`;
others emit `(outcome_name="Miami Heat", outcome_point=+2.5)` for the
same line. Both describe the same bet, but they hash to distinct cache
keys and the resulting duplicate rows confuse flat-outcome queries.

Canonical form: favored team (negative point). This module is venue-
agnostic — the sportsbook normalizer, Kalshi normalizer, and
Polymarket normalizer all apply it at ingest time.

The pickem case (point = 0) has no orientation; pass through.
Out-of-roster outcome names (typos, unresolved aliases) also pass
through unchanged so we never silently swap to the wrong team.
"""
from __future__ import annotations


def is_spread_market(market_key: str) -> bool:
    """True iff this market_key is a spread-family market (main or
    alternate, base or period-suffixed). Examples: 'spreads',
    'alternate_spreads', 'spreads_h1', 'alternate_spreads_1st_5_innings'.
    """
    if not market_key:
        return False
    return market_key.startswith("spreads") or market_key.startswith("alternate_spreads")


def canonicalize_spread_outcome(
    outcome_name: str,
    outcome_point: float,
    home_team: str,
    away_team: str,
) -> tuple[str, float]:
    """Return the canonical (outcome_name, outcome_point) where the
    point is always ≤ 0 (favored team's view).

    Behavior:
      - point < 0: pass through (already canonical).
      - point > 0 and outcome_name matches home or away: flip to the
        OTHER team with the point negated.
      - point > 0 and outcome_name matches neither: pass through
        (defensive — don't guess).
      - point == 0: pass through (pickem; no orientation).

    Idempotent.
    """
    if outcome_point >= 0:
        if outcome_point == 0:
            return outcome_name, outcome_point
        if outcome_name == home_team:
            return away_team, -outcome_point
        if outcome_name == away_team:
            return home_team, -outcome_point
        # Unknown team — don't guess; pass through.
        return outcome_name, outcome_point
    return outcome_name, outcome_point
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_spread_orientation.py -v
```

Expected: all 6 pass.

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/spread_orientation.py server/tests/test_spread_orientation.py
git commit -m "$(cat <<'EOF'
feat(matching): canonicalize_spread_outcome helper for M4

Venue-agnostic helper that flips a positive-point alt-spread outcome
to the favored-team's view (negative point). Idempotent. Wired into
sportsbook / Kalshi / Polymarket normalizers in the next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: M4b — Wire canonicalization into 3 ingest sites

**Files:**
- Modify: `server/odds/normalize.py` (sportsbook ingest path — where rows are first written from Odds API responses)
- Modify: `server/odds/books/kalshi/normalizer.py`
- Modify: `server/odds/books/polymarket/normalizer.py`
- Test: `server/tests/test_normalize.py` + venue-specific tests

- [ ] **Step 1: Failing tests — sportsbook ingest**

Append to `server/tests/test_normalize.py`:

```python
def test_alt_spread_outcome_canonicalized_at_ingest():
    """A book emitting Away +2.5 is canonicalized to Home -2.5 at the
    row level. Verifies the actual normalize path, not the helper."""
    # NOTE: the function under test depends on where sportsbook rows are
    # first constructed. If `normalize_odds_response` is the entry point,
    # use that here. Otherwise use the lowest-level row constructor.
    from server.odds.normalize import normalize_odds_response
    raw = [{
        "id": "ev1",
        "sport_key": "basketball_nba",
        "home_team": "Boston Celtics",
        "away_team": "Miami Heat",
        "commence_time": "2026-06-21T19:00:00Z",
        "bookmakers": [{
            "key": "draftkings",
            "markets": [{
                "key": "spreads",
                "outcomes": [
                    {"name": "Miami Heat", "point": 2.5, "price": 110},
                    {"name": "Boston Celtics", "point": -2.5, "price": -130},
                ],
            }],
        }],
    }]
    from datetime import datetime, timezone
    rows = normalize_odds_response(raw, fetched_at=datetime(2026, 6, 21, tzinfo=timezone.utc), sport_key="nba")
    # After canonicalization, BOTH outcomes should be Celtics-side with
    # negative points (one at -2.5 from BOS-side row, one flipped from
    # MIA-side row). They'd collide on the same (outcome_name,
    # outcome_point) key but they're from different books in real life;
    # here we just verify the flip happened.
    spreads = [r for r in rows if r["market_key"] == "spreads"]
    points = sorted(r["outcome_point"] for r in spreads)
    names = {r["outcome_name"] for r in spreads}
    # Both rows should canonicalize to Celtics -2.5 → only one outcome_name
    assert names == {"Boston Celtics"}
    assert all(p == -2.5 for p in points)
```

(Adjust to match the actual entry point in `normalize.py`. Read the existing tests for shape patterns first.)

- [ ] **Step 2: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_normalize.py -v -k canonicaliz
```

Expected: rows have mixed orientation (assert fails).

- [ ] **Step 3: Implement in sportsbook normalize**

Find the row-construction loop in `server/odds/normalize.py` (where market outcomes become `odds_snapshot`-shaped dicts). Just before writing the dict, call the helper for spread markets:

```python
from .books.spread_orientation import (
    canonicalize_spread_outcome, is_spread_market,
)

# inside the per-outcome loop:
outcome_name = outcome["name"]
outcome_point = outcome.get("point") or 0.0
if is_spread_market(market_key):
    outcome_name, outcome_point = canonicalize_spread_outcome(
        outcome_name, outcome_point, home_team, away_team,
    )
# ... continue building row
```

(The exact location depends on the function's shape. Read the existing code carefully — the canonicalize call must happen AFTER the home/away teams are resolved but BEFORE the row dict is finalized.)

- [ ] **Step 4: Wire Kalshi normalizer**

In `server/odds/books/kalshi/normalizer.py`, find the spread-emission path (around line 630, search for "alternate_spreads"). Apply the same canonicalization:

```python
from .spread_orientation import canonicalize_spread_outcome, is_spread_market
# adjust import path if module is elsewhere
```

At each spread-row construction site, apply:
```python
if is_spread_market(market_key):
    outcome_name, outcome_point = canonicalize_spread_outcome(
        outcome_name, outcome_point, home_team, away_team,
    )
```

- [ ] **Step 5: Wire Polymarket normalizer**

In `server/odds/books/polymarket/normalizer.py`, do the same. Find the spread-emission path and apply the canonicalize call at row construction.

- [ ] **Step 6: Add venue-specific tests**

In `server/tests/test_kalshi_normalizer.py` and `server/tests/test_polymarket_normalizer.py`, add a test for each venue:

```python
def test_kalshi_alt_spread_canonicalized():
    # Construct a Kalshi market with positive-point orientation
    # (whichever side Kalshi naturally emits when the away team is the
    # underdog by 2.5). After normalization, the row should have
    # outcome_name = favored team, outcome_point = -2.5.
    ...
```

(Build the test from the existing test patterns in those files; the exact fixture shape varies by venue.)

- [ ] **Step 7: Run tests**

```bash
.venv/bin/python -m pytest server/tests/test_normalize.py server/tests/test_kalshi_normalizer.py server/tests/test_polymarket_normalizer.py -v -k canonicaliz
.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py
```

Expected: new tests pass, no regressions.

- [ ] **Step 8: Commit**

```bash
git add server/odds/normalize.py server/odds/books/kalshi/normalizer.py server/odds/books/polymarket/normalizer.py server/tests/test_normalize.py server/tests/test_kalshi_normalizer.py server/tests/test_polymarket_normalizer.py
git commit -m "$(cat <<'EOF'
feat(matching): wire canonicalize_spread_outcome into 3 ingest sites (M4)

Sportsbook, Kalshi, and Polymarket normalizers all flip positive-point
alt-spread outcomes to the favored-team's view at row-construction
time. Cache-flat queries now return one row per spread line instead
of two duplicates. Scanner output unchanged (pairing already handled
the merge before scanning).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: M3 — Multi-anchor date-only matching

**Files:**
- Modify: `server/odds/books/polymarket/event_matcher.py` (new `match_multi_anchor` method)
- Modify: `server/odds/books/kalshi/event_matcher.py` (new `match_multi_anchor` method)
- Modify: `server/odds/books/kalshi/normalizer.py` (date-only call site at ~line 379)
- Modify: `server/odds/books/polymarket/normalizer.py` or wherever the matcher is called (find via grep)
- Create: `server/odds/books/_anchor_table.py` (per-sport anchor times)
- Test: `server/tests/test_polymarket_event_matcher.py` + `server/tests/test_kalshi_event_matcher.py`

- [ ] **Step 1: Create the anchor table**

Create `server/odds/books/_anchor_table.py`:

```python
"""Per-sport candidate game-start anchors for date-only matching (M3).

When a venue ticker / slug carries only a date (no HHMM), we try
matching against multiple US-Eastern start-time anchors before
falling back to the wider noon-ET single-anchor window. The anchors
cover the realistic windows for each sport.

Each entry is a list of (hour, minute) tuples in US/Eastern.
"""
from __future__ import annotations

_DEFAULT_ANCHORS_ET: list[tuple[int, int]] = [
    (12, 0),   # noon — day games
    (19, 0),   # primetime
    (22, 0),   # late West Coast
]

# Per-sport overrides; absent sports use DEFAULT.
_ANCHORS_BY_SPORT_ET: dict[str, list[tuple[int, int]]] = {
    # MLB plays day games + evening — same as default works well.
    # NBA / NHL / WNBA are mostly evening + late.
    "nba":  [(19, 0), (22, 0)],
    "nhl":  [(19, 0), (22, 0)],
    "wnba": [(19, 0), (21, 0)],
}

# Tight window per anchor, in minutes.
TIGHT_WINDOW_MIN = 180


def anchors_for_sport(sport_key: str) -> list[tuple[int, int]]:
    """Return the candidate (hour, minute) ET anchors for this sport."""
    return _ANCHORS_BY_SPORT_ET.get(sport_key, _DEFAULT_ANCHORS_ET)
```

- [ ] **Step 2: Failing tests — Polymarket matcher**

Create `server/tests/test_polymarket_event_matcher.py`:

```python
"""Tests for multi-anchor matching in PolymarketEventMatcher (M3)."""
from datetime import datetime, timezone, timedelta

import pytest


def _events(*event_specs):
    """Build a (sport → events) callable for the matcher fixture."""
    by_sport: dict[str, list[dict]] = {}
    for sport, *rest in event_specs:
        eid, home, away, commence = rest
        by_sport.setdefault(sport, []).append({
            "event_id": eid, "home_team": home, "away_team": away,
            "commence_time": commence,
        })
    return lambda sport: by_sport.get(sport, [])


def _et_utc(year, month, day, hour, minute=0):
    """ET datetime returned as a UTC-tz datetime (ET = UTC-4 during DST)."""
    from datetime import timezone as _tz
    return datetime(year, month, day, hour + 4, minute, tzinfo=_tz.utc)


def test_multi_anchor_picks_closest_to_anchor():
    """Two same-team events on same day; multi-anchor scan picks the
    event closest to one of the candidate anchors."""
    from server.odds.books.polymarket.event_matcher import PolymarketEventMatcher
    # Two NBA games at 1pm ET and 8pm ET on 2026-06-21
    events = _events(
        ("nba", "ev_day", "Boston Celtics", "Miami Heat", _et_utc(2026, 6, 21, 13, 0)),
        ("nba", "ev_pm",  "Boston Celtics", "Miami Heat", _et_utc(2026, 6, 21, 20, 0)),
    )
    matcher = PolymarketEventMatcher(cache_events_for_sport=events)
    # Date-only slug → matcher tries anchors {7pm, 10pm} (NBA per anchor table)
    # 8pm event is closest to 7pm anchor → should pick ev_pm.
    noon_et_anchor = _et_utc(2026, 6, 21, 12, 0)
    result = matcher.match_multi_anchor(
        "nba", "Boston Celtics", "Miami Heat",
        candidate_commences=[
            _et_utc(2026, 6, 21, 19, 0),
            _et_utc(2026, 6, 21, 22, 0),
        ],
        tight_window_min=180,
    )
    assert result is not None
    assert result["event_id"] == "ev_pm"


def test_multi_anchor_returns_none_when_no_anchor_hits():
    """If all anchors are too far from any event, return None."""
    from server.odds.books.polymarket.event_matcher import PolymarketEventMatcher
    # A single event at 2am ET (way outside any anchor window)
    events = _events(
        ("nba", "ev1", "Boston Celtics", "Miami Heat", _et_utc(2026, 6, 21, 2, 0)),
    )
    matcher = PolymarketEventMatcher(cache_events_for_sport=events)
    result = matcher.match_multi_anchor(
        "nba", "Boston Celtics", "Miami Heat",
        candidate_commences=[
            _et_utc(2026, 6, 21, 19, 0),
            _et_utc(2026, 6, 21, 22, 0),
        ],
        tight_window_min=180,
    )
    assert result is None
```

- [ ] **Step 3: Run to verify fail**

```bash
.venv/bin/python -m pytest server/tests/test_polymarket_event_matcher.py -v
```

Expected: AttributeError on `match_multi_anchor`.

- [ ] **Step 4: Implement on Polymarket matcher**

In `server/odds/books/polymarket/event_matcher.py`, add to the `PolymarketEventMatcher` class:

```python
    def match_multi_anchor(
        self,
        sport_key: str,
        team_a: str, team_b: str,
        candidate_commences: list[datetime],
        tight_window_min: int = 180,
    ) -> dict | None:
        """Try each anchor in turn at `tight_window_min`. Return the
        match closest in time to any anchor, or None if none hit.

        Falls back to caller's existing single-anchor wide-window
        `match()` is the caller's responsibility — keep that one as
        the safety net.
        """
        best: tuple[float, dict] | None = None
        for anchor in candidate_commences:
            result = self.match(
                sport_key, team_a, team_b, anchor,
                window_minutes=tight_window_min,
            )
            if result is None:
                continue
            ev_ts = result["commence_time"]
            if isinstance(ev_ts, str):
                from datetime import datetime as _dt
                ev_ts = _dt.fromisoformat(ev_ts.replace("Z", "+00:00"))
            if ev_ts.tzinfo is None:
                ev_ts = ev_ts.replace(tzinfo=timezone.utc)
            diff = abs((ev_ts - anchor).total_seconds())
            if best is None or diff < best[0]:
                best = (diff, result)
        return best[1] if best is not None else None
```

- [ ] **Step 5: Implement on Kalshi matcher**

Same shape in `server/odds/books/kalshi/event_matcher.py` — add `match_multi_anchor` to the class. Same body.

- [ ] **Step 6: Wire into Polymarket normalizer call site**

Find where `PolymarketEventMatcher.match()` is called from the normalizer with a date-only noon-ET anchor (search `matcher.match\|.match(` in `server/odds/books/polymarket/`). Wrap that call with a multi-anchor scan first, falling back to the existing wide-window single-anchor call if multi-anchor returns None:

```python
from ._anchor_table import anchors_for_sport, TIGHT_WINDOW_MIN

# Build candidate anchors at the slug date in US/Eastern
slug_date = ...  # already parsed
from zoneinfo import ZoneInfo
ET = ZoneInfo("America/New_York")
candidates = [
    datetime(slug_date.year, slug_date.month, slug_date.day, h, m, tzinfo=ET).astimezone(timezone.utc)
    for h, m in anchors_for_sport(sport_key)
]
# Try tight multi-anchor first
event = matcher.match_multi_anchor(
    sport_key, team_a, team_b, candidates, tight_window_min=TIGHT_WINDOW_MIN,
)
if event is None:
    # Fallback: original wide-window noon-ET anchor
    noon_et = datetime(slug_date.year, slug_date.month, slug_date.day, 12, 0, tzinfo=ET).astimezone(timezone.utc)
    event = matcher.match(sport_key, team_a, team_b, noon_et)
```

- [ ] **Step 7: Wire into Kalshi normalizer call site**

In `server/odds/books/kalshi/normalizer.py`, find line 413 (`matched = match_event(sport_key, canon_a, canon_b, commence, match_window)`). Only on the date-only branch (where `has_precise_time` is False), do the multi-anchor try-then-fallback dance.

- [ ] **Step 8: Run all tests**

```bash
.venv/bin/python -m pytest server/tests/test_polymarket_event_matcher.py server/tests/test_kalshi_normalizer.py -v
.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py
```

Expected: new tests pass, no regressions.

- [ ] **Step 9: Commit**

```bash
git add server/odds/books/_anchor_table.py server/odds/books/polymarket/event_matcher.py server/odds/books/polymarket/normalizer.py server/odds/books/kalshi/event_matcher.py server/odds/books/kalshi/normalizer.py server/tests/test_polymarket_event_matcher.py
git commit -m "$(cat <<'EOF'
feat(matching): multi-anchor date-only event matching (M3)

When a Polymarket slug / Kalshi ticker carries only a date (no HHMM),
try matching against per-sport US-Eastern candidate anchors
({noon, 7pm, 10pm} default; tighter for NBA/NHL/WNBA evening-only)
each at a ±3h window. Pick the closest match across anchors. Falls
back to the existing noon-ET ±12h wide-window match if no anchor
hits. Removes the random-pick behavior on same-day back-to-backs
between the same two teams.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verification — manual end-to-end

```bash
.venv/bin/python -m pytest server/tests/ -q --ignore=server/tests/test_coral33_event_matcher.py --ignore=server/tests/test_coral33_normalizer.py --ignore=server/tests/test_ev.py
```

Expected: all pass, no new skips. The pre-existing failures in coral33_event_matcher / coral33_normalizer / ev tests (15 total, from before this session) remain — they're unrelated to Tier 3 and excluded from this verification.

Restart the server, navigate to `/edges`, confirm:
- Server boots without errors (M5 validation passes against the real code map).
- No arbs disappear vs pre-Tier-3 baseline (the fixes are additive / correctness-preserving — they may surface MORE arbs from M6 partials and unify M4 duplicates, never fewer).
- The uvicorn log contains the M7 collision warnings (if any colliding addresses exist in the cache).

---

## Deferred follow-ups (intentionally out of scope)

- True Coral33 live-game-status polling (M8 alternative; new endpoint subscription + state machine).
- M4 backfill of existing duplicate rows (10-minute cache TTL does it for free).
- A "matching health" dashboard surfacing M7 WARN counts.
- M3 per-sport tuning of anchor sets beyond NBA/NHL/WNBA (revisit if specific miss cases surface).
