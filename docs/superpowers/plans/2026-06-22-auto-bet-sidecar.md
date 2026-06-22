# Auto-Bet Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Coral33 auto-bet sidecar end-to-end — proxied per-account placements of open-spot parlays driven by the existing EV scanner, with a static-bankroll splitter that fans out across the 7-account pool when Kelly stake exceeds a single account's parlay cap. Master `dry-run` / `live` toggle is the only guardrail; spec is `docs/superpowers/specs/2026-06-21-auto-bet-sidecar-design.md`.

**Architecture:** In-process inside the existing FastAPI server. Coral33 placement logic lives in a new `server/odds/books/coral33/placement.py` (separate from the read-only `client.py`). The sidecar orchestrator (splitter, audit, mode store, sequential-with-jitter placement loop) lives in a new `server/sidecar/` package. The Next.js frontend gets an `Auto-place` button on `/edges` rows and a new `/sidecar` dashboard page; both consume the existing SSE channel with three new event types.

**Tech Stack:** Python 3.11, FastAPI BackgroundTasks, `curl_cffi.requests.AsyncSession` with per-call proxy support, SQLite (existing `cache.db`), pytest + pytest-asyncio, Next.js 14, SWR, TanStack Table.

**HAR Reference:** `~/Downloads/coral33.com.har` — captured 2026-06-21. Contains real `checkWagerLineMulti` + `insertWagerStraight` + `insertWagerParlay` request/response pairs that are the ground truth for all payload tests. Not committed (contains JWT + customer credentials).

**Supersedes:** `docs/superpowers/plans/2026-04-30-coral33-placement.md` — never executed. Structural choices borrowed (separate `placement.py`, HAR fixtures, byte-accuracy tests, three-layer kill switch); content rewritten against the open-spot HAR.

---

## File Structure

```
server/odds/books/coral33/
├── placement.py                          # NEW — pure builders + Coral33Placer class
├── client.py                             # MODIFY — accept proxy_url, expose new ops as helpers
└── accounts.py                           # MODIFY — extend AccountCredential, pass proxy through

server/sidecar/                           # NEW PACKAGE
├── __init__.py
├── models.py                             # Pydantic + dataclasses (LegSpec, SplitAssignment, SplitPlan, …)
├── splitter.py                           # plan_splits()
├── placement.py                          # orchestrator: splitter → loop → audit → SSE
├── audit.py                              # sidecar_placements I/O
├── mode_store.py                         # SidecarModeStore — mirrors CacheModeStore
└── settings.py                           # sidecar_bankroll / sidecar_default_kelly accessors

server/api/
├── sidecar.py                            # NEW — POST /api/sidecar/place, GET runs, GET/POST mode
└── stream.py                             # MODIFY — register 4 new event types

server/odds/cache.py                      # MODIFY — add sidecar_placements table to _init_schema
server/main.py                            # MODIFY — register sidecar router

server/tests/
├── test_sidecar_splitter.py              # NEW — exhaustive splitter unit + Hypothesis tests
├── test_sidecar_audit.py                 # NEW — round-trip persistence
├── test_sidecar_mode_store.py            # NEW — mirror test_cache_mode (which exists)
├── test_sidecar_settings.py              # NEW
├── test_sidecar_placement.py             # NEW — orchestrator with FakeCoral33Placer
├── test_sidecar_api.py                   # NEW — FastAPI route tests
├── test_coral33_placement.py             # NEW — payload builders + 5-call chain
├── test_coral33_proxy.py                 # NEW — proxy_url plumbing
└── fixtures/coral33/placement/           # NEW
    ├── get_parlay_specs.json
    ├── get_info_parlay.json
    ├── check_wager_line_multi_parlay.json
    ├── insert_wager_parlay.json
    └── get_pending_by_ticket.json

web/app/sidecar/page.tsx                  # NEW — dashboard route
web/components/sidecar/
├── AutoPlaceButton.tsx                   # NEW — injected into /edges rows
├── ConfirmModal.tsx                      # NEW — Kelly radio + payout strip + split plan
├── AccountPoolGrid.tsx                   # NEW
├── SignalFeed.tsx                        # NEW (reuses /edges row component)
└── RunLog.tsx                            # NEW
web/lib/sidecar/
├── splitter.ts                           # NEW — mirrors server splitter for live modal preview
└── useSidecarStream.ts                   # NEW — typed SSE subscription helper
web/types/api.ts                          # REGEN — pulls new endpoints from openapi.json

scripts/
├── extract_har_fixtures.py               # NEW — one-shot, scrubs HAR → fixtures
└── coral33_preflight_smoke.py            # NEW — manual safe smoke test (no insert)
```

**Why split `placement.py` from `client.py`:** `client.py` stays focused on read operations and auth (already 285 LOC). `placement.py` carries the write surface, the byte-accuracy fixtures, and the three-layer kill switch. Mirrors how the prior superseded plan structured it.

**Why a `server/sidecar/` package:** the orchestrator is sport-agnostic in shape (only the Coral33Placer dependency is sport-specific). Keeps the splitter, audit, mode toggle, and settings reusable if a future second book gets the same treatment.

---

## Phase A — Config foundation

### Task A1: Extend `AccountCredential` with `proxy_url` + `max_parlay_stake`

**Files:**
- Modify: `server/odds/books/coral33/accounts.py:37-45` (AccountCredential dataclass)
- Modify: `server/odds/books/coral33/accounts.py:167-200` (load_account_credentials)
- Test: `server/tests/test_coral33_accounts_load.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_coral33_accounts_load.py
import json
from server.odds.books.coral33.accounts import load_account_credentials


def test_load_credentials_parses_proxy_and_cap(monkeypatch):
    monkeypatch.setenv("CORAL33_ACCOUNTS", json.dumps([
        {"customer_id": "VR11606", "password": "stanley1",
         "label": "Ryan Stanley",
         "proxy_url": "http://u:p@isp.decodo.com:10007",
         "max_parlay_stake": 150},
        {"customer_id": "VR11601", "password": "dixon1",
         "label": "Jimmy Dixon"},
    ]))
    creds = load_account_credentials()
    assert len(creds) == 2
    stanley, dixon = creds
    assert stanley.proxy_url == "http://u:p@isp.decodo.com:10007"
    assert stanley.max_parlay_stake == 150
    assert dixon.proxy_url is None
    assert dixon.max_parlay_stake == 100   # default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest server/tests/test_coral33_accounts_load.py -v`
