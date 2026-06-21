# Tier 3 — Odds-Matching Audit Fixes

**Date:** 2026-06-21
**Status:** Design — pending reviewer pass
**Roadmap items:** Tier 3 M3, M4, M5, M6, M7, M8

## Context

The 2026-06-21 odds-matching audit identified six correctness/observability gaps in the matching layer. None blocks current functionality, but each one is a known source of silent data loss or duplicate outcomes. They share a theme (matching-layer correctness) and ship cleanly as one batch — most are sub-100 LOC.

## Goals

Fix all six items so:
- Date-only Kalshi/Polymarket events resolve to the correct game even during high-cadence stretches (back-to-back playoff games, doubleheaders).
- Alt-spread rows from differently-emitting books collapse to a single canonical outcome key in the cache.
- A future Kalshi team rebrand can't silently break `_split_team_pair` event resolution.
- Polymarket soccer events with 2-of-3 legs available still emit (instead of being dropped entirely).
- Outcome-name collisions across books are logged for debugging before they become unrecoverable.
- Coral33's in-play purge stops eating rows for delayed / soft-start games.

## Non-goals

- New cross-book matching strategies (this is correctness on the existing flow).
- Schema migrations of historical data (M4 canonicalizes going forward; existing stale rows expire in 10 minutes).
- A new Coral33 endpoint poll to read live game status (M8 uses a grace window instead — same effect, no new HTTP).
- Visual changes to `/edges` or any UI surface.

## Architecture — six independent fixes

Each item lands as a discrete change. The audit recommendations already specify the direction; this spec pins implementation details and test surface.

### M3 — Tighter date-only time-window matching

**Files:** `server/odds/books/kalshi/normalizer.py`, `server/odds/books/polymarket/event_matcher.py`.

**Today:** Date-only Kalshi tickers and Polymarket date-only slugs anchor a single noon-ET candidate `commence_time` and the matcher accepts any Odds-API event within a wide window (`±6h` on Polymarket; Kalshi inherits the wide window indirectly via `_parse_event_ticker_commence`). Playoff back-to-backs between the same two teams can theoretically cross-pair.

**Fix:** Multi-anchor scan. For date-only inputs, generate candidate `commence_time`s at `{12:00, 19:00, 22:00}` US-Eastern (covers day games, primetime, late West-Coast windows). For each candidate, use a tight `±3h` window. Pick the candidate that's nearest in time to a real Odds-API event in the same date bucket. Falls back to the original wide window only when no candidate hits.

Anchors live in a per-sport constant (`_DATE_ONLY_ANCHORS_BY_SPORT_KEY`) so we can tune per sport without touching call sites. Default applies to all sports until overridden.

**Behavior change:** Same-team back-to-backs on the same day now resolve to the closer-in-time event (previously: random of the two, depending on the first to match). When the cache only has one event for the team pair on that date, behavior is unchanged.

### M4 — Canonicalize alt-spread orientation

**Files:** `server/odds/normalize.py` (sportsbook ingest), `server/odds/books/kalshi/normalizer.py`, `server/odds/books/polymarket/normalizer.py`.

**Today:** Some books emit `(outcome_name="Boston Celtics", outcome_point=-2.5)`; others emit `(outcome_name="Toronto Raptors", outcome_point=+2.5)` for the same line. The cache stores both as distinct outcome rows. `pairing.collect_spread_pairs` handles the complementary-signed-points join for arb/EV scanners, but the cache surface still has duplicates, which leaks into anything that reads outcomes flat (e.g., "best price for BOS at -2.5" queries).

**Fix:** Canonicalize spread outcomes at write time so every alt-spread row stores `(favored_team, negative_point)`. A new helper:

```python
def canonicalize_spread_outcome(
    outcome_name: str, outcome_point: float,
    home_team: str, away_team: str,
) -> tuple[str, float]:
    """If outcome_point >= 0, flip: outcome becomes the OTHER team with
    the negated point. Otherwise unchanged.
    Returns the canonicalized (outcome_name, outcome_point).
    Idempotent — re-applying produces the same result."""
```

Applied to spread-family markets (`spreads`, `alternate_spreads`, `spreads_h1`, etc. — anything keying on `outcome_point != 0` with two complementary outcomes) at three ingest sites: sportsbook normalize, Kalshi normalizer, Polymarket normalizer. Spread-family detection: `_is_spread_market(market_key)` helper checking if the key starts with `spreads` or `alternate_spreads` (covers period suffixes like `_h1`, `_q1`).

**No data migration:** existing rows expire in 10 minutes via `purge_stale_rows`; they'll be replaced by canonicalized rows on next fetch.

**Behavior change:** Cache-flat outcome queries return one row per line instead of two. Scanner output is unchanged (the pairing logic already merged the duplicates before scanning).

### M5 — Defensive Kalshi code_map validation

**Files:** `server/odds/books/kalshi/normalizer.py` (or its mapping module).

**Today:** `_split_team_pair("BOSMIA", code_map)` walks every split point and accepts the unique split where both halves are keys. If two codes are prefix-overlapping (e.g., `BOS` and `BOSEN` for a hypothetical future team), a ticker like `BOSENBOS` could split two valid ways and the function returns None, silently dropping the event.

**Fix:** A `validate_code_map_unique_prefixes(code_map: dict[str, str])` helper:

```python
def validate_code_map_unique_prefixes(code_map: dict[str, str]) -> None:
    """Raise if any code is a prefix of another. Called once at config
    load — fail loud so adding a future team rebrand doesn't silently
    break event resolution."""
```

