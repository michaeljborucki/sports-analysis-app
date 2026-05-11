# Coral33 Placement Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Coral33 placement client (preflight + straight + parlay) that is fully implemented and tested, but cannot place real bets without an explicit per-call flag AND an environment variable being set. The module exists, has byte-accurate HAR-verified payloads, but is **not wired into any API endpoint, scheduler, or call site** — fully isolated until the user says "plug it in."

**Architecture:**
- New module `server/odds/books/coral33/placement.py`. Mirrors the structure of the existing `accounts.py` (dataclasses + helpers + client in one file, ~400 LOC).
- Pure payload-builder functions are separated from the network-touching `Coral33Placer` class so payload shape can be tested against HAR fixtures without mocking HTTP.
- **Three-layer kill switch on `place_*` methods:**
  1. Per-call `live: bool = False` — defaults to dry-run
  2. Env gate `CORAL33_PLACEMENT_LIVE=true` — must be explicitly set
  3. No instance is constructed anywhere in the app (no API route, no scheduler hook). The class is dead code until imported in a future PR.
- Dry-run mode returns the payload that *would* have been sent, so callers can inspect/log/diff before going live.
- The `preflight()` method has no kill switch — it's a pure re-quote, no booking, safe to call. This is what we'll smoke-test against the live API.

**Tech Stack:** Python 3.11, `curl_cffi.requests.AsyncSession` (Chrome impersonation, already used in `client.py`), dataclasses, pytest with pytest-asyncio.

**HAR Reference:** `/Users/mikeborucki/Downloads/coral33.com.har` — captured 2026-04-30, contains real `checkWagerLineMulti` + `insertWagerStraight` + `insertWagerParlay` request/response pairs that are the ground truth for all payload tests.

---

## File Structure

```
server/odds/books/coral33/
├── placement.py                          # NEW — all placement logic
└── client.py                             # UNCHANGED — read-only client stays as-is

server/tests/
├── test_coral33_placement.py             # NEW — unit + payload-equivalence tests
└── fixtures/coral33/placement/           # NEW — HAR-extracted request/response pairs
    ├── preflight_straight.json
    ├── preflight_parlay.json
    ├── insert_straight.json
    └── insert_parlay.json

scripts/
└── coral33_preflight_smoke.py            # NEW — manual safe smoke test

docs/superpowers/plans/
└── 2026-04-30-coral33-placement.md       # this plan
```

**Why one file for placement.py:** mirrors `accounts.py` (552 LOC, same pattern: dataclasses + helpers + client class together). Splitting prematurely would scatter logic that always changes together.

**Why HAR fixtures live in the repo:** existing `test_coral33_normalizer.py` already follows this pattern at `server/tests/fixtures/coral33/`. Fixtures are scrubbed of JWT and cookies in Task 1 before commit.

---

## Task 1: Extract and scrub HAR fixtures

**Files:**
- Create: `server/tests/fixtures/coral33/placement/preflight_straight.json`
- Create: `server/tests/fixtures/coral33/placement/insert_straight.json`
- Create: `server/tests/fixtures/coral33/placement/preflight_parlay.json`
- Create: `server/tests/fixtures/coral33/placement/insert_parlay.json`
- Create (temporary, not committed): `scripts/_extract_har_fixtures.py`

Each fixture file is a JSON object: `{"request_form": {...parsed form fields...}, "response": {...parsed response body...}}`. Sensitive fields (`token`, `Authorization`) are replaced with `"<REDACTED_JWT>"`.

- [ ] **Step 1: Write the extractor script** (one-shot, gets deleted after fixtures land)

