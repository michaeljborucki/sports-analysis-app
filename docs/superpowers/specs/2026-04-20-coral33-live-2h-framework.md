# coral33 Live 2nd-Half Line Framework

**Date:** 2026-04-20
**Status:** Design — **NOT BUILT YET**
**Scope v1:** NBA only. Framework extensible to soccer, NCAAB, NHL, MLB.

---

## Goal

Turn coral33's period-specific lines (2nd Half in NBA, eventually `2nd Half` / `3rd Period` / etc. in other sports) into **drop-in equivalents of the Odds API's live full-game lines**, under the same market_key and adjusted-point value, so the existing scanners (arbitrage, low-hold, EV) don't need any awareness that the row is "second-half derived."

**Principle:** the row should land in the cache as a coral33 `totals` / `spreads` / `team_totals` entry, not as a separate `totals_h2` / `spreads_h2`. The "live" nature is carried implicitly (via `fetched_at > commence_time` — see purge logic below), not via a new market taxonomy.

---

## Markets in scope

- `totals` (Over / Under)
- `spreads` (signed per-team)
- `team_totals` (per-team Over / Under)

**Explicitly out of scope:** `h2h`. Coral's 2H moneyline (who wins just the second half) is fundamentally *not* the same market as the live full-game moneyline (who wins the match) even after score adjustment — the bets have different outcome spaces.

---

## Translation rules

Given `score = (home, away)` at the moment coral's 2H line is fetched, and a coral 2H line `coral_pt`:

| Market | Coral 2H value | Game-equivalent output |
|---|---|---|
| `totals` | Over / Under at `coral_pt` | Over / Under at `score_home + score_away + coral_pt` |
| `spreads` | home at `-X` / away at `+X` (signed) | home at `-X + (score_home − score_away)` / away at `+X − (score_home − score_away)` |
| `team_totals` | home Over/Under at `home_pt` | home Over/Under at `score_home + home_pt` |
| | away Over/Under at `away_pt` | away Over/Under at `score_away + away_pt` |

Prices (American odds) pass through unchanged — only the point is translated. The row is written under the same `market_key` coral would use for the full-game version (`totals`, `spreads`, `team_totals`), never under a `_h2` suffix.

**If score is unavailable or stale (>60s old), skip the row.** Better to drop data than to emit misaligned points.

---

## Dependency: Score fetcher

Odds API `/sports/{sport}/scores?daysFrom=1` — **paid endpoint** (deducts from `requests_remaining`). Returns an array of in-progress and recently-completed events, each with `score_home`, `score_away`, `status` (e.g., `"halftime"`, `"in_progress"`), and `last_update`.

We do **not** poll this continuously. See polling strategy below.

---

## Polling strategy — cost-aware

Score polling is the expensive leg of this feature. The rule set is designed to minimize `/scores` calls while still catching halftime shortly after it starts.

### Per-sport baseline offsets

Each sport has a static estimate of how long after `commence_time` halftime (or the relevant mid-game inflection) typically arrives. Until the estimated window opens, we don't poll scores at all for that event.

| Sport | Halftime offset | Notes |
|---|---|---|
| **NBA** | **60 min** | Regulation 24 min × 2 + ~30 min of clock stoppages → halftime falls ~1 h real-time after tip |
| NCAAB | 50 min | 20-min halves, slightly tighter clock |
| Soccer | 45 min | 1st half = 45 min regulation + 1–5 min stoppage (hence some buffer on the poll trigger, not the offset itself) |
| NHL | 40 min | 2nd intermission; 2H concept maps to "after P2" for this model |
| MLB | 60 min | "After 5th inning" as the 2H analogue; average length of the first half of an MLB game |

**Flagged for v1: estimates only.** Track actual halftime arrival vs. our offset for 30 days, then tune per sport from the observed distribution. The doc contains estimates, not empirical truth.

### Dynamic adjustment

Once a first `/scores` poll succeeds for a live event, the response's `status` or game-clock field drives the next poll time. Two cases:

1. **Halftime detected** (`status="halftime"` or equivalent): poll coral's 2H endpoint for this event on the next coral main-tier cycle. Once we successfully insert a translated row, back off score polling for this event to 2–3 min intervals until the 2H line stops updating, then stop.

2. **Not halftime yet** (`status="in_progress"`, still in first half): estimate time-to-halftime from the game clock. Use the formula:

   ```
   next_poll_in = max(60s, remaining_time_to_halftime / 2)
   ```

   Rationale: halve the remaining wait repeatedly until we're close to halftime, then poll once a minute to catch the transition. E.g., "10 min left in 1st half" → next poll in 5 min. "2 min left" → next poll in 60 s.

### Per-event stop conditions

Stop polling scores for an event when **any** of:

- 2H lines successfully captured *and* we've ingested at least one full cycle of live-translated rows
- Game ends (`status="final"` or similar)
- 30 min into the 2nd half with no coral 2H data detected (bail out — coral sometimes skips)
- Coral returns a CaptchaRequired (shared backoff with main fetcher)

### Budget / observability