Expected: FAIL (`AccountCredential` doesn't accept those kwargs yet)

- [ ] **Step 3: Add the fields to `AccountCredential`**

In `server/odds/books/coral33/accounts.py:37`:

```python
@dataclass(frozen=True)
class AccountCredential:
    customer_id: str
    password: str
    label: str | None = None
    proxy_url: str | None = None
    max_parlay_stake: int = 100   # standard cap; Stanley overrides to 150
```

- [ ] **Step 4: Update `load_account_credentials` to read the new fields**

Around `server/odds/books/coral33/accounts.py:167-200`, in the loop that constructs `AccountCredential`, pass the new fields through with `dict.get` so older env shapes still work:

```python
creds.append(AccountCredential(
    customer_id=entry["customer_id"].strip(),
    password=entry["password"],
    label=entry.get("label"),
    proxy_url=entry.get("proxy_url"),
    max_parlay_stake=int(entry.get("max_parlay_stake", 100)),
))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest server/tests/test_coral33_accounts_load.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add server/odds/books/coral33/accounts.py server/tests/test_coral33_accounts_load.py
git commit -m "feat(coral33): proxy_url + max_parlay_stake on AccountCredential"
```

---

### Task A2: Extend `Coral33Client` to accept `proxy_url`

**Files:**
- Modify: `server/odds/books/coral33/client.py:91-98` (`__init__`)
- Modify: `server/odds/books/coral33/client.py` (every `AsyncSession(...)` instantiation site)
- Test: `server/tests/test_coral33_proxy.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_coral33_proxy.py
from server.odds.books.coral33.client import Coral33Client


def test_client_records_proxy_url():
    c = Coral33Client("VR11606", "pw",
                     proxy_url="http://u:p@isp.decodo.com:10007")
    assert c.proxy_url == "http://u:p@isp.decodo.com:10007"


def test_client_proxy_url_defaults_to_none():
    c = Coral33Client("VR11606", "pw")
    assert c.proxy_url is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest server/tests/test_coral33_proxy.py -v`
Expected: FAIL

- [ ] **Step 3: Add `proxy_url` to `Coral33Client.__init__`**

```python
def __init__(self, customer_id: str, password: str,
             proxy_url: str | None = None):
    if not customer_id or not password:
        raise Coral33AuthError("coral33 credentials missing")
    self.customer_id = customer_id.strip()
    self.password = password
    self.proxy_url = proxy_url
    self._token: str | None = None
    self._token_exp: int | None = None
    self._lock = asyncio.Lock()
```

- [ ] **Step 4: Pass proxies into every `AsyncSession` construction in `client.py`**

Search `client.py` for `AsyncSession(` and `with AsyncSession(`. For each, add a `proxies` kwarg gated on `self.proxy_url`:

```python
proxies = {"http": self.proxy_url, "https": self.proxy_url} if self.proxy_url else None
async with AsyncSession(impersonate="chrome", proxies=proxies) as session:
    ...
```

- [ ] **Step 5: Add integration test verifying curl_cffi receives the proxies kwarg**

Append to `server/tests/test_coral33_proxy.py`:

```python
import asyncio
from unittest.mock import patch
from curl_cffi.requests import AsyncSession


def test_async_session_constructed_with_proxies(monkeypatch):
    captured = {}
    real_init = AsyncSession.__init__

    def spy_init(self, *args, **kwargs):
        captured["proxies"] = kwargs.get("proxies")
        # Construct but don't actually use the session for this test
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "__init__", spy_init)

    c = Coral33Client("VR11606", "pw",
                     proxy_url="http://u:p@isp.decodo.com:10007")
    # Drive the authenticate path far enough to construct a session, but
    # catch the HTTP failure since we have no real server.
    try:
        asyncio.run(c.authenticate())
    except Exception:
        pass
    assert captured["proxies"] == {
        "http": "http://u:p@isp.decodo.com:10007",
        "https": "http://u:p@isp.decodo.com:10007",
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest server/tests/test_coral33_proxy.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add server/odds/books/coral33/client.py server/tests/test_coral33_proxy.py
git commit -m "feat(coral33): client proxy_url support via curl_cffi proxies kwarg"
```

---

### Task A3: Thread `proxy_url` through `AccountsScraper`

**Files:**
- Modify: `server/odds/books/coral33/accounts.py` (every `Coral33Client(creds.customer_id, creds.password)` site)
- Test: extend `server/tests/test_coral33_accounts_load.py`

- [ ] **Step 1: Write the failing test**

```python
def test_accounts_scraper_passes_proxy_to_client(monkeypatch):
    """The scrape loop must construct each client with the credential's proxy."""
    monkeypatch.setenv("CORAL33_ACCOUNTS", json.dumps([
        {"customer_id": "VR11606", "password": "p",
         "proxy_url": "http://u:p@isp.decodo.com:10007"},
    ]))
    from server.odds.books.coral33 import accounts as accts
    captured = []
    real_init = accts.Coral33Client.__init__

    def spy_init(self, customer_id, password, proxy_url=None):
        captured.append({"cust": customer_id, "proxy": proxy_url})
        real_init(self, customer_id, password, proxy_url=proxy_url)

    monkeypatch.setattr(accts.Coral33Client, "__init__", spy_init)

    scraper = accts.AccountsScraper(accts.load_account_credentials())
    # Drive enough of the scrape to construct a client; the network call will
    # fail but we only care about the constructor capture.
    asyncio.run(scraper._scrape_one(scraper.credentials[0]))  # noqa
    # If _scrape_one is async + raises on net failure, wrap in try/except inside.
    assert captured[0]["proxy"] == "http://u:p@isp.decodo.com:10007"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest server/tests/test_coral33_accounts_load.py::test_accounts_scraper_passes_proxy_to_client -v`
Expected: FAIL (current `AccountsScraper` doesn't pass `proxy_url`)

- [ ] **Step 3: Update every `Coral33Client(...)` construction in `accounts.py`**

Find each site where `Coral33Client(creds.customer_id, creds.password)` is called and add `proxy_url=creds.proxy_url`. There's typically one in `_scrape_one` and possibly one in any history-fetch helper.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest server/tests/test_coral33_accounts_load.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/coral33/accounts.py server/tests/test_coral33_accounts_load.py
git commit -m "feat(coral33): AccountsScraper routes per-account proxy_url to client"
```

---

## Phase B — Sidecar persistence layer

### Task B1: Create the `server/sidecar/` package skeleton

**Files:**
- Create: `server/sidecar/__init__.py`

- [ ] **Step 1: Create the package**

```python
# server/sidecar/__init__.py
"""Auto-bet sidecar orchestrator.

See docs/superpowers/specs/2026-06-21-auto-bet-sidecar-design.md."""
```

- [ ] **Step 2: Commit**

```bash
git add server/sidecar/__init__.py
git commit -m "feat(sidecar): package skeleton"
```

---

### Task B2: `SidecarModeStore` — own file, mirrors `CacheModeStore`

**Files:**
- Create: `server/sidecar/mode_store.py`
- Test: `server/tests/test_sidecar_mode_store.py`

- [ ] **Step 1: Read the existing `CacheModeStore` for the pattern**

Read `server/odds/cache_mode.py` end-to-end. The mirror should match its locking, JSON shape, default-on-missing-file, and write-then-rename atomicity.

- [ ] **Step 2: Write the failing test**

```python
# server/tests/test_sidecar_mode_store.py
from pathlib import Path
from server.sidecar.mode_store import SidecarMode, SidecarModeStore


def test_default_is_dry_run(tmp_path: Path):
    store = SidecarModeStore(tmp_path / "sidecar_mode.json")
    assert store.get() is SidecarMode.DRY_RUN


def test_round_trip(tmp_path: Path):
    store = SidecarModeStore(tmp_path / "sidecar_mode.json")
    store.set(SidecarMode.LIVE)
    # Re-open from disk
    store2 = SidecarModeStore(tmp_path / "sidecar_mode.json")
    assert store2.get() is SidecarMode.LIVE


def test_missing_file_defaults(tmp_path: Path):
    p = tmp_path / "sidecar_mode.json"
    # File never written
    assert SidecarModeStore(p).get() is SidecarMode.DRY_RUN


def test_rejects_bogus_mode(tmp_path: Path):
    import pytest
    store = SidecarModeStore(tmp_path / "sidecar_mode.json")
    with pytest.raises(ValueError):
        store.set("wild-mode")  # type: ignore
```

- [ ] **Step 3: Implement `SidecarModeStore`**

```python
# server/sidecar/mode_store.py
"""Live/dry-run gate for the auto-bet sidecar.

Mirrors server/odds/cache_mode.py exactly — own JSON file, own lock, default
to safe value (dry-run) on missing file. The user must explicitly POST to
flip to live; the system never auto-flips."""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Literal


class SidecarMode(str, Enum):
    DRY_RUN = "dry-run"
    LIVE = "live"


SidecarModeLiteral = Literal["dry-run", "live"]


class SidecarModeStore:
    def __init__(self, config_path: Path):
        self.path = config_path
        self._lock = Lock()

    def get(self) -> SidecarMode:
        try:
            with open(self.path) as f:
                data = json.load(f)
            return SidecarMode(data["mode"])
        except (FileNotFoundError, KeyError, ValueError):
            return SidecarMode.DRY_RUN

    def set(self, mode: SidecarMode | SidecarModeLiteral) -> None:
        if isinstance(mode, str):
            mode = SidecarMode(mode)   # raises ValueError on bogus input
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"mode": mode.value}))
            tmp.replace(self.path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest server/tests/test_sidecar_mode_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/sidecar/mode_store.py server/tests/test_sidecar_mode_store.py
git commit -m "feat(sidecar): SidecarModeStore — dedicated dry-run/live JSON, defaults safe"
```

---

### Task B3: Settings accessors for `sidecar_bankroll` + `sidecar_default_kelly`

**Files:**
- Create: `server/sidecar/settings.py` (typed accessors)
- Test: `server/tests/test_sidecar_settings.py`

The existing `server/user_settings.py` exposes `UserSettings` (dataclass) + `UserSettingsStore` (class with hardcoded `SETTINGS_PATH = server/config/user_settings.json`). It does NOT expose a `read_settings()` function and has no env-path override. The `UserSettings` dataclass strict-validates known keys (`disabled_sports`, `disabled_markets`, `visible_books`) — adding new keys to `UserSettings` would force every consumer to update. Instead, treat the sidecar keys as **opaque additions** to the JSON file: read them with raw `json.load` and let the existing `UserSettingsStore` continue ignoring them.

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_sidecar_settings.py
import json
from server.sidecar.settings import (
    get_bankroll, get_default_kelly, KellyFraction, _settings_path,
)


def _write(tmp_path, payload):
    p = tmp_path / "user_settings.json"
    p.write_text(json.dumps(payload))
    return p


def test_bankroll_default_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("server.sidecar.settings._settings_path",
                       lambda: tmp_path / "user_settings.json")
    assert get_bankroll() == 10000


def test_default_kelly_default_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("server.sidecar.settings._settings_path",
                       lambda: tmp_path / "user_settings.json")
    assert get_default_kelly() is KellyFraction.HALF


def test_bankroll_from_user_settings(tmp_path, monkeypatch):
    p = _write(tmp_path, {"sidecar_bankroll": 7500})
    monkeypatch.setattr("server.sidecar.settings._settings_path",
                       lambda: p)
    assert get_bankroll() == 7500


def test_invalid_kelly_falls_back_to_half(tmp_path, monkeypatch):
    p = _write(tmp_path, {"sidecar_default_kelly": "wild"})
    monkeypatch.setattr("server.sidecar.settings._settings_path",
                       lambda: p)
    assert get_default_kelly() is KellyFraction.HALF


def test_sidecar_keys_dont_break_existing_user_settings_load(tmp_path):
    """Verify the existing UserSettingsStore tolerates the new keys."""
    from server.user_settings import UserSettingsStore
    p = _write(tmp_path, {
        "disabled_sports": [],
        "sidecar_bankroll": 7500,
        "sidecar_default_kelly": "quarter",
    })
    # If UserSettingsStore strictly validates keys, this will throw.
    store = UserSettingsStore(p)
    settings = store.load()
    assert settings is not None
```

- [ ] **Step 2: Implement `server/sidecar/settings.py` using a path-indirection helper**

```python
"""Typed accessors over user_settings.json for sidecar-routine settings.

The mode toggle (live vs dry-run) lives in its own sidecar_mode.json file
(see mode_store.py). Bankroll and default Kelly are routine values that ride
on the existing user-settings store as opaque extra keys — the existing
UserSettings dataclass ignores unknown fields, so we read them directly via
json.load without depending on its strict schema."""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from server.user_settings import SETTINGS_PATH as _DEFAULT_SETTINGS_PATH


class KellyFraction(str, Enum):
    FULL = "full"
    HALF = "half"
    QUARTER = "quarter"


_FRACTION_VALUES = {f.value for f in KellyFraction}


def _settings_path() -> Path:
    """Indirection seam so tests can patch this without touching the store."""
    return _DEFAULT_SETTINGS_PATH


def _load_raw() -> dict:
    try:
        return json.loads(_settings_path().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_bankroll() -> int:
    """Static bankroll used by the splitter. Default $10,000."""
    raw = _load_raw()
    val = raw.get("sidecar_bankroll", 10000)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 10000


def get_default_kelly() -> KellyFraction:
    """Default Kelly fraction shown in the confirm modal. Default half."""
    raw = _load_raw()
    val = raw.get("sidecar_default_kelly", "half")
    if isinstance(val, str) and val in _FRACTION_VALUES:
        return KellyFraction(val)
    return KellyFraction.HALF


def kelly_to_pct(fraction: KellyFraction, full_kelly_pct: float) -> float:
    if fraction is KellyFraction.FULL:
        return full_kelly_pct
    if fraction is KellyFraction.HALF:
        return full_kelly_pct * 0.5
    return full_kelly_pct * 0.25
```

- [ ] **Step 3: Verify the existing `UserSettingsStore` doesn't reject unknown keys**

Run: `grep -n "from_dict\|strict\|unknown" server/user_settings.py`. The existing `UserSettings.from_dict` uses `.get()` per known key and ignores extras (verified at lines 56–62). Adding new keys is safe.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest server/tests/test_sidecar_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/sidecar/settings.py server/tests/test_sidecar_settings.py
git commit -m "feat(sidecar): settings accessors for bankroll + default Kelly fraction"
```

---

### Task B4: `sidecar_placements` table schema

**Files:**
- Modify: `server/odds/cache.py` (`_init_schema` or equivalent table-creation site)

- [ ] **Step 1: Find the existing schema init**

Run: `grep -n "CREATE TABLE\|CREATE INDEX" server/odds/cache.py | head -20`

The new table joins the existing init pattern. Read 5-10 lines before/after the closest existing `CREATE TABLE` so the addition matches the existing style (idempotency: `CREATE TABLE IF NOT EXISTS`).

- [ ] **Step 2: Add the table + indexes to the schema-init function**

```sql
CREATE TABLE IF NOT EXISTS sidecar_placements (
  placement_id     TEXT PRIMARY KEY,
  job_id           TEXT NOT NULL,
  created_at       INTEGER NOT NULL,
  ev_row_id        TEXT NOT NULL,
  ev_leg           TEXT NOT NULL,
  parlay_name      TEXT NOT NULL DEFAULT '10 team',
  kelly_fraction   TEXT NOT NULL,
  target_stake     REAL NOT NULL,
  stake            REAL,
  mode             TEXT NOT NULL,
  picked_account   TEXT,
  result           TEXT NOT NULL,
  ticket_number    TEXT,
  accepted_payload TEXT,
  error_message    TEXT
);
CREATE INDEX IF NOT EXISTS sidecar_placements_job_id ON sidecar_placements(job_id);
CREATE INDEX IF NOT EXISTS sidecar_placements_created_at ON sidecar_placements(created_at DESC);
```

- [ ] **Step 3: Smoke-test the schema by booting the server**

Run: `python -c "from server.odds.cache import init_schema; init_schema()"` (or whatever the existing one-shot init entry point is). Then `sqlite3 server/cache.db ".schema sidecar_placements"` to verify the table exists.

- [ ] **Step 4: Commit**

```bash
git add server/odds/cache.py
git commit -m "feat(sidecar): sidecar_placements table + indexes in cache.db"
```

---

### Task B5: `audit.py` — sidecar_placements I/O

**Files:**
- Create: `server/sidecar/audit.py`
- Test: `server/tests/test_sidecar_audit.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_sidecar_audit.py
import json
import time
from uuid import uuid4

import pytest

from server.sidecar.audit import (
    AuditRow,
    insert_placement,
    fetch_placements,
    fetch_job,
)


@pytest.fixture
def conn(tmp_path):
    """Return a sqlite3 connection with the sidecar_placements table."""
    import sqlite3
    from server.odds.cache import init_schema_on_path  # may need to add this helper
    path = tmp_path / "test_cache.db"
    init_schema_on_path(path)
    c = sqlite3.connect(path)
    yield c
    c.close()


def test_insert_then_fetch_by_job(conn):
    job_id = uuid4().hex
    row = AuditRow(
        placement_id=uuid4().hex,
        job_id=job_id,
        created_at=int(time.time()),
        ev_row_id="619136397|h2h|new_zealand",
        ev_leg=json.dumps({"team": "New Zealand", "price": 475}),
        parlay_name="10 team",
        kelly_fraction="half",
        target_stake=130.0,
        stake=100.0,
        mode="live",
        picked_account="VR11606",
        result="placed",
        ticket_number="1471133392",
        accepted_payload=json.dumps({"STATUS": {"STATE": 1, "DOC": 1471133392}}),
        error_message=None,
    )
    insert_placement(conn, row)
    fetched = fetch_job(conn, job_id)
    assert len(fetched) == 1
    assert fetched[0].picked_account == "VR11606"


def test_multiple_placements_same_job(conn):
    job_id = uuid4().hex
    for split_amount in (100, 30):
        insert_placement(conn, AuditRow(
            placement_id=uuid4().hex,
            job_id=job_id,
            created_at=int(time.time()),
            ev_row_id="rid",
            ev_leg="{}",
            parlay_name="10 team",
            kelly_fraction="half",
            target_stake=130.0,
            stake=split_amount,
            mode="live",
            picked_account="VR11606",
            result="placed",
            ticket_number=None,
            accepted_payload=None,
            error_message=None,
        ))
    rows = fetch_job(conn, job_id)
    assert len(rows) == 2
    assert sum(r.stake for r in rows) == 130.0


def test_pre_flight_refusal_row(conn):
    """no_eligible_account: picked_account NULL, stake NULL."""
    insert_placement(conn, AuditRow(
        placement_id=uuid4().hex,
        job_id=uuid4().hex,
        created_at=int(time.time()),
        ev_row_id="rid",
        ev_leg="{}",
        parlay_name="10 team",
        kelly_fraction="half",
        target_stake=200.0,
        stake=None,
        mode="live",
        picked_account=None,
        result="no_eligible_account",
        ticket_number=None,
        accepted_payload=None,
        error_message="lowest balance $20 < required $30",
    ))
    rows = fetch_placements(conn, limit=1)
    assert rows[0].result == "no_eligible_account"
    assert rows[0].picked_account is None


def test_recent_placements_orders_newest_first(conn):
    older_id = uuid4().hex
    newer_id = uuid4().hex
    insert_placement(conn, AuditRow(
        placement_id=older_id, job_id=older_id, created_at=1000,
        ev_row_id="r", ev_leg="{}", parlay_name="10 team",
        kelly_fraction="half", target_stake=30, stake=30, mode="dry-run",
        picked_account="VR11601", result="dry_run",
        ticket_number=None, accepted_payload=None, error_message=None,
    ))
    insert_placement(conn, AuditRow(
        placement_id=newer_id, job_id=newer_id, created_at=2000,
        ev_row_id="r", ev_leg="{}", parlay_name="10 team",
        kelly_fraction="half", target_stake=30, stake=30, mode="dry-run",
        picked_account="VR11601", result="dry_run",
        ticket_number=None, accepted_payload=None, error_message=None,
    ))
    rows = fetch_placements(conn, limit=2)
    assert rows[0].placement_id == newer_id
    assert rows[1].placement_id == older_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest server/tests/test_sidecar_audit.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Implement `audit.py`**

```python
# server/sidecar/audit.py
"""sidecar_placements I/O — one row per placement attempt.

Audit-grade: every attempt (including pre-flight refusals and dry-runs) lands
here. Never deleted by code; user can DELETE manually."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal


Result = Literal[
    "placed", "dry_run",
    "no_eligible_account", "below_minimum", "partial_fill",
    "error",
]


@dataclass
class AuditRow:
    placement_id: str
    job_id: str
    created_at: int
    ev_row_id: str
    ev_leg: str               # JSON-encoded LegSpec
    parlay_name: str
    kelly_fraction: str       # 'full' | 'half' | 'quarter'
    target_stake: float
    stake: float | None
    mode: str                 # 'dry-run' | 'live'
    picked_account: str | None
    result: Result
    ticket_number: str | None
    accepted_payload: str | None
    error_message: str | None


def insert_placement(conn: sqlite3.Connection, row: AuditRow) -> None:
    conn.execute(
        """
        INSERT INTO sidecar_placements (
            placement_id, job_id, created_at, ev_row_id, ev_leg,
            parlay_name, kelly_fraction, target_stake, stake, mode,
            picked_account, result, ticket_number, accepted_payload,
            error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.placement_id, row.job_id, row.created_at, row.ev_row_id,
            row.ev_leg, row.parlay_name, row.kelly_fraction,
            row.target_stake, row.stake, row.mode, row.picked_account,
            row.result, row.ticket_number, row.accepted_payload,
            row.error_message,
        ),
    )
    conn.commit()


def fetch_job(conn: sqlite3.Connection, job_id: str) -> list[AuditRow]:
    cur = conn.execute(
        "SELECT * FROM sidecar_placements WHERE job_id = ? "
        "ORDER BY created_at ASC, placement_id ASC",
        (job_id,),
    )
    return [_row_from_cursor(r, cur) for r in cur.fetchall()]


def fetch_placements(
    conn: sqlite3.Connection, limit: int = 100
) -> list[AuditRow]:
    cur = conn.execute(
        "SELECT * FROM sidecar_placements "
        "ORDER BY created_at DESC, placement_id DESC LIMIT ?",
        (limit,),
    )
    return [_row_from_cursor(r, cur) for r in cur.fetchall()]


def _row_from_cursor(r, cur) -> AuditRow:
    cols = [c[0] for c in cur.description]
    d = dict(zip(cols, r))
    return AuditRow(**d)
```

- [ ] **Step 4: Add `init_schema_on_path` helper to `server/odds/cache.py`**

Tests need a way to spin up a temp DB with the sidecar table without polluting global state. First check what's there:

Run: `grep -n "def _init_schema\|def init_schema\|CREATE TABLE" server/odds/cache.py | head -20`

If `_init_schema(conn)` (or equivalent) is already a module-level function: add a thin path-taking wrapper next to it. If schema init is inlined in `__init__`, extract the DDL block into a `_init_schema(conn)` function first, then wrap. Either way the final shape is:

```python
def init_schema_on_path(path) -> None:
    """Initialize the cache schema at a given path. Used by tests so each
    test gets a clean DB without touching the global server/cache.db."""
    import sqlite3
    conn = sqlite3.connect(str(path))
    try:
        _init_schema(conn)
    finally:
        conn.close()
```

Export it from `server/odds/cache.py` so the audit test can `from server.odds.cache import init_schema_on_path`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest server/tests/test_sidecar_audit.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add server/sidecar/audit.py server/odds/cache.py server/tests/test_sidecar_audit.py
git commit -m "feat(sidecar): audit.py — insert + fetch sidecar_placements"
```

---

## Phase C — Splitter (pure algorithm)

### Task C1: Models — `LegSpec`, `SplitAssignment`, `SplitPlan`

**Files:**
- Create: `server/sidecar/models.py`

- [ ] **Step 1: Implement the dataclasses**

```python
# server/sidecar/models.py
"""Shared dataclasses for the sidecar package."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from server.odds.books.coral33.accounts import AccountCredential


SplitStatus = Literal[
    "planned", "below_minimum", "no_eligible_account", "partial_fill",
]


@dataclass
class LegSpec:
    """Minimal snapshot of the +EV leg at fire time. Mirrors the fields the
    Coral33 insertWagerParlay payload requires per-leg."""
    sport_type: str
    sport_sub_type: str
    period: str
    line_type: str            # 'M' (moneyline), 'S' (spread), 'T' (total)
    game_num: int
    chosen_team_id: str
    rot_num: int              # team1 rotation number used in description
    price_american: int       # e.g. 475
    price_decimal: float      # e.g. 5.75
    price_numerator: int
    price_denominator: int
    spread: float = 0.0
    total_points: float = 0.0
    game_datetime: str = ""   # ISO-ish string from Coral's response
    description: str = ""     # e.g. "Soccer #225390 New Zealand +475 - For Game "


@dataclass
class AccountSnapshot:
    """Per-account state used by the splitter."""
    credential: AccountCredential
    available_balance: float

    @property
    def customer_id(self) -> str:
        return self.credential.customer_id

    @property
    def max_parlay_stake(self) -> int:
        return self.credential.max_parlay_stake


@dataclass
class SplitAssignment:
    account: AccountSnapshot
    amount: int               # whole dollars


@dataclass
class SplitPlan:
    assignments: list[SplitAssignment] = field(default_factory=list)
    status: SplitStatus = "planned"
    target: int = 0           # the dollar target the splitter was asked to fill

    @property
    def filled(self) -> int:
        return sum(a.amount for a in self.assignments)

    @property
    def unfilled(self) -> int:
        return self.target - self.filled
```

- [ ] **Step 2: Commit**

```bash
git add server/sidecar/models.py
git commit -m "feat(sidecar): LegSpec, AccountSnapshot, SplitAssignment, SplitPlan"
```

---

### Task C2: `splitter.py` — the algorithm

**Files:**
- Create: `server/sidecar/splitter.py`
- Test: `server/tests/test_sidecar_splitter.py`

- [ ] **Step 1: Write the worked-example tests first (the spec's table is the ground truth)**

```python
# server/tests/test_sidecar_splitter.py
from server.odds.books.coral33.accounts import AccountCredential
from server.sidecar.models import AccountSnapshot
from server.sidecar.splitter import plan_splits, FLOOR


def _acct(cust, bal, cap=100):
    return AccountSnapshot(
        credential=AccountCredential(customer_id=cust, password="p",
                                     max_parlay_stake=cap),
        available_balance=bal,
    )


# --- worked examples from the spec ---

def test_target_300_a_balance_250_drains_then_moves_to_b():
    pool = [_acct("A", 250), _acct("B", 1000)]
    plan = plan_splits(300, pool)
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("A", 100), ("A", 100), ("A", 50), ("B", 50)]


def test_target_300_a_balance_500_all_on_a():
    pool = [_acct("A", 500), _acct("B", 1000)]
    plan = plan_splits(300, pool)
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("A", 100), ("A", 100), ("A", 100)]


def test_target_105_peelback_to_b():
    pool = [_acct("A", 1000), _acct("B", 1000)]
    plan = plan_splits(105, pool)
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("A", 75), ("B", 30)]


def test_target_260_a_balance_250():
    pool = [_acct("A", 250), _acct("B", 1000)]
    plan = plan_splits(260, pool)
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("A", 100), ("A", 100), ("A", 30), ("B", 30)]


def test_target_130_stanley_lowest_balance_takes_alone():
    stanley = _acct("STANLEY", 300, cap=150)
    other = _acct("B", 1000)
    pool = [stanley, other]
    plan = plan_splits(130, pool)
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("STANLEY", 130)]


def test_target_230_stanley_then_standard():
    stanley = _acct("STANLEY", 300, cap=150)
    other = _acct("B", 1000)
    plan = plan_splits(230, [stanley, other])
    assert plan.status == "planned"
    amounts = [(a.account.customer_id, a.amount) for a in plan.assignments]
    assert amounts == [("STANLEY", 150), ("B", 80)]


# --- refusals ---

def test_below_minimum():
    plan = plan_splits(18, [_acct("A", 1000)])
    assert plan.status == "below_minimum"
    assert plan.assignments == []


def test_no_eligible_account():
    pool = [_acct("A", 20), _acct("B", 25)]   # neither has FLOOR
    plan = plan_splits(50, pool)
    assert plan.status == "no_eligible_account"


def test_partial_fill():
    # Only one acct has 80, request 200
    plan = plan_splits(200, [_acct("ONLY", 80)])
    assert plan.status == "partial_fill"
    assert plan.filled == 80
    assert plan.unfilled == 120
```

- [ ] **Step 2: Implement the splitter (copy directly from the spec)**

```python
# server/sidecar/splitter.py
"""Plan how a Kelly target gets allocated across the account pool.

Multi-parlay-per-account walk; lowest balance first; stack max-cap parlays
on each account until it can't fund another; take one partial; peel-back
when the residual would drop below the per-parlay floor."""
from __future__ import annotations

from server.sidecar.models import (
    AccountSnapshot,
    SplitAssignment,
    SplitPlan,
)


FLOOR = 30   # dollars; no individual parlay smaller than this


def plan_splits(
    target: int,
    accounts: list[AccountSnapshot],
) -> SplitPlan:
    if target < FLOOR:
        return SplitPlan(assignments=[], status="below_minimum", target=target)

    eligible = sorted(
        [a for a in accounts if a.available_balance >= FLOOR],
        key=lambda a: a.available_balance,
    )
    if not eligible:
        return SplitPlan(
            assignments=[], status="no_eligible_account", target=target,
        )

    assignments: list[SplitAssignment] = []
    remaining = target

    for account in eligible:
        if remaining == 0:
            break
        balance = int(account.available_balance)
        cap = account.max_parlay_stake

        # Pack full-cap parlays on this account
        while balance >= cap and remaining >= cap:
            assignments.append(SplitAssignment(account, cap))
            balance -= cap
            remaining -= cap

        if remaining == 0:
            break

        # Try one partial parlay on this account
        partial = min(balance, remaining, cap)
        if partial < FLOOR:
            continue
        new_remaining = remaining - partial
        if new_remaining == 0 or new_remaining >= FLOOR:
            assignments.append(SplitAssignment(account, partial))
            balance -= partial
            remaining = new_remaining
        else:
            # Shrink this partial so residual lands on FLOOR exactly
            adjusted = partial - (FLOOR - new_remaining)
            if adjusted >= FLOOR:
                assignments.append(SplitAssignment(account, adjusted))
                balance -= adjusted
                remaining = FLOOR

    # Final peel-back: reduce last assignment by (FLOOR - remaining) and
    # place a fresh FLOOR-sized bet on the next-cheapest non-same account.
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

- [ ] **Step 3: Run the worked-example tests to verify they pass**

Run: `pytest server/tests/test_sidecar_splitter.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 4: Add Hypothesis property tests**

```python
# append to test_sidecar_splitter.py
from hypothesis import given, strategies as st


@given(
    target=st.integers(min_value=0, max_value=2000),
    balances=st.lists(
        st.integers(min_value=0, max_value=2000),
        min_size=1, max_size=10,
    ),
    caps=st.lists(
        st.sampled_from([100, 150]),
        min_size=1, max_size=10,
    ),
)
def test_invariants_hold_for_arbitrary_inputs(target, balances, caps):
    pool = [
        _acct(f"A{i}", b, c)
        for i, (b, c) in enumerate(zip(balances, caps))
    ]
    plan = plan_splits(target, pool)

    if plan.status == "planned":
        assert plan.filled == target

    # Property 2: every amount ≥ FLOOR
    assert all(a.amount >= FLOOR for a in plan.assignments)

    # Property 3: per-parlay cap honored
    assert all(
        a.amount <= a.account.max_parlay_stake
        for a in plan.assignments
    )

    # Property 4: per-account total ≤ balance
    by_acct: dict[str, int] = {}
    for a in plan.assignments:
        by_acct.setdefault(a.account.customer_id, 0)
        by_acct[a.account.customer_id] += a.amount
    for cust, total in by_acct.items():
        bal = next(b for b, acc in zip(balances, pool)
                   if acc.customer_id == cust)
        assert total <= bal
```

If `hypothesis` isn't already a dev dependency, add it to `pyproject.toml`'s `[project.optional-dependencies] dev`.

- [ ] **Step 5: Run all splitter tests**

Run: `pytest server/tests/test_sidecar_splitter.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add server/sidecar/splitter.py server/tests/test_sidecar_splitter.py pyproject.toml
git commit -m "feat(sidecar): splitter — multi-parlay-per-account walk with peel-back"
```

---

## Phase D — Coral33 placement client

### Task D1: Extract + scrub HAR fixtures

**Files:**
- Create: `scripts/extract_har_fixtures.py`
- Create: `server/tests/fixtures/coral33/placement/get_parlay_specs.json`
- Create: `server/tests/fixtures/coral33/placement/get_info_parlay.json`
- Create: `server/tests/fixtures/coral33/placement/check_wager_line_multi_parlay.json`
- Create: `server/tests/fixtures/coral33/placement/insert_wager_parlay.json`
- Create: `server/tests/fixtures/coral33/placement/get_pending_by_ticket.json`

- [ ] **Step 1: Write the extractor**

```python
# scripts/extract_har_fixtures.py
"""One-shot: pull placement entries out of the dev HAR and scrub secrets.

Reads ~/Downloads/coral33.com.har, pulls the five parlay-placement entries
identified by entry index, scrubs JWT + customer-specific tokens, and
writes JSON fixtures under server/tests/fixtures/coral33/placement/."""
from __future__ import annotations

import json
import re
from pathlib import Path


HAR = Path.home() / "Downloads/coral33.com.har"
OUT = Path("server/tests/fixtures/coral33/placement")

# entry_index → fixture name (verified against HAR run on 2026-06-21)
ENTRIES = {
    36: "get_parlay_specs",
    37: "get_info_parlay",
    40: "check_wager_line_multi_parlay",
    41: "insert_wager_parlay",
    44: "get_pending_by_ticket",
}


def scrub_jwt(obj):
    """Recursively replace anything that looks like a JWT with a placeholder."""
    if isinstance(obj, str):
        # Loose JWT pattern: three base64url chunks separated by dots
        return re.sub(
            r"eyJ[A-Za-z0-9_\-=.]+\.[A-Za-z0-9_\-=.]+\.[A-Za-z0-9_\-=.]+",
            "<REDACTED_JWT>", obj,
        )
    if isinstance(obj, dict):
        return {k: scrub_jwt(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_jwt(v) for v in obj]
    return obj


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    har = json.loads(HAR.read_text())
    entries = har["log"]["entries"]
    for idx, name in ENTRIES.items():
        e = entries[idx]
        request_body = e["request"].get("postData", {}).get("text", "")
        request_json = json.loads(request_body) if request_body else None
        response_body = e["response"]["content"].get("text", "")
        response_json = json.loads(response_body) if response_body else None
        out = {
            "url": e["request"]["url"],
            "request": scrub_jwt(request_json),
            "response": scrub_jwt(response_json),
        }
        (OUT / f"{name}.json").write_text(
            json.dumps(out, indent=2, sort_keys=False) + "\n"
        )
        print(f"wrote {name}.json")


if __name__ == "__main__":
    main()
```

- [ ] **Step 1.5: Verify HAR entry indices match the expected operations**

Add this to the extractor immediately before writing each fixture file:

```python
EXPECTED_OPS = {
    36: "getParlaySpecs",
    37: "getInfoParlay",
    40: "checkWagerLineMulti",
    41: "insertWagerParlay",
    44: "getPendingByTicket",
}
for idx, name in ENTRIES.items():
    e = entries[idx]
    url = e["request"]["url"]
    expected = EXPECTED_OPS[idx]
    if expected not in url:
        raise SystemExit(
            f"HAR entry {idx} URL {url!r} does not contain expected "
            f"operation {expected!r}; HAR may have changed shape — "
            f"re-capture or update ENTRIES indices."
        )
```

This guards against HAR drift: if the user re-captures with a slightly different click sequence, the indices may shift. The script aborts loudly instead of silently writing the wrong fixtures.

- [ ] **Step 2: Run the extractor**

Run: `python scripts/extract_har_fixtures.py`

Expected output: 5 files written, none containing the literal user JWT.

- [ ] **Step 3: Verify no secrets leaked**

```bash
grep -r "eyJ" server/tests/fixtures/coral33/placement/ || echo "clean"
# Also scan for the user's actual JWT prefix if known
```

Expected: `clean` (no JWT-shaped strings remain).

- [ ] **Step 4: Commit fixtures**

```bash
git add scripts/extract_har_fixtures.py server/tests/fixtures/coral33/placement/
git commit -m "test(coral33): HAR fixtures for placement five-call chain"
```

---

### Task D2: Pure payload builders

**Files:**
- Create: `server/odds/books/coral33/placement.py` (builders section only)
- Test: `server/tests/test_coral33_placement.py` (payload-equivalence tests)

- [ ] **Step 1: Write the byte-equivalence test against the HAR fixture**

```python
# server/tests/test_coral33_placement.py
import json
from pathlib import Path

import pytest

from server.odds.books.coral33.placement import (
    build_check_wager_line_multi_parlay,
    build_insert_wager_parlay,
    build_get_info_parlay,
    build_get_parlay_specs,
    build_get_pending_by_ticket,
)
from server.sidecar.models import LegSpec


FIXTURE_DIR = Path(__file__).parent / "fixtures/coral33/placement"


def load(name):
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


@pytest.fixture
def new_zealand_leg() -> LegSpec:
    """Reconstruct the leg from the HAR's insert_wager_parlay payload."""
    return LegSpec(
        sport_type="Soccer              ",
        sport_sub_type="WORLD CUP   ",
        period="Game",
        line_type="M",
        game_num=619136397,
        chosen_team_id="New Zealand",
        rot_num=225390,
        price_american=475,
        price_decimal=5.75,
        price_numerator=19,
        price_denominator=4,
        game_datetime="2026-06-21 19:00:01.000",
        description="Soccer #225390 New Zealand +475 - For Game ",
    )


def test_build_get_parlay_specs_matches_har():
    fixture = load("get_parlay_specs")
    built = build_get_parlay_specs(
        customer_id="VR12509",
        parlay_name="10 team",
    )
    assert built == fixture["request"]


def test_build_get_info_parlay_matches_har():
    fixture = load("get_info_parlay")
    built = build_get_info_parlay(
        customer_id="VR12509",
        parlay_name="10 team",
        teams=2,
        selects="619136397-M|New Zealand^0",
    )
    assert built == fixture["request"]


def test_build_check_wager_line_multi_matches_har(new_zealand_leg):
    fixture = load("check_wager_line_multi_parlay")
    built = build_check_wager_line_multi_parlay(
        customer_id="VR12509",
        leg=new_zealand_leg,
        position=25710414,           # HAR-captured value
        risk_dollars=10.0,
        win_dollars=99.77,
    )
    assert built == fixture["request"]


def test_build_insert_wager_parlay_matches_har(new_zealand_leg):
    fixture = load("insert_wager_parlay")
    delay = fixture["request"]["delay"]
    built = build_insert_wager_parlay(
        customer_id="VR12509",
        agent_id="TYSONR",
        store="wiseguys",
        cust_profile=".                   ",
        leg=new_zealand_leg,
        stake_dollars=10.0,
        win_dollars=99.77,
        decimal_win_amount=47.5,
        parlay_name="10 team",
        doc_num=27458945,            # HAR-captured value
        delay=delay,
    )
    # The HAR has minor field-ordering jitter; compare structurally.
    assert built["operation"] == "insertWagerParlay"
    assert built["list"][0]["chosenTeamID"] == "New Zealand"
    assert built["list"][0]["wager"]["openSpotFlag"] == "O"
    assert built["list"][0]["wager"]["totalPicks"] == 2
    assert built["list"][0]["wager"]["minPicks"] == 1
    assert built["list"][0]["wager"]["parlayName"] == "10 team"
    assert built["delay"] == delay
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest server/tests/test_coral33_placement.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the builders in `placement.py`**

```python
# server/odds/books/coral33/placement.py
"""Coral33 bet-placement client — pure builders + Coral33Placer class.

The builders below are pure functions: they produce the exact JSON body
shape Coral33's web client sends. Byte-accuracy tests under
server/tests/test_coral33_placement.py compare them against HAR fixtures.

The Coral33Placer class wraps the builders with the network layer (uses
Coral33Client's authenticated session) and orchestrates the five-call
chain into a single place_open_parlay() method.

Kill switch:
  - Per-call live: bool — defaults to False (dry-run halts before step 4)
  - Module env CORAL33_PLACEMENT_LIVE=true — must be set for live placements
  - No instance is constructed by any API route or scheduler until the
    explicit wiring task lands.

See docs/superpowers/specs/2026-06-21-auto-bet-sidecar-design.md.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from server.sidecar.models import LegSpec


CUSTOMER_ID_WIDTH = 10


def _padded(customer_id: str) -> str:
    return customer_id + " " * max(0, CUSTOMER_ID_WIDTH - len(customer_id))


# --- Builders ----------------------------------------------------------------

def build_get_parlay_specs(customer_id: str, parlay_name: str) -> dict:
    return {
        "customerID": _padded(customer_id),
        "parlayName": parlay_name,
        "operation": "getParlaySpecs",
        "RRO": 1,
    }


def build_get_info_parlay(
    customer_id: str,
    parlay_name: str,
    teams: int,
    selects: str,
) -> dict:
    return {
        "customerID": _padded(customer_id),
        "teams": teams,
        "parlayName": parlay_name,
        "selects": selects,
        "operation": "getInfoParlay",
        "RRO": 1,
    }


def build_check_wager_line_multi_parlay(
    customer_id: str,
    leg: LegSpec,
    position: int,
    risk_dollars: float,
    win_dollars: float,
) -> dict:
    return {
        "list": [
            {
                "position": position,
                "gameNum": leg.game_num,
                "contestantNum": 0,
                "periodNumber": 0,
                "store": "wiseguys",
                "status": "O",
                "profile": ".",
                "periodType": leg.period,
                "description": leg.description,
                "risk": f"{risk_dollars:g}",
                "win": f"{win_dollars:g}",
                "wagerType": "P",
            }
        ],
        "customerID": _padded(customer_id),
        "operation": "checkWagerLineMulti",
        "RRO": 0,
    }


def build_insert_wager_parlay(
    customer_id: str,
    agent_id: str,
    store: str,
    cust_profile: str,
    leg: LegSpec,
    stake_dollars: float,
    win_dollars: float,
    decimal_win_amount: float,
    parlay_name: str,
    doc_num: int,
    delay: dict,
) -> dict:
    """Build the insertWagerParlay body. Matches the HAR's entry-41 schema."""
    padded = _padded(customer_id)
    today = time.strftime("%Y-%m-%d")
    return {
        "customerID": padded,
        "list": [
            {
                "customerID": padded,
                "docNum": doc_num,
                "wagerType": "P",
                "gameNum": leg.game_num,
                "wagerCount": 1,
                "gameDate": leg.game_datetime,
                "sportType": leg.sport_type,
                "sportSubType": leg.sport_sub_type,
                "lineType": leg.line_type,
                "adjSpread": 0,
                "adjTotal": 0,
                "priceType": "A",
                "finalMoney": leg.price_american,
                "finalDecimal": leg.price_decimal,
                "finalNumerator": leg.price_numerator,
                "finalDenominator": leg.price_denominator,
                "chosenTeamID": leg.chosen_team_id,
                "riskAmount": stake_dollars,
                "winAmount": decimal_win_amount,
                "store": store,
                "custProfile": cust_profile,
                "periodNumber": 0,
                "periodDescription": leg.period,
                "oddsFlag": "Y",
                "listedPitcher1": None,
                "pitcher1ReqFlag": "",
                "listedPitcher2": None,
                "pitcher2ReqFlag": "",
                "percentBook": 100,
                "volumeAmount": int(stake_dollars * 100),
                "currencyCode": "USD",
                "date": today,
                "agentID": agent_id,
                "easternLine": 0,
                "origPrice": leg.price_american,
                "origDecimal": leg.price_decimal,
                "origNumerator": leg.price_numerator,
                "origDenominator": leg.price_denominator,
                "creditAcctFlag": "Y",
                "wager": {
                    "date": today,
                    "minPicks": 1,
                    "totalPicks": 2,
                    "wagerCount": 1,
                    "riskAmount": stake_dollars,
                    "winAmount": f"{win_dollars:.2f}",
                    "description": leg.description,
                    "lineType": "P",
                    "freePlay": "N",
                    "agentID": agent_id,
                    "currencyCode": "USD",
                    "creditAcctFlag": "Y",
                    "playNumber": 1,
                    "roundRobin": 0,
                    "parlayName": parlay_name,
                    "openSpotFlag": "O",
                    "parlayPayOutType": "R",
                    "maxPayOut": 1000000,
                    "update": False,
                    "team": 2,
                },
                "itemNumber": 1,
                "wagerNumber": 1,
                "origSpread": leg.price_american,
                "origTotal": leg.price_american,
                "origMoney": leg.price_american,
                "roundRobin": "0",
                "extra": {
                    "team1": "",
                    "team2": leg.chosen_team_id,
                    "rot1": 0,
                    "rot2": leg.rot_num,
                    "line": f"{leg.price_american:+d}",
                    "buy": False,
                    "point": 0,
                },
                "status": "O",
            }
        ],
        "agentView": False,
        "operation": "insertWagerParlay",
        "delay": delay,
    }


def build_get_pending_by_ticket(
    agent_id: str, customer_id: str, ticket_number: int
) -> dict:
    return {
        "agentID": agent_id,
        "customerID": _padded(customer_id),
        "ticketNumber": ticket_number,
        "path": "/cloud/api/Report/getPendingByTicket",
        "RRO": 0,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest server/tests/test_coral33_placement.py -v`
Expected: PASS for all five builder tests (the `insert_wager_parlay` test compares structurally, not field-by-field, because the HAR has some field ordering jitter; that's intentional).

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/coral33/placement.py server/tests/test_coral33_placement.py
git commit -m "feat(coral33): pure payload builders for parlay placement chain"
```

---

### Task D2.5: Add `post_json` method to `Coral33Client`

**Why:** The existing `Coral33Client.post_form` (client.py:162) is hard-wired for **form-encoded** bodies: it `_stringify`s every param value and sends `application/x-www-form-urlencoded; charset=UTF-8`. The HAR shows placement bodies are **JSON** with nested arrays (`list: [...]`) and nested objects (`wager: {...}`, `extra: {...}`, `delay: {...}`). Trying to `_stringify` a `list` produces `str(list)` (e.g., `"[{'gameNum': 619136397, ...}]"`) — broken on the wire. We need a parallel method that POSTs raw JSON.

**Files:**
- Modify: `server/odds/books/coral33/client.py` (add `post_json`)
- Test: `server/tests/test_coral33_post_json.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_coral33_post_json.py
import json
import asyncio
import pytest
from unittest.mock import patch
from server.odds.books.coral33.client import Coral33Client


@pytest.mark.asyncio
async def test_post_json_sends_application_json_body(monkeypatch):
    """post_json must serialize the body as JSON, not form-encoded, and
    set content-type accordingly. Captures the request via a mock and
    asserts the captured body equals the input dict."""
    captured = {}

    async def fake_post(self, url, data=None, headers=None, json=None, **kw):
        captured["data"] = data
        captured["json"] = json
        captured["headers"] = headers
        # Return a fake response object
        class R:
            status_code = 200
            text = '{"INFO": {"MaxPicks": 10}}'
            def json(self):
                return {"INFO": {"MaxPicks": 10}}
        return R()

    from curl_cffi.requests import AsyncSession
    monkeypatch.setattr(AsyncSession, "post", fake_post)

    c = Coral33Client("VR12509", "pw")
    # Pre-set a token to skip auth
    c._token = "FAKE_JWT"
    c._token_exp = 9999999999

    nested_body = {
        "customerID": "VR12509   ",
        "list": [{"gameNum": 619136397, "wagerType": "P"}],
        "operation": "checkWagerLineMulti",
        "RRO": 0,
    }
    result = await c.post_json("checkWagerLineMulti", nested_body)
    assert result == {"INFO": {"MaxPicks": 10}}
    # Content-type must indicate JSON
    assert "application/json" in captured["headers"]["content-type"].lower()
    # Body must round-trip as the SAME nested dict (no _stringify)
    sent = captured["json"] or json.loads(captured["data"])
    assert sent == nested_body
    assert isinstance(sent["list"], list)
    assert isinstance(sent["list"][0], dict)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest server/tests/test_coral33_post_json.py -v`
Expected: FAIL — `post_json` not defined.

- [ ] **Step 3: Implement `post_json`**

In `server/odds/books/coral33/client.py`, add after `_raw_post`:

```python
    async def post_json(
        self, operation: str, body: dict[str, Any]
    ) -> dict:
        """POST {operation} with a JSON body (not form-encoded).
        Used by the placement chain — the bodies have nested arrays and
        nested objects that the form-encoded post_form path mangles.

        Same auth / proxy / impersonation behavior as post_form: re-auths
        on 401, retries once."""
        async with self._lock:
            if not self._token or self._token_expired():
                await self.authenticate()
            token_at_call = self._token
        try:
            return await self._raw_post_json(operation, body)
        except Coral33AuthError:
            async with self._lock:
                if self._token is None or self._token == token_at_call:
                    await self.authenticate()
            return await self._raw_post_json(operation, body)

    async def _raw_post_json(
        self, operation: str, body: dict[str, Any]
    ) -> dict:
        headers = {
            **_browser_headers(),
            "content-type": "application/json",
            "authorization": f"Bearer {self._token}",
        }
        proxies = {"http": self.proxy_url, "https": self.proxy_url} \
                  if self.proxy_url else None
        async with AsyncSession(
            impersonate="chrome", timeout=TIMEOUT, proxies=proxies
        ) as http:
            resp = await http.post(
                f"{BASE_URL}/{_operation_path(operation)}",
                json=body,
                headers=headers,
            )
            if resp.status_code == 401:
                self._token = None
                self._token_exp = None
                raise Coral33AuthError(f"{operation}: 401 — token rejected")
            if resp.status_code != 200:
                raise Coral33APIError(
                    f"{operation} {resp.status_code}: {resp.text[:300]}"
                )
            return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest server/tests/test_coral33_post_json.py -v`
Expected: PASS

- [ ] **Step 5: Reminder — D3's code blocks below already use `post_json`**

This is a forward reference: when you implement Task D3 in the next task, the placer's five-call orchestration and the `FakeCoral33Client` test fixture are both written against `post_json`. Don't accidentally copy a `post_form` from anywhere else.

- [ ] **Step 6: Commit**

```bash
git add server/odds/books/coral33/client.py server/tests/test_coral33_post_json.py
git commit -m "feat(coral33): post_json — JSON-body alternative to form-encoded post_form"
```

---

### Task D3: `Coral33Placer` class — the five-call chain

**Files:**
- Modify: `server/odds/books/coral33/placement.py` (append the class)
- Test: extend `server/tests/test_coral33_placement.py`

- [ ] **Step 1: Write the failing test (FakeClient + chain orchestration)**

```python
# Append to server/tests/test_coral33_placement.py
import pytest
from server.odds.books.coral33.placement import (
    Coral33Placer,
    PlacementResult,
    PlacementError,
)


class FakeCoral33Client:
    """In-memory replacement for Coral33Client. Records every POST and
    returns scripted responses keyed by operation name."""

    def __init__(self):
        self.customer_id = "VR12509"
        self.posts: list[tuple[str, dict]] = []
        self._responses: dict[str, Any] = {}

    def script(self, operation: str, response: Any) -> None:
        self._responses[operation] = response

    async def post_json(self, operation: str, body: dict) -> dict:
        self.posts.append((operation, body))
        if operation in self._responses:
            return self._responses[operation]
        raise AssertionError(f"unscripted op: {operation}")


@pytest.mark.asyncio
async def test_place_open_parlay_runs_five_calls_in_order(new_zealand_leg):
    client = FakeCoral33Client()
    client.script("getParlaySpecs",
                  {"INFO": {"MaxPicks": 10, "DefaultPrice": -110}})
    client.script("getInfoParlay",
                  {"INFO": {"CARD": [{"GamesPicked": 2, "MoneyLine": 2.6,
                                       "ToBase": 1, "MaxPayoutMoneyLine": None,
                                       "MaxPayoutToBase": None}]}})
    client.script("checkWagerLineMulti",
                  {"LIST": [{"position": 25710414,
                              "Status": "O",
                              "MoneyLine2": 475}],
                   "DELAY": {"time": 1782088322, "secs": 0, "sig": "SIG_X"}})
    client.script("insertWagerParlay",
                  {"STATUS": {"STATE": 1, "DOC": 1471133392, "T": ""}})
    client.script("getPendingByTicket",
                  {"PENDING": [{"TicketNumber": 1471133392}]})

    placer = Coral33Placer(
        client=client,
        agent_id="TYSONR",
        store="wiseguys",
        cust_profile=".                   ",
    )
    result = await placer.place_open_parlay(
        ev_leg=new_zealand_leg,
        stake_dollars=10,
        live=True,
    )
    assert isinstance(result, PlacementResult)
    assert result.ticket_number == 1471133392
    # Five-call sequence in exact order
    assert [op for op, _ in client.posts] == [
        "getParlaySpecs", "getInfoParlay", "checkWagerLineMulti",
        "insertWagerParlay", "getPendingByTicket",
    ]


@pytest.mark.asyncio
async def test_dry_run_halts_before_insert(new_zealand_leg):
    client = FakeCoral33Client()
    client.script("getParlaySpecs",
                  {"INFO": {"MaxPicks": 10, "DefaultPrice": -110}})
    client.script("getInfoParlay",
                  {"INFO": {"CARD": [{"GamesPicked": 2, "MoneyLine": 2.6,
                                       "ToBase": 1, "MaxPayoutMoneyLine": None,
                                       "MaxPayoutToBase": None}]}})
    client.script("checkWagerLineMulti",
                  {"LIST": [{"position": 1}],
                   "DELAY": {"time": 0, "secs": 0, "sig": "SIG_DRY"}})

    placer = Coral33Placer(client=client, agent_id="A", store="s",
                           cust_profile=".")
    result = await placer.place_open_parlay(
        ev_leg=new_zealand_leg, stake_dollars=10, live=False,
    )
    assert result.ticket_number is None
    assert result.dry_run is True
    assert result.would_be_payload is not None
    # Three calls, no insert, no pending fetch
    assert [op for op, _ in client.posts] == [
        "getParlaySpecs", "getInfoParlay", "checkWagerLineMulti",
    ]


@pytest.mark.asyncio
async def test_live_flag_false_overrides_env_true(new_zealand_leg, monkeypatch):
    monkeypatch.setenv("CORAL33_PLACEMENT_LIVE", "true")
    client = FakeCoral33Client()
    # Script enough for the dry-run path
    client.script("getParlaySpecs", {"INFO": {"MaxPicks": 10, "DefaultPrice": -110}})
    client.script("getInfoParlay", {"INFO": {"CARD": [{"GamesPicked": 2, "MoneyLine": 2.6, "ToBase": 1, "MaxPayoutMoneyLine": None, "MaxPayoutToBase": None}]}})
    client.script("checkWagerLineMulti", {"LIST": [{"position": 1}], "DELAY": {"time": 0, "secs": 0, "sig": "S"}})

    placer = Coral33Placer(client=client, agent_id="A", store="s",
                           cust_profile=".")
    result = await placer.place_open_parlay(
        ev_leg=new_zealand_leg, stake_dollars=10, live=False,
    )
    # The env says live, but the per-call flag says dry-run. Dry-run wins.
    assert result.dry_run is True


@pytest.mark.asyncio
async def test_live_requires_env_var(new_zealand_leg, monkeypatch):
    monkeypatch.delenv("CORAL33_PLACEMENT_LIVE", raising=False)
    client = FakeCoral33Client()
    placer = Coral33Placer(client=client, agent_id="A", store="s",
                           cust_profile=".")
    with pytest.raises(PlacementError, match="CORAL33_PLACEMENT_LIVE"):
        await placer.place_open_parlay(
            ev_leg=new_zealand_leg, stake_dollars=10, live=True,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest server/tests/test_coral33_placement.py -v -k "place_open_parlay or dry_run or live_"`
Expected: FAIL

- [ ] **Step 3: Implement `Coral33Placer`**

Append to `server/odds/books/coral33/placement.py`:

```python
# --- Coral33Placer -----------------------------------------------------------

@dataclass
class PlacementResult:
    ticket_number: int | None
    dry_run: bool
    accepted_payload: dict | None
    would_be_payload: dict | None     # set in dry-run; the body that WOULD have been sent
    decimal_payout: float             # from getInfoParlay × leg's decimal odds
    expected_win: float               # decimal_payout × stake - stake


class PlacementError(Exception):
    """Raised when the placement cannot proceed (sig missing, env gate, etc.)."""


class Coral33Placer:
    """Orchestrates the five-call open-spot parlay placement chain."""

    LIVE_ENV_VAR = "CORAL33_PLACEMENT_LIVE"

    def __init__(
        self,
        client: Any,                  # Coral33Client or FakeCoral33Client
        agent_id: str,
        store: str,
        cust_profile: str,
        parlay_name: str = "10 team",
    ):
        self.client = client
        self.agent_id = agent_id
        self.store = store
        self.cust_profile = cust_profile
        self.parlay_name = parlay_name
        self._specs_cache: dict | None = None

    async def place_open_parlay(
        self,
        ev_leg: LegSpec,
        stake_dollars: float,
        live: bool = False,
    ) -> PlacementResult:
        if live and os.environ.get(self.LIVE_ENV_VAR, "").lower() != "true":
            raise PlacementError(
                f"live placement requires {self.LIVE_ENV_VAR}=true"
            )

        # 1. getParlaySpecs (cached per Placer instance)
        if self._specs_cache is None:
            self._specs_cache = await self.client.post_json(
                "getParlaySpecs",
                build_get_parlay_specs(self.client.customer_id, self.parlay_name),
            )

        # 2. getInfoParlay — payout multiplier for a 2-team card
        selects = f"{ev_leg.game_num}-{ev_leg.line_type}|{ev_leg.chosen_team_id}^0"
        info = await self.client.post_json(
            "getInfoParlay",
            build_get_info_parlay(
                customer_id=self.client.customer_id,
                parlay_name=self.parlay_name,
                teams=2,
                selects=selects,
            ),
        )
        two_team_card = next(
            (c for c in info["INFO"]["CARD"] if c["GamesPicked"] == 2),
            None,
        )
        if two_team_card is None:
            raise PlacementError("getInfoParlay missing 2-team card row")
        decimal_multiplier = two_team_card["MoneyLine"]
        decimal_payout = ev_leg.price_decimal * decimal_multiplier
        expected_win = decimal_payout * stake_dollars - stake_dollars
        decimal_win_amount = ev_leg.price_decimal * stake_dollars - stake_dollars

        # 3. checkWagerLineMulti — line snapshot + DELAY.sig
        position = int(time.time() * 1000) % 10**8   # client-side unique id
        check = await self.client.post_json(
            "checkWagerLineMulti",
            build_check_wager_line_multi_parlay(
                customer_id=self.client.customer_id,
                leg=ev_leg,
                position=position,
                risk_dollars=stake_dollars,
                win_dollars=expected_win,
            ),
        )
        delay = check.get("DELAY")
        if not delay or "sig" not in delay:
            raise PlacementError("checkWagerLineMulti returned no DELAY.sig")

        # Build the insert payload regardless of mode (audit/preview)
        doc_num = int(time.time() * 1000) % 10**8
        insert_body = build_insert_wager_parlay(
            customer_id=self.client.customer_id,
            agent_id=self.agent_id,
            store=self.store,
            cust_profile=self.cust_profile,
            leg=ev_leg,
            stake_dollars=stake_dollars,
            win_dollars=expected_win,
            decimal_win_amount=decimal_win_amount,
            parlay_name=self.parlay_name,
            doc_num=doc_num,
            delay=delay,
        )

        if not live:
            # Dry-run: stop here, return the would-be payload
            return PlacementResult(
                ticket_number=None,
                dry_run=True,
                accepted_payload=None,
                would_be_payload=insert_body,
                decimal_payout=decimal_payout,
                expected_win=expected_win,
            )

        # 4. insertWagerParlay — actually place
        insert_resp = await self.client.post_json(
            "insertWagerParlay", insert_body
        )
        status = insert_resp.get("STATUS", {})
        if status.get("STATE") != 1 or "DOC" not in status:
            raise PlacementError(
                f"insertWagerParlay rejected: {insert_resp}"
            )
        ticket_number = int(status["DOC"])

        # 5. getPendingByTicket — receipt confirmation
        try:
            await self.client.post_json(
                "getPendingByTicket",
                build_get_pending_by_ticket(
                    agent_id=self.agent_id,
                    customer_id=self.client.customer_id,
                    ticket_number=ticket_number,
                ),
            )
        except Exception:
            # Receipt fetch is non-fatal — the bet landed.
            pass

        return PlacementResult(
            ticket_number=ticket_number,
            dry_run=False,
            accepted_payload=insert_resp,
            would_be_payload=None,
            decimal_payout=decimal_payout,
            expected_win=expected_win,
        )
```

- [ ] **Step 4: Add the five new operations to the `_OP_PATHS` map**

The real `Coral33Client` routes operation names → URL paths via `_OP_PATHS` (client.py:274–285). Both `post_form` and `post_json` consult this map. Add the new entries at the bottom of `client.py`:

```python
_OP_PATHS = {
    ... existing entries ...
    "getParlaySpecs":      "Limit/getParlaySpecs",
    "getInfoParlay":       "Limit/getInfoParlay",
    "checkWagerLineMulti": "WagerSport/checkWagerLineMulti",
    "insertWagerParlay":   "WagerSport/insertWagerParlay",
    "getPendingByTicket":  "Report/getPendingByTicket",
}
```

- [ ] **Step 5: Run all placement tests**

Run: `pytest server/tests/test_coral33_placement.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add server/odds/books/coral33/placement.py server/odds/books/coral33/client.py server/tests/test_coral33_placement.py
git commit -m "feat(coral33): Coral33Placer — five-call open-spot parlay chain"
```

---

### Task D4: Wire per-customer placement context (`agent_id`, `store`, `cust_profile`) from `getAccountInfo`

**Files:**
- Modify: `server/odds/books/coral33/accounts.py` (`AccountSnapshot` and the scrape loop)
- Test: extend `server/tests/test_coral33_accounts_load.py`

- [ ] **Step 1: Inspect what `getAccountInfo` already returns**

Run a quick HAR check: in `~/Downloads/coral33.com.har`, entry 7 is `Customer/getAccountInfo`. Read its response to confirm `AgentID`, `Store`, `CustProfile` are present.

- [ ] **Step 2: Add the fields to `AccountSnapshot`**

In `accounts.py:AccountSnapshot`, add:

```python
agent_id: str | None = None
store: str | None = None
cust_profile: str | None = None
```

And populate them in the scrape loop where the existing balance fields are parsed from `getAccountInfo`.

- [ ] **Step 3: Write the failing test**

```python
# Append to server/tests/test_coral33_accounts_load.py
import asyncio
from unittest.mock import AsyncMock

def test_account_snapshot_carries_placement_context(monkeypatch):
    """After a scrape, AccountSnapshot exposes the per-customer placement
    context fields the Coral33Placer needs."""
    from server.odds.books.coral33 import accounts as accts

    cred = accts.AccountCredential(
        customer_id="VR11606", password="p", label="Stanley",
        proxy_url="http://u:p@h:1", max_parlay_stake=150,
    )

    # Mock Coral33Client.post_form to return a getAccountInfo response that
    # includes the placement-context fields the HAR shows.
    fake_account_info = {
        "ACCOUNTINFO": {
            "CurrentBalance": 500.0,
            "AvailableBalance": 480.0,
            "PendingWagerBalance": 20.0,
            "FreePlayBalance": 0.0,
            "CreditLimit": 1000.0,
            "WagerLimit": 200.0,
            "AgentID": "TYSONR",
            "Store": "wiseguys",
            "CustProfile": ".                   ",
        }
    }

    async def fake_post_form(self, op, params=None):
        if op == "getAccountInfo":
            return fake_account_info
        raise AssertionError(f"unscripted op in test: {op}")

    monkeypatch.setattr(accts.Coral33Client, "post_form", fake_post_form)
    # Skip the real authenticate
    monkeypatch.setattr(accts.Coral33Client, "authenticate",
                       AsyncMock(return_value=None))

    scraper = accts.AccountsScraper([cred])
    snap = asyncio.run(scraper._scrape_one(cred))   # whatever the existing
                                                     # per-account fetch is named

    assert snap.credential.customer_id == "VR11606"
    assert snap.agent_id == "TYSONR"
    assert snap.store == "wiseguys"
    assert snap.cust_profile == ".                   "
    assert snap.available_balance == 480.0
```

- [ ] **Step 4: Run tests + commit**

```bash
git add server/odds/books/coral33/accounts.py server/tests/test_coral33_accounts_load.py
git commit -m "feat(coral33): carry agent_id/store/cust_profile on AccountSnapshot"
```

---

## Phase E — Sidecar orchestrator

### Task E1: SSE event types — `publish()` on the existing broker

**Why this is different from how it's drafted:** The SSE broker lives at `server/odds/events.py`, not `server/api/stream.py`. It has `mark_dirty()` (line 74) and `subscribe()` (line 90), but no public publish — only a module-private `_broadcast(event: dict)` (line 115). The existing flow is **dumb-tick**: `mark_dirty()` enqueues a flag that the `flush_loop` debounces into a single generic event. The sidecar needs **typed** events (per-job placement results), so we add one new public function `publish(event)` that bypasses the dumb-tick coalescing and broadcasts immediately with whatever shape the caller chose.

**Files:**
- Modify: `server/odds/events.py` (add public `publish`)
- Modify: `server/api/stream.py` (verify the SSE writer forwards the new event types unchanged — it should because `_format_event` already emits whatever dict it's given)
- Create: `server/sidecar/sse.py`
- Test: extend an existing `server/tests/test_events.py` if present, or add `server/tests/test_sidecar_sse.py`

- [ ] **Step 1: Read `server/odds/events.py` end-to-end**

Note: `_broadcast(event)` (line 115) iterates `subscribers` and calls `put_nowait` per queue. `flush_loop` (line 138) is what mark_dirty schedules. They're orthogonal — `publish` needs to call `_broadcast` directly.

- [ ] **Step 2: Write the failing test**

```python
# server/tests/test_sidecar_sse.py
import asyncio
import pytest
from server.odds import events


@pytest.mark.asyncio
async def test_publish_broadcasts_typed_event_to_subscriber():
    events._reset_for_tests()
    q = events.subscribe()
    try:
        events.publish({"type": "sidecar_placement", "job_id": "j1",
                        "result": "placed", "stake": 100})
        # Should land in the queue effectively immediately
        msg = await asyncio.wait_for(q.get(), timeout=0.5)
        assert msg["type"] == "sidecar_placement"
        assert msg["job_id"] == "j1"
    finally:
        events.unsubscribe(q)


@pytest.mark.asyncio
async def test_publish_does_not_disturb_mark_dirty_coalescing():
    """publish() is a separate path; it shouldn't reset the mark_dirty
    debounce window."""
    events._reset_for_tests()
    q = events.subscribe()
    try:
        events.mark_dirty()
        events.publish({"type": "sidecar_placement", "job_id": "j2"})
        # mark_dirty is still pending until the next flush tick. publish
        # delivered immediately. So the queue has at least the publish.
        first = await asyncio.wait_for(q.get(), timeout=0.5)
        assert first["type"] == "sidecar_placement"
    finally:
        events.unsubscribe(q)
```

- [ ] **Step 3: Implement `publish` in `server/odds/events.py`**

```python
def publish(event: dict[str, Any]) -> None:
    """Broadcast a typed event to every subscriber IMMEDIATELY.

    Distinct from mark_dirty(), which is the dumb-tick coalescing path used
    by cache writers. Callers (currently: the sidecar orchestrator) own the
    event shape — convention is to set event['type'] so consumers can
    discriminate. The SSE writer in server/api/stream.py emits whatever
    dict it receives, so no parser changes are needed."""
    if "type" not in event:
        raise ValueError("publish() event must carry a 'type' field")
    _broadcast(event)
```

- [ ] **Step 4: Implement the sidecar SSE helpers**

```python
# server/sidecar/sse.py
"""Typed publish helpers for the four sidecar SSE event types.

Thin layer over server.odds.events.publish() — every helper sets the type
field. Keeping these inline-typed dicts ensures the consumer schema is
discoverable from one file."""
from __future__ import annotations

from server.odds import events


def emit_placement(payload: dict) -> None:
    events.publish({"type": "sidecar_placement", **payload})


def emit_topup_required(payload: dict) -> None:
    events.publish({"type": "sidecar_topup_required", **payload})


def emit_signal_skipped(payload: dict) -> None:
    events.publish({"type": "sidecar_signal_skipped", **payload})


def emit_partial_fill(payload: dict) -> None:
    events.publish({"type": "sidecar_partial_fill", **payload})
```

- [ ] **Step 5: Verify `server/api/stream.py` forwards the new event types**

Read `stream.py`'s event-writing loop. It pulls events from the subscriber queue and yields SSE frames. If it does `yield f"data: {json.dumps(event)}\n\n"` or `yield _format_event(...)` with the event dict verbatim, no changes needed. If it filters by allow-listed event types, add the four new types.

- [ ] **Step 6: Run tests + commit**

```bash
pytest server/tests/test_sidecar_sse.py -v
git add server/odds/events.py server/sidecar/sse.py server/tests/test_sidecar_sse.py
git commit -m "feat(sidecar): publish() on events broker + typed SSE helpers"
```

---

### Task E2: `placement.py` orchestrator — splitter + loop + audit

**Files:**
- Create: `server/sidecar/placement.py`
- Test: `server/tests/test_sidecar_placement.py`

- [ ] **Step 1: Write the failing test for the happy path**

```python
# server/tests/test_sidecar_placement.py
import json
import uuid
import pytest

from server.odds.books.coral33.accounts import AccountCredential
from server.sidecar.models import AccountSnapshot, LegSpec
from server.sidecar.placement import (
    SidecarOrchestrator,
    SidecarPlaceRequest,
    JitterDisabled,
)


def make_leg() -> LegSpec:
    return LegSpec(
        sport_type="Soccer              ",
        sport_sub_type="WORLD CUP   ",
        period="Game",
        line_type="M",
        game_num=619136397,
        chosen_team_id="New Zealand",
        rot_num=225390,
        price_american=475,
        price_decimal=5.75,
        price_numerator=19,
        price_denominator=4,
        game_datetime="2026-06-21 19:00:01.000",
        description="Soccer #225390 New Zealand +475 - For Game ",
    )


def make_pool() -> list[AccountSnapshot]:
    return [
        AccountSnapshot(
            credential=AccountCredential(
                "VR11606", "p", "Stanley", "http://p:p@h:1", 150),
            available_balance=500.0,
            agent_id="TYSONR", store="wiseguys",
            cust_profile=".                   ",
        ),
        AccountSnapshot(
            credential=AccountCredential(
                "VR11601", "p", "Dixon", "http://p:p@h:2", 100),
            available_balance=1000.0,
            agent_id="TYSONR", store="wiseguys",
            cust_profile=".                   ",
        ),
    ]


class FakePlacerFactory:
    """Returns a fresh FakeCoral33Placer per customer_id."""
    def __init__(self):
        self.placers: dict[str, "FakeCoral33Placer"] = {}

    def for_account(self, snapshot: AccountSnapshot):
        ...   # construct or reuse a FakeCoral33Placer keyed by customer_id


@pytest.mark.asyncio
async def test_dry_run_target_230_stanley_then_dixon(tmp_path):
    """Target $230 → Stanley($150) + Dixon($80), both as dry_run rows."""
    pool = make_pool()
    leg = make_leg()
    orchestrator = SidecarOrchestrator(
        pool_provider=lambda: pool,
        placer_factory=FakePlacerFactory(),
        mode="dry-run",
        db_path=tmp_path / "cache.db",
        jitter=JitterDisabled,
    )
    job_id = uuid.uuid4().hex
    returned = await orchestrator.handle_place(
        SidecarPlaceRequest(
            ev_row_id="rid",
            ev_leg=leg,
            kelly_full_pct=0.046,        # produces $230 target at $10k × half
            kelly_fraction=KellyFraction.HALF,
            bankroll=10000,
        ),
        job_id,
    )
    assert returned == job_id
    rows = orchestrator.audit.fetch_job(job_id)
    assert len(rows) == 2
    assert [r.picked_account for r in rows] == ["VR11606", "VR11601"]
    assert [r.stake for r in rows] == [150, 80]
    assert all(r.result == "dry_run" for r in rows)
```

- [ ] **Step 2: Implement `SidecarOrchestrator`**

```python
# server/sidecar/placement.py
"""Sidecar orchestrator: splitter → per-assignment placement loop → audit + SSE.

Run inside a FastAPI BackgroundTask. The HTTP route validates the request,
enqueues the orchestrator, and returns a job_id immediately. UI subscribes
to SSE for updates."""
from __future__ import annotations

import asyncio
import json
import random
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable

from server.sidecar import audit, sse
from server.sidecar.models import (
    AccountSnapshot,
    LegSpec,
    SplitAssignment,
    SplitPlan,
)
from server.sidecar.settings import KellyFraction, kelly_to_pct
from server.sidecar.splitter import plan_splits


@dataclass
class SidecarPlaceRequest:
    ev_row_id: str
    ev_leg: LegSpec
    kelly_full_pct: float       # the +EV row's full-Kelly %
    kelly_fraction: KellyFraction
    bankroll: int


class JitterDisabled:
    """Sentinel for tests: no sleep between assignments."""
    async def sleep(self, ix: int, total: int) -> None:
        return None


class JitterRandom:
    """Production jitter: 3–8s uniform between assignments, no gap on the
    first one or single-assignment jobs."""
    def __init__(self, low: float = 3.0, high: float = 8.0):
        self.low, self.high = low, high

    async def sleep(self, ix: int, total: int) -> None:
        if total <= 1 or ix == 0:
            return
        await asyncio.sleep(random.uniform(self.low, self.high))


def _payload_for_audit(result) -> dict | None:
    """Pick whichever placement payload exists for the audit row.

    - live success → accepted_payload (the actual server response)
    - dry-run     → would_be_payload  (the payload we constructed)
    - error path  → None              (caller passes result=None)
    """
    if result is None:
        return None
    return result.accepted_payload or result.would_be_payload


class SidecarOrchestrator:
    def __init__(
        self,
        pool_provider: Callable[[], list[AccountSnapshot]],
        placer_factory,                  # has .for_account(snapshot) → placer
        mode: str,                       # 'dry-run' | 'live'
        db_path,
        jitter=None,
    ):
        self.pool_provider = pool_provider
        self.placer_factory = placer_factory
        self.mode = mode
        self.db_path = db_path
        self.jitter = jitter or JitterRandom()

    @property
    def audit_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    async def handle_place(
        self,
        req: SidecarPlaceRequest,
        job_id: str,             # caller-provided (route generates and returns it)
    ) -> str:
        kelly_pct = kelly_to_pct(req.kelly_fraction, req.kelly_full_pct)
        target = round(kelly_pct * req.bankroll)

        pool = self.pool_provider()
        plan = plan_splits(target, pool)

        conn = self.audit_conn
        try:
            if plan.status == "below_minimum":
                self._record_refusal(conn, job_id, req, plan, "below_minimum",
                                     "Kelly target $%d below $30 floor" % target)
                sse.emit_signal_skipped({
                    "job_id": job_id, "target_stake": target, "floor": 30,
                })
                return job_id

            if plan.status == "no_eligible_account":
                self._record_refusal(conn, job_id, req, plan,
                                     "no_eligible_account",
                                     "no account has $30+ available")
                lowest = min((a for a in pool), key=lambda a: a.available_balance)
                sse.emit_topup_required({
                    "job_id": job_id, "target_stake": target,
                    "max_fundable": 0,
                    "lowest_balance_account": lowest.customer_id,
                })
                return job_id

            # Per-account session reuse: group assignments by customer_id in
            # the order they appear in plan.assignments (preserves the
            # splitter's lowest-balance-first ordering).
            placers: dict[str, object] = {}

            total = len(plan.assignments)
            for ix, assignment in enumerate(plan.assignments):
                await self.jitter.sleep(ix, total)
                cid = assignment.account.customer_id
                if cid not in placers:
                    placers[cid] = self.placer_factory.for_account(
                        assignment.account
                    )
                placer = placers[cid]
                await self._fire_one(conn, job_id, req, assignment, placer)

            if plan.status == "partial_fill":
                self._record_partial(conn, job_id, req, plan)
                sse.emit_partial_fill({
                    "job_id": job_id,
                    "target_stake": target,
                    "filled_stake": plan.filled,
                    "unfilled_stake": plan.unfilled,
                })

            return job_id
        finally:
            conn.close()

    async def _fire_one(
        self, conn, job_id, req, assignment: SplitAssignment, placer,
    ):
        try:
            result = await placer.place_open_parlay(
                ev_leg=req.ev_leg,
                stake_dollars=assignment.amount,
                live=(self.mode == "live"),
            )
            self._record_placement(
                conn, job_id, req, assignment, result, "placed"
                if not result.dry_run else "dry_run",
            )
            sse.emit_placement({
                "job_id": job_id,
                "result": "placed" if not result.dry_run else "dry_run",
                "ticket_number": str(result.ticket_number)
                                  if result.ticket_number else None,
                "picked_account": assignment.account.customer_id,
                "stake": assignment.amount,
                "mode": self.mode,
            })
        except Exception as ex:
            self._record_placement(
                conn, job_id, req, assignment, None, "error", str(ex),
            )
            sse.emit_placement({
                "job_id": job_id, "result": "error",
                "picked_account": assignment.account.customer_id,
                "stake": assignment.amount, "mode": self.mode,
                "error_message": str(ex),
            })

    # --- audit row helpers (one per result kind) ---

    def _record_placement(self, conn, job_id, req, assignment, result, kind,
                          error_message=None):
        audit.insert_placement(conn, audit.AuditRow(
            placement_id=uuid.uuid4().hex,
            job_id=job_id,
            created_at=int(time.time()),
            ev_row_id=req.ev_row_id,
            ev_leg=json.dumps(req.ev_leg.__dict__),
            parlay_name="10 team",
            kelly_fraction=req.kelly_fraction.value,
            target_stake=float(round(
                kelly_to_pct(req.kelly_fraction, req.kelly_full_pct)
                * req.bankroll
            )),
            stake=float(assignment.amount),
            mode=self.mode,
            picked_account=assignment.account.customer_id,
            result=kind,
            ticket_number=str(result.ticket_number)
                          if result and result.ticket_number else None,
            accepted_payload=json.dumps(_payload_for_audit(result)),
            error_message=error_message,
        ))

    def _record_refusal(self, conn, job_id, req, plan, kind, msg):
        audit.insert_placement(conn, audit.AuditRow(
            placement_id=uuid.uuid4().hex,
            job_id=job_id, created_at=int(time.time()),
            ev_row_id=req.ev_row_id,
            ev_leg=json.dumps(req.ev_leg.__dict__),
            parlay_name="10 team",
            kelly_fraction=req.kelly_fraction.value,
            target_stake=float(plan.target), stake=None,
            mode=self.mode,
            picked_account=None,
            result=kind,
            ticket_number=None, accepted_payload=None,
            error_message=msg,
        ))

    def _record_partial(self, conn, job_id, req, plan):
        audit.insert_placement(conn, audit.AuditRow(
            placement_id=uuid.uuid4().hex,
            job_id=job_id, created_at=int(time.time()),
            ev_row_id=req.ev_row_id,
            ev_leg=json.dumps(req.ev_leg.__dict__),
            parlay_name="10 team",
            kelly_fraction=req.kelly_fraction.value,
            target_stake=float(plan.target),
            stake=float(plan.filled),
            mode=self.mode,
            picked_account=None,
            result="partial_fill",
            ticket_number=None, accepted_payload=None,
            error_message=f"pool filled ${plan.filled} of ${plan.target}",
        ))
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `pytest server/tests/test_sidecar_placement.py -v`
Expected: PASS

- [ ] **Step 4: Add cascade tests**

Extend the test file with:

```python
@pytest.mark.asyncio
async def test_account_scoped_failure_skips_remaining_same_account_siblings(
    tmp_path,
):
    """Target $250 against A=$300, cap $100 → A:$100, A:$100, A:$50.
    First A:$100 raises Coral33AuthError. Remaining A:* assignments are
    recorded as 'error' without an HTTP attempt."""
    from server.odds.books.coral33.client import Coral33AuthError

    cred_a = AccountCredential(
        "A", "pw", "AcctA", "http://p:p@h:1", max_parlay_stake=100,
    )
    pool = [AccountSnapshot(
        credential=cred_a, available_balance=300.0,
        agent_id="TYSONR", store="wiseguys",
        cust_profile=".                   ",
    )]

    call_count = {"n": 0}

    class FailingPlacer:
        async def place_open_parlay(self, ev_leg, stake_dollars, live):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise Coral33AuthError("token rejected")
            raise AssertionError(
                "should not reach a second HTTP attempt after auth failure"
            )

    class FailingFactory:
        def for_account(self, snapshot):
            return FailingPlacer()

    orchestrator = SidecarOrchestrator(
        pool_provider=lambda: pool,
        placer_factory=FailingFactory(),
        mode="live",
        db_path=tmp_path / "cache.db",
        jitter=JitterDisabled(),
    )
    job_id = uuid.uuid4().hex
    await orchestrator.handle_place(
        SidecarPlaceRequest(
            ev_row_id="rid",
            ev_leg=make_leg(),
            kelly_full_pct=0.05,    # target $250 at $10k × half
            kelly_fraction=KellyFraction.HALF,
            bankroll=10000,
        ),
        job_id,
    )
    rows = orchestrator.audit.fetch_job(job_id)

    # Three split-siblings, but only ONE HTTP call was attempted
    assert call_count["n"] == 1
    assert len(rows) == 3
    assert all(r.picked_account == "A" for r in rows)
    assert all(r.result == "error" for r in rows)
    # First row's error is the auth failure; the next two are the cascade
    assert "token rejected" in rows[0].error_message
    assert "auth_failed (account-scoped cascade)" in rows[1].error_message
    assert "auth_failed (account-scoped cascade)" in rows[2].error_message
```

> **Cascade semantics in the orchestrator:** the `_fire_one` loop catches account-scoped exceptions (`Coral33AuthError`, `Coral33ConnectionError`, balance-rejection responses), records `error` for the current assignment, AND records `error` rows for every remaining assignment on the same `customer_id` in the plan before continuing to the next distinct account. Implement this by partitioning `plan.assignments` by `customer_id` up front and processing each group as a unit; on the first failure inside a group, mark every remaining sibling as error without invoking the placer.

- [ ] **Step 5: Commit**

```bash
git add server/sidecar/placement.py server/tests/test_sidecar_placement.py
git commit -m "feat(sidecar): orchestrator — splitter → loop → audit → SSE"
```

---

## Phase F — API endpoints

### Task F0: Define `ev_row_id` format + add the field to `EVOpportunity`

**Why:** The plan and spec reference `ev_row_id` as if it exists on the EV API surface, but it doesn't — `EVOpportunity` (server/api/ev.py:17–42) has `event_id`, `market_kind`, `point`, `outcome_name`, `book`, but no canonical row identifier. The frontend needs ONE string per row to send back in `POST /api/sidecar/place`. We define a canonical pipe-delimited string and add it as a computed field.

**Format:** `f"{event_id}|{market_kind}|{point or ''}|{outcome_name}|{book}"`. Sport_key is omitted (already implicit in event_id under the cache's keying). `point` serializes empty when None.

**Files:**
- Create: `server/sidecar/ev_row_id.py` (canonical format + parser)
- Modify: `server/api/ev.py` (add `ev_row_id` field to `EVOpportunity`)
- Modify: `web/types/api.ts` (regenerate from openapi after the field lands)
- Test: `server/tests/test_sidecar_ev_row_id.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_sidecar_ev_row_id.py
from server.sidecar.ev_row_id import build_ev_row_id, parse_ev_row_id


def test_round_trip_with_point():
    rid = build_ev_row_id(
        event_id="evt-123", market_kind="totals", point=2.5,
        outcome_name="Over", book="coral33",
    )
    assert rid == "evt-123|totals|2.5|Over|coral33"
    parsed = parse_ev_row_id(rid)
    assert parsed["event_id"] == "evt-123"
    assert parsed["market_kind"] == "totals"
    assert parsed["point"] == 2.5
    assert parsed["outcome_name"] == "Over"
    assert parsed["book"] == "coral33"


def test_round_trip_with_none_point():
    rid = build_ev_row_id(
        event_id="evt-X", market_kind="h2h", point=None,
        outcome_name="New Zealand", book="coral33",
    )
    assert rid == "evt-X|h2h||New Zealand|coral33"
    parsed = parse_ev_row_id(rid)
    assert parsed["point"] is None


def test_outcome_name_with_pipe_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        build_ev_row_id(
            event_id="e", market_kind="h2h", point=None,
            outcome_name="Bad|name", book="coral33",
        )


def test_malformed_row_id_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        parse_ev_row_id("not-enough-parts")
```

- [ ] **Step 2: Implement the canonical-id module**

```python
# server/sidecar/ev_row_id.py
"""Canonical row identifier for /api/ev opportunities.

Format: f"{event_id}|{market_kind}|{point or ''}|{outcome_name}|{book}"

Strict: no field may contain a literal '|'. event_id and outcome_name in
Odds-API data don't contain pipes today, but we validate to avoid silent
ambiguity if that ever changes."""
from __future__ import annotations


SEP = "|"


def build_ev_row_id(
    *,
    event_id: str,
    market_kind: str,
    point: float | None,
    outcome_name: str,
    book: str,
) -> str:
    for name, val in [
        ("event_id", event_id), ("market_kind", market_kind),
        ("outcome_name", outcome_name), ("book", book),
    ]:
        if SEP in val:
            raise ValueError(f"{name} contains '{SEP}': {val!r}")
    point_str = "" if point is None else f"{point:g}"
    return SEP.join([event_id, market_kind, point_str, outcome_name, book])


def parse_ev_row_id(rid: str) -> dict:
    parts = rid.split(SEP)
    if len(parts) != 5:
        raise ValueError(f"malformed ev_row_id (expected 5 parts): {rid!r}")
    event_id, market_kind, point_str, outcome_name, book = parts
    return {
        "event_id": event_id,
        "market_kind": market_kind,
        "point": float(point_str) if point_str else None,
        "outcome_name": outcome_name,
        "book": book,
    }
```

- [ ] **Step 3: Add the field to `EVOpportunity` and populate it**

In `server/api/ev.py`, add to `EVOpportunity`:

```python
class EVOpportunity(BaseModel):
    sport_key: str
    event_id: str
    ...existing fields...
    wager_type: Literal["straight", "parlay", "both"] | None = None
    ev_row_id: str   # canonical (event_id, market_kind, point, outcome_name, book)
```

In the response builder (search `model_validate` or wherever `EVOpportunity` instances are constructed), populate `ev_row_id` via `build_ev_row_id(...)` from the same fields.

- [ ] **Step 4: Implement `resolve_ev_row_to_leg`**

This is the resolver the API endpoint uses. It takes the row_id, parses it, looks up the current cached EV row, and returns `(LegSpec, kelly_full_pct)`:

```python
# server/sidecar/resolve.py
"""Resolve an ev_row_id back into a LegSpec + Kelly% by re-reading the
current /api/ev output. Re-uses the live EV scanner (with TTL cache) so
the sidecar fires against the same snapshot the UI sees.

Returns None if the row is no longer present (line moved off best price,
event went off the board, etc.). The orchestrator surfaces a 404 in that
case."""
from __future__ import annotations

from server.sidecar.ev_row_id import parse_ev_row_id
from server.sidecar.models import LegSpec


def resolve_ev_row_to_leg(ev_row_id: str) -> tuple[LegSpec, float] | None:
    parsed = parse_ev_row_id(ev_row_id)
    # Use the same scanner the /api/ev endpoint uses; the response model
    # gives us every field we need to build a LegSpec.
    from server.api.ev import _scan_ev_opportunities  # internal helper
    opps = _scan_ev_opportunities(
        # Reasonable defaults — we just need to FIND this one row.
        min_ev=-100.0, stale_seconds=300, max_results=10000,
    )
    match = next(
        (o for o in opps
         if o.event_id == parsed["event_id"]
         and o.market_kind == parsed["market_kind"]
         and (o.point or None) == parsed["point"]
         and o.outcome_name == parsed["outcome_name"]
         and o.book == parsed["book"]),
        None,
    )
    if match is None:
        return None
    # The Coral33-specific fields (sport_type, game_num, rot_num,
    # price_decimal, etc.) come from the SAME cache row that fed
    # /api/ev. Look them up via the cache's existing event lookup
    # (`OddsCache.get_event_row(event_id, market_kind, outcome_name, book)`)
    # — the helper or its equivalent already exists; if not, add it.
    ...
    return leg, match.kelly_full_pct
```

The actual resolver implementation needs to walk from `EVOpportunity` (which has prices in American + decimal + ev_pct + kelly) plus the cache's raw row (which has sport_type, sport_sub_type, game_num, rot_num, game_datetime, price_numerator/denominator, etc.) into a `LegSpec`. Both data sources are already in `cache.db`. The plan executor: read `server/odds/cache.py` for the existing row-lookup pattern; copy the join logic that `/api/ev` itself uses.

- [ ] **Step 5: Run all new tests + commit**

```bash
pytest server/tests/test_sidecar_ev_row_id.py -v
git add server/sidecar/ev_row_id.py server/sidecar/resolve.py server/api/ev.py server/tests/test_sidecar_ev_row_id.py
git commit -m "feat(sidecar): canonical ev_row_id on EVOpportunity + resolver"
```

---

### Task F1: `POST /api/sidecar/place`

**Files:**
- Create: `server/api/sidecar.py`
- Modify: `server/main.py` (register router)
- Test: `server/tests/test_sidecar_api.py`

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_sidecar_api.py
from fastapi.testclient import TestClient
from server.main import app


def test_post_place_returns_job_id():
    client = TestClient(app)
    r = client.post("/api/sidecar/place", json={
        "ev_row_id": "619136397|h2h|new_zealand",
        "kelly_fraction": "half",
    })
    assert r.status_code == 202
    body = r.json()
    assert "job_id" in body and len(body["job_id"]) == 32   # uuid4 hex


def test_post_place_validates_ev_row_id_exists(monkeypatch):
    client = TestClient(app)
    r = client.post("/api/sidecar/place", json={
        "ev_row_id": "nonexistent",
        "kelly_fraction": "half",
    })
    assert r.status_code == 404


def test_get_runs_returns_recent_jobs():
    client = TestClient(app)
    r = client.get("/api/sidecar/runs?limit=20")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_mode_default_is_dry_run():
    client = TestClient(app)
    r = client.get("/api/sidecar/mode")
    assert r.json() == {"mode": "dry-run"}


def test_post_mode_flips_to_live():
    client = TestClient(app)
    r = client.post("/api/sidecar/mode", json={"mode": "live"})
    assert r.status_code == 200
    assert client.get("/api/sidecar/mode").json() == {"mode": "live"}
    # Restore
    client.post("/api/sidecar/mode", json={"mode": "dry-run"})
```

- [ ] **Step 2: Implement the router**

```python
# server/api/sidecar.py
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from server.sidecar.mode_store import SidecarModeStore, SidecarMode
from server.sidecar.placement import SidecarOrchestrator, SidecarPlaceRequest
from server.sidecar.settings import KellyFraction, get_bankroll
from server.sidecar.audit import fetch_placements, fetch_job


router = APIRouter(prefix="/api/sidecar", tags=["sidecar"])


class PlaceBody(BaseModel):
    ev_row_id: str
    kelly_fraction: str        # 'full' | 'half' | 'quarter'


class PlaceResponse(BaseModel):
    job_id: str
    plan_preview: dict | None = None


@router.post("/place", status_code=202, response_model=PlaceResponse)
async def post_place(body: PlaceBody, background_tasks: BackgroundTasks):
    # Resolve ev_row_id → LegSpec from the cache (sport-agnostic helper to add)
    from server.sidecar.resolve import resolve_ev_row_to_leg
    ev_leg, kelly_full_pct = resolve_ev_row_to_leg(body.ev_row_id) or (None, None)
    if ev_leg is None:
        raise HTTPException(404, detail=f"ev_row_id not found: {body.ev_row_id}")

    fraction = KellyFraction(body.kelly_fraction)
    bankroll = get_bankroll()

    from server.sidecar.factory import get_orchestrator
    orchestrator = get_orchestrator()
    req = SidecarPlaceRequest(
        ev_row_id=body.ev_row_id, ev_leg=ev_leg,
        kelly_full_pct=kelly_full_pct, kelly_fraction=fraction,
        bankroll=bankroll,
    )
    # Pre-compute the plan synchronously so the UI gets a plan_preview
    from server.sidecar.splitter import plan_splits
    from server.sidecar.settings import kelly_to_pct
    target = round(kelly_to_pct(fraction, kelly_full_pct) * bankroll)
    plan = plan_splits(target, orchestrator.pool_provider())

    job_id = uuid.uuid4().hex
    background_tasks.add_task(orchestrator.handle_place, req, job_id)
    return PlaceResponse(
        job_id=job_id,
        plan_preview={
            "target": plan.target,
            "status": plan.status,
            "assignments": [
                {"customer_id": a.account.customer_id, "amount": a.amount}
                for a in plan.assignments
            ],
        },
    )
```

- [ ] **Step 1.5: Note — Task E2's `handle_place` already takes `job_id` as a parameter**

The orchestrator implementation in Task E2 below is written with `handle_place(req: SidecarPlaceRequest, job_id: str)` from the start. The route here generates the uuid, returns it immediately, and passes it through to the background task. No mid-flight refactor needed.

- [ ] **Step 3: Add `resolve_ev_row_to_leg` and `get_orchestrator` helpers**

```python
# server/sidecar/resolve.py
"""Resolve an ev_row_id (canonical event+market+address) into a LegSpec.

Reads from the existing odds cache. The ev_row_id format matches what
/api/ev returns so the frontend can pass it back verbatim."""
from typing import Tuple

from server.sidecar.models import LegSpec


def resolve_ev_row_to_leg(ev_row_id: str) -> Tuple[LegSpec, float] | None:
    """Returns (LegSpec, kelly_full_pct) or None if the row is no longer in
    the cache."""
    # Implementation: look up the row in the odds cache by the canonical
    # (event_id, market_key, address) tuple-string. Map the cached fields
    # onto LegSpec. The kelly_full_pct comes from the same EV computation
    # used by /api/ev — extract it as a shared helper.
    ...
```

```python
# server/sidecar/factory.py
"""Singleton orchestrator builder. Imports config at first call only."""
from functools import lru_cache

from server.sidecar.placement import SidecarOrchestrator
from server.sidecar.mode_store import SidecarModeStore
from pathlib import Path


@lru_cache(maxsize=1)
def get_orchestrator() -> SidecarOrchestrator:
    mode_store = SidecarModeStore(Path("server/config/sidecar_mode.json"))
    return SidecarOrchestrator(
        pool_provider=_load_pool,           # reads from AccountsScraper cache
        placer_factory=_make_placer_factory(),
        mode=mode_store.get().value,
        db_path=Path("server/cache.db"),
    )


def _load_pool(): ...
def _make_placer_factory(): ...
```

- [ ] **Step 4: Add GET endpoints**

```python
def _audit_conn():
    """One sqlite3 connection per call, properly closed via context manager.
    Used by the read-only GET routes; the orchestrator opens its own."""
    import sqlite3
    return sqlite3.connect("server/cache.db")


@router.get("/runs")
def get_runs(limit: int = 100):
    from server.sidecar.audit import fetch_placements
    conn = _audit_conn()
    try:
        return [r.__dict__ for r in fetch_placements(conn, limit=limit)]
    finally:
        conn.close()


@router.get("/runs/{job_id}")
def get_run(job_id: str):
    from server.sidecar.audit import fetch_job
    conn = _audit_conn()
    try:
        rows = fetch_job(conn, job_id)
        if not rows:
            raise HTTPException(404)
        return [r.__dict__ for r in rows]
    finally:
        conn.close()


class ModeResponse(BaseModel):
    mode: str


class ModeBody(BaseModel):
    mode: str


@router.get("/mode", response_model=ModeResponse)
def get_mode():
    from server.sidecar.mode_store import SidecarModeStore
    from pathlib import Path
    return ModeResponse(
        mode=SidecarModeStore(Path("server/config/sidecar_mode.json")).get().value
    )


@router.post("/mode", response_model=ModeResponse)
def post_mode(body: ModeBody):
    from server.sidecar.mode_store import SidecarModeStore, SidecarMode
    from pathlib import Path
    store = SidecarModeStore(Path("server/config/sidecar_mode.json"))
    store.set(SidecarMode(body.mode))
    return ModeResponse(mode=store.get().value)
```

- [ ] **Step 5: Register router in `server/main.py`**

```python
from server.api.sidecar import router as sidecar_router
app.include_router(sidecar_router)
```

- [ ] **Step 6: Run tests + commit**

Run: `pytest server/tests/test_sidecar_api.py -v`

```bash
git add server/api/sidecar.py server/sidecar/resolve.py server/sidecar/factory.py server/main.py server/tests/test_sidecar_api.py
git commit -m "feat(sidecar): API endpoints — POST place, GET runs, GET/POST mode"
```

---

## Phase G — Frontend: /edges + confirm modal

### Task G1: Client-side splitter mirror

**Files:**
- Create: `web/lib/sidecar/splitter.ts`

Mirror the Python splitter byte-for-byte so the confirm modal can re-render the split-plan preview locally without round-tripping when the user changes the Kelly radio.

- [ ] **Step 1: Port the algorithm to TypeScript**

```typescript
// web/lib/sidecar/splitter.ts
export const FLOOR = 30;

export type SplitStatus = "planned" | "below_minimum" | "no_eligible_account" | "partial_fill";

export interface AccountSnapshot {
  customer_id: string;
  label?: string;
  available_balance: number;
  max_parlay_stake: number;
}

export interface SplitAssignment {
  account: AccountSnapshot;
  amount: number;
}

export interface SplitPlan {
  assignments: SplitAssignment[];
  status: SplitStatus;
  target: number;
  filled: number;
  unfilled: number;
}

export function planSplits(target: number, accounts: AccountSnapshot[]): SplitPlan {
  // Port of server/sidecar/splitter.py. Property tests in jest mirror the Python tests.
  ...
}
```

- [ ] **Step 2: Add jest tests mirroring the Python worked examples**

`web/lib/sidecar/__tests__/splitter.test.ts`:

```typescript
import { planSplits, FLOOR } from "../splitter";

const acct = (id: string, bal: number, cap = 100) => ({
  customer_id: id, available_balance: bal, max_parlay_stake: cap,
});

test("target 300, A=250, B=1000 → A:100 A:100 A:50 B:50", () => {
  const plan = planSplits(300, [acct("A", 250), acct("B", 1000)]);
  expect(plan.status).toBe("planned");
  expect(plan.assignments.map(a => [a.account.customer_id, a.amount]))
    .toEqual([["A", 100], ["A", 100], ["A", 50], ["B", 50]]);
});

// ... (repeat the seven other worked examples)
```

- [ ] **Step 3: Run tests + commit**

```bash
cd web && npm test -- splitter
git add web/lib/sidecar/
git commit -m "feat(web): client-side splitter mirror for live modal preview"
```

---

### Task G2: AutoPlaceButton component

**Files:**
- Create: `web/components/sidecar/AutoPlaceButton.tsx`

Compact button that appears at the end of /edges rows when the row meets the eligibility predicate (Coral33 best price + `wager_type ∈ {parlay, both}`).

- [ ] **Step 1: Implement the button**

```tsx
// web/components/sidecar/AutoPlaceButton.tsx
"use client";
import { useState } from "react";
import { ConfirmModal } from "./ConfirmModal";

interface Props {
  evRowId: string;
  // Plus everything the modal header needs (sport, market, side, price, EV%, fullKellyPct)
  ...
}

export function AutoPlaceButton(props: Props) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)} className="btn-compact">
        Auto-place
      </button>
      {open && <ConfirmModal {...props} onClose={() => setOpen(false)} />}
    </>
  );
}
```

- [ ] **Step 2: Inject the button into the /edges row component**

Find the EV-row component (probably `web/components/edges/*` or similar). Add the button conditionally where the eligibility predicate is true.

- [ ] **Step 3: Commit**

```bash
git add web/components/sidecar/AutoPlaceButton.tsx web/components/edges/
git commit -m "feat(web): AutoPlaceButton on Coral33 best-price parlay-eligible /edges rows"
```

---

### Task G3: ConfirmModal — Kelly radio, payout strip, split plan preview

**Files:**
- Create: `web/components/sidecar/ConfirmModal.tsx`

- [ ] **Step 1: Implement the modal scaffolding**

```tsx
// web/components/sidecar/ConfirmModal.tsx
"use client";
import { useState, useEffect } from "react";
import useSWR from "swr";

import { planSplits, KellyFraction } from "@/lib/sidecar/splitter";
import { useSidecarStream } from "@/lib/sidecar/useSidecarStream";

export function ConfirmModal({ evRowId, fullKellyPct, decimalOdds, onClose }) {
  const [fraction, setFraction] = useState<KellyFraction>("half");
  const { data: settings } = useSWR("/api/settings");
  const { data: accounts } = useSWR("/api/coral33/accounts");
  const { data: mode } = useSWR("/api/sidecar/mode");

  const bankroll = settings?.sidecar_bankroll ?? 10000;
  const target = Math.round(toFraction(fraction, fullKellyPct) * bankroll);
  const plan = accounts ? planSplits(target, accounts.map(toSnapshot)) : null;

  const twoTeamMultiplier = 2.6; // fetch once on mount via /api/sidecar/parlay-info or hardcode
  const expectedWin = target * decimalOdds * twoTeamMultiplier - target;

  const [jobId, setJobId] = useState<string | null>(null);
  const events = useSidecarStream(jobId);

  async function confirm() {
    const res = await fetch("/api/sidecar/place", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ev_row_id: evRowId, kelly_fraction: fraction }),
    });
    const body = await res.json();
    setJobId(body.job_id);
  }

  return (
    <div className="modal">
      <Header evRowId={evRowId} fraction={fraction} setFraction={setFraction} target={target} />
      <PayoutStrip target={target} expectedWin={expectedWin} />
      <PlanPreview plan={plan} />
      <Footer mode={mode?.mode} onConfirm={confirm} onClose={onClose}
              disabled={!plan || plan.status === "below_minimum" || plan.status === "no_eligible_account"} />
      {jobId && <ReceiptSequence events={events} expectedCount={plan!.assignments.length} />}
    </div>
  );
}
```

- [ ] **Step 2: Implement each sub-component as a typed primitive**

Header, PayoutStrip, PlanPreview, Footer, ReceiptSequence — each a small React component. Use the existing Bloomberg-terminal palette tokens.

- [ ] **Step 3: Commit**

```bash
git add web/components/sidecar/ConfirmModal.tsx web/lib/sidecar/useSidecarStream.ts
git commit -m "feat(web): ConfirmModal — kelly radio + payout strip + split plan preview"
```

---

## Phase H — Frontend: /sidecar dashboard

### Task H1: /sidecar route + layout

**Files:**
- Create: `web/app/sidecar/page.tsx`
- Modify: top-nav component to include /sidecar tab

- [ ] **Step 1: Implement the page**

```tsx
// web/app/sidecar/page.tsx
import { AccountPoolGrid } from "@/components/sidecar/AccountPoolGrid";
import { SignalFeed } from "@/components/sidecar/SignalFeed";
import { RunLog } from "@/components/sidecar/RunLog";
import { ModeToggle } from "@/components/sidecar/ModeToggle";

export default function SidecarPage() {
  return (
    <div className="page-grid sidecar-grid">
      <header className="sidecar-header">
        <h1>Sidecar</h1>
        <ModeToggle />
      </header>
      <SignalFeed className="left" />
      <AccountPoolGrid className="right" />
      <RunLog className="bottom" />
    </div>
  );
}
```

- [ ] **Step 2: Add /sidecar to the top-nav**

Modify the existing nav component to include the new tab between /edges and /accounts.

- [ ] **Step 3: Commit**

```bash
git add web/app/sidecar/ web/components/sidecar/
git commit -m "feat(web): /sidecar page scaffold with top-nav entry"
```

---

### Task H2: AccountPoolGrid

Each card shows customer_id, label, current/available balance, today's count + stake, last-used, proxy-status dot. Sorted by balance ascending.

- [ ] **Step 1: Implement the component**
- [ ] **Step 2: Wire to `/api/coral33/accounts` (existing endpoint)**
- [ ] **Step 3: Commit**

---

### Task H3: SignalFeed

Mirrors the existing /edges page filtered to `wager_filter=parlay&book=coral33&best_price=1`. Reuses the row component but injects the AutoPlaceButton inline.

- [ ] **Step 1: Reuse + filter**
- [ ] **Step 2: Commit**

---

### Task H4: RunLog with job grouping

Dense newest-first table. Rows sharing job_id get a subtle background tint and a "1/N, 2/N..." pill. Use `useSWR` to poll `/api/sidecar/runs` plus subscribe to `sidecar_placement` SSE to invalidate.

- [ ] **Step 1: Implement the table**
- [ ] **Step 2: SSE-driven invalidation**
- [ ] **Step 3: Commit**

---

## Phase I — Wiring + smoke

### Task I1: Force-refresh accounts after a job completes

**Files:**
- Modify: `server/sidecar/placement.py`

- [ ] **Step 1: After `handle_place` finishes its assignment loop, fire a refresh for every customer_id that was actually used**

```python
async def handle_place(self, req):
    ...
    used_accounts = {a.account.customer_id for a in plan.assignments}
    asyncio.create_task(self._refresh_accounts(used_accounts))
```

- [ ] **Step 2: Test + commit**

---

### Task I2: Dry-run smoke

- [ ] Open `http://localhost:3000/edges`, find a Coral33 best-price parlay-eligible row. Click Auto-place.
- [ ] Modal opens. Default Kelly = half. Verify target $ = round(0.5 × full_kelly_pct × 10000).
- [ ] Split plan preview matches what the splitter computes.
- [ ] Click Confirm. Receipt sequence shows N rows, each `dry_run`.
- [ ] Visit `/sidecar`. Run log has the rows grouped under one job_id.
- [ ] Inspect SQLite: `sqlite3 server/cache.db "SELECT * FROM sidecar_placements ORDER BY created_at DESC LIMIT 10"` — see the rows with `accepted_payload` populated with the would-be insertWagerParlay body.

### Task I3: Live smoke, single bet

- [ ] `POST /api/sidecar/mode` body `{"mode": "live"}` — flip to live.
- [ ] Set `CORAL33_PLACEMENT_LIVE=true` in `.env` and restart the server.
- [ ] Find a heavy underdog you're willing to risk $30 on. Click Auto-place.
- [ ] Confirm. Receipt shows one ticket #.
- [ ] On coral33.com web UI, log into the picked account (which one? Lowest balance.). Verify the new ticket is in Pending Wagers with "1 of 2 — 1 Open Spot".
- [ ] Wait for the 30-min wager-mirror tick. Verify the new wager lands in `bets` table.

### Task I4: Live smoke, multi-account split

- [ ] Configure one account with intentionally low balance (~$50). Find a row whose Kelly target with bankroll $10k × half exceeds $50.
- [ ] Click Auto-place. Confirm. Verify the receipt sequence shows two rows over ~5–10s wall time (the jitter gap).
- [ ] Two tickets land, on the lowest-balance and the next-lowest-balance accounts respectively.
- [ ] Both wager-mirror rows surface in `bets` table.

---

## Verification gates before merge

- [ ] `pytest server/tests -v` passes including all new sidecar tests.
- [ ] `cd web && npx tsc --noEmit && npm run build` passes.
- [ ] `cd web && npm test` passes (the splitter mirror jest tests).
- [ ] Dry-run smoke (Task I2) completes end-to-end through the UI.
- [ ] Live smoke single + multi-split (Tasks I3, I4) complete with verified ticket landing.
- [ ] No fixtures contain a real JWT — grep `server/tests/fixtures/coral33/placement/ -r -e "eyJ"` returns nothing.
- [ ] `CORAL33_ACCOUNTS` env shape lives in `.env` only; no proxy URLs or credentials in committed files.
