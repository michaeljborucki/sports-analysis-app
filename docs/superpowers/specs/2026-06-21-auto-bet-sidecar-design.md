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
- Sidecar selects exactly one Coral33 sub-account per signal — never multi-fire the same signal across accounts.
- Per-account requests route through a dedicated sticky residential proxy URL (one per account, static).
- Stake is computed from a user-set static bankroll × the chosen Kelly fraction; the account with the **lowest balance that still covers the stake** wins.
- If no account in the pool has the available balance, the sidecar refuses to fire and pages the user to top up.
- A `dry-run` / `live` master toggle in `user_settings.json` is the sole guardrail, defaulted to `dry-run` and explicitly flipped by the user — mirrors the `cache_mode` pattern already established for the metered Odds API fetcher.

## Non-goals (v1)

- **Auto-firing the hedge** on regulated books. The user remains in the loop for the non-Coral side.
- **Auto-picking the open leg.** The open leg is always user-supplied per placement.
- **Auto-firing on EV signal** without an explicit click. The user remains the trigger; the sidecar automates which-account + login + payload + receipt.
- **Multi-account simultaneous placement** of the same signal. One signal → one account.
- **Daily loss / count / stake caps, min-EV threshold, auto-quarantine of error-prone accounts.** Explicitly excluded per user decision. The `dry-run` / `live` toggle is the only guardrail.
- **Pacing / jitter / two-tier batching.** Moot because only one account fires per signal; there is no "burst" to disguise.
- **Refreshing account balances at fire time.** The sidecar trusts the existing accounts cache from `AccountsScraper`. Stale-balance edge cases land as `auth_failed` / `placement_timeout` and surface via the standard error path.

## Architecture

### Process model

In-process inside the existing FastAPI server. New module `server/sidecar/`. New API surface under `server/api/sidecar.py`. New Next.js route `/sidecar` for the dashboard. The trigger flow is **synchronous-looking but background-tasked**: `POST /api/sidecar/place` validates the request, enqueues a `BackgroundTask` and returns a `job_id` immediately. The UI subscribes to the existing SSE channel for the result.

Rationale: a single-process, single-user, laptop-local deployment doesn't justify a separate daemon. The placement path reuses the FastAPI worker pool the same way the existing `/api/coral33/accounts/refresh` already does for the multi-account scrape.

### Module layout

```
server/sidecar/
  __init__.py
  models.py          # Pydantic: LegSpec, SidecarPlaceRequest, PlacementResult, RunLogEntry
  picker.py          # select_account(required_stake, accounts) → AccountCredential | None
  placement.py       # orchestrator: picker → client.place_parlay → audit log → SSE emit
  audit.py           # SQLite r/w for sidecar_placements
  settings.py        # typed accessors over user_settings.json (sidecar_mode, sidecar_bankroll)
server/api/sidecar.py
  POST /api/sidecar/place           → 202 { job_id }
  GET  /api/sidecar/runs            → recent placements (paginated)
  GET  /api/sidecar/runs/{job_id}   → one placement detail
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

The existing `CORAL33_ACCOUNTS` env JSON is extended with a per-entry `proxy_url`:

```json
[
  {
    "customer_id": "VR11601",
    "password": "…",
    "label": "Account 1",
    "proxy_url": "http://user:pass@us-east.residential-pool.example:7777"
  }
]
```

- Missing/null `proxy_url` is allowed but emits a startup `WARN` per account (development convenience; production use should always set it).
- `accounts.py:AccountCredential` gains a `proxy_url: str | None = None` field.
- `AccountsScraper` reads the proxy and passes it through when constructing the per-account `Coral33Client` for the balance scrape. This means the existing accounts roll-up *also* starts using per-account proxies — desirable side effect, since same-IP reads across 9 accounts is the same anti-detection concern as same-IP placements.

### Picker rule

```python
def select_account(
    required_stake: float,
    accounts: list[AccountSnapshot],
) -> AccountCredential | None:
    eligible = [a for a in accounts if a.available_balance >= required_stake]
    if not eligible:
        return None
    return min(eligible, key=lambda a: a.available_balance).credential
