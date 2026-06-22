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
- **Per-parlay maximum stake is a hard constraint per account.** Standard accounts cap at **$100/parlay**; the Ryan Stanley account caps at **$150/parlay**. The cap travels with each account in `CORAL33_ACCOUNTS` env JSON (`max_parlay_stake` field). The cap is per-parlay, NOT per-account-per-signal: **the same account may take multiple separate parlays** for one signal if its balance covers them.
- **When the Kelly target exceeds a single parlay's cap, the sidecar fans out across multiple parlays** — stacking on the same account as long as the account's balance covers each successive parlay, then moving to the next account. Examples:
  - Target $300, account A has $250 balance → **A: $100, A: $100, A: $50, B: $50** (3 parlays on A drain its balance, then 1 parlay on B for the remainder).
  - Target $300, account A has $500 balance → **A: $100, A: $100, A: $100** (3 parlays all on A; B never used).
  - Target $105, account A has high balance → **A: $75, B: $30** (NOT A: $100 + leftover $5; the floor forces a peel-back).
- **Per-parlay floor: $30.** No individual parlay placement is allowed to be smaller than $30. If a planned tail residual would fall under $30, the splitter peels dollars back from a prior parlay to bring the tail up to exactly $30 (see Splitter algorithm). If the entire Kelly target itself is below $30, the signal is skipped and logged.
- **Account ordering is lowest-balance-first.** The walk visits accounts in ascending balance order, draining each one's parlay capacity (multiple parlays as needed) before moving on. Stanley's $150 cap is honored only when Stanley happens to be the next-walked account; the splitter does NOT reorder to minimize parlay count.
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
FLOOR = 30   # dollars; no individual parlay smaller than this

def plan_splits(
    target: int,                     # dollars, rounded
    accounts: list[AccountSnapshot], # full pool snapshot with credentials
) -> SplitPlan:
    """Multi-parlay-per-account walk. Lowest balance first; drain each account
    by stacking max-cap parlays; take one partial if it fits; peel back the
    last parlay if the residual would be sub-floor."""
    if target < FLOOR:
        return SplitPlan(assignments=[], status="below_minimum", target=target)

    eligible = sorted(
        [a for a in accounts if a.available_balance >= FLOOR],
        key=lambda a: a.available_balance,
    )
    if not eligible:
        return SplitPlan(assignments=[], status="no_eligible_account",
                         target=target)

    assignments: list[SplitAssignment] = []   # list of {account, amount}
    remaining = target

    for account in eligible:
        if remaining == 0:
            break
        balance = account.available_balance
        cap = account.max_parlay_stake

        # 1. Stack full-cap parlays while the account can fund another
        #    AND the target still needs another full-cap parlay.
        while balance >= cap and remaining >= cap:
            assignments.append(SplitAssignment(account, cap))
            balance -= cap
            remaining -= cap

        if remaining == 0:
            break

        # 2. Try one partial parlay on this account.
        partial = min(balance, remaining, cap)
        if partial < FLOOR:
            continue   # this account has too little headroom for another parlay
        new_remaining = remaining - partial
        if new_remaining == 0 or new_remaining >= FLOOR:
            assignments.append(SplitAssignment(account, partial))
            balance -= partial
            remaining = new_remaining
        else:
            # 0 < new_remaining < FLOOR. Shrink this partial so the residual
            # lands exactly on FLOOR, which the next account can take cleanly.
            adjusted = partial - (FLOOR - new_remaining)
            if adjusted >= FLOOR:
                assignments.append(SplitAssignment(account, adjusted))
                balance -= adjusted
                remaining = FLOOR

    # 3. Final peel-back. If we exited the loop with a sub-floor residual,
    #    try reducing the most recent parlay by (FLOOR - remaining) and
    #    placing the FLOOR on the next-cheapest account that has FLOOR free
    #    (different account from the one we peeled from — keeps the bet on
    #    a fresh proxy and avoids stacking yet another parlay on a draining
    #    account).
    if 0 < remaining < FLOOR and assignments:
        last = assignments[-1]
        deficit = FLOOR - remaining
        if last.amount - deficit >= FLOOR:
            alt = next(
                (a for a in eligible
                 if a.customer_id != last.account.customer_id
                 and a.available_balance >= FLOOR),
                None,
            )
            if alt is not None:
                last.amount -= deficit
                assignments.append(SplitAssignment(alt, FLOOR))
                remaining = 0

    status = "planned" if remaining == 0 else "partial_fill"
    return SplitPlan(assignments=assignments, status=status, target=target)