Wired into the same load path that builds `code_map` today (likely a module-level constant in `kalshi/normalizer.py` or `kalshi/mapping.py`). On violation: raises `ValueError` with the offending pair.

**Behavior change:** Process boot fails if any current team-code pair violates the constraint. The audit's premise is that today's code maps are clean, so this is a guard against future regressions rather than a fix for an existing bug.

### M6 — Polymarket soccer 3-way partial-market emission

**Files:** `server/odds/books/polymarket/normalizer.py` (3-way aggregation pass).

**Today:** The 3-way aggregation requires all three soccer outcomes (home / draw / away) to be present. ~2-5% of early-tournament Polymarket soccer events have one leg missing (typically draw not yet listed) → entire event dropped.

**Fix:** Emit partials. When 2 of 3 outcomes are present, emit those 2 as a soccer h2h market with `outcome_name`s set per Polymarket's existing convention. Don't synthesize the missing leg. The 3-way overround sanity check (`overround_sum ~ 1.0 + small vig`) only runs when all 3 are present; partials skip it. Behavior preserved: when 3-of-3 are present, the existing emission stays unchanged.

**Behavior change:** Cross-book aggregation in `rows_to_games` now sees Polymarket contributing to 2-of-3 events. Scanner output may surface arbs that were previously hidden by the missing-leg drop.

### M7 — Outcome-name collision WARN logging

**Files:** `server/odds/normalize.py` (`rows_to_games` or its outcome grouping helper).

**Today:** When two books emit different `outcome_name` strings for the same `(event_id, market_key, outcome_point)` — e.g., "BOS" from Kalshi vs "Boston Celtics" from DraftKings — they hash to distinct outcome groups and never pair. There's no visibility.

**Fix:** During the outcome grouping pass, also group prices by `(event_id, market_key, outcome_point)` independently. When that bucket has multiple distinct `outcome_name` values, emit a `WARNING` once per `(event_id, market_key, outcome_point)` per process lifetime via a module-level dedup `set`. No behavior change — purely observability.

Log format: `outcome-name collision in {event_id}/{market_key}/{outcome_point}: {comma-separated names from each book}`.

### M8 — Coral33 in-play purge grace window

**Files:** `server/odds/books/coral33/fetcher.py` (around line 276) and the underlying `OddsCache.purge_live_rows_for_book`.

**Today:** `cache.purge_live_rows_for_book("coral33", now)` deletes any Coral33 row with `commence_time <= now`. Delayed games, rain delays, and soft starts have their pre-game lines purged even though they're still effectively "future."

**Fix:** Add an optional `grace_seconds` parameter to `purge_live_rows_for_book`. Default `0` (existing behavior for other call sites). Coral33's call passes `grace_seconds=1800` (30 minutes). The cache method becomes:

```python
def purge_live_rows_for_book(
    self, bookmaker_key: str, now: datetime,
    grace_seconds: int = 0,
) -> int:
    cutoff = (now - timedelta(seconds=grace_seconds)).isoformat()
    ...
```

The grace window catches the common delay case (most rain delays / soft starts are < 30 minutes) without polling Coral33 for live game status (audit's preferred fix — out of scope for this batch).

**Behavior change:** Coral33 rows whose `commence_time` is within the last 30 minutes survive the purge. Rows older than 30 minutes still get purged (Coral33 in-play prices remain untrusted by the sharp devig model).

## Testing

| Item | Test file | What it pins |
|------|-----------|--------------|
| M3 | `server/tests/test_kalshi_normalizer.py` + `server/tests/test_polymarket_event_matcher.py` | Multi-anchor scan picks the time-closest event; falls back to wide window when no anchor hits. |
| M4 | `server/tests/test_normalize.py` (new) and existing normalizer tests | Idempotency; happy path for both orientations from each source; non-spread markets pass through unchanged. |
| M5 | `server/tests/test_kalshi_normalizer.py` | Prefix collision raises; existing real `code_map` doesn't raise. |
| M6 | `server/tests/test_polymarket_normalizer.py` | 2-of-3 emits the 2 present outcomes; 3-of-3 happy path unchanged; existing overround filter still applies to 3-of-3. |
| M7 | `server/tests/test_normalize.py` (new) | Two books with different outcome_names on the same address emit one WARN; second occurrence is suppressed. |
| M8 | `server/tests/test_cache.py` and `server/tests/test_coral33_fetcher.py` (new) | `grace_seconds=1800` preserves rows in the grace window; rows older than that are purged. |

Existing scanner / arb / EV tests must remain green — none of these fixes change the scanner output shape.

## Error handling

| Failure | Behavior |
|---------|----------|
| M3: no anchor matches any event | Falls back to the existing wide-window scan (preserves today's behavior). |
| M4: home/away missing on the row | Skip canonicalization (no flip), pass through. Log a WARNING. |
| M5: code_map prefix violation at boot | Raises `ValueError` during config load — fail loud. |
| M6: partials emitted but overround check would fail on the 2-of-2 | Emit anyway; the cross-book devig downstream applies its own gates. |
| M7: dedup set memory growth | Bounded by distinct `(event_id, market_key, outcome_point)` tuples × process lifetime. Realistic worst case ~few thousand entries. Acceptable. |
| M8: server clock drift makes grace-window math negative | Guard with `max(grace_seconds, 0)` — never expand the purge window. |

## Out of scope / deferred

- True Coral33 live-game-status polling (would require a new endpoint subscription + state machine; the grace window captures the common case).
- M4 backfill of existing duplicate rows (10-minute staleness window does it for free).
- A "matching health" dashboard surfacing M7 WARN counts (the structured log line is enough for grep-based debugging today).
