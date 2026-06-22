# Auto-Bet Sidecar — Coral33 Multi-Account Placement

**Date:** 2026-06-21
**Status:** Design — pending reviewer pass
**Roadmap item:** New (not yet in `ROADMAP.md`)

## Context

The site already runs a `/api/ev` scanner that surfaces +EV rows across every connected book, tagged with `kelly_full_pct` / `kelly_quarter_pct` and (for Coral33 rows only) a `wager_type` ∈ {`straight`, `parlay`, `both`} indicating whether the offered line lives on Coral33's Parlay tab.

The user is running a 9-account Coral33 strategy that deliberately *cycles* deposits/promos out of Coral and into regulated books via low-hold and middling. The Coral33 side of every trade is structured as a parlay: the +EV leg (from `/api/ev`) is paired with a manually-picked "open" second leg, then hedged on a regulated book separately. The site already authenticates and reads from all 9 Coral33 sub-accounts via `server/odds/books/coral33/client.py:Coral33Client` and `accounts.py:AccountsScraper`, but the client is **read-only** — `Get_LeagueLines2`, `getAccountInfo`, `Pending`, `getWagersByFigureDate`. There is no `placeWager` operation today.

Today, the user manually logs into each account, picks the eligible one with enough balance, and places the parlay by hand. The repetition is the bottleneck. This spec covers a "sidecar" that automates the **Coral33 leg only** — the user continues to place the hedge manually on the regulated book.

## Goals

- One-click placement of a 2-leg parlay (one +EV leg surfaced by the scanner + one user-picked open leg) on Coral33 from `/edges`.
- Stake is computed from a user-set static bankroll × the chosen Kelly fraction. Default bankroll **$10,000**; default Kelly fraction **half**. (Modal also exposes Full and Quarter.)
- **Per-account parlay maximum is a hard constraint.** Standard accounts cap at **$100/parlay**; the Ryan Stanley account caps at **$150/parlay**. The cap travels with each account in `CORAL33_ACCOUNTS` env JSON (`max_parlay_stake` field).
- **When the Kelly target exceeds a single account's cap, the sidecar splits the target across multiple accounts as multiple separate parlays.** Example: target $300 → three $100 bets on three different accounts. Example: target $105 → $75 + $30 (NOT $100 + $5, because $5 < $30 floor).
- **Per-split floor: $30.** No individual placement is allowed to be smaller than $30. If the residual after capping would fall under the floor, the splitter pulls dollars back from the prior placement to bring the tail up to $30 (see Splitter algorithm). If the entire Kelly target itself is below $30, the signal is skipped and logged.
- **Account selection within each split is lowest-balance-first.** Stanley's $150 cap is honored only when Stanley happens to be the next-picked account. The picker does NOT prefer Stanley to minimize split count.
- Per-account requests route through a dedicated sticky residential proxy URL (one per account, static).
- If the pool can't fund the full target even after splitting, the sidecar refuses to fire and pages the user to top up.
- A `dry-run` / `live` master toggle in a dedicated `sidecar_mode.json` store is the sole guardrail, defaulted to `dry-run` and explicitly flipped by the user — mirrors the `cache_mode` pattern (`server/odds/cache_mode.py`, `server/config/cache_mode.json`) already established for the metered Odds API fetcher.

## Non-goals (v1)

- **Auto-firing the hedge** on regulated books. The user remains in the loop for the non-Coral side.
- **Auto-picking the open leg.** The open leg is always user-supplied per placement.
- **Auto-firing on EV signal** without an explicit click. The user remains the trigger; the sidecar automates split planning, login, payload, and receipts.
- **Cap-aware splitter optimization** (preferring Stanley to minimize split count). Explicitly rejected — lowest-balance-first wins.
- **Below-floor rounding** (placing $30 when Kelly says $18). Sub-floor signals are skipped, not rounded up.
- **Daily loss / count / stake caps, min-EV threshold, auto-quarantine of error-prone accounts.** Explicitly excluded per user decision. The `dry-run` / `live` toggle is the only guardrail.
- **Refreshing account balances at fire time.** The sidecar trusts the existing accounts cache from `AccountsScraper`. Stale-balance edge cases land as `auth_failed` / `placement_timeout` / `insufficient_balance` and surface via the standard error path.

## Architecture

### Process model

