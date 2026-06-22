# Auto-Bet Sidecar — Coral33 Multi-Account Placement

**Date:** 2026-06-21
**Status:** Design — pending reviewer pass
**Roadmap item:** New (not yet in `ROADMAP.md`)

## Context

The site already runs a `/api/ev` scanner that surfaces +EV rows across every connected book, tagged with `kelly_full_pct` / `kelly_quarter_pct` and (for Coral33 rows only) a `wager_type` ∈ {`straight`, `parlay`, `both`} indicating whether the offered line lives on Coral33's Parlay tab.

The user is running a 7-account Coral33 strategy that deliberately *cycles* deposits/promos out of Coral and into regulated books via low-hold and middling. The Coral33 side of every trade is structured as an open-spot parlay: the +EV leg (from `/api/ev`) is placed as the single picked leg of a 2-pick parlay with one server-reserved open slot, then hedged on a regulated book separately. The site already authenticates and reads from all 7 Coral33 sub-accounts via `server/odds/books/coral33/client.py:Coral33Client` and `accounts.py:AccountsScraper`, but the client is **read-only** — `Get_LeagueLines2`, `getAccountInfo`, `Pending`, `getWagersByFigureDate`. There is no `placeWager` operation today.

The 7 accounts in the pool (Jimmy Dixon `VR11601`, Mike Bower `VR11605`, Ben Schraeder `VR65801014`, Ryan Stanley `VR11606`, Parker Guild `VR11607`, Kellen Platt `VR11609`, Owen Foster `VR11610`) each have a dedicated sticky-IP residential proxy (Decodo, distinct ports 10001–10007). Ryan Stanley's account has a $150/parlay limit; the other six are capped at $100/parlay.

Today, the user manually logs into each account, picks the eligible one with enough balance, and places the parlay by hand. The repetition is the bottleneck. This spec covers a "sidecar" that automates the **Coral33 leg only** — the user continues to place the hedge manually on the regulated book.

## Goals