```

The lowest-balance eligible account drains its bankroll first — matching the user's promo-cycling strategy (consolidate cash into the few highest-balance accounts).

### Configuration shape — `user_settings.json`

Two new keys, both required, with safe defaults:

```json
{
  "sidecar_mode": "dry-run",
  "sidecar_bankroll": 4000
}
```

- `sidecar_mode`: `"dry-run"` | `"live"`. The default is `"dry-run"` and the user must explicitly PATCH to `"live"` via `/api/settings` — same gate model as `cache_mode`. Memory rule: **never auto-flip `sidecar_mode` to `"live"`** (mirrors `cache_mode`).
- `sidecar_bankroll`: the dollar figure that Kelly fractions multiply against to produce the stake. Set once, edited rarely.

### Storage — one new table in `cache.db`

```sql
CREATE TABLE sidecar_placements (
  job_id          TEXT PRIMARY KEY,            -- uuid4
  created_at      INTEGER NOT NULL,            -- unix seconds
  ev_row_id       TEXT NOT NULL,               -- canonical (event_id, market_key, address) tuple-string
  open_leg        TEXT NOT NULL,               -- JSON of LegSpec
  ev_leg          TEXT NOT NULL,               -- JSON of LegSpec at fire time (price snapshot)
  kelly_fraction  REAL NOT NULL,               -- the fraction the user picked (full / quarter / custom)
  stake           REAL NOT NULL,               -- dollars
  mode            TEXT NOT NULL,               -- 'dry-run' | 'live'
  picked_account  TEXT,                        -- customer_id, NULL if no_eligible_account
  result          TEXT NOT NULL,               -- 'placed' | 'dry_run' | 'no_eligible_account' | 'error'
  ticket_number   TEXT,                        -- Coral33 wager #, NULL on dry-run / error
  accepted_payload TEXT,                       -- raw JSON response (full body for audit)
  error_message   TEXT                         -- short error class for UI; NULL on success
);
CREATE INDEX sidecar_placements_created_at ON sidecar_placements(created_at DESC);
```

Audit-grade: every placement attempt (including refusals and dry-runs) lands here. Never deleted by code; user can `DELETE` manually.

### Data flow

```
[User on /edges]
    ↓ click "Auto-place" on a row with Coral33 best price AND wager_type ∈ {parlay, both}
[Open-leg modal]
    ↓ type-ahead picks the open leg from current Coral33 odds cache
    ↓ select kelly_fraction (default: kelly_quarter)
    ↓ Confirm
POST /api/sidecar/place { ev_row_id, open_leg, kelly_fraction }
    ↓ resolve ev_row_id → ev_leg snapshot
    ↓ stake = round(kelly_fraction × sidecar_bankroll)
    ↓ enqueue BackgroundTask, return 202 { job_id }
[BackgroundTask]
    ↓ load accounts cache → picker
    ↓ no eligible? → write audit (no_eligible_account), emit sidecar_topup_required SSE, done
    ↓ dry-run? → write audit (dry_run), emit sidecar_placement SSE with would-be payload, done
    ↓ live? → Coral33Client(creds.customer_id, creds.password, proxy_url=creds.proxy_url)
            → client.authenticate()
            → client.place_parlay(legs=[ev_leg, open_leg], stake_dollars=stake)
            → write audit (placed, ticket_number, accepted_payload)
            → emit sidecar_placement SSE
[UI]
    ↓ modal subscribes to SSE → spinner → receipt card
    ↓ /sidecar page run-log appends in place