`scripts/_extract_har_fixtures.py`:
```python
"""One-shot: pull placement entries out of the dev HAR and scrub secrets.

Reads /Users/mikeborucki/Downloads/coral33.com.har, pulls the four placement
entries, parses form bodies, scrubs JWT tokens, and writes JSON fixtures
under server/tests/fixtures/coral33/placement/.
"""
from __future__ import annotations
import json
import urllib.parse
from pathlib import Path

HAR = Path("/Users/mikeborucki/Downloads/coral33.com.har")
OUT = Path(__file__).parent.parent / "server/tests/fixtures/coral33/placement"

# (entry_index, fixture_name) — verified against the captured HAR
ENTRIES = [
    (2,  "preflight_straight"),
    (3,  "insert_straight"),
    (20, "preflight_parlay"),
    (21, "insert_parlay"),
]

REDACTED_JWT = "<REDACTED_JWT>"


def scrub_form(form: dict) -> dict:
    if "token" in form:
        form["token"] = REDACTED_JWT
    return form


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    har = json.loads(HAR.read_text())
    entries = har["log"]["entries"]
    for idx, name in ENTRIES:
        e = entries[idx]
        form = dict(urllib.parse.parse_qsl(
            e["request"]["postData"]["text"], keep_blank_values=True
        ))
        # The `list` and `delay` fields are JSON-encoded — keep them as raw
        # strings in the fixture so byte-equivalence tests can compare exactly.
        scrub_form(form)
        response = json.loads(e["response"]["content"]["text"])
        out = {"request_form": form, "response": response}
        (OUT / f"{name}.json").write_text(json.dumps(out, indent=2))
        print(f"wrote {name}.json")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the extractor**

```bash
cd /Users/mikeborucki/personal_workspace/betting-site
python scripts/_extract_har_fixtures.py
```
Expected: prints `wrote preflight_straight.json` etc, four files appear under `server/tests/fixtures/coral33/placement/`.

- [ ] **Step 3: Verify fixtures are scrubbed**

```bash
grep -l 'eyJ' server/tests/fixtures/coral33/placement/*.json
```
Expected: no output (no leaked JWTs starting with `eyJ`).

- [ ] **Step 4: Delete the extractor**

```bash
rm scripts/_extract_har_fixtures.py
```
The script's job is done; we don't ship one-shot extractors.

- [ ] **Step 5: Commit**

```bash
git add server/tests/fixtures/coral33/placement/
git commit -m "test: add coral33 placement HAR fixtures (scrubbed)"
```

---

## Task 2: Dataclasses and constants

**Files:**
- Create: `server/odds/books/coral33/placement.py`
- Create: `server/tests/test_coral33_placement.py`

- [ ] **Step 1: Write the failing test for `Selection` dataclass**

`server/tests/test_coral33_placement.py`:
```python
"""Tests for the coral33 placement client.

Payload-builder tests load HAR-captured request bodies as ground truth and
assert byte-equivalent reproduction.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.odds.books.coral33.placement import Selection, BetType


FIXTURES = Path(__file__).parent / "fixtures" / "coral33" / "placement"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_selection_dataclass_holds_minimum_fields():
    sel = Selection(
        position=41535519,
        game_num=619105412,
        period_number=0,
        store="wiseguys",
        profile=".",
        period_type="Game",
        description="Basketball #511 Knicks -2½ -110 - For Game ",
        risk="5.5",
        win="5",
        bet_type=BetType.STRAIGHT,
    )
    assert sel.game_num == 619105412
    assert sel.bet_type is BetType.STRAIGHT
```

- [ ] **Step 2: Run test, expect ImportError**

```bash
cd /Users/mikeborucki/personal_workspace/betting-site
pytest server/tests/test_coral33_placement.py -v
```
Expected: `ModuleNotFoundError: No module named 'server.odds.books.coral33.placement'`

- [ ] **Step 3: Create the placement module skeleton**

`server/odds/books/coral33/placement.py`:
```python
"""Coral33 bet-placement client.

Reverse-engineered from a real placement HAR captured 2026-04-30. Endpoint
family is `/cloud/api/WagerSport/<operation>` over the same Bearer-JWT auth
and curl_cffi Chrome impersonation that powers the read-only client.

Placement is a two-step flow:
  1. POST checkWagerLineMulti — server re-quotes the line, returns a
     signed `delay` token (HMAC over time + secs).
  2. POST insertWagerStraight (or insertWagerParlay/Teaser/IfBet/Reverse/
     RoundRobinThin) with the same `delay` token verbatim. Server validates
     the signature; this is the anti-replay mechanism.

This module is **not connected** to any API route or background task. The
`place_*` methods require both a per-call `live=True` argument AND the
`CORAL33_PLACEMENT_LIVE=true` env var to actually POST. Otherwise they
return a `PlacementResult(dry_run=True, would_send=...)` so callers can
inspect the wire payload before going live.
"""
from __future__ import annotations

import enum
import os
from dataclasses import dataclass, field
from typing import Any


PLACEMENT_PATH = "WagerSport"
LIVE_ENV_VAR = "CORAL33_PLACEMENT_LIVE"


class BetType(enum.Enum):
    STRAIGHT = "S"
    PARLAY = "P"


@dataclass(frozen=True)
class Selection:
    """One leg the user wants to place. Built from a row in our normalized
    odds cache + the user's stake. All fields here are inputs the caller
    chooses; everything else (line type, decimal odds, game date, etc.)
    comes from the preflight response."""
    position: int           # arbitrary client ref, echoed in response
    game_num: int           # GameNum from Get_LeagueLines2
    period_number: int      # 0 = Game, 1 = 1H, etc.
    store: str              # accountInfo.Store, untrimmed
    profile: str            # accountInfo.CustProfile, untrimmed
    period_type: str        # "Game" / "1st Half" / etc.
    description: str        # Display text, sent verbatim
    risk: str               # Stake in dollars, as string
    win: str                # Win amount, as string
    bet_type: BetType
    contestant_num: int = 0
    status: str = "O"       # "O" = open
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest server/tests/test_coral33_placement.py::test_selection_dataclass_holds_minimum_fields -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/coral33/placement.py server/tests/test_coral33_placement.py
git commit -m "feat(coral33): scaffold placement module with Selection dataclass"
```

---

## Task 3: Preflight payload builder

**Files:**
- Modify: `server/odds/books/coral33/placement.py`
- Modify: `server/tests/test_coral33_placement.py`

- [ ] **Step 1: Write the failing payload-equivalence test**

Add to `test_coral33_placement.py`:
```python
import urllib.parse

from server.odds.books.coral33.placement import build_preflight_form


def test_preflight_straight_payload_matches_har():
    """The preflight form for the straight bet must reproduce the captured
    HAR request byte-for-byte (modulo the redacted JWT)."""
    fixture = _load("preflight_straight")
    expected = fixture["request_form"]
    expected_list = json.loads(expected["list"])

    sel = Selection(
        position=expected_list[0]["position"],
        game_num=619105412,
        period_number=0,
        store="wiseguys",
        profile=".",
        period_type="Game",
        description="Basketball #511 Knicks -2&#189; -110 - For Game ",
        risk="5.5",
        win="5",
        bet_type=BetType.STRAIGHT,
    )
    form = build_preflight_form(
        selections=[sel],
        customer_id="VR12509",
        token="<REDACTED_JWT>",
    )

    # `list` is JSON-encoded; compare parsed
    assert json.loads(form["list"]) == expected_list
    # All other form fields exactly match
    for key in ("token", "customerID", "operation", "RRO", "agentSite"):
        assert form[key] == expected[key], f"{key} mismatch"


def test_preflight_parlay_payload_matches_har():
    fixture = _load("preflight_parlay")
    expected = fixture["request_form"]
    expected_list = json.loads(expected["list"])
    sel = Selection(
        position=expected_list[0]["position"],
        game_num=619105412,
        period_number=0,
        store="wiseguys",
        profile=".",
        period_type="Game",
        description="Basketball #511 Knicks -2&#189; -110 - For Game ",
        risk="5",
        win="13.00",
        bet_type=BetType.PARLAY,
    )
    form = build_preflight_form(
        selections=[sel],
        customer_id="VR12509",
        token="<REDACTED_JWT>",
    )
    assert json.loads(form["list"]) == expected_list
    for key in ("token", "customerID", "operation", "RRO", "agentSite"):
        assert form[key] == expected[key]
```

- [ ] **Step 2: Run tests, expect ImportError**

```bash
pytest server/tests/test_coral33_placement.py -v
```
Expected: `ImportError: cannot import name 'build_preflight_form'`

- [ ] **Step 3: Implement `build_preflight_form`**

Add to `placement.py`:
```python
import json

# customerID is space-padded to 10 chars on the hot path. The server's SQL
# column is CHAR(10); unpadded values are rejected on some endpoints.
_CUSTOMER_ID_WIDTH = 10


def _pad_customer_id(cid: str) -> str:
    cid = cid.strip()
    return cid + " " * max(0, _CUSTOMER_ID_WIDTH - len(cid))


def build_preflight_form(
    *,
    selections: list[Selection],
    customer_id: str,
    token: str,
) -> dict[str, str]:
    """Build the form-encoded body for `checkWagerLineMulti`.

    Source of truth: HAR entry 2 (straight) and 20 (parlay) captured
    2026-04-30 — see `server/tests/fixtures/coral33/placement/`.
    """
    selection_list = [
        {
            "position": s.position,
            "gameNum": s.game_num,
            "contestantNum": s.contestant_num,
            "periodNumber": s.period_number,
            "store": s.store,
            "status": s.status,
            "profile": s.profile,
            "periodType": s.period_type,
            "description": s.description,
            "risk": s.risk,
            "win": s.win,
            "wagerType": s.bet_type.value,
        }
        for s in selections
    ]
    return {
        "list": json.dumps(selection_list),
        "token": token,
        "customerID": _pad_customer_id(customer_id),
        "operation": "checkWagerLineMulti",
        "RRO": "0",
        "agentSite": "0",
    }
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pytest server/tests/test_coral33_placement.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/coral33/placement.py server/tests/test_coral33_placement.py
git commit -m "feat(coral33): preflight payload builder, HAR-verified"
```

---

## Task 4: Preflight response parser → `LineQuote`

**Files:**
- Modify: `server/odds/books/coral33/placement.py`
- Modify: `server/tests/test_coral33_placement.py`

- [ ] **Step 1: Write the failing test**

Add to `test_coral33_placement.py`:
```python
from server.odds.books.coral33.placement import (
    parse_preflight_response, LineQuote, DelayToken,
)


def test_parse_preflight_straight_returns_quotes_and_delay():
    fixture = _load("preflight_straight")
    quotes, delay = parse_preflight_response(fixture["response"])

    assert isinstance(delay, DelayToken)
    assert delay.time == 1777587219
    assert delay.secs == 0
    assert delay.sig == "uTAQxbwAGBPhjFjg3A1xxD9t54zfG0Vqf29d6FKBDqU"

    assert len(quotes) == 1
    q = quotes[0]
    assert isinstance(q, LineQuote)
    assert q.position == 41535519
    assert q.game_num == 619105412
    assert q.spread == -2.5
    assert q.spread_adj_1 == -110
    assert q.team1_id == "New York Knicks"
    assert q.team2_id == "Atlanta Hawks"
    # Trailing-space padding from the wire is preserved verbatim
    assert q.sport_type == "Basketball          "
    assert q.sport_sub_type == "NBA         "
    assert q.store == "wiseguys            "
    assert q.cust_profile == ".                   "
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest server/tests/test_coral33_placement.py::test_parse_preflight_straight_returns_quotes_and_delay -v
```

- [ ] **Step 3: Implement `LineQuote`, `DelayToken`, `parse_preflight_response`**

Add to `placement.py`:
```python
@dataclass(frozen=True)
class DelayToken:
    """HMAC-signed continuation token. Returned by checkWagerLineMulti and
    passed verbatim to the placement call as the anti-replay token."""
    time: int
    secs: int
    sig: str

    def to_json(self) -> str:
        return json.dumps({"time": self.time, "secs": self.secs, "sig": self.sig})


@dataclass(frozen=True)
class LineQuote:
    """Server-quoted line returned by checkWagerLineMulti. Field padding
    (trailing spaces) is preserved verbatim — the placement payload must
    echo padded values back, since some are CHAR(N) on the SQL side."""
    position: int           # echoed from request, used to correlate
    game_num: int
    line_seq: int
    game_datetime: str      # "YYYY-MM-DD HH:MM:SS.fff"
    status: str
    team1_id: str
    team2_id: str
    team1_rot_num: int
    team2_rot_num: int
    favored_team_id: str | None
    spread: float | None
    spread_adj_1: int | None
    spread_decimal_1: float | None
    spread_numerator_1: int | None
    spread_denominator_1: int | None
    money_line_1: int | None
    money_line_decimal_1: float | None
    total_points: float | None
    period_wager_cutoff: str
    sport_type: str          # padded
    sport_sub_type: str      # padded
    period_description: str
    period_number: int
    store: str               # padded
    cust_profile: str        # padded
    schedule_date: str
    parlay_restriction: str | None
    short_name_1: str | None
    short_name_2: str | None
    raw: dict[str, Any] = field(repr=False)  # full server row, for fields we don't model


def parse_preflight_response(
    response: dict[str, Any],
) -> tuple[list[LineQuote], DelayToken]:
    """Decode the response from checkWagerLineMulti."""
    raw_quotes = response.get("LIST") or []
    quotes = [
        LineQuote(
            position=r["position"],
            game_num=r["GameNum"],
            line_seq=r.get("LineSeq", 0),
            game_datetime=r.get("GameDateTime", ""),
            status=r.get("Status", ""),
            team1_id=r.get("Team1ID", ""),
            team2_id=r.get("Team2ID", ""),
            team1_rot_num=r.get("Team1RotNum", 0),
            team2_rot_num=r.get("Team2RotNum", 0),
            favored_team_id=r.get("FavoredTeamID"),
            spread=r.get("Spread"),
            spread_adj_1=r.get("SpreadAdj1"),
            spread_decimal_1=r.get("SpreadDecimal1"),
            spread_numerator_1=r.get("SpreadNumerator1"),
            spread_denominator_1=r.get("SpreadDenominator1"),
            money_line_1=r.get("MoneyLine1"),
            money_line_decimal_1=r.get("MoneyLineDecimal1"),
            total_points=r.get("TotalPoints"),
            period_wager_cutoff=r.get("PeriodWagerCutoff", ""),
            sport_type=r.get("SportType", ""),
            sport_sub_type=r.get("SportSubType", ""),
            period_description=r.get("PeriodDescription", ""),
            period_number=r.get("PeriodNumber", 0),
            store=r.get("Store", ""),
            cust_profile=r.get("CustProfile", ""),
            schedule_date=r.get("ScheduleDate", ""),
            parlay_restriction=r.get("ParlayRestriction"),
            short_name_1=r.get("ShortName1"),
            short_name_2=r.get("ShortName2"),
            raw=r,
        )
        for r in raw_quotes
    ]
    delay_raw = response.get("DELAY") or {}
    delay = DelayToken(
        time=int(delay_raw.get("time", 0)),
        secs=int(delay_raw.get("secs", 0)),
        sig=str(delay_raw.get("sig", "")),
    )
    return quotes, delay
```

- [ ] **Step 4: Run, expect PASS**

```bash
pytest server/tests/test_coral33_placement.py -v
```

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/coral33/placement.py server/tests/test_coral33_placement.py
git commit -m "feat(coral33): parse preflight response into LineQuote + DelayToken"
```

---

## Task 5: Straight placement payload builder

**Files:**
- Modify: `server/odds/books/coral33/placement.py`
- Modify: `server/tests/test_coral33_placement.py`

The straight-placement form has two layers: (a) top-level form fields (`customerID`, `agentView`, `operation`, `agToken`, `delay`, `agentSite`, `list`) and (b) inside `list`, a fat wager object with ~45 fields covering line, stake, account, and sub-`wager` block.

We need a `PlacementContext` dataclass that bundles the read-only inputs (account info + chosen team + price selection) so the builder is pure.

- [ ] **Step 1: Write the failing test**

Add to `test_coral33_placement.py`:
```python
from server.odds.books.coral33.placement import (
    build_straight_form, PlacementContext, ChosenSide,
)


def test_straight_placement_payload_matches_har():
    """The straight insertWager form must reproduce the captured HAR
    request body exactly, given the same inputs."""
    pre_fixture = _load("preflight_straight")
    placement_fixture = _load("insert_straight")
    expected = placement_fixture["request_form"]
    expected_list = json.loads(expected["list"])
    expected_leg = expected_list[0]

    quotes, delay = parse_preflight_response(pre_fixture["response"])
    quote = quotes[0]

    sel = Selection(
        position=quote.position,
        game_num=quote.game_num,
        period_number=0,
        store="wiseguys",
        profile=".",
        period_type="Game",
        description="Basketball #511 Knicks -2&#189; -110 - For Game ",
        risk="5.5",
        win="5",
        bet_type=BetType.STRAIGHT,
    )
    ctx = PlacementContext(
        customer_id="VR12509",
        agent_id="TYSONR",
        office="LEOOFFICE",
        currency_code="USD",
        percent_book=100,
        credit_acct_flag="Y",
        baseball_action_fixed=False,
        chosen=ChosenSide(
            team_id="New York Knicks",
            line_type="S",          # spread
            adj_spread="-2.5",
            adj_total=0,
            price_type="A",
            final_money=-110,
            final_decimal=1.9091,
            final_numerator=10,
            final_denominator=11,
            orig_price=-110,
            orig_decimal=1.9091,
            orig_numerator=10,
            orig_denominator=11,
            orig_spread="-2.5",
            orig_total="-2.5",
            orig_money=-110,
        ),
        doc_num=92657540,
        date="2026-04-30",
    )
    form = build_straight_form(
        selection=sel,
        quote=quote,
        context=ctx,
        delay=delay,
        risk_amount=5.5,
        win_amount=5,
    )

    # Compare top-level form fields exactly
    for key in ("customerID", "agentView", "operation", "agToken",
                "delay", "agentSite"):
        assert form[key] == expected[key], f"top-level {key} mismatch"
    # Compare the leg payload field-by-field for clearer diffs on failure
    actual_leg = json.loads(form["list"])[0]
    for key in expected_leg:
        assert actual_leg[key] == expected_leg[key], (
            f"leg field {key!r}: expected {expected_leg[key]!r}, "
            f"got {actual_leg.get(key)!r}"
        )
    assert set(actual_leg.keys()) == set(expected_leg.keys()), \
        f"unexpected keys: {set(actual_leg) ^ set(expected_leg)}"
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest server/tests/test_coral33_placement.py::test_straight_placement_payload_matches_har -v
```

- [ ] **Step 3: Implement `ChosenSide`, `PlacementContext`, `build_straight_form`**

Add to `placement.py`:
```python
@dataclass(frozen=True)
class ChosenSide:
    """The user's pick for a single leg — which team, which market, the
    price the user expects to get. Decoupled from the quote so the caller
    can decide which side/market to take from the LineQuote."""
    team_id: str            # "New York Knicks" — match LineQuote.team1_id/team2_id
    line_type: str          # "S" spread, "M" moneyline, "T" total, etc.
    adj_spread: str | int   # signed line as string ("-2.5") or 0
    adj_total: float | int
    price_type: str         # "A" American, "D" Decimal, "F" Fractional
    final_money: int        # American odds at placement
    final_decimal: float
    final_numerator: int
    final_denominator: int
    orig_price: int         # original price before any line move
    orig_decimal: float
    orig_numerator: int
    orig_denominator: int
    orig_spread: str | int
    orig_total: str | int
    orig_money: int


@dataclass(frozen=True)
class PlacementContext:
    """Account + agent context that's the same across every leg of a
    placement. All from accountInfo (getAccountInfo response) except
    `chosen`, `doc_num`, `date`."""
    customer_id: str
    agent_id: str
    office: str
    currency_code: str
    percent_book: int
    credit_acct_flag: str          # "Y" / "N"
    baseball_action_fixed: bool    # accountInfo.BaseballAction === FIXED
    chosen: ChosenSide
    doc_num: int                   # client-side wager nonce
    date: str                      # "YYYY-MM-DD"


def _build_straight_leg(
    sel: Selection,
    quote: LineQuote,
    ctx: PlacementContext,
    risk_amount: float,
    win_amount: float,
) -> dict[str, Any]:
    """Build the fat per-leg dict for `insertWagerStraight`. Mirrors the
    HAR-captured shape exactly — see fixtures/coral33/placement/insert_straight.json."""
    chosen = ctx.chosen
    odds_flag = "N" if ctx.baseball_action_fixed else "N"
    pitcher1_flag = "N" if ctx.baseball_action_fixed else "Y"
    pitcher2_flag = "N" if ctx.baseball_action_fixed else "Y"
    return {
        "customerID": _pad_customer_id(ctx.customer_id),
        "docNum": ctx.doc_num,
        "wagerType": "S",
        "gameNum": sel.game_num,
        "wagerCount": 1,
        "gameDate": quote.game_datetime.replace("19:", "17:") if False else quote.game_datetime,
        # NOTE: HAR shows gameDate as "2026-04-30 17:00:01.000" (Eastern? local?)
        # while preflight returned "2026-04-30 19:00:01.000" (UTC). Caller
        # must pass the local-time variant the server expects. For now we
        # mirror the wire shape; revisit if the server rejects.
        "buyingFlag": "N",
        "extraGames": None,
        "sportType": quote.sport_type,
        "sportSubType": quote.sport_sub_type,
        "lineType": chosen.line_type,
        "adjSpread": chosen.adj_spread,
        "adjTotal": chosen.adj_total,
        "priceType": chosen.price_type,
        "finalMoney": chosen.final_money,
        "finalDecimal": chosen.final_decimal,
        "finalNumerator": chosen.final_numerator,
        "finalDenominator": chosen.final_denominator,
        "chosenTeamID": chosen.team_id,
        "riskAmount": risk_amount,
        "winAmount": win_amount,
        "store": quote.store,
        "office": ctx.office,
        "custProfile": quote.cust_profile,
        "periodNumber": sel.period_number,
        "periodDescription": sel.period_type,
        "oddsFlag": odds_flag,
        "listedPitcher1": None,
        "pitcher1ReqFlag": pitcher1_flag,
        "listedPitcher2": None,
        "pitcher2ReqFlag": pitcher2_flag,
        "percentBook": ctx.percent_book,
        "volumeAmount": int(round(risk_amount * 100)),
        "currencyCode": ctx.currency_code,
        "date": ctx.date,
        "agentID": ctx.agent_id,
        "easternLine": 0,
        "origPrice": chosen.orig_price,
        "origDecimal": chosen.orig_decimal,
        "origNumerator": chosen.orig_numerator,
        "origDenominator": chosen.orig_denominator,
        "creditAcctFlag": ctx.credit_acct_flag,
        "wager": {
            "date": ctx.date,
            "minPicks": 1,
            "totalPicks": 1,
            "maxPayOut": 0,
            "wagerCount": 1,
            "riskAmount": str(risk_amount) if isinstance(risk_amount, float) and risk_amount != int(risk_amount) else str(risk_amount),
            # NOTE: HAR shows riskAmount/winAmount as strings inside
            # `wager` ("5.5"/"5") but as numbers at the top level (5.5/5).
            # We mirror that.
            "winAmount": str(win_amount) if isinstance(win_amount, float) and win_amount != int(win_amount) else str(int(win_amount)) if isinstance(win_amount, (int, float)) else str(win_amount),
            "description": sel.description.rstrip(),  # HAR: trailing space stripped in `wager.description` only
            "lineType": "S",
            "team": 1,
            "freePlay": "N",
            "agentID": ctx.agent_id,
            "currencyCode": ctx.currency_code,
            "creditAcctFlag": ctx.credit_acct_flag,
            "playNumber": 1,
        },
        "itemNumber": 1,
        "wagerNumber": 0,
        "origSpread": chosen.orig_spread,
        "origTotal": chosen.orig_total,
        "origMoney": chosen.orig_money,
        "extra": {
            "team1": quote.team1_id,
            "team2": quote.team2_id,
            "rot1": quote.team1_rot_num,
            "rot2": quote.team2_rot_num,
            "line": _format_line_summary(chosen),
            "buy": False,
            "point": 0,
        },
        "status": "O",
        "printing": False,
    }


def _format_line_summary(chosen: ChosenSide) -> str:
    """Render the chosen line as the UI-style summary string the server
    echoes into the ticket (e.g. '-2½ -110')."""
    spread = chosen.adj_spread
    if isinstance(spread, str):
        try:
            f = float(spread)
        except ValueError:
            f = 0.0
    else:
        f = float(spread)
    # HAR shows '-2½' for -2.5; we approximate by checking for .5
    int_part = int(f)
    frac = abs(f - int_part)
    if abs(frac - 0.5) < 1e-6:
        sign = "-" if f < 0 else "+"
        spread_str = f"{sign}{abs(int_part)}½"
    else:
        spread_str = f"{f:+g}"
    return f"{spread_str} {chosen.final_money}"


def build_straight_form(
    *,
    selection: Selection,
    quote: LineQuote,
    context: PlacementContext,
    delay: DelayToken,
    risk_amount: float,
    win_amount: float,
) -> dict[str, str]:
    """Build the form-encoded body for `insertWagerStraight`.

    Source of truth: HAR fixture `insert_straight.json`.
    """
    leg = _build_straight_leg(selection, quote, context, risk_amount, win_amount)
    return {
        "customerID": _pad_customer_id(context.customer_id),
        "list": json.dumps([leg]),
        "agentView": "false",
        "operation": "insertWagerStraight",
        "agToken": "",
        "delay": delay.to_json(),
        "agentSite": "0",
    }
```

- [ ] **Step 4: Run test, debug field mismatches**

```bash
pytest server/tests/test_coral33_placement.py::test_straight_placement_payload_matches_har -v
```
Expected: PASS. If the assertion shows specific field mismatches, iterate by reading the HAR fixture and adjusting `_build_straight_leg`. **Do not skip this debug loop** — the goal is byte-equivalence with HAR. Likely mismatches:
- **`volumeAmount`**: HAR shows `500` for both bets despite different risk amounts (straight: $5.50, parlay: $5). This is NOT `risk * 100`. The JS source `i.getVolumenAmount` takes both risk + win; formula appears to be tied to win amount or a minimum-volume floor. Try `int(round(win_amount * 100))` first, then a `max(risk_amount * 100, win_amount * 100)` floor.
- **`description` trimming**: HAR's top-level `description` keeps trailing space; `wager.description` strips it for straight but **preserves it** for parlay (note the asymmetry).
- **`gameDate` timezone**: HAR's `gameDate` is `17:00:01.000` while preflight's `GameDateTime` is `19:00:01.000` — differs by 2hr (probably UTC vs ET). Caller may need to pre-shift, or the server may be tolerant. Try passing through unchanged first.
- **Numeric `riskAmount`/`winAmount` inside `wager`**: HAR shows them as strings (`"5.5"`, `"5"`), but at the top level they're numbers (`5.5`, `5`). The conditional formatting in `_build_straight_leg` is brittle — simplify to plain `str(risk_amount)` and `str(win_amount)` if needed.

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/coral33/placement.py server/tests/test_coral33_placement.py
git commit -m "feat(coral33): straight placement payload builder, HAR-verified"
```

---

## Task 6: Parlay placement payload builder

**Files:**
- Modify: `server/odds/books/coral33/placement.py`
- Modify: `server/tests/test_coral33_placement.py`

The parlay differs from straight in three ways:
1. Operation name (`insertWagerParlay`)
2. The `wager` sub-object has parlay-specific fields: `lineType: "P"`, `parlayName`, `parlayPayOutType`, `openSpotFlag`, `roundRobin`, `update`
3. Top-level `office` is **absent**, `extraGames` is absent, `printing` is absent
4. Adds top-level `roundRobin` and `wagerNumber: 1` (vs `0` for straight)

The HAR captured a 1-leg open parlay (`openSpotFlag: "O"`). For now, mirror that structure; multi-leg parlays will follow the same pattern with one entry per leg.

- [ ] **Step 1: Write the failing test**

Add to `test_coral33_placement.py`:
```python
from server.odds.books.coral33.placement import build_parlay_form, ParlaySpec


def test_parlay_placement_payload_matches_har():
    pre_fixture = _load("preflight_parlay")
    placement_fixture = _load("insert_parlay")
    expected = placement_fixture["request_form"]
    expected_list = json.loads(expected["list"])
    expected_leg = expected_list[0]

    quotes, delay = parse_preflight_response(pre_fixture["response"])
    quote = quotes[0]

    sel = Selection(
        position=quote.position,
        game_num=quote.game_num,
        period_number=0,
        store="wiseguys",
        profile=".",
        period_type="Game",
        description="Basketball #511 Knicks -2&#189; -110 - For Game ",
        risk="5",
        win="13.00",
        bet_type=BetType.PARLAY,
    )
    ctx = PlacementContext(
        customer_id="VR12509",
        agent_id="TYSONR",
        office="LEOOFFICE",
        currency_code="USD",
        percent_book=100,
        credit_acct_flag="Y",
        baseball_action_fixed=False,
        chosen=ChosenSide(
            team_id="New York Knicks",
            line_type="S",
            adj_spread="-2.5",
            adj_total=0,
            price_type="A",
            final_money=-110,
            final_decimal=1.9091,
            final_numerator=10,
            final_denominator=11,
            orig_price=-110,
            orig_decimal=1.9091,
            orig_numerator=10,
            orig_denominator=11,
            orig_spread="-2.5",
            orig_total="-2.5",
            orig_money=-110,
        ),
        doc_num=531210,
        date="2026-04-30",
    )
    spec = ParlaySpec(
        total_picks=2,
        min_picks=1,
        risk_amount=5,
        win_amount="13.00",
        parlay_name="10 team                  ",
        parlay_payout_type="R",
        open_spot_flag="O",
        max_payout=1000000,
    )
    form = build_parlay_form(
        selections=[sel],
        quotes=[quote],
        context=ctx,
        spec=spec,
        delay=delay,
    )

    for key in ("customerID", "agentView", "operation", "agToken",
                "delay", "agentSite"):
        assert form[key] == expected[key], f"top-level {key} mismatch"
    actual_leg = json.loads(form["list"])[0]
    for key in expected_leg:
        assert actual_leg[key] == expected_leg[key], (
            f"leg field {key!r}: expected {expected_leg[key]!r}, "
            f"got {actual_leg.get(key)!r}"
        )
    assert set(actual_leg.keys()) == set(expected_leg.keys())
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest server/tests/test_coral33_placement.py::test_parlay_placement_payload_matches_har -v
```

- [ ] **Step 3: Implement `ParlaySpec` and `build_parlay_form`**

Add to `placement.py`:
```python
@dataclass(frozen=True)
class ParlaySpec:
    """Parlay-level metadata. Most fields come from coral33's
    `getParlaySpecs` / `getInfoParlay` calls (the UI fetches these before
    building the slip). For 1-leg open parlays, `total_picks` can exceed
    the leg count — server holds the slot open."""
    total_picks: int
    min_picks: int
    risk_amount: float
    win_amount: str | float        # HAR shows string ("13.00")
    parlay_name: str               # padded, e.g. "10 team                  "
    parlay_payout_type: str        # "R" rotation, "F" fixed
    open_spot_flag: str            # "O" open, "C" closed
    max_payout: int


def _build_parlay_leg(
    sel: Selection,
    quote: LineQuote,
    ctx: PlacementContext,
    spec: ParlaySpec,
    leg_index: int,
) -> dict[str, Any]:
    chosen = ctx.chosen
    pitcher1_flag = "N" if ctx.baseball_action_fixed else "Y"
    pitcher2_flag = "N" if ctx.baseball_action_fixed else "Y"
    odds_flag = "N"
    return {
        "customerID": _pad_customer_id(ctx.customer_id),
        "docNum": ctx.doc_num,
        "wagerType": "P",
        "gameNum": sel.game_num,
        "wagerCount": 1,
        "gameDate": quote.game_datetime,
        "sportType": quote.sport_type,
        "sportSubType": quote.sport_sub_type,
        "lineType": chosen.line_type,
        "adjSpread": chosen.adj_spread,
        "adjTotal": chosen.adj_total,
        "priceType": chosen.price_type,
        "finalMoney": chosen.final_money,
        "finalDecimal": chosen.final_decimal,
        "finalNumerator": chosen.final_numerator,
        "finalDenominator": chosen.final_denominator,
        "chosenTeamID": chosen.team_id,
        "riskAmount": spec.risk_amount,
        # On parlay legs, winAmount is the per-leg straight-equivalent
        # win, NOT the parlay payout. HAR: 4.545454545454545 for -110.
        "winAmount": _decimal_win(spec.risk_amount, chosen.final_decimal),
        "store": quote.store,
        "custProfile": quote.cust_profile,
        "periodNumber": sel.period_number,
        "periodDescription": sel.period_type,
        "oddsFlag": odds_flag,
        "listedPitcher1": None,
        "pitcher1ReqFlag": pitcher1_flag,
        "listedPitcher2": None,
        "pitcher2ReqFlag": pitcher2_flag,
        "percentBook": ctx.percent_book,
        "volumeAmount": int(round(spec.risk_amount * 100)),
        "currencyCode": ctx.currency_code,
        "date": ctx.date,
        "agentID": ctx.agent_id,
        "easternLine": 0,
        "origPrice": chosen.orig_price,
        "origDecimal": chosen.orig_decimal,
        "origNumerator": chosen.orig_numerator,
        "origDenominator": chosen.orig_denominator,
        "creditAcctFlag": ctx.credit_acct_flag,
        "wager": {
            "date": ctx.date,
            "minPicks": spec.min_picks,
            "totalPicks": spec.total_picks,
            "wagerCount": 1,
            "riskAmount": spec.risk_amount,
            "winAmount": spec.win_amount,
            "description": sel.description.rstrip() + " ",  # HAR: trailing space restored
            "lineType": "P",
            "freePlay": "N",
            "agentID": ctx.agent_id,
            "currencyCode": ctx.currency_code,
            "creditAcctFlag": ctx.credit_acct_flag,
            "playNumber": leg_index + 1,
            "roundRobin": 0,
            "parlayName": spec.parlay_name,
            "openSpotFlag": spec.open_spot_flag,
            "parlayPayOutType": spec.parlay_payout_type,
            "maxPayOut": spec.max_payout,
            "update": False,
            "team": 1,
        },
        "itemNumber": 1,
        "wagerNumber": leg_index + 1,
        "origSpread": chosen.orig_spread,
        "origTotal": chosen.orig_total,
        "origMoney": chosen.orig_money,
        "roundRobin": "0",
        "extra": {
            "team1": quote.team1_id,
            "team2": quote.team2_id,
            "rot1": quote.team1_rot_num,
            "rot2": quote.team2_rot_num,
            "line": _format_line_summary(chosen),
            "buy": False,
            "point": 0,
        },
        "status": "O",
    }


def _decimal_win(risk: float, decimal_odds: float) -> float:
    """Per-leg straight-equivalent win for parlay legs. HAR shows full
    Python-float precision (4.545454545454545), so no rounding here."""
    return risk * (decimal_odds - 1)


def build_parlay_form(
    *,
    selections: list[Selection],
    quotes: list[LineQuote],
    context: PlacementContext,
    spec: ParlaySpec,
    delay: DelayToken,
) -> dict[str, str]:
    """Build the form-encoded body for `insertWagerParlay`.

    Note: callers building multi-leg parlays must pass `selections` and
    `quotes` aligned by index. `context.chosen` covers the *current* leg —
    for multi-leg, this builder needs a per-leg ChosenSide; that's a
    Phase-2 extension since the captured HAR is single-leg.
    """
    if len(selections) != len(quotes):
        raise ValueError("selections and quotes length mismatch")
    if len(selections) > 1:
        raise NotImplementedError(
            "Multi-leg parlays require per-leg ChosenSide — captured HAR "
            "is single-leg only. Add coverage before enabling."
        )
    legs = [
        _build_parlay_leg(s, q, context, spec, i)
        for i, (s, q) in enumerate(zip(selections, quotes))
    ]
    return {
        "customerID": _pad_customer_id(context.customer_id),
        "list": json.dumps(legs),
        "agentView": "false",
        "operation": "insertWagerParlay",
        "agToken": "",
        "delay": delay.to_json(),
        "agentSite": "0",
    }
```

- [ ] **Step 4: Run test, debug field mismatches**

```bash
pytest server/tests/test_coral33_placement.py::test_parlay_placement_payload_matches_har -v
```

- [ ] **Step 5: Commit**

```bash
git add server/odds/books/coral33/placement.py server/tests/test_coral33_placement.py
git commit -m "feat(coral33): parlay placement payload builder, HAR-verified"
```

---

## Task 7: `Coral33Placer` class with kill switch

**Files:**
- Modify: `server/odds/books/coral33/placement.py`
- Modify: `server/tests/test_coral33_placement.py`

This is the network-touching layer. It composes the existing `Coral33Client` (for auth + transport) with our new payload builders. The `place_*` methods enforce the dual gate:
- `live=True` argument
- `CORAL33_PLACEMENT_LIVE=true` env var

If either is missing, returns a `PlacementResult(dry_run=True, would_send=...)` so callers can inspect the wire payload.

- [ ] **Step 1: Write failing tests for the kill switch**

Add to `test_coral33_placement.py`:
```python
from unittest.mock import AsyncMock, patch

from server.odds.books.coral33.placement import (
    Coral33Placer, PlacementResult, PlacementBlockedError,
)


@pytest.fixture
def placer():
    """Build a Placer with a mock client. Tests can override `_post_form`."""
    mock_client = AsyncMock()
    mock_client.customer_id = "VR12509"
    return Coral33Placer(client=mock_client)


@pytest.mark.asyncio
async def test_place_straight_dry_run_returns_payload_without_post(placer):
    pre_fixture = _load("preflight_straight")
    placement_fixture = _load("insert_straight")
    quotes, delay = parse_preflight_response(pre_fixture["response"])
    sel = Selection(
        position=quotes[0].position, game_num=quotes[0].game_num,
        period_number=0, store="wiseguys", profile=".",
        period_type="Game",
        description="Basketball #511 Knicks -2&#189; -110 - For Game ",
        risk="5.5", win="5", bet_type=BetType.STRAIGHT,
    )
    ctx = PlacementContext(
        customer_id="VR12509", agent_id="TYSONR", office="LEOOFFICE",
        currency_code="USD", percent_book=100, credit_acct_flag="Y",
        baseball_action_fixed=False,
        chosen=ChosenSide(
            team_id="New York Knicks", line_type="S", adj_spread="-2.5",
            adj_total=0, price_type="A", final_money=-110,
            final_decimal=1.9091, final_numerator=10, final_denominator=11,
            orig_price=-110, orig_decimal=1.9091, orig_numerator=10,
            orig_denominator=11, orig_spread="-2.5", orig_total="-2.5",
            orig_money=-110,
        ),
        doc_num=92657540, date="2026-04-30",
    )

    result = await placer.place_straight(
        selection=sel, quote=quotes[0], context=ctx, delay=delay,
        risk_amount=5.5, win_amount=5,
        live=False,  # ← dry-run
    )
    assert isinstance(result, PlacementResult)
    assert result.dry_run is True
    assert result.ticket_number is None
    assert result.would_send["operation"] == "insertWagerStraight"
    placer._client.post_form.assert_not_called()


@pytest.mark.asyncio
async def test_place_straight_live_without_env_blocks(placer, monkeypatch):
    monkeypatch.delenv("CORAL33_PLACEMENT_LIVE", raising=False)
    pre_fixture = _load("preflight_straight")
    quotes, delay = parse_preflight_response(pre_fixture["response"])
    # Re-use minimal inputs
    sel = Selection(
        position=quotes[0].position, game_num=quotes[0].game_num,
        period_number=0, store="wiseguys", profile=".", period_type="Game",
        description="x", risk="5", win="5", bet_type=BetType.STRAIGHT,
    )
    ctx = PlacementContext(
        customer_id="VR12509", agent_id="TYSONR", office="LEOOFFICE",
        currency_code="USD", percent_book=100, credit_acct_flag="Y",
        baseball_action_fixed=False,
        chosen=ChosenSide(
            team_id="New York Knicks", line_type="S", adj_spread="-2.5",
            adj_total=0, price_type="A", final_money=-110,
            final_decimal=1.9091, final_numerator=10, final_denominator=11,
            orig_price=-110, orig_decimal=1.9091, orig_numerator=10,
            orig_denominator=11, orig_spread="-2.5", orig_total="-2.5",
            orig_money=-110,
        ),
        doc_num=1, date="2026-04-30",
    )
    with pytest.raises(PlacementBlockedError, match="CORAL33_PLACEMENT_LIVE"):
        await placer.place_straight(
            selection=sel, quote=quotes[0], context=ctx, delay=delay,
            risk_amount=5.5, win_amount=5, live=True,
        )
    placer._client.post_form.assert_not_called()


@pytest.mark.asyncio
async def test_place_straight_live_with_env_posts(placer, monkeypatch):
    monkeypatch.setenv("CORAL33_PLACEMENT_LIVE", "true")
    pre_fixture = _load("preflight_straight")
    placement_fixture = _load("insert_straight")
    quotes, delay = parse_preflight_response(pre_fixture["response"])
    placer._client.post_form = AsyncMock(return_value={
        "STATUS": {"STATE": 1, "DOC": 1420831507, "test": "ok"}
    })
    sel = Selection(
        position=quotes[0].position, game_num=quotes[0].game_num,
        period_number=0, store="wiseguys", profile=".", period_type="Game",
        description="x", risk="5.5", win="5", bet_type=BetType.STRAIGHT,
    )
    ctx = PlacementContext(
        customer_id="VR12509", agent_id="TYSONR", office="LEOOFFICE",
        currency_code="USD", percent_book=100, credit_acct_flag="Y",
        baseball_action_fixed=False,
        chosen=ChosenSide(
            team_id="New York Knicks", line_type="S", adj_spread="-2.5",
            adj_total=0, price_type="A", final_money=-110,
            final_decimal=1.9091, final_numerator=10, final_denominator=11,
            orig_price=-110, orig_decimal=1.9091, orig_numerator=10,
            orig_denominator=11, orig_spread="-2.5", orig_total="-2.5",
            orig_money=-110,
        ),
        doc_num=1, date="2026-04-30",
    )
    result = await placer.place_straight(
        selection=sel, quote=quotes[0], context=ctx, delay=delay,
        risk_amount=5.5, win_amount=5, live=True,
    )
    assert result.dry_run is False
    assert result.success is True
    assert result.ticket_number == 1420831507
    placer._client.post_form.assert_called_once()
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest server/tests/test_coral33_placement.py -v -k "place_straight"
```

- [ ] **Step 3: Implement `Coral33Placer`, `PlacementResult`, `PlacementBlockedError`**

Add to `placement.py`:
```python
import logging

from .client import Coral33Client


logger = logging.getLogger(__name__)


class PlacementBlockedError(RuntimeError):
    """Raised when `live=True` is requested but the env gate is not set.
    This is the second of two safety locks; the first is the per-call
    `live` flag defaulting to False."""


@dataclass
class PlacementResult:
    """Outcome of a placement attempt. In dry-run mode `would_send` carries
    the exact form body that would have hit the wire."""
    dry_run: bool
    success: bool = False
    ticket_number: int | None = None
    state: int | None = None      # STATUS.STATE from response (1 = OK)
    raw_response: dict[str, Any] | None = None
    would_send: dict[str, str] | None = None  # populated in dry-run mode


def _live_gate_or_block(*, live: bool, operation: str, payload: dict[str, str]) -> bool:
    """Two-lock kill switch.
    - lock 1: per-call `live` arg, default False → dry-run
    - lock 2: env CORAL33_PLACEMENT_LIVE must equal "true" → block otherwise
    Returns True if cleared to actually POST. Raises if live requested
    but env is missing."""
    if not live:
        return False
    env = os.environ.get(LIVE_ENV_VAR, "").strip().lower()
    if env != "true":
        raise PlacementBlockedError(
            f"refusing to {operation}: CORAL33_PLACEMENT_LIVE != 'true' "
            f"(set the env var to confirm real-money placement is allowed)"
        )
    logger.warning(
        "coral33: LIVE PLACEMENT %s — customerID=%s, op=%s, list_len=%d",
        operation, payload.get("customerID"), payload.get("operation"),
        len(payload.get("list", "")),
    )
    return True


class Coral33Placer:
    """Bet-placement client. Composes a `Coral33Client` for auth/transport.

    **Not connected to anything in the running app.** Construct and call
    explicitly when you're ready to place.
    """

    def __init__(self, client: Coral33Client):
        self._client = client

    async def preflight(
        self, selections: list[Selection]
    ) -> tuple[list[LineQuote], DelayToken]:
        """Re-quote a slate of selections. Safe — no booking, just a
        line check. Returns (quotes, delay_token); pass `delay_token`
        verbatim into the matching `place_*` call."""
        if not self._client.is_authenticated:
            await self._client.authenticate()
        form = build_preflight_form(
            selections=selections,
            customer_id=self._client.customer_id,
            token=self._client._token or "",
        )
        # Note: we use the same post_form helper but pre-build the body
        # to avoid post_form's auto-injection of `customerID`/`operation`.
        # See _post_raw below.
        resp = await self._post_raw(form)
        return parse_preflight_response(resp)

    async def place_straight(
        self,
        *,
        selection: Selection,
        quote: LineQuote,
        context: PlacementContext,
        delay: DelayToken,
        risk_amount: float,
        win_amount: float,
        live: bool = False,
    ) -> PlacementResult:
        """Place a single straight bet.

        Real-money POST requires `live=True` AND env CORAL33_PLACEMENT_LIVE=true.
        Otherwise returns a dry-run result with the exact wire payload.
        """
        form = build_straight_form(
            selection=selection, quote=quote, context=context, delay=delay,
            risk_amount=risk_amount, win_amount=win_amount,
        )
        if not _live_gate_or_block(
            live=live, operation="place_straight", payload=form
        ):
            return PlacementResult(dry_run=True, would_send=form)
        resp = await self._post_raw(form)
        return _parse_placement_response(resp)

    async def place_parlay(
        self,
        *,
        selections: list[Selection],
        quotes: list[LineQuote],
        context: PlacementContext,
        spec: ParlaySpec,
        delay: DelayToken,
        live: bool = False,
    ) -> PlacementResult:
        """Place a parlay. Same gate as `place_straight`."""
        form = build_parlay_form(
            selections=selections, quotes=quotes, context=context,
            spec=spec, delay=delay,
        )
        if not _live_gate_or_block(
            live=live, operation="place_parlay", payload=form
        ):
            return PlacementResult(dry_run=True, would_send=form)
        resp = await self._post_raw(form)
        return _parse_placement_response(resp)

    async def _post_raw(self, form: dict[str, str]) -> dict[str, Any]:
        """POST a fully-formed body to /cloud/api/WagerSport/<operation>.
        Bypasses Coral33Client.post_form (which auto-injects customerID/
        operation/office) since our placement bodies are already complete."""
        # We need the same Bearer + headers + curl_cffi session the read
        # client uses. Reach into _raw_post-equivalent territory; the
        # cleanest path is to extend Coral33Client with a public method.
        # For now, implement it inline using the client's auth state.
        raise NotImplementedError("wire to Coral33Client._raw_post in next step")


def _parse_placement_response(resp: dict[str, Any]) -> PlacementResult:
    status = resp.get("STATUS") or {}
    state = status.get("STATE")
    return PlacementResult(
        dry_run=False,
        success=state == 1,
        ticket_number=status.get("DOC"),
        state=state,
        raw_response=resp,
    )
```

- [ ] **Step 4: Wire `_post_raw` to a new public method on `Coral33Client`**

The existing `Coral33Client._raw_post` auto-injects `customerID`/`operation`/`office` (`client.py:182-191`), which we don't want for placement (the body is already complete). Add a new public method on `Coral33Client` that posts a pre-built form to a given path.

In `server/odds/books/coral33/client.py`, add after `_raw_post` (near line 218):
```python
async def post_raw(
    self, path: str, form: dict[str, str]
) -> dict:
    """POST a pre-built form-encoded body to `{BASE_URL}/{path}`. Unlike
    `post_form`, does NOT inject customerID/operation/office — the caller
    is responsible for the entire body. Used by the placement client
    where bodies are byte-equivalent to captured browser traffic.

    Still ensures Bearer auth and retries once on 401."""
    async with self._lock:
        if not self._token or self._token_expired():
            await self.authenticate()
        token_at_call = self._token
    try:
        return await self._raw_post_to_path(path, form)
    except Coral33AuthError:
        async with self._lock:
            if self._token is None or self._token == token_at_call:
                await self.authenticate()
        return await self._raw_post_to_path(path, form)


async def _raw_post_to_path(
    self, path: str, form: dict[str, str]
) -> dict:
    headers = {
        **_browser_headers(),
        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
        "authorization": f"Bearer {self._token}",
    }
    async with AsyncSession(impersonate="chrome", timeout=TIMEOUT) as http:
        resp = await http.post(
            f"{BASE_URL}/{path}", data=form, headers=headers,
        )
        if resp.status_code == 401:
            self._token = None
            self._token_exp = None
            raise Coral33AuthError(f"{path}: 401 — token rejected")
        if resp.status_code != 200:
            raise Coral33APIError(
                f"{path} {resp.status_code}: {resp.text[:300]}"
            )
        try:
            return resp.json()
        except Exception as e:
            raise Coral33APIError(
                f"{path} non-JSON body: {resp.text[:300]}"
            ) from e
```

Then in `placement.py`, replace `_post_raw` with:
```python
async def _post_raw(self, form: dict[str, str]) -> dict[str, Any]:
    operation = form.get("operation", "")
    return await self._client.post_raw(
        f"api/{PLACEMENT_PATH}/{operation}", form
    )
```

- [ ] **Step 5: Run all placement tests**

```bash
pytest server/tests/test_coral33_placement.py -v
```
Expected: all tests pass, including the three live-gate tests.

- [ ] **Step 6: Verify no API route imports `Coral33Placer`**

```bash
grep -rE 'Coral33Placer|from.*placement import' server/ --include='*.py' | grep -v test_
```
Expected: only `placement.py` itself appears (its own internal references). No `server/api/*.py` or `server/main.py` imports it.

- [ ] **Step 7: Commit**

```bash
git add server/odds/books/coral33/placement.py server/odds/books/coral33/client.py server/tests/test_coral33_placement.py
git commit -m "feat(coral33): Coral33Placer with two-lock kill switch (live arg + env gate)"
```

---

## Task 8: Manual smoke test script (preflight only — safe)

**Files:**
- Create: `scripts/coral33_preflight_smoke.py`

The preflight call is safe — it just re-quotes the line, no booking. This script is the bridge to "go live": it proves end-to-end that auth + transport + payload all work against the real server, without risking any money. It is **never imported by the app** — manual run only.

- [ ] **Step 1: Write the script**

`scripts/coral33_preflight_smoke.py`:
```python
"""Manual smoke test for Coral33Placer.preflight. SAFE — no booking.

Pulls credentials from CORAL33_CUSTOMER_ID / CORAL33_PASSWORD env vars
(same as the read-only client), authenticates, runs preflight on a
selection you provide via env, and prints the requoted line + delay.

Usage:
    CORAL33_CUSTOMER_ID=VR12509 \\
    CORAL33_PASSWORD=... \\
    CORAL33_SMOKE_GAME_NUM=619105412 \\
    CORAL33_SMOKE_STORE=wiseguys \\
    CORAL33_SMOKE_PROFILE=. \\
    CORAL33_SMOKE_DESCRIPTION='Basketball #511 Knicks -2½ -110 - For Game ' \\
    python scripts/coral33_preflight_smoke.py

Exits 0 on success, 1 on any error.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from server.odds.books.coral33.client import Coral33Client
from server.odds.books.coral33.placement import (
    BetType, Coral33Placer, Selection,
)


async def main() -> int:
    customer_id = os.environ.get("CORAL33_CUSTOMER_ID", "").strip()
    password = os.environ.get("CORAL33_PASSWORD", "").strip()
    if not customer_id or not password:
        print("ERROR: set CORAL33_CUSTOMER_ID and CORAL33_PASSWORD", file=sys.stderr)
        return 1
    game_num = int(os.environ.get("CORAL33_SMOKE_GAME_NUM", "0"))
    if not game_num:
        print("ERROR: set CORAL33_SMOKE_GAME_NUM", file=sys.stderr)
        return 1

    client = Coral33Client(customer_id=customer_id, password=password)
    placer = Coral33Placer(client=client)

    sel = Selection(
        position=99999999,
        game_num=game_num,
        period_number=0,
        store=os.environ.get("CORAL33_SMOKE_STORE", "wiseguys"),
        profile=os.environ.get("CORAL33_SMOKE_PROFILE", "."),
        period_type="Game",
        description=os.environ.get(
            "CORAL33_SMOKE_DESCRIPTION", "smoke test selection"
        ),
        risk="1",
        win="1",
        bet_type=BetType.STRAIGHT,
    )
    quotes, delay = await placer.preflight([sel])
    print(json.dumps({
        "ok": True,
        "delay": {"time": delay.time, "secs": delay.secs, "sig_present": bool(delay.sig)},
        "quote_count": len(quotes),
        "first_quote": {
            "team1": quotes[0].team1_id if quotes else None,
            "team2": quotes[0].team2_id if quotes else None,
            "spread": quotes[0].spread if quotes else None,
            "spread_adj_1": quotes[0].spread_adj_1 if quotes else None,
            "money_line_1": quotes[0].money_line_1 if quotes else None,
            "total_points": quotes[0].total_points if quotes else None,
        } if quotes else None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Run with bogus game_num to verify error path**

```bash
CORAL33_CUSTOMER_ID=$CORAL33_CUSTOMER_ID \
CORAL33_PASSWORD=$CORAL33_PASSWORD \
CORAL33_SMOKE_GAME_NUM=1 \
python scripts/coral33_preflight_smoke.py
```
Expected: either an empty `LIST` (server handles gracefully) or a clean error from `parse_preflight_response`. No exception in our code.

- [ ] **Step 3: Skip the real-game smoke run** (the user runs this manually when ready)

The plan stops here — actually running the smoke test against a real game is a manual decision the user makes. Document it but do not run.

- [ ] **Step 4: Commit**

```bash
git add scripts/coral33_preflight_smoke.py
git commit -m "feat(coral33): manual preflight smoke test script (safe, no booking)"
```

---

## Task 9: Final integration check

**Files:** none (read-only verification)

- [ ] **Step 1: Confirm zero connection points**

```bash
grep -rE 'Coral33Placer|from.*\.placement\b|import.*placement' server/ --include='*.py' | grep -v 'test_\|placement\.py'
```
Expected: empty. The placement module is fully isolated.

- [ ] **Step 2: Confirm full test pass**

```bash
pytest server/tests/test_coral33_placement.py -v
```
Expected: all tests pass, including:
- `test_selection_dataclass_holds_minimum_fields`
- `test_preflight_straight_payload_matches_har`
- `test_preflight_parlay_payload_matches_har`
- `test_parse_preflight_straight_returns_quotes_and_delay`
- `test_straight_placement_payload_matches_har`
- `test_parlay_placement_payload_matches_har`
- `test_place_straight_dry_run_returns_payload_without_post`
- `test_place_straight_live_without_env_blocks`
- `test_place_straight_live_with_env_posts`

- [ ] **Step 3: Confirm read-only client untouched (other than additive method)**

```bash
git diff main -- server/odds/books/coral33/client.py
```
Expected: only the `post_raw` + `_raw_post_to_path` additions; no edits to existing methods.

- [ ] **Step 4: Print the "ready to plug in" summary**

The placement module is now:
- ✅ Implemented and tested
- ✅ Byte-equivalent to captured HAR for both straight and parlay
- ✅ Has dual kill switch (per-call `live=True` + `CORAL33_PLACEMENT_LIVE=true`)
- ✅ Not imported by any API route, scheduler, or background task
- ✅ Has a safe manual preflight smoke test ready to run

To wire it in (future work, not part of this plan):
1. Add a backend route under `server/api/` that constructs a `Coral33Placer`
2. Add UI in `web/` to trigger placements
3. Decide whether to set `CORAL33_PLACEMENT_LIVE=true` in env (real money) or stay dry-run for first deploy

---

## Notes & known gaps

- **`docNum` provenance**: HAR shows non-sequential values (92657540 straight, 531210 parlay). For now we accept caller-provided `doc_num` and pass it through. If server rejects unknown values, we'll need to sniff one more HAR — the UI may pull this from a separate endpoint we haven't traced.
- **Multi-leg parlay**: `build_parlay_form` raises `NotImplementedError` for >1 leg until we capture a multi-leg HAR. Each leg needs its own `ChosenSide`; the captured single-leg case doesn't exercise this.
- **`gameDate` timezone**: HAR's `gameDate` (`17:00:01.000`) differs from preflight's `GameDateTime` (`19:00:01.000`). Server may accept either; we mirror what the browser sent. If the server rejects, the fix is in `_build_straight_leg`'s `gameDate` line.
- **`description` trimming**: HAR shows top-level `description` keeps the trailing space (`"… For Game "`) but `wager.description` strips it (`"… For Game"`). Mirrored in builder; revisit if wrong.
- **Captcha**: Did not trigger for this account/IP. Code path for `CaptchaRequired` in placement response is **not yet handled** — Phase 2 once we observe the rejection shape.
- **Idempotency**: No client-side request ID. If a placement times out mid-flight, retrying could double-book. Caller responsibility for now; consider adding a client-generated UUID in `extra` if needed.