- One-click placement of a **1-placed-leg + 1-open-spot parlay** on Coral33 from `/edges`. The +EV leg surfaced by the scanner goes in as the single picked leg; Coral's server-side `openSpotFlag` reserves the second slot at the parlay card's default `-110`, producing a ~2.6× payout multiplier on a 2-team card (this is how the HAR's $10 → $99.77 math works). There is no user-picked second leg — the open spot is server-managed.
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
- A **three-state** master toggle `off` / `dry-run` / `live` in a dedicated `sidecar_mode.json` store is the sole guardrail, defaulted to `off` and explicitly flipped by the user — mirrors the `cache_mode` pattern (`server/odds/cache_mode.py`, `server/config/cache_mode.json`) already established for the metered Odds API fetcher. **`off` is a hard kill-switch** intended for use while debugging live: no new user-triggered placements accepted, no background delta re-fires, no Auto-place affordance visible in the UI. In-flight `BackgroundTask`s already running when `off` is flipped run to completion (we don't leave Coral in a half-placed state); they just don't get successors.
- **Autonomous Kelly-delta re-firing.** Once the user clicks Auto-place on a signal, the sidecar tracks it as an active signal and **autonomously fires additional placements as Kelly grows**. A background tick (every 60s) re-checks every active signal's current Kelly target; when `current_target - total_placed_for_this_signal >= $30` (the same per-parlay floor), the delta is enqueued as a new placement job that runs through the splitter, the picker, and the placement chain exactly like a user-triggered fire. Tracking stops when the event's `commence_time` passes; if the EV scanner stops surfacing the row mid-tracking, the tick simply skips it for that minute (could come back).

## Non-goals (v1)

- **Auto-firing the hedge** on regulated books. The user remains in the loop for the non-Coral side.
- **User-picked second leg.** The HAR confirms the open spot is server-side via `openSpotFlag: "O"` + `totalPicks: 2` + `minPicks: 1`. Nothing for the user to type in. Earlier brainstorm draft proposed an open-leg typeahead; the HAR contradicts it; the typeahead is dropped.
- **Auto-firing on EV signal** without an explicit click. The user remains the trigger; the sidecar automates split planning, login, payload, and receipts.
- **Cap-aware splitter optimization** (preferring Stanley to minimize split count). Explicitly rejected — lowest-balance-first wins.
- **Below-floor rounding** (placing $30 when Kelly says $18). Sub-floor signals are skipped, not rounded up.
- **Daily loss / count / stake caps, min-EV threshold, auto-quarantine of error-prone accounts.** Explicitly excluded per user decision. The `dry-run` / `live` toggle is the only guardrail.
- **Refreshing account balances at fire time.** The sidecar trusts the existing accounts cache from `AccountsScraper`. Stale-balance edge cases land as `auth_failed` / `placement_timeout` / `insufficient_balance` and surface via the standard error path.
- **Unwinding placed bets when Kelly shrinks.** If the line moves against you and current Kelly drops below `total_placed`, the sidecar does NOT void any placed parlays. New deltas just stop firing until Kelly grows past `total_placed + $30` again (could be never, that's fine).
- **Per-signal stop conditions other than `commence_time`.** No Coral33-no-longer-best-price stop, no manual stop button, no automatic deactivation on drop-out. The only deactivation is the game starting. If the signal drops out of `/api/ev` briefly mid-game-day, the tick skips it; if it reappears later, tracking resumes.

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

`server/odds/books/coral33/client.py` gains **one public method** (`place_open_parlay`) that internally orchestrates the captured five-call placement sequence reverse-engineered from the user's HAR (`~/Downloads/coral33.com.har`).

```python
async def place_open_parlay(
    self,
    ev_leg: LegSpec,            # the +EV leg surfaced by the scanner
    stake_dollars: float,       # ≤ this client's max_parlay_stake; ≥ FLOOR
    parlay_name: str = "10 team",
) -> PlaceParlayResponse:
    """Place one 1-placed-leg + 1-open-spot parlay.
    Returns ticket # + accepted price + the parsed payout block."""
```

`Coral33Client.__init__` is extended with an optional `proxy_url: str | None`. When set, the underlying `curl_cffi.AsyncSession` is constructed with `proxies={"http": proxy_url, "https": proxy_url}`. The token cache, browser-header fingerprinting, and JWT refresh logic are unchanged.

#### The five-call placement chain (from HAR)

Every successful parlay placement Coral33's web UI makes is this exact sequence. The sidecar replicates it:

| # | Operation | Path | Purpose | Required? |
|---|---|---|---|---|
| 1 | `getParlaySpecs` | `Limit/getParlaySpecs` | Returns `{ MaxPicks, DefaultPrice: -110 }` for the parlay card. Cacheable per (customer, parlayName). | Once per session per customer; cache result. |
| 2 | `getInfoParlay` | `Limit/getInfoParlay` | Returns the per-team-count multiplier table. For `teams: 2`, the 2-team card pays `MoneyLine: 2.6` × the placed leg's decimal odds. Used for the modal payout display. | Once per placement (cheap; tells us expected payout for the receipt). |
| 3 | `checkWagerLineMulti` | `WagerSport/checkWagerLineMulti` | **Mandatory gate.** Pre-validates the line and returns: (a) the current line snapshot, (b) a `DELAY: { time, secs, sig }` block. The `sig` is a short-lived server signature that `insertWagerParlay` MUST replay or the placement is rejected as anti-tamper. | Every placement, immediately before step 4. |
| 4 | `insertWagerParlay` | `WagerSport/insertWagerParlay` | The actual placement. Carries the `list: [leg]` + `wager.openSpotFlag: "O"` + `wager.totalPicks: 2` + `wager.minPicks: 1` + the `delay` block from step 3. Returns `{ STATUS: { STATE: 1, DOC: <ticket# } }` on success. | Once per placement. |
| 5 | `getPendingByTicket` | `Report/getPendingByTicket` | Pulls the just-landed ticket for receipt display. | Optional but useful — feeds the modal receipt card and audit's `accepted_payload`. |

#### Per-customer placement context

Several placement-payload fields come from the customer's profile and don't vary per bet. The sidecar reads them once via `Customer/getAccountInfo` (already wired) and caches them on the client:

- `agentID` (e.g., `"TYSONR"`) — master agent. May differ per customer.
- `store` (e.g., `"wiseguys"`) — observed static across the HAR but read it dynamically.
- `custProfile` (e.g., `".                   "` — 20-char padded) — read from `getAccountInfo`.
- `office` — already a constant in the client (`"LEOOFFICE"`).
- `volumeAmount` — per-customer; appears in the HAR as `500` (straight) and `1000` (parlay). The sidecar sets it to `stake_dollars * 100` empirically (matches the HAR ratios); confirm by replay.

#### Open-spot payload shape (the placement body's critical fields)

The `wager` block inside `insertWagerParlay.list[0]` is what makes this an open-spot parlay:

```json
{
  "minPicks": 1,
  "totalPicks": 2,
  "openSpotFlag": "O",
  "parlayName": "10 team",
  "parlayPayOutType": "R",
  "maxPayOut": 1000000,
  "roundRobin": 0,
  "wagerCount": 1,
  "team": 2,
  "lineType": "P",
  "riskAmount": <stake_dollars>,
  "winAmount": <getInfoParlay 2-team multiplier × decimal_odds × stake>,
  "description": "<sport> #<rotNum> <chosenTeam> <price_american> - For Game ",
  "playNumber": 1,
  ...constant fields (date, freePlay, agentID, currencyCode, creditAcctFlag)
}
```

The outer placement record carries the per-leg pricing snapshot (`finalMoney`, `finalDecimal`, `finalNumerator`, `finalDenominator`, `chosenTeamID`, etc.) — all of which come from the `checkWagerLineMulti` response in step 3. The sidecar copies that block verbatim.

#### Dry-run vs live

In dry-run mode the client stops after step 3 (`checkWagerLineMulti`), captures the would-be `insertWagerParlay` payload (constructed but not sent), and returns a synthetic `PlaceParlayResponse` with `result="dry_run"` plus the constructed payload for audit display. In live mode steps 4–5 execute.

The choice to still run step 3 in dry-run is deliberate: it (a) confirms the leg is still live and parlay-eligible right now (catches stale-cache mismatches), and (b) gives the audit log a real `DELAY.sig` value so the dry-run payload is a true replica.

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
- `AccountsScraper` reads the proxy and passes it through when constructing the per-account `Coral33Client` for the balance scrape. The existing accounts roll-up therefore also starts using per-account proxies — desirable side effect, since same-IP reads across 7 accounts is the same anti-detection concern as same-IP placements. `max_parlay_stake` rides on the credential dataclass and feeds the splitter.

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
{"mode": "off"}
```

- `mode`: `"off"` | `"dry-run"` | `"live"`. Defaults to `"off"`. Flipped via a dedicated `POST /api/sidecar/mode` endpoint (paralleling `POST /api/cache_mode`), which the UI exposes as a three-button toggle at the top of `/sidecar`. Backed by a `SidecarModeStore` class modeled on `CacheModeStore` (`server/odds/cache_mode.py`). Memory rule: **never auto-flip `sidecar_mode` to `"live"`** — same protocol as `cache_mode`. `"off"` mode behavior:
  - `POST /api/sidecar/place` returns `503 Service Unavailable` with body `{"detail": "sidecar mode is off"}`.
  - Auto-place button on `/edges` is hidden (or disabled with a tooltip).
  - The 60s background re-fire tick exits early without scanning active signals.
  - In-flight `BackgroundTask`s already running when `off` is flipped DO complete (jitter, all assignments). After they finish, no new jobs accept.

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
  ev_leg          TEXT NOT NULL,               -- JSON of LegSpec at fire time (identical across split-siblings)
  parlay_name     TEXT NOT NULL DEFAULT '10 team',  -- Coral parlay card name; always "10 team" for now
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

### Storage — second new table: `sidecar_active_signals`

The autonomous re-fire loop needs persistent state surviving server restarts. One row per (`ev_row_id`) currently being tracked:

```sql
CREATE TABLE sidecar_active_signals (
  ev_row_id         TEXT PRIMARY KEY,
  kelly_fraction    TEXT NOT NULL,             -- 'full' | 'half' | 'quarter' — fraction the user selected
  bankroll_at_arm   INTEGER NOT NULL,          -- $ snapshot when the signal was armed
  commence_time     INTEGER NOT NULL,          -- unix s; tick stops re-firing once now > this
  total_placed      REAL NOT NULL DEFAULT 0,   -- sum of every successful 'placed' / 'dry_run' stake on this ev_row_id
  first_armed_at    INTEGER NOT NULL,          -- when the user originally clicked Auto-place
  last_checked_at   INTEGER,                   -- updated on every tick scan, fire or not
  last_delta_at     INTEGER,                   -- updated only when a delta fire actually happens
  last_target       REAL                       -- the kelly_pct × bankroll value at the most recent tick
);
CREATE INDEX sidecar_active_signals_commence ON sidecar_active_signals(commence_time);
```

- Rows are **inserted** when a user-triggered placement succeeds for the first time (the orchestrator's `handle_place` finishes its loop AND `bankroll_at_arm` snapshot reflects the bankroll setting at arm time, so future bankroll edits don't retroactively change earlier-armed signals' targets).
- Rows are **updated** by the re-fire tick on every minute it runs (`last_checked_at`) and by the orchestrator on every successful placement that ties to this `ev_row_id` (`total_placed += stake`).
- Rows are **not deleted** automatically; rows with `commence_time < now` are filtered out at tick scan time. Stale rows accumulate but the table stays small (max one row per game per signal).
- The orchestrator also writes through to `total_placed` after a delta-driven job lands, so the next tick sees the updated baseline.

### Data flow

```
[User on /edges]
    ↓ click "Auto-place" on a row with Coral33 best price AND wager_type ∈ {parlay, both}
[Confirm modal]
    ↓ select kelly_fraction (default from sidecar_default_kelly, typically 'half')
    ↓ modal displays the SplitPlan preview (N rows: account, label, $amount, expected payout)
    ↓ Confirm
POST /api/sidecar/place { ev_row_id, kelly_fraction }
    ↓ resolve ev_row_id → ev_leg snapshot
    ↓ target = round(kelly_fraction × sidecar_bankroll)
    ↓ plan = splitter.plan_splits(target, accounts_cache)
    ↓ enqueue BackgroundTask(job_id, plan), return 202 { job_id, plan_preview }
[BackgroundTask]
    ↓ if plan.status == 'below_minimum' → write 1 refusal row, emit sidecar_signal_skipped SSE, done
    ↓ if plan.status == 'no_eligible_account' → write 1 refusal row, emit sidecar_topup_required SSE, done
    ↓ for each assignment in plan.assignments (sequential, jittered 3–8s):
            client = Coral33Client(creds, proxy_url=creds.proxy_url)  # reused across same-acct siblings
              → authenticate() (if not already)
              → place_open_parlay(ev_leg, stake_dollars=assignment.amount, parlay_name="10 team"):
                   1. getParlaySpecs("10 team")                   [cached per session]
                   2. getInfoParlay(teams=2, selects=…, parlayName="10 team")
                   3. checkWagerLineMulti([ev_leg])  →  DELAY.sig
                   4. dry-run? → return synthetic response with would-be payload, skip 4–5
                      live?    → insertWagerParlay(list=[ev_leg],
                                                   wager={openSpotFlag:"O", totalPicks:2, minPicks:1, …},
                                                   delay=DELAY)
                   5. getPendingByTicket(ticket_number)
              → write audit row (placed | dry_run | error), emit sidecar_placement SSE
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

### Autonomous Kelly-delta re-firing

A 60-second APScheduler tick (registered alongside the existing fetchers in `main.py`) runs `delta_tick()`:

```
def delta_tick():
    if sidecar_mode in ("off", ...): return     # bail early on hard kill
    now = unix_now()
    active = SELECT * FROM sidecar_active_signals WHERE commence_time > now
    for signal in active:
        leg, kelly_full_pct = resolve_ev_row_to_leg(signal.ev_row_id) or (None, None)
        UPDATE sidecar_active_signals SET last_checked_at = now WHERE ev_row_id = signal.ev_row_id
        if leg is None:
            continue   # row dropped out of /api/ev this tick — try again next minute

        current_kelly_pct = kelly_to_pct(signal.kelly_fraction, kelly_full_pct)
        current_target_dollars = round(current_kelly_pct × signal.bankroll_at_arm)
        delta = current_target_dollars - signal.total_placed
        UPDATE sidecar_active_signals SET last_target = current_target_dollars

        if delta < $30: continue   # below floor, skip
        enqueue a placement job for `delta` dollars on this signal
        UPDATE sidecar_active_signals SET last_delta_at = now
```

**Key design decisions:**

- **`bankroll_at_arm` is frozen at the first placement** — this prevents "user changed bankroll setting, now every active signal re-targets and fires huge deltas next tick." If the user wants the new bankroll applied to existing active signals, they manually re-arm by clicking Auto-place again (which inserts a fresh row with the new bankroll). This matches the principle that bankroll edits should require deliberate user action per active signal.
- **`kelly_fraction` is also frozen** — same reasoning. The user committed to a fraction at original-placement time.
- **`total_placed` includes every successful placement** for this `ev_row_id` regardless of which job created it (initial or delta). The orchestrator increments it atomically (within a sqlite transaction) when each `placed` audit row lands.
- **The delta-driven job is structurally identical to a user-triggered job**: same `ev_row_id`, same `kelly_fraction`, same orchestrator path, same splitter/picker/placer/SSE/audit flow. The only difference is the **trigger source field** in the audit row (new column `trigger_source TEXT NOT NULL DEFAULT 'user'` — `'user'` | `'delta_tick'`).
- **Dry-run mode also fires delta ticks** — same as user-triggered, just halts at step 3 of the placement chain. This is critical for testing the autonomous loop without burning real money.
- **Re-entry safety**: if a delta job is still in-flight when the next tick fires (e.g., 60s isn't long enough for a 4-split sequential placement at maxed-out jitter), the tick computes the delta against the row's CURRENT `total_placed` which doesn't yet include in-flight splits. To avoid double-firing, the tick takes a row-level lock (`UPDATE sidecar_active_signals SET ... WHERE ev_row_id = ? AND last_delta_at IS NOT ? RETURNING ...`) so concurrent ticks see consistent state. Or simpler: in-process per-signal asyncio lock that the tick acquires before computing delta and releases after the job is fully drained. Latter is simpler given we're in a single-process server.

**Schema addition (deferred to a small migration step, not on the existing `sidecar_placements` until E2):**

```sql
ALTER TABLE sidecar_placements ADD COLUMN trigger_source TEXT NOT NULL DEFAULT 'user';
-- 'user' | 'delta_tick'
```

The UI surfaces this on the run log as a small badge: "user" for user-triggered, "delta" for delta-triggered.

### Multi-parlay pacing

When a single signal produces N > 1 parlays — whether stacked on the same account or spread across accounts — the BackgroundTask fires them **sequentially with a small jittered delay** between each (3–8 seconds, uniform random).

Rationale: even on a single account, three identical parlays arriving inside one second is an obvious automation fingerprint. The same gap that disguises multi-account placements also looks like a human re-typing the next slip on the same account. Single-parlay jobs fire immediately (no gap because there's nothing to disguise).

Total wall time for N=3 is ~10–25s — acceptable for parlays where line decay is measured in tens of seconds.

When consecutive assignments land on the same account, the sidecar **reuses the open `Coral33Client` session** (single JWT, single proxied connection) rather than re-authenticating per parlay. The jitter still applies, but the client lifecycle is per-account, not per-parlay.

## UI surface

### `/edges` — new "Auto-place" button

Each row where `book == "coral33"` AND `is_best_price` AND `wager_type ∈ {parlay, both}` gets a compact button at the end of the row. The button is suppressed entirely when `sidecar_mode == "dry-run"` and `sidecar_bankroll` is zero/unset — there's nothing to fire.

Click opens a confirm modal (NO open-leg picker — the open spot is server-side):

- **Header.** The +EV leg description (event, market, side, American price). Three stat chips:
  - **EV%** — from the EV row.
  - **Kelly%** — radio: Full / Half / Quarter. Default from `sidecar_default_kelly` (typically Half).
  - **Target $** — `round(kelly_fraction × sidecar_bankroll)`. Re-renders on radio change.
- **Expected payout strip.** Below the header, a single line: *"2-team parlay (open spot at -110): Risk $X → Win $Y"*. The 2-team multiplier comes from a cached `getInfoParlay` per (sport, parlay_name); on first open the modal makes the call, caches it in memory for ~5 minutes, and shows a small loading shimmer while it fetches. The win amount uses `Target $` × (decimal_odds × 2.6 multiplier).
- **Split plan preview.** A live-computed table:

  ```
  Plan: $230 across 2 placements
    1. VR12509 — Ryan Stanley       $150   (balance $640)
    2. VR11601 — Account 1          $80    (balance $920)
  ```

  Re-renders on Kelly radio change. Status banners:
  - `below_minimum` → red: "Kelly target $18 is below the $30 floor — signal will be skipped."
  - `no_eligible_account` → red: "No account has $30+ available — top up to fire."
  - `partial_fill` → yellow: "Pool can fund $80 of $230; only $80 will be placed."
  - Confirm is **disabled** for `below_minimum` / `no_eligible_account`; **enabled** for `partial_fill` (user accepts the partial).
- **Footer.** Mode badge: *dry-run* (muted yellow) or *live* (saturated green). Buttons: **Cancel** / **Confirm**.
- **Result.** Modal shows a row per planned assignment, each with a spinner that swaps to a ticket # on SSE receipt. Sequential reveal mirrors the jittered placement order. Closes after the last assignment lands (or errors out) plus a ~3s read window.

### `/sidecar` — new top-nav page

Pinned to the existing top-nav alongside `/odds`, `/edges`, `/accounts`. Layout in the established Bloomberg-terminal palette (dark mode first, tabular figures for all $ values):

- **Top bar — three-button mode toggle.** `Off` / `Dry-run` / `Live`. The active mode is highlighted (off = muted gray, dry-run = muted yellow, live = saturated green); the other two are subdued and clickable. Clicking a non-current button POSTs `/api/sidecar/mode` and the page re-fetches mode + active signals. The toggle is the most prominent affordance on the page during debugging. A small "stop sign" badge in the same row indicates "in-flight jobs running" when any `BackgroundTask` is mid-flight after an off-flip — the user knows the system is draining.
- **Left — live signal feed.** Mirrors `/api/ev?wager_filter=parlay&book=coral33&best_price=1` with the same inline Auto-place button. Filterable by sport tab bar at the top.
- **Center — active-signals panel.** One card per row in `sidecar_active_signals` where `commence_time > now`. Each card: event label + market + side, kelly_fraction badge, bankroll_at_arm, **total_placed** (large), current Kelly target, **delta-to-fire** (`current_target − total_placed`; green when `>= $30`, gray when below floor), `last_delta_at` timestamp. Cards sort by largest delta-to-fire first so pending re-fires are eyeball-able. Hovering a card opens a small inline placements list (every audit row tied to that `ev_row_id`).
- **Right — account pool grid.** 7 cards, one per Coral33 sub-account. Each card: customer_id, label, current balance (large), available balance (smaller), today's bet count + stake total, last-used timestamp, a small dot indicator (green = last request succeeded, red = last 3 failed in a row, gray = no activity today). Cards sort by current balance ascending so the lowest-balance / next-to-fire account is at the top.
- **Bottom — run log.** Recent placements newest-first as a dense table. Rows that share a `job_id` are grouped visually (subtle background tint + a small "1/3, 2/3, 3/3" pill in the leftmost column). Columns: job time, sport, event/market/side, stake, account, result badge, ticket #, **trigger badge** (`user` vs `delta`). Result badges: green `placed`, yellow `dry_run`, gray `no_eligible_account` / `below_minimum`, orange `partial_fill`, red `error` (with hover-tooltip for `error_message`).

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

- `FakeCoral33Client` (test fixture) records every `place_open_parlay` call AND every intermediate step (`getParlaySpecs`, `getInfoParlay`, `checkWagerLineMulti`). End-to-end through `POST /api/sidecar/place` proves:
  - dry-run runs steps 1–3, captures the would-be insertWagerParlay payload, does NOT issue step 4 (`insertWagerParlay`) or step 5 (`getPendingByTicket`).
  - live mode runs all five steps in order, with the `DELAY.sig` from step 3 propagating into step 4 verbatim.
  - SSE events fire on the right paths in the right order; audit rows land grouped by `job_id`.
- **Payload shape test.** Build a synthetic LegSpec for "Soccer #225390 New Zealand +475" and confirm `place_open_parlay` produces an `insertWagerParlay` payload byte-equivalent to the HAR's entry-41 payload modulo `docNum`/`delay` (which are non-deterministic). This locks down the schema until Coral's API changes.
- **Stacked-on-one-account end-to-end test:** target $250 against a fixture pool where account A has $260 balance produces three assignments (A:$100, A:$100, A:$50) all on the same `Coral33Client` session, three `placed` audit rows under one `job_id` with the same `picked_account`. The session reuse means `getParlaySpecs` is called once (cache hit on bets 2 and 3).
- **Cross-account end-to-end test:** target $300 against (A:$250, B:$500) produces A:$100, A:$100, A:$50, B:$50 — four assignments, two distinct client sessions, four `placed` rows. `getParlaySpecs` runs twice (once per session).
- **Account-scoped cascade test:** target $250 against A=$300 balance cap $100 → A:$100, A:$100, A:$50. If the first A:$100 fails on auth, both other A assignments are marked `error` without an HTTP attempt.
- **Partial-fill end-to-end test:** target $300 against a pool that can only fund $130 → one `placed` row + one `partial_fill` row + `sidecar_partial_fill` SSE.
- **Peel-back test:** target $105 against (A:$1000, B:$1000) produces A:$75, B:$30 — verify the partial on A is the peel-back result, not a naive $100.
- Splitter integration with `AccountsScraper`'s cache shape — confirms `max_parlay_stake` round-trips from env → credential → cache → splitter.

### Manual smoke (one-time, against the real captured endpoint)

1. **Dry-run smoke.** Place one synthetic parlay through `/api/sidecar/place` in dry-run mode at a target that requires a split (e.g., $230). Inspect the resulting audit rows and SSE payloads to confirm both assignments construct an `insertWagerParlay` payload that matches the HAR's entry-41 shape (modulo dynamic fields). Step 3 (`checkWagerLineMulti`) should land successfully against the real server even in dry-run; step 4 should NOT.
2. **Live smoke, single bet.** Flip `sidecar_mode = "live"`, fire one real placement at minimum stake ($30) on a heavy underdog. Verify (a) the modal receipt matches Coral's web UI (one ticket # appears under "Pending Wagers" with 1 placed + 1 open spot), (b) the existing 30-min wager-mirror tick picks the new ticket up into `bets`, (c) the proxy IP appears in Coral's session log if exposed.
3. **Live smoke, multi-parlay-one-account.** Fire one real placement at a target that forces stacked parlays on a single account (e.g., $250 against an account with ≥$260 balance). Verify: three distinct Coral wager numbers land all on the same customer_id, jittered gap visible in network logs, three wager-mirror rows surface.
4. **Live smoke, multi-account.** Fire one real placement at a target that forces a cross-account split (e.g., $130 against an account with $80 balance and a second account with $50 balance). Verify: two distinct sessions, two tickets, two wager-mirror rows.

### Verification gates before merge

- `pytest server/tests -v` passes including the new sidecar tests.
- `npx tsc --noEmit` + `npm run build` pass in `web/`.
- A dry-run end-to-end through the real UI button → real SSE receipt path, manually exercised.

## Open questions for plan-writing

- **HAR file lives at `~/Downloads/coral33.com.har`.** Not committed to the repo (contains auth tokens). Plan should reference it for verification during implementation but not rely on its long-term availability.
- **`volumeAmount` derivation.** The HAR shows `volumeAmount: 500` on the $5.15 straight bet and `volumeAmount: 1000` on the $10 parlay. The ratio is roughly $100 per $1 of risk. The sidecar uses `volumeAmount = stake_dollars × 100` empirically; this needs verification in the dry-run smoke (Coral may reject mismatched values).
- **Where `agentID` comes from.** All HAR calls under `VR12509` show `agentID: "TYSONR"`. Likely each customer has a fixed `agentID` reachable via `Customer/getAccountInfo` (already wired). Plan should add an `agent_id` field to `AccountSnapshot` populated on the first authenticate-and-scrape cycle, then carry it through to placements. The remaining 6 accounts in the 7-account pool get their `agent_id`s from the same source.
- **`docNum` semantics.** The placement payload carries `docNum: 27458945` (parlay) and `docNum: 72704614` (straight). These look like client-generated unique IDs (possibly hash of timestamp + leg). The sidecar can generate a fresh int per call using `int(time.time() * 1000) % 10**8` or similar — confirm Coral accepts arbitrary values vs requires server-side coordination.
- **Wager-mirror reconciliation.** The existing 30-min `bets_mirror.py` tick should naturally pick up sidecar-placed wagers (it reads from `Pending` which surfaces the same ticket numbers `insertWagerParlay` returns). Worth a single integration test that confirms the new tickets land in the unified `bets` table without a sidecar-specific code path. With splits, one signal can produce N rows in `bets`; the test should confirm the existing schema handles N independent wagers under one `job_id` cleanly (or store `job_id` on the bets rows for grouping).
- **Proxy-status dot derivation.** The "last 3 failed" indicator implies the sidecar tracks per-account request outcomes outside the audit log (which only records placement attempts, not the balance-scrape passes that share the same proxy). Two options to consider in the plan: extend the audit log to record balance-scrape results, or add a tiny in-memory ring buffer per account. Latter is probably simpler; plan to evaluate.
- **Force-refresh after placement.** When a live placement succeeds, should the sidecar fire `POST /api/coral33/accounts/refresh` for the picked account(s) immediately? Default: yes, so the new ticket and updated balance land in `/accounts` and the next signal's split plan reflects the spent dollars. Single refresh per `job_id` after all assignments complete, scoped to the customer IDs actually used.

## Migration / rollout

There is no data migration — the new table is empty on first boot. The new `sidecar_mode` / `sidecar_bankroll` / `sidecar_default_kelly` settings default cleanly to safe values. The `proxy_url` and `max_parlay_stake` fields are optional on `CORAL33_ACCOUNTS` entries (`max_parlay_stake` defaults to $100 when absent, matching the standard-account ceiling). Backward compatibility is automatic.

Rollout sequence:

1. Land the read-only path: settings, audit table, splitter, dry-run placement, SSE wiring, `/sidecar` page, `/edges` button with the split-plan preview — all behind `sidecar_mode=dry-run`. User can drive the full UX end-to-end and inspect would-be payloads at every split size.
2. Land the captured `place_parlay` endpoint method on the client (operation name, path, payload, response parsing) using the user-provided HAR.
3. User flips `sidecar_mode=live` after the single-split live smoke test passes.
4. After the multi-split live smoke test passes on a small target, the system is fully live.