```

### SSE events

Two new event types added to the existing broker (`server/api/stream.py`):

- `sidecar_placement`: `{ job_id, result, ticket_number?, picked_account?, stake, mode }`
- `sidecar_topup_required`: `{ job_id, required_stake, lowest_balance, lowest_balance_account }`

Reuses the existing `useLiveUpdates` hook in the Next.js app — no new transport wiring.

## UI surface

### `/edges` — new "Auto-place" button

Each row where `book == "coral33"` AND `is_best_price` AND `wager_type ∈ {parlay, both}` gets a compact button at the end of the row. The button is suppressed entirely when `sidecar_mode == "dry-run"` and `sidecar_bankroll` is zero/unset — there's nothing to fire.

Click opens a modal:

- **Header.** The +EV leg description (event, market, side, price). Three stat chips: **EV%**, **Kelly%** (user-selectable: Full / Quarter / Custom), **Stake $** (live-computed from the kelly fraction × `sidecar_bankroll`).
- **Body.** A type-ahead "Pick the open leg" search. Filters the current Coral33 odds cache (already in browser state via SWR) by event name, market, side. Selected leg renders as a card under the search with a "change" link.
- **Footer.** A preview line: *"Will fire on **VR12509** (Account 4) — balance $2,140, lowest eligible of 6/9. Mode: **dry-run**."* The badge reads *dry-run* in muted yellow or *live* in saturated green. Two buttons: **Cancel** / **Confirm**. Confirm is disabled until an open leg is picked.
- **Result.** Modal shows a spinner, then on SSE receipt swaps to a receipt card: ticket #, accepted price, account used, "View on /sidecar" link. Auto-closes after ~3s.

### `/sidecar` — new top-nav page

Pinned to the existing top-nav alongside `/odds`, `/edges`, `/accounts`. Three panels in the established Bloomberg-terminal palette (dark mode first, tabular figures for all $ values):

- **Left — live signal feed.** Mirrors `/api/ev?wager_filter=parlay&book=coral33&best_price=1` with the same inline Auto-place button. Filterable by sport tab bar at the top.
- **Right — account pool grid.** 9 cards, one per Coral33 sub-account. Each card: customer_id, label, current balance (large), available balance (smaller), today's bet count + stake total, last-used timestamp, a small dot indicator (green = last request succeeded, red = last 3 failed in a row, gray = no activity today). Cards sort by current balance ascending so the lowest-balance / next-to-fire account is at the top.
- **Bottom — run log.** Recent placements newest-first as a dense table (job time, sport, event/market/side, open leg short, stake, account, result badge, ticket #). Result badges: green `placed`, yellow `dry_run`, gray `no_eligible_account`, red `error` (with hover-tooltip for `error_message`).

## Error handling

Five named failure modes, each with a deterministic message and a deterministic next step:

| Mode | Trigger | Behavior |
|---|---|---|
| `no_eligible_account` | Picker returns None | SSE `sidecar_topup_required`; modal shows top-up banner with `lowest_balance` + gap; no placement attempted. |
| `auth_failed` | `client.authenticate()` raises `Coral33AuthError` | Treat this signal's chosen account as ineligible (do not drop it from the long-term pool), re-pick the next-lowest eligible account, retry **once**. On second failure: write `error`, surface to modal + run log. |
| `line_changed` | Coral returns a price-changed error from `place_parlay` | Abort placement, write `error` with the diff in `error_message`, surface to modal. **No auto-accept** of the new price. |
| `placement_timeout` | No response in 20s on the `place_parlay` POST | Write `error`. Surface a "verify manually" banner — placement state is now ambiguous; the existing `POST /api/coral33/accounts/refresh` will determine if the bet actually landed. |
| `proxy_failure` | `curl_cffi` raises a connection error before the request body sends | Same as `auth_failed`: retry once with the next lowest eligible account; on second failure surface as `error`. |

Note on `auth_failed` and `proxy_failure` retry: the retry is **across accounts**, not across attempts on the same account. The original picked account is not re-used in this signal's lifetime.

## Testing strategy

### Unit

- `picker.py`: eligibility filter (no eligible, one eligible, all eligible), sort order (ascending balance), tie-break determinism.
- `placement.py`: mode gating — dry-run never instantiates a real `Coral33Client`, never authenticates, never POSTs; live mode does. Stake rounding to whole dollars.
- `audit.py`: round-trip persistence of every `result` state including `error_message` and `accepted_payload`.
- `settings.py`: defaults applied when keys are absent; type validation rejects bogus modes.

### Integration

- `FakeCoral33Client` (test fixture) that records every `place_parlay` call: end-to-end through `POST /api/sidecar/place` proves dry-run is a no-op, live calls the client with the right payload, both SSE events emit on the right paths, audit row lands with the right `result`.
- Picker integration with `AccountsScraper`'s cache shape — confirms the picker reads the same dataclasses the UI sees.

### Manual smoke (one-time, against the real captured endpoint)

1. **Dry-run smoke.** Place one synthetic 2-leg parlay through `/api/sidecar/place` in dry-run mode. Inspect the audit row and SSE payload to confirm the captured-endpoint payload shape is what would have been sent.
2. **Live smoke.** Flip `sidecar_mode = "live"`, fire one real placement on a single real account against a heavy underdog at minimum stake. Verify (a) the modal receipt matches Coral's web UI, (b) the existing 30-min wager-mirror tick picks the new ticket up into `bets`, (c) the proxy IP shows in Coral's web UI session log if Coral exposes one.

### Verification gates before merge

- `pytest server/tests -v` passes including the new sidecar tests.
- `npx tsc --noEmit` + `npm run build` pass in `web/`.
- A dry-run end-to-end through the real UI button → real SSE receipt path, manually exercised.

## Open questions for plan-writing

- **Placement-endpoint capture timing.** The captured-request handoff must happen before live mode can be used. Plan should keep dry-run and live paths separable so dry-run lands first, with the live-mode wiring slotting in once the operation name + form payload are known.
- **Wager-mirror reconciliation.** The existing 30-min `bets_mirror.py` tick should naturally pick up sidecar-placed wagers. Worth a single integration test that confirms the new tickets land in the unified `bets` table without a sidecar-specific code path.
- **Proxy-status dot derivation.** The "last 3 failed" indicator implies the sidecar tracks per-account request outcomes outside the audit log (which only records placement attempts, not the balance-scrape passes that share the same proxy). Two options to consider in the plan: extend the audit log to record balance-scrape results, or add a tiny in-memory ring buffer per account. Latter is probably simpler; plan to evaluate.

## Migration / rollout

There is no data migration — the new table is empty on first boot. The new `sidecar_mode` / `sidecar_bankroll` settings default cleanly to safe values. The `proxy_url` field is optional on `CORAL33_ACCOUNTS` entries. Backward compatibility is automatic.

Rollout sequence:

1. Land the read-only path: settings, audit table, picker, dry-run placement, SSE wiring, `/sidecar` page, `/edges` button — all behind `sidecar_mode=dry-run`. User can drive the full UX end-to-end and inspect would-be payloads.
2. Land the captured `place_parlay` endpoint method on the client.
3. User flips `sidecar_mode=live` after the live smoke test passes.