**Required instrumentation from day 1:**

- Log every `/scores` call with: `event_id, sport, time_since_kickoff, reason, response_status`
- Per-event counter: total score polls, first-halftime-detected-at, whether 2H translated rows were successfully written
- Aggregate: `/api/coral33/score-poll-stats` endpoint returning daily `{requests: N, matches_produced: M, efficiency_ratio: M/N}`

Wasted polls (no halftime detected, no rows captured) are the headline metric. If `efficiency_ratio < 0.3` for an extended period, the baseline offsets need tuning.

---

## Architecture (v1 — NBA only)

### New modules

```
server/odds/scores/
  __init__.py
  fetcher.py          # ScoreFetcher — polls /scores on dynamic cadence per live event
  cache.py            # in-memory store: {event_id → (home_score, away_score, last_update, status)}
  stats.py            # per-event poll counters + aggregate metrics
server/api/
  scores_ctl.py       # GET /api/coral33/score-poll-stats
```

### Modified modules

- `server/odds/books/coral33/normalizer.py` — **new path** `normalize_live_period(response, period, score_lookup, sport_key, fetched_at)`. For each 2H line: look up score via injected callable; if fresh, apply the translation rule table above; emit rows under `totals` / `spreads` / `team_totals`.
- `server/odds/books/coral33/fetcher.py` — NBA main cycle includes a "2nd Half" pull; when data is present, route through the live-period normalizer with a score-lookup callable pointed at `ScoreFetcher`.
- `server/odds/cache.py::purge_live_rows_for_book` — updated purge rule: `DELETE WHERE bookmaker='coral33' AND commence_time <= now AND fetched_at < commence_time`. Preserves live-translated rows (`fetched_at >= commence_time`) while still stripping stale pre-game rows once the event has tipped off.

### Config

```toml
# server/config/coral33.toml  (additions)

[sports.nba.live_2h]
enabled                  = true
halftime_offset_minutes  = 60     # start polling scores after this point from kickoff
score_poll_min_seconds   = 60     # hard floor on score-poll cadence
markets                  = ["totals", "spreads", "team_totals"]

# Placeholders for future sports (NOT enabled in v1):
# [sports.soccer.live_2h]
# enabled                 = false
# halftime_offset_minutes = 45
# markets                 = ["totals", "spreads", "team_totals"]

# [sports.baseball_ncaa.live_2h] etc.
```

---

## Phased rollout

### Phase 1 — data plumbing (NBA, 60-min static baseline)
- `ScoreFetcher` with baseline offset only, no dynamic adjustment yet
- Live-period normalizer for NBA `totals` / `spreads` / `team_totals`
- Updated `purge_live_rows_for_book` rule
- Score-poll logging to stdout
- Verify live-translated rows land in cache under game-level market keys

### Phase 2 — dynamic poll cadence
- Parse game clock from `/scores` response
- `next_poll_in = max(60s, remaining / 2)` schedule
- Per-event stop conditions

### Phase 3 — efficiency dashboard
- `GET /api/coral33/score-poll-stats`
- UI card on `/settings` showing daily polls / matches / ratio
- Track 30-day distribution of actual halftime offset vs. baseline → recommend tuning

### Phase 4 — multi-sport
- Soccer (MLS first)
- NCAAB (when in season)
- NHL + MLB if value is demonstrated

---

## Efficiency note — to revisit

The 60-min NBA baseline and `max(60s, remaining/2)` dynamic rule are **estimates**, not measured. Review after 30 days of real data:

- Actual distribution of `halftime_time − commence_time` per sport
- Average `/scores` calls per successful 2H capture
- Score-poll waste ratio

If the feature isn't producing a defensible number of +EV matches per 1000 score-polls spent, tighten offsets or deprecate the whole pipeline. Build the metric before building the feature dependency on it.

---

## Open questions

- Exact shape of the Odds API `/scores` response for NBA (field names, clock format) — confirm via a one-shot test call before building ScoreFetcher
- `/scores` quota cost — docs say it's metered; need to verify the per-request cost empirically
- Does coral33's own main-tier response include current score for live games? If yes, we could partially avoid the Odds API dependency on the score side (coral score → translate coral 2H point → compare against Odds API live full-game price). Worth probing.
- How accurate is coral33's 2H line vs. sharp live markets? Track mean/variance of (coral_2H_equivalent_total − pinnacle_live_total) after 30 days to know whether the feature is actually +EV or noise.

---

## What's built today vs. what this spec adds

**Already built (this session, previous commits):**
- Coral33 client, normalizer, fetcher for pre-game + in-play pre-kickoff
- Live-game row purge (`purge_live_rows_for_book`) — currently over-aggressive, needs the `fetched_at < commence_time` refinement for this feature
- Full EV / arb / low-hold / free-bet scanners that read game-level market keys

**To build for v1 (Phase 1):**
- `server/odds/scores/*` (new)
- `normalize_live_period` function
- NBA "2nd Half" period in coral33's main cycle
- Updated purge rule
- `/api/coral33/score-poll-stats` endpoint (can stub initially)