```

**Worked examples (validating against user-stated cases):**

| Target | Pool snapshot | Result | Why |
|--------|---------------|--------|-----|
| $300 | A=$250 balance, B=$500 balance, standard caps | **A:$100, A:$100, A:$50, B:$50** | Stack on A until balance drained; carry the $50 residual to B. |
| $300 | A=$500 balance, B=$500 balance, standard caps | **A:$100, A:$100, A:$100** | All three parlays fit on A; B never visited. |
| $105 | A=$1000 balance, B=$1000 balance, standard caps | **A:$75, B:$30** | Naïve walk would leave a $5 sub-floor residual; peel-back reduces A's parlay by $25 and places $30 on B. |
| $260 | A=$250 balance, B=$1000 balance, standard caps | **A:$100, A:$100, A:$30, B:$30** | Partial on A is shrunk from $50→$30 so the residual lands exactly on FLOOR for B. |
| $130 | Stanley=$300 (cap $150), B=$1000 (cap $100); Stanley lowest balance | **Stanley:$130** | One parlay on Stanley fits cleanly under its $150 cap. |
| $230 | Stanley lowest, then a standard at $1000 | **Stanley:$150, B:$80** | Drain Stanley's cap; carry residual to B. |
| $18 | any pool | `below_minimum` | Skipped. |
| $200 | only one account has balance ≥ $30, balance $80 | `partial_fill` at $80 | User paged for top-up. |

**Property checks the unit tests must enforce:**

1. `sum(a.amount for a in plan.assignments) == target` when `status == "planned"`.
2. Every `a.amount >= FLOOR` in every plan.
3. Every `a.amount <= account.max_parlay_stake` (per-parlay cap honored).
4. The **sum** of amounts per `account.customer_id` in a plan is `<= account.available_balance` (no account is over-spent across its multiple parlays).
5. Account ordering of first-appearance in the assignments list is ascending by `available_balance` at the time of planning.

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

### Multi-parlay pacing

When a single signal produces N > 1 parlays — whether stacked on the same account or spread across accounts — the BackgroundTask fires them **sequentially with a small jittered delay** between each (3–8 seconds, uniform random).

Rationale: even on a single account, three identical parlays arriving inside one second is an obvious automation fingerprint. The same gap that disguises multi-account placements also looks like a human re-typing the next slip on the same account. Single-parlay jobs fire immediately (no gap because there's nothing to disguise).

Total wall time for N=3 is ~10–25s — acceptable for parlays where line decay is measured in tens of seconds.

When consecutive assignments land on the same account, the sidecar **reuses the open `Coral33Client` session** (single JWT, single proxied connection) rather than re-authenticating per parlay. The jitter still applies, but the client lifecycle is per-account, not per-parlay.

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

### Per-placement failures (one row per failed assignment)

The behavior depends on whether the failure is **account-scoped** (will repeat for every sibling assignment on the same account) or **parlay-scoped** (specific to this one parlay request).

| Mode | Scope | Trigger | Behavior |
|---|---|---|---|
| `auth_failed` | account-scoped | `client.authenticate()` raises `Coral33AuthError` | Mark this assignment failed. **Skip all remaining sibling assignments queued for the SAME account** (they would fail identically). Continue with assignments on other accounts. |
| `proxy_failure` | account-scoped | `curl_cffi` raises a connection error before the request body sends | Same as `auth_failed`: skip remaining same-account siblings; continue with other accounts. |
| `line_changed` | parlay-scoped (but signal-correlated) | Coral returns a price-changed error | Abort THIS parlay. Write `error` with the price diff. **Stop the entire job** — every sibling assignment will hit the same line change. Emit `sidecar_partial_fill` with whatever has already landed. **No auto-accept**. |
| `insufficient_balance` | account-scoped | Coral rejects the bet citing balance | The accounts cache was stale, OR a prior sibling on this account drained it more than expected. Mark failed; skip remaining same-account siblings; continue with other accounts. |
| `placement_timeout` | parlay-scoped | No response in 20s on `place_parlay` | Write `error`. Surface "verify manually" — placement state ambiguous; `POST /api/coral33/accounts/refresh` will resolve. **Continue with the next assignment** (the user may want partial coverage even if this one is unclear). |

### Post-loop status

| Mode | Trigger | Behavior |
|---|---|---|
| `partial_fill` | Splitter planned `status='partial_fill'` (pool short of target) OR one+ assignments errored | SSE `sidecar_partial_fill` with `filled_stake = sum(placed)` and `unfilled_stake = target - filled_stake`. Run-log row tagged orange. |

**Key principles:**

- Per-placement failures **do not re-pick** to a different account or re-run the splitter mid-job. Retrying mid-flight can produce an over-floor / under-cap violation if the remaining pool can't host the new amount. Simpler: surface the failure and let the user re-fire if they want full coverage.
- **Account-scoped failures cascade** within the job: if account A's first parlay fails on auth, parlays 2 and 3 queued on A also get marked `error` and skipped without an attempt. This avoids burning 3 placement attempts on a known-broken session.
- **`line_changed` halts the whole job.** Every sibling parlay is on the same +EV leg, so the price change applies to all of them. Continuing would just produce N copies of the same error.

## Testing strategy

### Unit

- `splitter.py`: every property check listed in Splitter rule, plus all seven worked-example rows from the table render to the correct assignments. Property tests with Hypothesis: any plan satisfies invariants (sum, floor, cap, no-dupes, sort order).
- `placement.py`: mode gating — dry-run never instantiates a real `Coral33Client`, never authenticates, never POSTs; live mode does. Jitter is bypassable via an injected sleep function so tests run synchronously.
- `audit.py`: round-trip persistence of every `result` state including `error_message` and `accepted_payload`; `job_id` grouping query returns rows ordered correctly.
- `settings.py`: defaults applied when keys are absent (bankroll → 10000, default_kelly → half); type validation rejects bogus modes / fractions.
- `mode_store.py`: round-trip of `dry-run` / `live`; defaults to `dry-run` on missing file; concurrent reads are safe (mirror existing `CacheModeStore` tests).

### Integration

- `FakeCoral33Client` (test fixture) records every `place_parlay` call. End-to-end through `POST /api/sidecar/place` proves: dry-run is a no-op (no client construction even when assignments exist), live calls the client with the right payload per assignment, all SSE events fire on the right paths in the right order, audit rows land grouped by `job_id`.
- **Stacked-on-one-account end-to-end test:** target $250 against a fixture pool where account A has $260 balance produces three assignments (A:$100, A:$100, A:$50) all on the same `Coral33Client` session, three `placed` audit rows under one `job_id` with the same `picked_account`.
- **Cross-account end-to-end test:** target $300 against (A:$250, B:$500) produces A:$100, A:$100, A:$50, B:$50 — four assignments, two distinct client sessions, four `placed` rows.
- **Account-scoped cascade test:** target $230 split as Stanley:$150, B:$80 — Stanley's auth fails on first attempt; the test confirms the splitter does NOT retry on Stanley for a hypothetical second sibling (there isn't one here; but in a target $250 case with Stanley:$150 + Stanley:$30 wait — Stanley's cap is $150, so 250 would be Stanley:$150 + B:$100; that doesn't stack on Stanley. Use a different fixture: target $250 against A=$300 balance cap $100 → A:$100, A:$100, A:$50; if first A:$100 auth-fails, both other A assignments are marked `error` without an HTTP attempt).
- **Partial-fill end-to-end test:** target $300 against a pool that can only fund $130 → one `placed` row + one `partial_fill` row + `sidecar_partial_fill` SSE.
- **Peel-back test:** target $105 against (A:$1000, B:$1000) produces A:$75, B:$30 — verify the partial on A is the peel-back result, not a naive $100.
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