In-process inside the existing FastAPI server. New module `server/sidecar/`. New API surface under `server/api/sidecar.py`. New Next.js route `/sidecar` for the dashboard. The trigger flow is **synchronous-looking but background-tasked**: `POST /api/sidecar/place` validates the request, enqueues a `BackgroundTask` and returns a `job_id` immediately. The UI subscribes to the existing SSE channel for the result.

Rationale: a single-process, single-user, laptop-local deployment doesn't justify a separate daemon. The placement path reuses the FastAPI worker pool the same way the existing `/api/coral33/accounts/refresh` already does for the multi-account scrape.

### Module layout

```
server/sidecar/
  __init__.py
  models.py          # Pydantic: LegSpec, SidecarPlaceRequest, SplitPlan, SplitAssignment, PlacementResult, RunLogEntry
  splitter.py        # plan_splits(target, accounts) → SplitPlan
  placement.py       # orchestrator: splitter → per-assignment client.place_parlay → audit log → SSE emit
  audit.py           # SQLite r/w for sidecar_placements
  mode_store.py      # SidecarModeStore — dedicated sidecar_mode.json (parallels cache_mode.py)
  settings.py        # typed accessors over user_settings.json for sidecar_bankroll
server/api/sidecar.py
  POST /api/sidecar/place           → 202 { job_id }
  GET  /api/sidecar/runs            → recent placements (paginated)
  GET  /api/sidecar/runs/{job_id}   → one placement detail
  GET  /api/sidecar/mode            → { mode: "dry-run" | "live" }
  POST /api/sidecar/mode            → flip mode (mirrors /api/cache_mode)
```

### Extension to the Coral33 client

`server/odds/books/coral33/client.py` gains exactly one new method:

```python
async def place_parlay(
    self,
    legs: list[LegSpec],     # 2-leg ticket: [ev_leg, open_leg]
    stake_dollars: float,
) -> PlaceParlayResponse:
    """POST the captured place-wager operation. Returns ticket # + accepted prices."""
```

The operation name, path, and form-payload shape come from a request the user captures from coral33.com via browser DevTools — same reverse-engineering path used to produce `authenticateCustomer` and `Get_LeagueLines2`. Until that request is captured, the method is stubbed and `place_parlay` raises `NotImplementedError` in live mode (dry-run still works against the stub, returning the payload that *would* have been sent).

`Coral33Client.__init__` is extended with an optional `proxy_url: str | None`. When set, the underlying `curl_cffi.AsyncSession` is constructed with `proxies={"http": proxy_url, "https": proxy_url}`. The token cache, browser-header fingerprinting, and JWT refresh logic are unchanged.

### Proxy plumbing

The existing `CORAL33_ACCOUNTS` env JSON is extended with **two** new per-entry fields:

```json
[
  {
    "customer_id": "VR11601",
    "password": "…",
    "label": "Account 1",
    "proxy_url": "http://user:pass@us-east.residential-pool.example:7777",
    "max_parlay_stake": 100
  },
  {
    "customer_id": "VR12509",
    "password": "…",
    "label": "Ryan Stanley",
    "proxy_url": "http://user:pass@us-west.residential-pool.example:7777",
    "max_parlay_stake": 150
  }
]
```

- `proxy_url`: missing/null is allowed but emits a startup `WARN` per account (development convenience; production use should always set it).
- `max_parlay_stake`: per-account hard ceiling Coral33 enforces server-side. Defaults to **$100** if absent. Stanley's entry sets **$150**. The splitter never allocates more than this to one account in one job.
- `accounts.py:AccountCredential` gains `proxy_url: str | None = None` and `max_parlay_stake: int = 100` fields.
- `AccountsScraper` reads the proxy and passes it through when constructing the per-account `Coral33Client` for the balance scrape. The existing accounts roll-up therefore also starts using per-account proxies — desirable side effect, since same-IP reads across 9 accounts is the same anti-detection concern as same-IP placements. `max_parlay_stake` rides on the credential dataclass and feeds the splitter.

### Splitter rule

```python
MIN_SPLIT = 30   # dollars; no individual placement smaller than this

def plan_splits(
    target: int,                     # dollars, rounded
    accounts: list[AccountSnapshot], # full pool snapshot with credentials
) -> SplitPlan:
    """Returns SplitPlan(assignments, status) where:
      - assignments is a list of (account, amount) tuples, sum == target on success,
      - status is one of: planned, below_minimum, no_eligible_account, partial_fill."""
    if target < MIN_SPLIT:
        return SplitPlan(assignments=[], status="below_minimum",
                         target=target)

    # Eligible = balance covers at least one split's worth.
    eligible = sorted(
        [a for a in accounts if a.available_balance >= MIN_SPLIT],
        key=lambda a: a.available_balance,
    )
    if not eligible:
        return SplitPlan(assignments=[], status="no_eligible_account",
                         target=target)

    assignments: list[SplitAssignment] = []
    remaining = target

    for account in eligible:
        if remaining == 0:
            break
        cap = min(account.max_parlay_stake, int(account.available_balance))
        if remaining > cap:
            # Full assignment; more to come on next account
            assignments.append(SplitAssignment(account, cap))
            remaining -= cap
        elif remaining >= MIN_SPLIT:
            # Final assignment fits cleanly
            assignments.append(SplitAssignment(account, remaining))
            remaining = 0
        else:
            # 0 < remaining < MIN_SPLIT — pull back from previous
            if assignments:
                pull_back = MIN_SPLIT - remaining
                prev = assignments[-1]
                if prev.amount - pull_back >= MIN_SPLIT:
                    prev.amount -= pull_back
                    assignments.append(SplitAssignment(account, MIN_SPLIT))
                    remaining = 0
                    break
            # Can't satisfy MIN_SPLIT on tail; drop residual
            break

    status = "planned" if remaining == 0 else "partial_fill"
    return SplitPlan(assignments=assignments, status=status, target=target)
```

**Worked examples (validating against user-stated cases):**

| Target | Pool snapshot | Result |
|--------|---------------|--------|
| $300 | three standard accounts (cap $100 each), each balance ≥ $100 | $100 + $100 + $100 across three accounts |
| $105 | two standard accounts (cap $100 each), each balance ≥ $100 | $75 + $30 (pull-back from naive $100 + $5) |
| $130 | Stanley (cap $150) is lowest balance, others above | $130 on Stanley alone |
| $130 | Stanley above; lowest standard account has $500 balance | $100 (standard) + $30 (next-lowest) |
| $230 | Stanley lowest, then standard, then standard | $150 (Stanley) + $80 (next-lowest) |
| $18 | any pool | `below_minimum`; signal skipped |
| $200 | only one account has balance ≥ $30 (others empty), that account has $80 | `partial_fill` at $80; user paged |

**Property checks the unit tests must enforce:**

1. `sum(a.amount for a in plan.assignments) == target` when `status == "planned"`.
2. Every `a.amount >= MIN_SPLIT` in every plan.
3. Every `a.amount <= min(account.max_parlay_stake, account.available_balance)`.
4. No account appears twice in one plan.
5. Account selection within the plan is ascending by `available_balance` at the time of planning.

### Configuration shape

Two new pieces of persisted state, deliberately split between two stores by sensitivity:

**`server/config/sidecar_mode.json`** — dedicated store, mirrors `cache_mode` exactly:

```json
{"mode": "dry-run"}
```

- `mode`: `"dry-run"` | `"live"`. Defaults to `"dry-run"`. Flipped via a dedicated `POST /api/sidecar/mode` endpoint (paralleling `POST /api/cache_mode`), which the UI exposes as a top-of-page toggle on `/sidecar`. Backed by a `SidecarModeStore` class modeled on `CacheModeStore` (`server/odds/cache_mode.py`). Memory rule: **never auto-flip `sidecar_mode` to `"live"`** — same protocol as `cache_mode`.

**`server/config/user_settings.json`** — the existing user-settings store gains two routine keys:

```json
{
  "sidecar_bankroll": 10000,
  "sidecar_default_kelly": "half"
}
```

- `sidecar_bankroll`: the dollar figure that Kelly fractions multiply against to produce the stake. Default **$10,000**. Set once, edited rarely. Exposed via the existing `/api/settings` PATCH surface.
- `sidecar_default_kelly`: `"full"` | `"half"` | `"quarter"`. Default **`"half"`**. Pre-selects the radio in the modal; user can change per placement.

The split is deliberate: live-mode arming is a sensitive blast-radius gate and earns its own store + endpoint + persistence file (same calculus that justified `cache_mode.json`'s separate existence); the bankroll number and default Kelly fraction are routine values that belong with other user preferences.

### Storage — one new table in `cache.db`

One row per **placement** (per Coral33 ticket attempt). A single user-triggered signal can produce N rows sharing the same `job_id` when the splitter fans out, plus one extra row for pre-flight refusals (`below_minimum`, `no_eligible_account`) where `picked_account` and `stake` are NULL.

```sql
CREATE TABLE sidecar_placements (
  placement_id    TEXT PRIMARY KEY,            -- uuid4, unique per row
  job_id          TEXT NOT NULL,               -- groups split-siblings of one signal
  created_at      INTEGER NOT NULL,            -- unix seconds
  ev_row_id       TEXT NOT NULL,               -- canonical (event_id, market_key, address) tuple-string
  open_leg        TEXT NOT NULL,               -- JSON of LegSpec (identical across split-siblings)
  ev_leg          TEXT NOT NULL,               -- JSON of LegSpec at fire time (identical across split-siblings)
  kelly_fraction  TEXT NOT NULL,               -- 'full' | 'half' | 'quarter'
  target_stake    REAL NOT NULL,               -- total Kelly target for the job (identical across split-siblings)
  stake           REAL,                        -- THIS placement's dollar amount; NULL on pre-flight refusal rows
  mode            TEXT NOT NULL,               -- 'dry-run' | 'live'
  picked_account  TEXT,                        -- customer_id, NULL on pre-flight refusal rows
  result          TEXT NOT NULL,               -- 'placed' | 'dry_run' | 'no_eligible_account' | 'below_minimum' | 'partial_fill' | 'error'
  ticket_number   TEXT,                        -- Coral33 wager #, NULL on dry-run / error / refusal
  accepted_payload TEXT,                       -- raw JSON response (full body for audit)
  error_message   TEXT                         -- short error class for UI; NULL on success
);
CREATE INDEX sidecar_placements_job_id ON sidecar_placements(job_id);
CREATE INDEX sidecar_placements_created_at ON sidecar_placements(created_at DESC);
```

- **`partial_fill` rows** capture the residual the splitter couldn't allocate (e.g., target $200 but pool can only fund $80). One `partial_fill` row + N successful `placed` rows can co-exist under one `job_id`.
- Audit-grade: every placement attempt (including refusals and dry-runs) lands here. Never deleted by code; user can `DELETE` manually.

### Data flow

```
[User on /edges]
    ↓ click "Auto-place" on a row with Coral33 best price AND wager_type ∈ {parlay, both}
[Open-leg modal]
    ↓ type-ahead picks the open leg from current Coral33 odds cache
    ↓ select kelly_fraction (default from sidecar_default_kelly, typically 'half')
    ↓ modal displays the SplitPlan preview (N rows: account, label, $amount)
    ↓ Confirm
POST /api/sidecar/place { ev_row_id, open_leg, kelly_fraction }
    ↓ resolve ev_row_id → ev_leg snapshot
    ↓ target = round(kelly_fraction × sidecar_bankroll)
    ↓ plan = splitter.plan_splits(target, accounts_cache)
    ↓ enqueue BackgroundTask(job_id, plan), return 202 { job_id, plan_preview }
[BackgroundTask]
    ↓ if plan.status == 'below_minimum' → write 1 refusal row, emit sidecar_signal_skipped SSE, done
    ↓ if plan.status == 'no_eligible_account' → write 1 refusal row, emit sidecar_topup_required SSE, done
    ↓ if dry-run → write 1 dry_run row per assignment with the would-be payload, emit sidecar_placement SSE per row, done
    ↓ live → for each assignment in plan.assignments (sequential, jittered):
            Coral33Client(creds, proxy_url=creds.proxy_url)
              → authenticate()
              → place_parlay(legs=[ev_leg, open_leg], stake_dollars=assignment.amount)
              → write audit row (placed | error), emit sidecar_placement SSE
    ↓ if plan.status == 'partial_fill' after the loop → write 1 partial_fill row, emit sidecar_partial_fill SSE
[UI]
    ↓ modal subscribes to job_id-scoped SSE → renders a row per split → ticket # appears as each lands
    ↓ /sidecar page run-log appends in place; rows that share job_id render grouped
```

### SSE events

Three new event types added to the existing broker (`server/api/stream.py`). All carry `job_id`:

- `sidecar_placement`: per-assignment result. `{ job_id, placement_id, result, ticket_number?, picked_account, stake, mode, split_index, split_total }`.
- `sidecar_topup_required`: pre-flight refusal due to insufficient pool funds. `{ job_id, target_stake, max_fundable, lowest_balance_account }`.
- `sidecar_signal_skipped`: pre-flight refusal due to sub-floor target. `{ job_id, target_stake, floor: 30 }`.
- `sidecar_partial_fill`: post-loop notification that the splitter couldn't allocate the full target. `{ job_id, target_stake, filled_stake, unfilled_stake }`.

Reuses the existing `useLiveUpdates` hook in the Next.js app — no new transport wiring.

### Multi-split pacing

When a single signal produces N > 1 placements, the BackgroundTask fires them **sequentially with a small jittered delay** between each (3–8 seconds, uniform random). Rationale: N separate parlays on the same +EV leg arriving at Coral via N different proxied sessions within milliseconds is the most fraud-team-friendly synchronization pattern available. A 3–8s gap looks like distinct sessions placing distinct bets. Single-split jobs fire immediately (no gap because there's nothing to disguise). Total wall time for N=3 is ~10–25s — acceptable for parlays where line decay is measured in tens of seconds.

## UI surface

### `/edges` — new "Auto-place" button

Each row where `book == "coral33"` AND `is_best_price` AND `wager_type ∈ {parlay, both}` gets a compact button at the end of the row. The button is suppressed entirely when `sidecar_mode == "dry-run"` and `sidecar_bankroll` is zero/unset — there's nothing to fire.

Click opens a modal:

- **Header.** The +EV leg description (event, market, side, price). Three stat chips: **EV%**, **Kelly%** (radio: Full / Half / Quarter, default from `sidecar_default_kelly`), **Target $** (live-computed from the kelly fraction × `sidecar_bankroll`, rounded to whole dollars).
- **Body.** A type-ahead "Pick the open leg" search. Filters the current Coral33 odds cache (already in browser state via SWR) by event name, market, side. Selected leg renders as a card under the search with a "change" link.
- **Split plan preview.** Below the open-leg picker, a live-computed table shows the splitter's plan for the current target:

  ```
  Plan: $230 across 2 placements
    1. VR12509 — Ryan Stanley       $150   (balance $640)
    2. VR11601 — Account 1          $80    (balance $920)
  ```

  Re-renders whenever the user changes the Kelly radio. If `status == 'below_minimum'`: red banner "Kelly target $18 is below $30 floor — signal will be skipped." If `status == 'no_eligible_account'`: red banner "No account has $30+ available — top up to fire." If `status == 'partial_fill'`: yellow banner "Pool can fund $80 of $230; only $80 will be placed." Confirm button is **disabled** for `below_minimum` and `no_eligible_account`; **enabled** for `partial_fill` (user accepts the partial).
- **Footer.** Mode badge: *dry-run* (muted yellow) or *live* (saturated green). Buttons: **Cancel** / **Confirm**. Confirm is disabled until an open leg is picked AND the plan is non-empty.
- **Result.** Modal shows a row per planned assignment, each with a spinner that swaps to a ticket # on SSE receipt. Sequential reveal mirrors the jittered placement order. Closes after the last assignment lands (or errors out) plus a ~3s read window.

### `/sidecar` — new top-nav page

Pinned to the existing top-nav alongside `/odds`, `/edges`, `/accounts`. Three panels in the established Bloomberg-terminal palette (dark mode first, tabular figures for all $ values):

- **Left — live signal feed.** Mirrors `/api/ev?wager_filter=parlay&book=coral33&best_price=1` with the same inline Auto-place button. Filterable by sport tab bar at the top.
- **Right — account pool grid.** 9 cards, one per Coral33 sub-account. Each card: customer_id, label, current balance (large), available balance (smaller), today's bet count + stake total, last-used timestamp, a small dot indicator (green = last request succeeded, red = last 3 failed in a row, gray = no activity today). Cards sort by current balance ascending so the lowest-balance / next-to-fire account is at the top.
- **Bottom — run log.** Recent placements newest-first as a dense table. Rows that share a `job_id` are grouped visually (subtle background tint + a small "1/3, 2/3, 3/3" pill in the leftmost column). Columns: job time, sport, event/market/side, open leg short, stake, account, result badge, ticket #. Result badges: green `placed`, yellow `dry_run`, gray `no_eligible_account` / `below_minimum`, orange `partial_fill`, red `error` (with hover-tooltip for `error_message`).

## Error handling

Failure modes are categorized as **pre-flight** (caught before any HTTP fires) or **per-placement** (one assignment in a multi-split plan fails). All have a deterministic message and a deterministic next step.

### Pre-flight refusals (one row per job, no placements attempted)

| Mode | Trigger | Behavior |
|---|---|---|
| `below_minimum` | Splitter returns `status='below_minimum'` (target < $30) | SSE `sidecar_signal_skipped`; modal shows "Below $30 floor" banner. No placement. |
| `no_eligible_account` | Splitter returns `status='no_eligible_account'` (no account has ≥$30 available) | SSE `sidecar_topup_required` with `max_fundable=0`; modal shows top-up banner. No placement. |

### Per-placement failures (one row per failed assignment; sibling assignments in the same job continue)

| Mode | Trigger | Behavior |
|---|---|---|
| `auth_failed` | `client.authenticate()` raises `Coral33AuthError` | Mark this assignment failed, **do not retry on a different account** (the splitter already allocated the target across the pool — re-picking would change the plan mid-flight). Surface to modal/log. Other assignments in the job continue. |
| `line_changed` | Coral returns a price-changed error from `place_parlay` | Abort THIS assignment. Write `error` with the diff in `error_message`. **No auto-accept**. Other assignments in the job continue (they will hit the same price change; expected). |
| `insufficient_balance` | Coral rejects the bet citing balance | The accounts cache was stale. Write `error`. Other assignments continue. |
| `placement_timeout` | No response in 20s on `place_parlay` | Write `error`. Surface "verify manually" — placement state ambiguous; `POST /api/coral33/accounts/refresh` will resolve. Other assignments continue. |
| `proxy_failure` | `curl_cffi` raises a connection error before the request body sends | Write `error`. Other assignments continue. |

### Post-loop status

| Mode | Trigger | Behavior |
|---|---|---|
| `partial_fill` | Splitter planned `status='partial_fill'` (pool short of target) OR one+ assignments errored | SSE `sidecar_partial_fill` with `filled_stake = sum(placed)` and `unfilled_stake = target - filled_stake`. Run-log row tagged orange. |

**Key change vs the original spec:** per-placement failures **do not re-pick** to a different account. The splitter computed a plan up front; retrying with a different account would mean re-running the splitter mid-job, which can produce a smaller-than-allowed assignment if the only remaining eligible account is below the original assignment's amount. Simpler and safer to surface the failure and let the user re-fire manually if they want full coverage.

## Testing strategy

### Unit

- `splitter.py`: every property check listed in Splitter rule, plus all seven worked-example rows from the table render to the correct assignments. Property tests with Hypothesis: any plan satisfies invariants (sum, floor, cap, no-dupes, sort order).
- `placement.py`: mode gating — dry-run never instantiates a real `Coral33Client`, never authenticates, never POSTs; live mode does. Jitter is bypassable via an injected sleep function so tests run synchronously.
- `audit.py`: round-trip persistence of every `result` state including `error_message` and `accepted_payload`; `job_id` grouping query returns rows ordered correctly.
- `settings.py`: defaults applied when keys are absent (bankroll → 10000, default_kelly → half); type validation rejects bogus modes / fractions.
- `mode_store.py`: round-trip of `dry-run` / `live`; defaults to `dry-run` on missing file; concurrent reads are safe (mirror existing `CacheModeStore` tests).

### Integration

- `FakeCoral33Client` (test fixture) records every `place_parlay` call. End-to-end through `POST /api/sidecar/place` proves: dry-run is a no-op (no client construction even when assignments exist), live calls the client with the right payload per assignment, all SSE events fire on the right paths in the right order, audit rows land grouped by `job_id`.
- **Multi-split end-to-end test:** target $230 against a fixture pool (Stanley lowest balance, then two standards) produces two assignments, two `place_parlay` calls, two `placed` audit rows under one `job_id`, and the modal receipt sequence is observable in the SSE stream.
- **Partial-fill end-to-end test:** target $300 against a pool that can only fund $130 → one `placed` row + one `partial_fill` row + `sidecar_partial_fill` SSE.
- Splitter integration with `AccountsScraper`'s cache shape — confirms the splitter reads the same dataclasses the UI sees and that `max_parlay_stake` round-trips from env → credential → cache → splitter.

### Manual smoke (one-time, against the real captured endpoint)

1. **Dry-run smoke.** Place one synthetic 2-leg parlay through `/api/sidecar/place` in dry-run mode at a target that requires a split (e.g., $230). Inspect the resulting audit rows and SSE payloads to confirm both assignments produce the captured-endpoint payload shape.
2. **Live smoke, single split.** Flip `sidecar_mode = "live"`, fire one real placement at minimum stake ($30) on a heavy underdog. Verify (a) the modal receipt matches Coral's web UI, (b) the existing 30-min wager-mirror tick picks the new ticket up into `bets`, (c) the proxy IP appears in Coral's session log if exposed.
3. **Live smoke, multi-split.** Fire one real placement at a target that forces a split (e.g., $130 across two accounts). Verify: two distinct Coral wager numbers land, jittered gap between placements is visible in network logs, both wager-mirror rows surface.

### Verification gates before merge

- `pytest server/tests -v` passes including the new sidecar tests.
- `npx tsc --noEmit` + `npm run build` pass in `web/`.
- A dry-run end-to-end through the real UI button → real SSE receipt path, manually exercised.

## Open questions for plan-writing

- **Placement-endpoint capture timing.** The captured-request handoff must happen before live mode can be used. The user will provide a HAR file containing two captured placements: a straight bet ($5.15 on Oklahoma) and the parlay structure we'll actually use ($10 on New Zealand with one open leg). Plan should keep dry-run and live paths separable so dry-run lands first, with the live-mode wiring slotting in once the operation name + form payload are known.
- **"One open leg" parlay structure in the captured payload.** The user's playbook is to place a 2-leg parlay where one leg is the +EV signal and the other is intentionally left "open" (unsettled). The captured parlay request will show how Coral represents this on the wire — whether the open leg has a special status flag, whether it's a future-game leg with no current line, or some other shape. Plan should treat the captured payload as ground truth and pattern-match the sidecar's payload construction to it exactly.
- **Wager-mirror reconciliation.** The existing 30-min `bets_mirror.py` tick should naturally pick up sidecar-placed wagers. Worth a single integration test that confirms the new tickets land in the unified `bets` table without a sidecar-specific code path. With splits, one signal can produce N rows in `bets`; the test should confirm grouping is preserved (or that the existing schema handles N independent wagers cleanly).
- **Proxy-status dot derivation.** The "last 3 failed" indicator implies the sidecar tracks per-account request outcomes outside the audit log (which only records placement attempts, not the balance-scrape passes that share the same proxy). Two options to consider in the plan: extend the audit log to record balance-scrape results, or add a tiny in-memory ring buffer per account. Latter is probably simpler; plan to evaluate.
- **Force-refresh after placement.** When a live placement succeeds, should the sidecar fire `POST /api/coral33/accounts/refresh` for the picked account(s) immediately? Default: yes, so the new ticket and updated balance land in `/accounts` and the next signal's split plan reflects the spent dollars. Confirm with user before implementing.

## Migration / rollout

There is no data migration — the new table is empty on first boot. The new `sidecar_mode` / `sidecar_bankroll` / `sidecar_default_kelly` settings default cleanly to safe values. The `proxy_url` and `max_parlay_stake` fields are optional on `CORAL33_ACCOUNTS` entries (`max_parlay_stake` defaults to $100 when absent, matching the standard-account ceiling). Backward compatibility is automatic.

Rollout sequence:

1. Land the read-only path: settings, audit table, splitter, dry-run placement, SSE wiring, `/sidecar` page, `/edges` button with the split-plan preview — all behind `sidecar_mode=dry-run`. User can drive the full UX end-to-end and inspect would-be payloads at every split size.
2. Land the captured `place_parlay` endpoint method on the client (operation name, path, payload, response parsing) using the user-provided HAR.
3. User flips `sidecar_mode=live` after the single-split live smoke test passes.
4. After the multi-split live smoke test passes on a small target, the system is fully live.
