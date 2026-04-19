# Betting Site MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-only, laptop-only MLB odds aggregator website (Bloomberg-Terminal-for-Betting aesthetic) with two pages: `/odds/mlb` (dense grid of live odds from ~8 US sportsbooks) and `/picks/mlb` (dense table of today's picks from the `baseball-agents` pipeline with expandable reasoning).

**Architecture:** Two-process split. Python FastAPI backend on `localhost:8000` owns the Odds API fetcher, SQLite cache, and bet-card-txt adapter. Next.js frontend on `localhost:3000` owns the UI, fetching JSON from the backend via SWR polling (15s odds, 60s picks). No auth, no deployment, no mobile, no WebSockets.

**Tech Stack:** Python 3.11+, FastAPI, APScheduler, SQLite (stdlib), httpx, pytest, VCR.py, Pydantic v2. Next.js 15 (App Router), TypeScript, Tailwind CSS, shadcn/ui, TanStack Table v8, SWR, Framer Motion, Inter font. `openapi-typescript` for type codegen.

**Spec reference:** `docs/superpowers/specs/2026-04-18-betting-site-mvp-design.md`

**Reality-check finding:** The `baseball-agents` pipeline writes `data/bet_card_YYYY-MM-DD.txt` (pipe-delimited text), **not** `picks-*.json` as originally assumed. There is no LLM-generated reasoning per pick; the pick lines carry `Mkt / Model / Edge / Kelly` stats only. The picks adapter (Task 1.8) parses the text format and synthesizes a short stats-based rationale. Track records come from `data/bets.csv` (which has resolution + P/L).

---

## File Structure (decomposition lock-in)

```
betting-site/
├── .gitignore
├── README.md                                  # how to run
├── pyproject.toml                             # Python deps + pytest config
├── .env.example
├── server/
│   ├── __init__.py
│   ├── main.py                                # FastAPI app, scheduler startup
│   ├── config.py                              # env vars → config
│   ├── models.py                              # Pydantic domain models
│   ├── odds/
│   │   ├── __init__.py
│   │   ├── client.py                          # Odds API HTTP client
│   │   ├── fetcher.py                         # APScheduler job
│   │   ├── cache.py                           # SQLite persistence
│   │   ├── devig.py                           # pure: devig math
│   │   ├── best_odds.py                       # pure: best-price + consensus
│   │   └── normalize.py                       # Odds API → domain
│   ├── picks/
│   │   ├── __init__.py
│   │   ├── bet_card_parser.py                 # text → structured picks
│   │   ├── track_record.py                    # bets.csv → 30d record
│   │   └── reader.py                          # orchestrates picks → domain
│   ├── api/
│   │   ├── __init__.py
│   │   ├── odds.py                            # GET /api/odds/mlb
│   │   ├── picks.py                           # GET /api/picks/mlb
│   │   └── health.py                          # GET /api/health
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py                        # pytest fixtures
│       ├── cassettes/
│       │   └── odds_api_mlb.yaml              # VCR recording
│       ├── fixtures/
│       │   ├── bet_card_example.txt           # captured from agents
│       │   └── bets_example.csv
│       ├── test_devig.py
│       ├── test_best_odds.py
│       ├── test_cache.py
│       ├── test_bet_card_parser.py
│       ├── test_track_record.py
│       ├── test_picks_reader.py
│       └── test_api.py
└── web/
    ├── package.json
    ├── next.config.ts
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── postcss.config.mjs
    ├── playwright.config.ts
    ├── app/
    │   ├── layout.tsx                         # Root: fonts, theme, nav shell
    │   ├── page.tsx                           # redirect to /odds/mlb
    │   ├── globals.css                        # tailwind + design tokens
    │   ├── odds/mlb/page.tsx
    │   └── picks/mlb/page.tsx
    ├── components/
    │   ├── nav-shell.tsx
    │   ├── stale-indicator.tsx
    │   ├── odds-grid/
    │   │   ├── index.tsx                      # TanStack Table wrapper
    │   │   ├── columns.tsx                    # column definitions
    │   │   ├── cell-flash.tsx                 # yellow-fade on change
    │   │   ├── best-cell.tsx                  # green price + book label
    │   │   └── market-tabs.tsx                # client-side market toggle
    │   ├── picks-table/
    │   │   ├── index.tsx
    │   │   ├── columns.tsx
    │   │   ├── tier-badge.tsx
    │   │   └── expanded-row.tsx
    │   └── ui/                                # shadcn primitives (generated)
    ├── lib/
    │   ├── api.ts                             # typed fetch wrapper
    │   ├── swr.ts                             # SWR config
    │   ├── format.ts                          # American odds, units, time-ago
    │   └── use-flash-diff.ts                  # line-move detection hook
    ├── types/
    │   └── api.ts                             # generated from /openapi.json
    └── scripts/
        └── gen-types.sh                       # codegen script

# Note: Vitest + Playwright are installed in Task 0.4 for future use,
# but no unit/e2e test files are created by this plan. They're deferred to v2.
```

---

## Phase 0 — Scaffolding

### Task 0.1: Initialize git + .gitignore

**Files:**
- Create: `betting-site/.gitignore`

- [ ] **Step 1: `git init` in the project root**

```bash
cd /Users/mikeborucki/personal_workspace/betting-site
git init -b main
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.mypy_cache/
*.egg-info/

# Node
node_modules/
.next/
.turbo/
out/

# Env
.env
.env.local
*.local

# Superpowers scratch
.superpowers/

# SQLite cache
server/cache.db
server/cache.db-journal

# OS
.DS_Store
```

- [ ] **Step 3: First commit**

```bash
# BRAINSTORM_STATE.md may or may not exist depending on prior work; add conditionally
files=".gitignore docs/"
[ -f BRAINSTORM_STATE.md ] && files="$files BRAINSTORM_STATE.md"
git add $files
git commit -m "chore: scaffolding — gitignore + brainstorm artifacts"
```

---

### Task 0.2: Capture bet card + bets.csv fixtures

**Files:**
- Create: `server/tests/fixtures/bet_card_example.txt`
- Create: `server/tests/fixtures/bets_example.csv`

- [ ] **Step 1: Copy existing bet card as the picks fixture**

```bash
mkdir -p server/tests/fixtures
cp ~/personal_workspace/agents/baseball-agents/data/bet_card_2026-04-01.txt \
   server/tests/fixtures/bet_card_example.txt
head -200 ~/personal_workspace/agents/baseball-agents/data/bets.csv \
   > server/tests/fixtures/bets_example.csv
```

- [ ] **Step 2: Commit fixtures**

```bash
git add server/tests/fixtures/
git commit -m "chore(fixtures): capture bet card + bets.csv samples from baseball-agents"
```

---

### Task 0.3: Python project setup

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `server/__init__.py`
- Create: `server/tests/__init__.py`
- Create: `server/tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "betting-site-server"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.29",
  "pydantic>=2.6",
  "httpx>=0.27",
  "apscheduler>=3.10",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "vcrpy>=6.0",
  "pytest-vcr>=1.0",
]

[tool.hatch.build.targets.wheel]
packages = ["server"]

[tool.pytest.ini_options]
testpaths = ["server/tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Write `.env.example`**

```bash
# Copy your Odds API key from the baseball-agents .env
ODDS_API_KEY=your_key_here
# Path where baseball-agents writes daily bet cards
BET_CARD_DIR=/Users/mikeborucki/personal_workspace/agents/baseball-agents/data
# Path to bets.csv (for track records)
BETS_CSV=/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/bets.csv
# Poll intervals (seconds)
ODDS_POLL_INTERVAL=30
# API budget floor — below this, skip per-event enrichment
API_BUDGET_FLOOR=100
# Backend bind
HOST=127.0.0.1
PORT=8000
```

- [ ] **Step 3: Create venv + install**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 4: Scaffold empty package files**

```bash
touch server/__init__.py
touch server/tests/__init__.py
touch server/tests/conftest.py
touch server/odds/__init__.py server/picks/__init__.py server/api/__init__.py
```

- [ ] **Step 5: Copy Odds API key from baseball-agents if present**

```bash
if [ -f ~/personal_workspace/agents/baseball-agents/.env ]; then
  grep '^ODDS_API_KEY=' ~/personal_workspace/agents/baseball-agents/.env > .env || true
fi
cp -n .env.example .env || true
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example server/
git commit -m "chore(server): Python scaffolding (pyproject, env template, empty packages)"
```

---

### Task 0.4: Frontend scaffold (Next.js + Tailwind + shadcn)

**Files:**
- Many under `web/`

- [ ] **Step 1: `create-next-app` into `web/`**

```bash
cd /Users/mikeborucki/personal_workspace/betting-site
npx --yes create-next-app@latest web \
  --typescript --tailwind --app --src-dir=false --eslint \
  --no-turbopack --import-alias "@/*" --no-git
```

- [ ] **Step 2: Install runtime deps**

```bash
cd web
npm install @tanstack/react-table swr framer-motion clsx tailwind-merge \
  class-variance-authority lucide-react
npm install -D @types/node openapi-typescript @playwright/test vitest \
  @vitejs/plugin-react @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 3: Initialize shadcn/ui**

```bash
cd web
npx --yes shadcn@latest init -d
npx --yes shadcn@latest add button badge dialog
```

- [ ] **Step 4: Install Playwright browsers**

```bash
cd web
npx playwright install chromium
```

- [ ] **Step 5: Commit**

```bash
cd ..
git add web/
git commit -m "chore(web): Next.js scaffold with Tailwind, shadcn/ui, TanStack, SWR, Playwright"
```

---

### Task 0.5: Design tokens + Inter font

**Files:**
- Modify: `web/app/globals.css`
- Modify: `web/tailwind.config.ts`
- Modify: `web/app/layout.tsx`

- [ ] **Step 1: Overwrite `web/app/globals.css` with design tokens**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --bg-0: #0B0F14;
  --bg-1: #131A22;
  --bg-2: #1C2530;
  --border: #263140;
  --text-1: #F5F7FA;
  --text-2: #9AA5B4;
  --text-3: #6B7685;
  --green: #2CB459;
  --red: #E5484D;
  --yellow: #F5A524;
  --accent: #22D3EE;
  --violet: #7C5CFF;
}

html, body {
  background: var(--bg-0);
  color: var(--text-1);
  font-feature-settings: 'tnum' 1, 'ss01' 1;
}

.tabular { font-variant-numeric: tabular-nums; font-feature-settings: 'tnum' 1; }
```

- [ ] **Step 2: Map tokens into Tailwind (`web/tailwind.config.ts`)**

```ts
import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        "bg-0": "var(--bg-0)",
        "bg-1": "var(--bg-1)",
        "bg-2": "var(--bg-2)",
        "border-subtle": "var(--border)",
        "text-1": "var(--text-1)",
        "text-2": "var(--text-2)",
        "text-3": "var(--text-3)",
        "price-up": "var(--green)",
        "price-down": "var(--red)",
        "flash": "var(--yellow)",
        "accent": "var(--accent)",
        "violet-accent": "var(--violet)",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
} satisfies Config;
```

- [ ] **Step 3: Load Inter in `web/app/layout.tsx`**

```tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Betting Site",
  description: "MLB odds aggregator + agent picks",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="font-sans bg-bg-0 text-text-1 antialiased">
        {children}
      </body>
    </html>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add web/app/globals.css web/tailwind.config.ts web/app/layout.tsx
git commit -m "style(web): design tokens, Inter font, dark palette"
```

---

## Phase 1 — Backend Data Layer

### Task 1.1: Pydantic domain models

**Files:**
- Create: `server/models.py`

- [ ] **Step 1: Write `server/models.py`**

```python
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class BookPrice(BaseModel):
    bookmaker_key: str
    price_american: int
    point: float | None = None
    fetched_at: datetime


class MarketOutcome(BaseModel):
    outcome_name: str
    prices: list[BookPrice]
    best_price: BookPrice
    consensus_price_american: int | None = None


class Market(BaseModel):
    market_key: str                              # 'h2h' | 'spreads' | 'totals' | ...
    outcomes: list[MarketOutcome]


class Game(BaseModel):
    event_id: str
    home_team: str
    away_team: str
    commence_time: datetime
    is_live: bool = False
    markets: list[Market]
    stale_seconds: int = 0                       # max across cells


class OddsResponse(BaseModel):
    games: list[Game]
    stale_seconds: int
    fetched_at: datetime


class PickTier(str, Enum):
    HIGH = "high"
    SWEET = "sweet"
    LEAN = "lean"


class PickStat(BaseModel):
    label: str
    value: str


class Pick(BaseModel):
    id: str
    tier: PickTier
    game_label: str
    market_label: str
    pick_side: str                               # 'home -1.5' | 'over 2.5' | ...
    odds_american: int
    best_book: str | None = None
    stake_units: float
    probability_pct: float                       # model probability
    market_probability_pct: float                # market-implied
    edge_pct: float
    stats: list[PickStat] = Field(default_factory=list)
    reasoning: str
    agent_key: str = "baseball-agents"
    agent_record_30d: str = ""
    commence_time: datetime | None = None


class PicksResponse(BaseModel):
    picks: list[Pick]
    status: Literal["ok", "no_picks_today"]
    last_checked_at: datetime
    bet_card_date: str | None = None             # YYYY-MM-DD of picks source


class FetcherStatus(BaseModel):
    last_fetch_at: datetime | None = None
    requests_used: int | None = None
    requests_remaining: int | None = None
    last_error: str | None = None
```

- [ ] **Step 2: Commit**

```bash
git add server/models.py
git commit -m "feat(server): Pydantic domain models (Game, Pick, Response)"
```

---

### Task 1.2: Config module

**Files:**
- Create: `server/config.py`

- [ ] **Step 1: Write `server/config.py`**

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    odds_api_key: str
    bet_card_dir: Path
    bets_csv: Path
    odds_poll_interval: int
    api_budget_floor: int
    host: str
    port: int
    cache_db: Path

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            odds_api_key=os.environ.get("ODDS_API_KEY", ""),
            bet_card_dir=Path(os.environ.get(
                "BET_CARD_DIR",
                str(Path.home() / "personal_workspace/agents/baseball-agents/data"),
            )),
            bets_csv=Path(os.environ.get(
                "BETS_CSV",
                str(Path.home() / "personal_workspace/agents/baseball-agents/data/bets.csv"),
            )),
            odds_poll_interval=int(os.environ.get("ODDS_POLL_INTERVAL", "30")),
            api_budget_floor=int(os.environ.get("API_BUDGET_FLOOR", "100")),
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8000")),
            cache_db=Path(__file__).parent / "cache.db",
        )
```

- [ ] **Step 2: Commit**

```bash
git add server/config.py
git commit -m "feat(server): config loader from env"
```

---

### Task 1.3: Devig math (TDD)

**Files:**
- Create: `server/odds/devig.py`
- Create: `server/tests/test_devig.py`

- [ ] **Step 1: Write failing tests**

```python
# server/tests/test_devig.py
import pytest
from server.odds.devig import american_to_implied_prob, devig_two_way


def test_american_to_implied_prob_negative():
    # -110 → implied ~52.38%
    assert abs(american_to_implied_prob(-110) - 0.5238) < 0.001


def test_american_to_implied_prob_positive():
    # +150 → implied 40.0%
    assert abs(american_to_implied_prob(150) - 0.4000) < 0.001


def test_devig_two_way_balanced():
    # both -110 → true 50/50 after devig
    home, away = devig_two_way(-110, -110)
    assert abs(home - 0.5) < 0.001
    assert abs(away - 0.5) < 0.001


def test_devig_two_way_skewed():
    # -200 / +170 (vig ≈ 4.3%)
    home, away = devig_two_way(-200, 170)
    assert home > away
    assert abs((home + away) - 1.0) < 0.0001  # sums to 1
```

- [ ] **Step 2: Run (expect FAIL — module not found)**

```bash
pytest server/tests/test_devig.py -v
# Expected: ImportError — server.odds.devig not found
```

- [ ] **Step 3: Implement `server/odds/devig.py`**

```python
from __future__ import annotations


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied (vigged) probability."""
    if odds < 0:
        return -odds / (-odds + 100)
    return 100 / (odds + 100)


def devig_two_way(price_a: int, price_b: int) -> tuple[float, float]:
    """
    Remove vig from a two-way market using proportional (power) method.
    Returns (prob_a, prob_b) summing to 1.0.
    """
    p_a = american_to_implied_prob(price_a)
    p_b = american_to_implied_prob(price_b)
    total = p_a + p_b
    return (p_a / total, p_b / total)
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
pytest server/tests/test_devig.py -v
```

- [ ] **Step 5: Commit**

```bash
git add server/odds/devig.py server/tests/test_devig.py
git commit -m "feat(server): devig math with tests"
```

---

### Task 1.4: Best-odds + median consensus (TDD)

**Files:**
- Create: `server/odds/best_odds.py`
- Create: `server/tests/test_best_odds.py`

- [ ] **Step 1: Write failing tests**

```python
# server/tests/test_best_odds.py
from server.odds.best_odds import pick_best_price, median_american_odds


def test_pick_best_price_positive_odds_higher_is_better():
    prices = [("dk", 150), ("fd", 160), ("mgm", 145)]
    best = pick_best_price(prices)
    assert best == ("fd", 160)


def test_pick_best_price_negative_odds_closer_to_zero_is_better():
    prices = [("dk", -150), ("fd", -140), ("mgm", -160)]
    best = pick_best_price(prices)
    assert best == ("fd", -140)


def test_pick_best_price_mixed_signs():
    # Any positive beats any negative
    prices = [("dk", -110), ("fd", 105)]
    best = pick_best_price(prices)
    assert best == ("fd", 105)


def test_median_american_odds_odd_count():
    assert median_american_odds([-110, -115, -105]) == -110


def test_median_american_odds_even_count():
    # Median of two values averaged in probability space, then back to American
    result = median_american_odds([-110, -110])
    assert result == -110


def test_median_american_odds_empty_returns_none():
    assert median_american_odds([]) is None
```

- [ ] **Step 2: Run (expect FAIL)**

```bash
pytest server/tests/test_best_odds.py -v
```

- [ ] **Step 3: Implement**

```python
# server/odds/best_odds.py
from __future__ import annotations

from statistics import median

from .devig import american_to_implied_prob


def _american_to_payout_multiplier(odds: int) -> float:
    """Higher = better for the bettor. Used for comparison only."""
    if odds > 0:
        return 1 + odds / 100.0
    return 1 + 100.0 / (-odds)


def pick_best_price(prices: list[tuple[str, int]]) -> tuple[str, int] | None:
    """Given [(bookmaker_key, american_odds), ...] pick the best payout for the bettor."""
    if not prices:
        return None
    return max(prices, key=lambda p: _american_to_payout_multiplier(p[1]))


def _prob_to_american(p: float) -> int:
    if p <= 0 or p >= 1:
        return 0
    if p >= 0.5:
        return round(-p / (1 - p) * 100)
    return round((1 - p) / p * 100)


def median_american_odds(prices: list[int]) -> int | None:
    """Median in implied-probability space, converted back to American."""
    if not prices:
        return None
    probs = sorted(american_to_implied_prob(p) for p in prices)
    return _prob_to_american(median(probs))
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
pytest server/tests/test_best_odds.py -v
```

- [ ] **Step 5: Commit**

```bash
git add server/odds/best_odds.py server/tests/test_best_odds.py
git commit -m "feat(server): best-odds picker + median consensus"
```

---

### Task 1.5: SQLite cache

**Files:**
- Create: `server/odds/cache.py`
- Create: `server/tests/test_cache.py`

- [ ] **Step 1: Write failing tests**

```python
# server/tests/test_cache.py
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.odds.cache import OddsCache


@pytest.fixture
def cache(tmp_path: Path) -> OddsCache:
    c = OddsCache(tmp_path / "cache.db")
    c.init()
    return c


def test_upsert_and_read_single_row(cache: OddsCache):
    now = datetime.now(timezone.utc)
    cache.upsert([
        {
            "event_id": "evt_1",
            "home_team": "Yankees", "away_team": "Red Sox",
            "commence_time": now,
            "bookmaker_key": "draftkings",
            "market_key": "h2h",
            "outcome_name": "Yankees",
            "outcome_point": None,
            "price_american": -138,
            "fetched_at": now,
        }
    ])
    rows = cache.all_current()
    assert len(rows) == 1
    assert rows[0]["price_american"] == -138


def test_upsert_overwrites_same_key(cache: OddsCache):
    now = datetime.now(timezone.utc)
    base = {
        "event_id": "evt_1",
        "home_team": "Yankees", "away_team": "Red Sox",
        "commence_time": now,
        "bookmaker_key": "draftkings",
        "market_key": "h2h",
        "outcome_name": "Yankees",
        "outcome_point": None,
        "fetched_at": now,
    }
    cache.upsert([{**base, "price_american": -138}])
    cache.upsert([{**base, "price_american": -140}])
    rows = cache.all_current()
    assert len(rows) == 1
    assert rows[0]["price_american"] == -140
```

- [ ] **Step 2: Run (expect FAIL)**

```bash
pytest server/tests/test_cache.py -v
```

- [ ] **Step 3: Implement**

```python
# server/odds/cache.py
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS odds_snapshot (
  event_id       TEXT NOT NULL,
  home_team      TEXT NOT NULL,
  away_team      TEXT NOT NULL,
  commence_time  TEXT NOT NULL,
  bookmaker_key  TEXT NOT NULL,
  market_key     TEXT NOT NULL,
  outcome_name   TEXT NOT NULL,
  outcome_point  REAL,
  price_american INTEGER NOT NULL,
  fetched_at     TEXT NOT NULL,
  PRIMARY KEY (event_id, bookmaker_key, market_key, outcome_name, outcome_point)
);

CREATE INDEX IF NOT EXISTS idx_odds_event ON odds_snapshot(event_id);

CREATE TABLE IF NOT EXISTS fetcher_status (
  key                TEXT PRIMARY KEY,
  last_fetch_at      TEXT,
  requests_used      INTEGER,
  requests_remaining INTEGER,
  last_error         TEXT
);
"""


class OddsCache:
    def __init__(self, path: Path):
        self.path = path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    def upsert(self, rows: Iterable[dict]) -> None:
        with self._conn() as c:
            c.executemany(
                """
                INSERT INTO odds_snapshot
                  (event_id, home_team, away_team, commence_time,
                   bookmaker_key, market_key, outcome_name, outcome_point,
                   price_american, fetched_at)
                VALUES
                  (:event_id, :home_team, :away_team, :commence_time,
                   :bookmaker_key, :market_key, :outcome_name, :outcome_point,
                   :price_american, :fetched_at)
                ON CONFLICT(event_id, bookmaker_key, market_key, outcome_name, outcome_point)
                DO UPDATE SET
                   price_american = excluded.price_american,
                   fetched_at     = excluded.fetched_at,
                   commence_time  = excluded.commence_time,
                   home_team      = excluded.home_team,
                   away_team      = excluded.away_team
                """,
                [
                    {
                        **r,
                        "commence_time": r["commence_time"].isoformat() if isinstance(r["commence_time"], datetime) else r["commence_time"],
                        "fetched_at": r["fetched_at"].isoformat() if isinstance(r["fetched_at"], datetime) else r["fetched_at"],
                    }
                    for r in rows
                ],
            )

    def all_current(self) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM odds_snapshot")]

    def set_status(self, *, last_fetch_at: datetime | None = None,
                   requests_used: int | None = None,
                   requests_remaining: int | None = None,
                   last_error: str | None = None) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO fetcher_status (key, last_fetch_at, requests_used, requests_remaining, last_error)
                VALUES ('default', :lf, :ru, :rr, :le)
                ON CONFLICT(key) DO UPDATE SET
                   last_fetch_at = COALESCE(:lf, last_fetch_at),
                   requests_used = COALESCE(:ru, requests_used),
                   requests_remaining = COALESCE(:rr, requests_remaining),
                   last_error = :le
                """,
                {
                    "lf": last_fetch_at.isoformat() if last_fetch_at else None,
                    "ru": requests_used,
                    "rr": requests_remaining,
                    "le": last_error,
                },
            )

    def get_status(self) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM fetcher_status WHERE key='default'").fetchone()
            return dict(row) if row else None
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
pytest server/tests/test_cache.py -v
```

- [ ] **Step 5: Commit**

```bash
git add server/odds/cache.py server/tests/test_cache.py
git commit -m "feat(server): SQLite cache with upsert and status tracking"
```

---

### Task 1.6: Odds API client (VCR-backed)

**Files:**
- Create: `server/odds/client.py`
- Create: `server/tests/test_odds_client.py` (VCR test)

- [ ] **Step 1: Write `server/odds/client.py`**

```python
from __future__ import annotations

import logging
from typing import Any

import httpx


logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"
MLB_SPORT_KEY = "baseball_mlb"
CORE_MARKETS = "h2h,spreads,totals"
REGIONS = "us,us2"
TIMEOUT = 15.0


class OddsAPIError(Exception):
    pass


class OddsAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch_mlb_core(self) -> tuple[list[dict], dict]:
        """
        Fetch today's MLB games with h2h/spreads/totals.
        Returns (games_list, rate_info).
        """
        params = {
            "apiKey": self.api_key,
            "regions": REGIONS,
            "oddsFormat": "american",
            "markets": CORE_MARKETS,
        }
        url = f"{BASE_URL}/sports/{MLB_SPORT_KEY}/odds"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            rate_info = {
                "requests_used": int(resp.headers.get("x-requests-used", 0) or 0),
                "requests_remaining": int(resp.headers.get("x-requests-remaining", 0) or 0),
            }
            if resp.status_code == 200:
                return resp.json(), rate_info
            if resp.status_code == 422:
                logger.warning("422 from odds API, returning empty: %s", resp.text)
                return [], rate_info
            raise OddsAPIError(f"{resp.status_code}: {resp.text}")

    async def fetch_event_markets(
        self, event_id: str, markets: str
    ) -> tuple[dict, dict]:
        params = {
            "apiKey": self.api_key,
            "regions": REGIONS,
            "oddsFormat": "american",
            "markets": markets,
        }
        url = f"{BASE_URL}/sports/{MLB_SPORT_KEY}/events/{event_id}/odds"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            rate_info = {
                "requests_used": int(resp.headers.get("x-requests-used", 0) or 0),
                "requests_remaining": int(resp.headers.get("x-requests-remaining", 0) or 0),
            }
            if resp.status_code == 200:
                return resp.json(), rate_info
            if resp.status_code == 422:
                return {}, rate_info
            raise OddsAPIError(f"{resp.status_code}: {resp.text}")
```

- [ ] **Step 2: Write VCR-backed smoke test**

```python
# server/tests/test_odds_client.py
import os
from pathlib import Path

import pytest


@pytest.mark.vcr(
    cassette_library_dir=str(Path(__file__).parent / "cassettes"),
    filter_query_parameters=["apiKey"],
    filter_headers=["authorization", "set-cookie"],
)
@pytest.mark.asyncio
async def test_fetch_mlb_core_smoke():
    """
    Run once manually with ODDS_API_KEY set to record the cassette.
    Subsequent CI runs replay from cassette.
    """
    from server.odds.client import OddsAPIClient

    key = os.environ.get("ODDS_API_KEY", "test-key-for-cassette")
    client = OddsAPIClient(api_key=key)
    games, rate = await client.fetch_mlb_core()
    assert isinstance(games, list)
    assert "requests_used" in rate
```

- [ ] **Step 3: Run test (records cassette if key present, replays otherwise)**

```bash
pytest server/tests/test_odds_client.py -v
```

- [ ] **Step 4: Commit (cassette included)**

```bash
git add server/odds/client.py server/tests/test_odds_client.py server/tests/cassettes/
git commit -m "feat(server): Odds API client with VCR-backed test"
```

---

### Task 1.7: Odds API → domain normalizer

**Files:**
- Create: `server/odds/normalize.py`

- [ ] **Step 1: Write `server/odds/normalize.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable


def normalize_odds_response(games: list[dict], fetched_at: datetime) -> list[dict]:
    """
    Flatten Odds API response into cache rows.
    Returns list of dicts ready for OddsCache.upsert().
    """
    rows: list[dict] = []
    for game in games:
        event_id = game["id"]
        home = game["home_team"]
        away = game["away_team"]
        commence = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
        for bm in game.get("bookmakers", []):
            bk = bm["key"]
            for mk in bm.get("markets", []):
                market_key = mk["key"]
                for oc in mk.get("outcomes", []):
                    rows.append({
                        "event_id": event_id,
                        "home_team": home,
                        "away_team": away,
                        "commence_time": commence,
                        "bookmaker_key": bk,
                        "market_key": market_key,
                        "outcome_name": oc["name"],
                        "outcome_point": oc.get("point"),
                        "price_american": int(oc["price"]),
                        "fetched_at": fetched_at,
                    })
    return rows


def rows_to_games(rows: Iterable[dict], now: datetime) -> list[dict]:
    """
    Group cache rows into Game → Market → MarketOutcome → BookPrice structure.
    Returns list of dicts matching the Game pydantic model shape.
    """
    from .best_odds import pick_best_price, median_american_odds

    by_event: dict[str, dict] = {}
    for r in rows:
        ev = by_event.setdefault(r["event_id"], {
            "event_id": r["event_id"],
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "commence_time": _coerce_dt(r["commence_time"]),
            "markets_by_key": {},
            "stale_seconds": 0,
        })
        mk = ev["markets_by_key"].setdefault(r["market_key"], {})
        out_key = (r["outcome_name"], r.get("outcome_point"))
        out = mk.setdefault(out_key, {
            "outcome_name": r["outcome_name"],
            "outcome_point": r.get("outcome_point"),
            "prices": [],
        })
        fetched_at = _coerce_dt(r["fetched_at"])
        out["prices"].append({
            "bookmaker_key": r["bookmaker_key"],
            "price_american": r["price_american"],
            "point": r.get("outcome_point"),
            "fetched_at": fetched_at,
        })
        age = max(0, int((now - fetched_at).total_seconds()))
        if age > ev["stale_seconds"]:
            ev["stale_seconds"] = age

    games = []
    for ev in by_event.values():
        markets = []
        for mk_key, outcomes in ev["markets_by_key"].items():
            out_list = []
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
            markets.append({"market_key": mk_key, "outcomes": out_list})
        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        games.append({
            "event_id": ev["event_id"],
            "home_team": ev["home_team"],
            "away_team": ev["away_team"],
            "commence_time": ev["commence_time"],
            "is_live": ev["commence_time"] <= now_utc,
            "markets": markets,
            "stale_seconds": ev["stale_seconds"],
        })
    games.sort(key=lambda g: g["commence_time"])
    return games


def _coerce_dt(v) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(v.replace("Z", "+00:00") if isinstance(v, str) else str(v))
```

- [ ] **Step 2: Commit**

```bash
git add server/odds/normalize.py
git commit -m "feat(server): Odds API response normalizer"
```

---

### Task 1.8: Bet card parser (TDD)

**Files:**
- Create: `server/picks/bet_card_parser.py`
- Create: `server/tests/test_bet_card_parser.py`

- [ ] **Step 1: Write failing tests against the fixture**

```python
# server/tests/test_bet_card_parser.py
from pathlib import Path

from server.picks.bet_card_parser import parse_bet_card


FIXTURE = Path(__file__).parent / "fixtures" / "bet_card_example.txt"


def test_parse_bet_card_returns_date():
    card = parse_bet_card(FIXTURE.read_text())
    assert card["date"] == "2026-04-01"


def test_parse_bet_card_returns_games():
    card = parse_bet_card(FIXTURE.read_text())
    assert len(card["games"]) >= 1
    assert card["games"][0]["game_label"] == "WSH@PHI"


def test_parse_bet_card_pick_fields():
    card = parse_bet_card(FIXTURE.read_text())
    first_game = card["games"][0]
    first_pick = first_game["picks"][0]
    assert first_pick["bet_type"] == "first_5_rl"
    assert first_pick["side"] == "home -1.5"
    assert first_pick["odds_american"] == 116
    assert abs(first_pick["market_prob"] - 0.439) < 0.005
    assert abs(first_pick["model_prob"] - 0.565) < 0.005
    assert abs(first_pick["edge"] - 0.126) < 0.005
    assert abs(first_pick["kelly_pct"] - 0.0474) < 0.001
```

- [ ] **Step 2: Run (expect FAIL)**

```bash
pytest server/tests/test_bet_card_parser.py -v
```

- [ ] **Step 3: Implement**

```python
# server/picks/bet_card_parser.py
from __future__ import annotations

import re
from typing import TypedDict


HEADER_DATE_RE = re.compile(r"MIROFISH BET CARD\s+—\s+(\d{4}-\d{2}-\d{2})")
GAME_HEADER_RE = re.compile(r"^\s{2}([A-Z]{2,4}@[A-Z]{2,4})\s*$")
PICK_LINE_RE = re.compile(
    r"^\s+(?P<bet_type>[a-z_]+)\s*\|\s*"
    r"(?P<side>[^|]+?)\s*\|\s*"
    r"(?P<odds>[+-]\d+)\s*\|\s*"
    r"Mkt:\s*(?P<mkt>[\d.]+)%\s*\|\s*"
    r"Model:\s*(?P<model>[\d.]+)%\s*\|\s*"
    r"Edge:\s*(?P<edge>[\d.\-]+)%\s*\|\s*"
    r"Kelly:\s*(?P<kelly>[\d.\-]+)%"
)


class PickDict(TypedDict):
    bet_type: str
    side: str
    odds_american: int
    market_prob: float
    model_prob: float
    edge: float
    kelly_pct: float


class GameDict(TypedDict):
    game_label: str
    picks: list[PickDict]


class CardDict(TypedDict):
    date: str
    games: list[GameDict]


def parse_bet_card(text: str) -> CardDict:
    date_match = HEADER_DATE_RE.search(text)
    if not date_match:
        raise ValueError("Bet card missing date header")

    games: list[GameDict] = []
    current: GameDict | None = None

    for line in text.splitlines():
        if (m := GAME_HEADER_RE.match(line)):
            current = {"game_label": m.group(1), "picks": []}
            games.append(current)
            continue
        if current is not None and (m := PICK_LINE_RE.match(line)):
            current["picks"].append({
                "bet_type": m.group("bet_type"),
                "side": m.group("side").strip(),
                "odds_american": int(m.group("odds")),
                "market_prob": float(m.group("mkt")) / 100.0,
                "model_prob": float(m.group("model")) / 100.0,
                "edge": float(m.group("edge")) / 100.0,
                "kelly_pct": float(m.group("kelly")) / 100.0,
            })

    # Drop games with no parsed picks
    games = [g for g in games if g["picks"]]
    return {"date": date_match.group(1), "games": games}
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
pytest server/tests/test_bet_card_parser.py -v
```

- [ ] **Step 5: Commit**

```bash
git add server/picks/bet_card_parser.py server/tests/test_bet_card_parser.py
git commit -m "feat(server): bet card text parser with TDD against fixture"
```

---

### Task 1.9: Track record from bets.csv (TDD)

**Files:**
- Create: `server/picks/track_record.py`
- Create: `server/tests/test_track_record.py`

- [ ] **Step 1: Failing test**

```python
# server/tests/test_track_record.py
from datetime import date
from pathlib import Path

from server.picks.track_record import compute_30d_record


FIXTURE = Path(__file__).parent / "fixtures" / "bets_example.csv"


def test_compute_30d_record_returns_wins_losses_units():
    # Reference date chosen so the fixture has data within the 30d window.
    result = compute_30d_record(FIXTURE, reference_date=date(2026, 4, 1))
    assert "wins" in result
    assert "losses" in result
    assert "units" in result
    assert isinstance(result["wins"], int)


def test_compute_30d_record_formats_label():
    result = compute_30d_record(FIXTURE, reference_date=date(2026, 4, 1))
    # Example label: "18-12 (+6.1u)"
    assert "-" in result["label"]
    assert "u" in result["label"]
```

- [ ] **Step 2: Run (expect FAIL)**

```bash
pytest server/tests/test_track_record.py -v
```

- [ ] **Step 3: Implement**

```python
# server/picks/track_record.py
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path


def compute_30d_record(csv_path: Path, reference_date: date | None = None) -> dict:
    ref = reference_date or date.today()
    window_start = ref - timedelta(days=30)

    wins = losses = pushes = 0
    units = 0.0

    if not csv_path.exists():
        return {"wins": 0, "losses": 0, "pushes": 0, "units": 0.0, "label": "0-0 (+0.0u)"}

    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                d = date.fromisoformat(row["date"])
            except (KeyError, ValueError):
                continue
            if d < window_start or d > ref:
                continue
            result = (row.get("result") or "").strip().upper()
            try:
                profit = float(row.get("profit") or 0)
            except ValueError:
                profit = 0.0
            if result == "W":
                wins += 1
                units += profit
            elif result == "L":
                losses += 1
                units += profit  # loss profit is typically -1
            elif result == "P":
                pushes += 1

    sign = "+" if units >= 0 else ""
    label = f"{wins}-{losses} ({sign}{units:.1f}u)"
    return {
        "wins": wins, "losses": losses, "pushes": pushes,
        "units": round(units, 2), "label": label,
    }
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
pytest server/tests/test_track_record.py -v
```

- [ ] **Step 5: Commit**

```bash
git add server/picks/track_record.py server/tests/test_track_record.py
git commit -m "feat(server): 30d track record from bets.csv"
```

---

### Task 1.10: Picks reader (orchestrator)

**Files:**
- Create: `server/picks/reader.py`
- Create: `server/tests/test_picks_reader.py`

- [ ] **Step 1: Failing test**

```python
# server/tests/test_picks_reader.py
from datetime import date
from pathlib import Path

from server.picks.reader import PicksReader


def test_picks_reader_returns_ok_when_card_exists(tmp_path: Path):
    fixture_dir = Path(__file__).parent / "fixtures"
    reader = PicksReader(
        bet_card_dir=fixture_dir,
        bets_csv=fixture_dir / "bets_example.csv",
    )
    response = reader.get_picks_for_date(date(2026, 4, 1))
    assert response["status"] == "ok"
    assert len(response["picks"]) > 0


def test_picks_reader_filters_by_kelly_and_tiers(tmp_path: Path):
    fixture_dir = Path(__file__).parent / "fixtures"
    reader = PicksReader(
        bet_card_dir=fixture_dir,
        bets_csv=fixture_dir / "bets_example.csv",
    )
    response = reader.get_picks_for_date(date(2026, 4, 1))
    tiers = {p["tier"] for p in response["picks"]}
    # Fixture has a mix — at least one tier present
    assert tiers <= {"high", "sweet", "lean"}


def test_picks_reader_no_file_returns_empty(tmp_path: Path):
    reader = PicksReader(bet_card_dir=tmp_path, bets_csv=tmp_path / "missing.csv")
    response = reader.get_picks_for_date(date(2026, 4, 1))
    assert response["status"] == "no_picks_today"
    assert response["picks"] == []


def test_picks_reader_get_todays_event_ids_empty_for_missing(tmp_path: Path):
    reader = PicksReader(bet_card_dir=tmp_path, bets_csv=tmp_path / "missing.csv")
    assert reader.get_todays_event_ids(date(2026, 4, 1)) == set()
```

- [ ] **Step 2: Run (expect FAIL)**

```bash
pytest server/tests/test_picks_reader.py -v
```

- [ ] **Step 3: Implement**

```python
# server/picks/reader.py
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

from .bet_card_parser import parse_bet_card, PickDict
from .track_record import compute_30d_record


# Kelly %-based tier cutoffs (Kelly pct stored as fraction: 0.10 = 10%)
KELLY_HIGH = 0.10
KELLY_SWEET = 0.03


def _tier_from_kelly(kelly: float) -> str:
    if kelly >= KELLY_HIGH:
        return "high"
    if kelly >= KELLY_SWEET:
        return "sweet"
    return "lean"


def _stake_from_kelly(kelly: float) -> float:
    """Round Kelly to a half-unit stake."""
    if kelly >= 0.15:
        return 1.5
    if kelly >= 0.07:
        return 1.0
    if kelly >= 0.02:
        return 0.5
    return 0.25


def _market_label(bet_type: str, side: str) -> str:
    readable = bet_type.replace("_", " ").title()
    return f"{readable}: {side}"


def _synthesize_reasoning(pick: PickDict) -> str:
    model_pct = pick["model_prob"] * 100
    market_pct = pick["market_prob"] * 100
    edge_pct = pick["edge"] * 100
    kelly_pct = pick["kelly_pct"] * 100
    return (
        f"Model projects {model_pct:.1f}% probability vs. market-implied "
        f"{market_pct:.1f}% — a {edge_pct:+.1f}% edge. "
        f"Full-Kelly sizing would be {kelly_pct:.1f}%."
    )


def _stable_id(game_label: str, bet_type: str, side: str) -> str:
    raw = f"{game_label}|{bet_type}|{side}".encode()
    return hashlib.md5(raw).hexdigest()[:12]


class PicksReader:
    def __init__(self, bet_card_dir: Path, bets_csv: Path):
        self.bet_card_dir = bet_card_dir
        self.bets_csv = bets_csv

    def _card_path(self, for_date: date) -> Path:
        return self.bet_card_dir / f"bet_card_{for_date.isoformat()}.txt"

    def get_picks_for_date(self, for_date: date) -> dict:
        path = self._card_path(for_date)
        now = datetime.now(timezone.utc)
        if not path.exists():
            return {
                "picks": [],
                "status": "no_picks_today",
                "last_checked_at": now,
                "bet_card_date": None,
            }

        card = parse_bet_card(path.read_text())
        record = compute_30d_record(self.bets_csv, reference_date=for_date)

        picks: list[dict] = []
        for game in card["games"]:
            for p in game["picks"]:
                picks.append({
                    "id": _stable_id(game["game_label"], p["bet_type"], p["side"]),
                    "tier": _tier_from_kelly(p["kelly_pct"]),
                    "game_label": game["game_label"],
                    "market_label": _market_label(p["bet_type"], p["side"]),
                    "pick_side": p["side"],
                    "odds_american": p["odds_american"],
                    "best_book": None,
                    "stake_units": _stake_from_kelly(p["kelly_pct"]),
                    "probability_pct": round(p["model_prob"] * 100, 1),
                    "market_probability_pct": round(p["market_prob"] * 100, 1),
                    "edge_pct": round(p["edge"] * 100, 1),
                    "stats": [
                        {"label": "Mkt", "value": f"{p['market_prob']*100:.1f}%"},
                        {"label": "Model", "value": f"{p['model_prob']*100:.1f}%"},
                        {"label": "Edge", "value": f"{p['edge']*100:+.1f}%"},
                        {"label": "Kelly", "value": f"{p['kelly_pct']*100:.1f}%"},
                    ],
                    "reasoning": _synthesize_reasoning(p),
                    "agent_key": "baseball-agents",
                    "agent_record_30d": record["label"],
                    "commence_time": None,
                })

        # Highest-edge first, then highest-Kelly
        picks.sort(key=lambda p: (-p["edge_pct"], -p["stake_units"]))

        return {
            "picks": picks,
            "status": "ok",
            "last_checked_at": now,
            "bet_card_date": card["date"],
        }

    def get_todays_event_ids(self, for_date: date) -> set[str]:
        """
        Future-use hook referenced in spec §4.3. For v1, bet-card games are
        `AWAY@HOME` team-code pairs, not Odds API event IDs; return an empty
        set and let the fetcher enrich all games for v1.
        """
        return set()
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
pytest server/tests/test_picks_reader.py -v
```

- [ ] **Step 5: Commit**

```bash
git add server/picks/reader.py server/tests/test_picks_reader.py
git commit -m "feat(server): picks reader adapter (bet card → Pick domain)"
```

---

### Task 1.11: Fetcher

**Files:**
- Create: `server/odds/fetcher.py`

- [ ] **Step 1: Write fetcher**

```python
# server/odds/fetcher.py
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import Config
from .cache import OddsCache
from .client import OddsAPIClient, OddsAPIError
from .normalize import normalize_odds_response


logger = logging.getLogger(__name__)


class OddsFetcher:
    def __init__(self, config: Config, cache: OddsCache, client: OddsAPIClient):
        self.config = config
        self.cache = cache
        self.client = client
        self.scheduler = AsyncIOScheduler()
        self._backoff_seconds = 0

    async def tick(self) -> None:
        now = datetime.now(timezone.utc)
        try:
            if self._backoff_seconds > 0:
                await asyncio.sleep(self._backoff_seconds)
            games, rate = await self.client.fetch_mlb_core()
            rows = normalize_odds_response(games, fetched_at=now)
            if rows:
                self.cache.upsert(rows)
            self.cache.set_status(
                last_fetch_at=now,
                requests_used=rate.get("requests_used"),
                requests_remaining=rate.get("requests_remaining"),
                last_error=None,
            )
            self._backoff_seconds = 0
        except OddsAPIError as e:
            logger.exception("Odds API error")
            self.cache.set_status(last_error=str(e))
            self._backoff_seconds = min(30, max(1, self._backoff_seconds * 2 or 1))
        except Exception as e:
            logger.exception("Fetcher unhandled error")
            self.cache.set_status(last_error=repr(e))

    def start(self) -> None:
        self.scheduler.add_job(
            self.tick,
            trigger="interval",
            seconds=self.config.odds_poll_interval,
            next_run_time=datetime.now(timezone.utc),  # tick immediately
        )
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.shutdown(wait=False)
```

- [ ] **Step 2: Commit**

```bash
git add server/odds/fetcher.py
git commit -m "feat(server): odds fetcher scheduled job"
```

---

## Phase 2 — Backend API

### Task 2.1: FastAPI main entry + health

**Files:**
- Create: `server/main.py`
- Create: `server/api/health.py`

- [ ] **Step 1: Write health endpoint**

```python
# server/api/health.py
from __future__ import annotations

from fastapi import APIRouter

from ..models import FetcherStatus
from ..odds.cache import OddsCache


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/health", response_model=FetcherStatus)
    async def health() -> FetcherStatus:
        status = cache.get_status() or {}
        return FetcherStatus(
            last_fetch_at=status.get("last_fetch_at"),
            requests_used=status.get("requests_used"),
            requests_remaining=status.get("requests_remaining"),
            last_error=status.get("last_error"),
        )

    return router
```

- [ ] **Step 2: Write `server/main.py`**

```python
# server/main.py
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Config
from .odds.cache import OddsCache
from .odds.client import OddsAPIClient
from .odds.fetcher import OddsFetcher
from .picks.reader import PicksReader


logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    config = Config.from_env()
    cache = OddsCache(config.cache_db)
    cache.init()
    client = OddsAPIClient(api_key=config.odds_api_key)
    fetcher = OddsFetcher(config, cache, client)
    picks_reader = PicksReader(
        bet_card_dir=config.bet_card_dir,
        bets_csv=config.bets_csv,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if config.odds_api_key:
            fetcher.start()
        else:
            logging.warning("ODDS_API_KEY not set — fetcher not started")
        yield
        fetcher.stop()

    app = FastAPI(title="Betting Site API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # Routers registered in later tasks
    from .api.health import build_router as health_router
    from .api.odds import build_router as odds_router
    from .api.picks import build_router as picks_router

    app.include_router(health_router(cache))
    app.include_router(odds_router(cache))
    app.include_router(picks_router(picks_reader))

    return app


app = create_app()
```

- [ ] **Step 3: Commit**

```bash
git add server/main.py server/api/health.py
git commit -m "feat(server): FastAPI entry with lifespan + health endpoint"
```

---

### Task 2.2: Odds endpoint

**Files:**
- Create: `server/api/odds.py`

- [ ] **Step 1: Write endpoint**

```python
# server/api/odds.py
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ..models import OddsResponse, Game
from ..odds.cache import OddsCache
from ..odds.normalize import rows_to_games


def build_router(cache: OddsCache) -> APIRouter:
    router = APIRouter()

    @router.get("/api/odds/mlb", response_model=OddsResponse)
    async def get_mlb_odds() -> OddsResponse:
        now = datetime.now(timezone.utc)
        rows = cache.all_current()
        game_dicts = rows_to_games(rows, now=now)
        games = [Game.model_validate(g) for g in game_dicts]
        stale = max((g.stale_seconds for g in games), default=0)
        return OddsResponse(games=games, stale_seconds=stale, fetched_at=now)

    return router
```

- [ ] **Step 2: Commit**

```bash
git add server/api/odds.py
git commit -m "feat(server): GET /api/odds/mlb"
```

---

### Task 2.3: Picks endpoint

**Files:**
- Create: `server/api/picks.py`

- [ ] **Step 1: Write endpoint**

```python
# server/api/picks.py
from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from ..models import Pick, PicksResponse
from ..picks.reader import PicksReader


def build_router(reader: PicksReader) -> APIRouter:
    router = APIRouter()

    @router.get("/api/picks/mlb", response_model=PicksResponse)
    async def get_mlb_picks() -> PicksResponse:
        result = reader.get_picks_for_date(date.today())
        picks = [Pick.model_validate(p) for p in result["picks"]]
        return PicksResponse(
            picks=picks,
            status=result["status"],
            last_checked_at=result["last_checked_at"],
            bet_card_date=result["bet_card_date"],
        )

    return router
```

- [ ] **Step 2: Commit**

```bash
git add server/api/picks.py
git commit -m "feat(server): GET /api/picks/mlb"
```

---

### Task 2.4: End-to-end API test

**Files:**
- Create: `server/tests/test_api.py`

- [ ] **Step 1: Write API smoke tests**

```python
# server/tests/test_api.py
import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

import pytest


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ODDS_API_KEY", "")  # disables fetcher
    monkeypatch.setenv("BET_CARD_DIR", str(Path(__file__).parent / "fixtures"))
    monkeypatch.setenv("BETS_CSV", str(Path(__file__).parent / "fixtures" / "bets_example.csv"))
    monkeypatch.setenv("HOST", "127.0.0.1")
    # Use an isolated cache.db per test run
    import server.config as config_mod

    original_from_env = config_mod.Config.from_env

    def patched_from_env():
        c = original_from_env()
        object.__setattr__(c, "cache_db", tmp_path / "cache.db")
        return c

    monkeypatch.setattr(config_mod.Config, "from_env", staticmethod(patched_from_env))

    from server.main import create_app
    return create_app()


def test_health_endpoint(app):
    with TestClient(app) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    assert "last_fetch_at" in r.json()


def test_odds_endpoint_empty_cache(app):
    with TestClient(app) as c:
        r = c.get("/api/odds/mlb")
    assert r.status_code == 200
    body = r.json()
    assert body["games"] == []
    assert body["stale_seconds"] == 0


def test_picks_endpoint_returns_ok_for_fixture_date(app, monkeypatch):
    # Today (runtime) likely doesn't have a bet card — test the "no picks" path
    with TestClient(app) as c:
        r = c.get("/api/picks/mlb")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "no_picks_today")
```

- [ ] **Step 2: Run all backend tests**

```bash
pytest server/tests -v
```

- [ ] **Step 3: Commit**

```bash
git add server/tests/test_api.py
git commit -m "test(server): end-to-end API smoke tests"
```

---

### Task 2.5: Boot the backend + capture OpenAPI

**Files:**
- None new. Start the server.

- [ ] **Step 1: Launch the backend**

```bash
cd /Users/mikeborucki/personal_workspace/betting-site
source .venv/bin/activate
uvicorn server.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
sleep 2
```

- [ ] **Step 2: Verify endpoints respond**

```bash
curl -s http://127.0.0.1:8000/api/health | head -c 200
echo
curl -s http://127.0.0.1:8000/api/odds/mlb | head -c 200
echo
curl -s http://127.0.0.1:8000/api/picks/mlb | head -c 200
echo
```

Expected: each returns a JSON body (not an HTTP error).

- [ ] **Step 3: Capture `openapi.json`**

```bash
curl -s http://127.0.0.1:8000/openapi.json > web/openapi.json
```

- [ ] **Step 4: Stop server**

```bash
kill $BACKEND_PID 2>/dev/null || true
```

- [ ] **Step 5: Commit**

```bash
git add web/openapi.json
git commit -m "chore: capture OpenAPI schema snapshot for frontend codegen"
```

---

## Phase 3 — Frontend Foundation

### Task 3.1: Generate TS types

**Files:**
- Create: `web/scripts/gen-types.sh`
- Create: `web/types/api.ts` (generated)
- Modify: `web/package.json` (add script)

- [ ] **Step 1: Write `web/scripts/gen-types.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
npx openapi-typescript openapi.json --output types/api.ts
```

- [ ] **Step 2: Make executable + run**

```bash
cd web
chmod +x scripts/gen-types.sh
./scripts/gen-types.sh
```

- [ ] **Step 3: Add npm script to `web/package.json`**

```json
"scripts": {
  "gen:types": "bash scripts/gen-types.sh",
  ...
}
```

- [ ] **Step 4: Commit**

```bash
git add web/scripts/gen-types.sh web/types/api.ts web/package.json
git commit -m "chore(web): generate TS types from OpenAPI"
```

---

### Task 3.2: API client + SWR config + formatters

**Files:**
- Create: `web/lib/api.ts`
- Create: `web/lib/swr.ts`
- Create: `web/lib/format.ts`

- [ ] **Step 1: Write `web/lib/api.ts`**

```ts
import type { components, paths } from "@/types/api";

export type OddsResponse = components["schemas"]["OddsResponse"];
export type PicksResponse = components["schemas"]["PicksResponse"];
export type Game = components["schemas"]["Game"];
export type Pick = components["schemas"]["Pick"];
export type Market = components["schemas"]["Market"];
export type MarketOutcome = components["schemas"]["MarketOutcome"];
export type BookPrice = components["schemas"]["BookPrice"];
export type FetcherStatus = components["schemas"]["FetcherStatus"];

const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const apiPaths = {
  odds: "/api/odds/mlb",
  picks: "/api/picks/mlb",
  health: "/api/health",
} as const;
```

- [ ] **Step 2: Write `web/lib/swr.tsx`** (JSX → must be `.tsx`, not `.ts`)

```tsx
"use client";
import { SWRConfig, type SWRConfiguration } from "swr";
import { fetchJson } from "./api";
import type { ReactNode } from "react";

const base: SWRConfiguration = {
  fetcher: fetchJson,
  revalidateOnFocus: true,
  keepPreviousData: true,
  dedupingInterval: 5_000,
};

export function SwrProvider({ children }: { children: ReactNode }) {
  return <SWRConfig value={base}>{children}</SWRConfig>;
}

export const intervals = {
  odds: 15_000,
  picks: 60_000,
  health: 30_000,
} as const;
```

- [ ] **Step 3: Write `web/lib/format.ts`**

```ts
export function formatAmerican(odds: number): string {
  if (odds === 0) return "-";
  return odds > 0 ? `+${odds}` : `${odds}`;
}

export function formatUnits(u: number): string {
  return `${u.toFixed(u % 1 === 0 ? 0 : 1)}u`;
}

export function formatPct(p: number, signed = false): string {
  const s = `${p.toFixed(1)}%`;
  return signed && p > 0 ? `+${s}` : s;
}

export function timeAgo(iso: string): string {
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export function formatBookAbbrev(key: string): string {
  const map: Record<string, string> = {
    draftkings: "DK",
    fanduel: "FD",
    betmgm: "MGM",
    caesars: "CZR",
    fanatics: "FAN",
    hardrockbet: "HRB",
    espnbet: "ESPN",
    pointsbetus: "PB",
  };
  return map[key] ?? key.slice(0, 3).toUpperCase();
}
```

- [ ] **Step 4: Commit**

```bash
git add web/lib/
git commit -m "feat(web): typed API client, SWR provider, formatters"
```

---

### Task 3.3: Nav shell + stale indicator + root layout update

**Files:**
- Create: `web/components/nav-shell.tsx`
- Create: `web/components/stale-indicator.tsx`
- Modify: `web/app/layout.tsx`
- Modify: `web/app/page.tsx` (redirect)

- [ ] **Step 1: `web/components/nav-shell.tsx`**

```tsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const tabs = [
  { href: "/odds/mlb", label: "Odds" },
  { href: "/picks/mlb", label: "Picks" },
];

export function NavShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border-subtle bg-bg-1">
        <div className="max-w-[1600px] mx-auto px-6 py-3 flex items-center gap-6">
          <div className="text-sm font-semibold tracking-wide">
            <span className="text-accent">◆</span> <span className="text-text-1">betting site</span>
          </div>
          <nav className="flex gap-5 text-sm">
            {tabs.map(t => (
              <Link
                key={t.href}
                href={t.href}
                className={clsx(
                  "py-1 transition-colors",
                  pathname === t.href
                    ? "text-text-1 border-b-2 border-accent"
                    : "text-text-2 hover:text-text-1"
                )}
              >
                {t.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto text-xs text-text-3">MLB · laptop build</div>
        </div>
      </header>
      <main className="flex-1 max-w-[1600px] mx-auto w-full px-6 py-4">
        {children}
      </main>
    </div>
  );
}
```

- [ ] **Step 2: `web/components/stale-indicator.tsx`**

```tsx
"use client";
import clsx from "clsx";

export function StaleIndicator({ staleSeconds }: { staleSeconds: number }) {
  const stale = staleSeconds > 90;
  const label =
    staleSeconds < 5 ? "live"
    : staleSeconds < 60 ? `${staleSeconds}s old`
    : `${Math.floor(staleSeconds / 60)}m ${staleSeconds % 60}s old`;
  return (
    <span className={clsx(
      "inline-flex items-center gap-1.5 text-xs tabular",
      stale ? "text-flash" : "text-text-2"
    )}>
      <span className={clsx(
        "inline-block w-1.5 h-1.5 rounded-full",
        stale ? "bg-flash" : "bg-price-up"
      )} />
      Updated {label}
    </span>
  );
}
```

- [ ] **Step 3: Update `web/app/layout.tsx` to wrap with SwrProvider + NavShell**

```tsx
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { SwrProvider } from "@/lib/swr";
import { NavShell } from "@/components/nav-shell";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "Betting Site",
  description: "MLB odds + agent picks",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="font-sans bg-bg-0 text-text-1 antialiased">
        <SwrProvider>
          <NavShell>{children}</NavShell>
        </SwrProvider>
      </body>
    </html>
  );
}
```

- [ ] **Step 4: Redirect `/` to `/odds/mlb` — overwrite `web/app/page.tsx`**

```tsx
import { redirect } from "next/navigation";
export default function Page() { redirect("/odds/mlb"); }
```

- [ ] **Step 5: Commit**

```bash
git add web/components/nav-shell.tsx web/components/stale-indicator.tsx web/app/layout.tsx web/app/page.tsx
git commit -m "feat(web): nav shell, stale indicator, root redirect"
```

---

## Phase 4 — Odds Page

### Task 4.1: Market tabs + best-cell + cell flash

**Files:**
- Create: `web/components/odds-grid/market-tabs.tsx`
- Create: `web/components/odds-grid/best-cell.tsx`
- Create: `web/components/odds-grid/cell-flash.tsx`
- Create: `web/lib/use-flash-diff.ts`

- [ ] **Step 1: `web/components/odds-grid/market-tabs.tsx`**

```tsx
"use client";
import clsx from "clsx";

export type MarketKey = "h2h" | "spreads" | "totals";

const tabs: { key: MarketKey; label: string }[] = [
  { key: "h2h", label: "Moneyline" },
  { key: "spreads", label: "Run Line" },
  { key: "totals", label: "Total" },
];

export function MarketTabs({ value, onChange }: { value: MarketKey; onChange: (k: MarketKey) => void }) {
  return (
    <div className="inline-flex rounded-md bg-bg-1 border border-border-subtle p-0.5">
      {tabs.map(t => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={clsx(
            "px-3 py-1 text-xs tracking-wide uppercase transition-colors rounded-sm",
            value === t.key ? "bg-bg-2 text-text-1" : "text-text-2 hover:text-text-1"
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: `web/components/odds-grid/cell-flash.tsx`**

```tsx
"use client";
import { useEffect, useRef } from "react";

export function CellFlash({
  value,
  flashKey,
  children,
}: {
  value: number;
  flashKey: string;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const last = useRef(value);
  useEffect(() => {
    if (last.current !== value) {
      const el = ref.current;
      if (el) {
        el.animate(
          [
            { backgroundColor: "rgba(245,165,36,0.35)" },
            { backgroundColor: "rgba(245,165,36,0)" },
          ],
          { duration: 30_000, easing: "ease-out" }
        );
      }
      last.current = value;
    }
  }, [value, flashKey]);
  return (
    <span ref={ref} className="inline-block px-1 rounded-sm">
      {children}
    </span>
  );
}
```

- [ ] **Step 3: `web/components/odds-grid/best-cell.tsx`**

```tsx
"use client";
import { formatAmerican, formatBookAbbrev } from "@/lib/format";

export function BestCell({ price, book }: { price: number; book: string }) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="text-price-up font-semibold tabular">{formatAmerican(price)}</span>
      <span className="text-text-3 text-[10px] uppercase tracking-wide">{formatBookAbbrev(book)}</span>
    </span>
  );
}
```

- [ ] **Step 4: `web/lib/use-flash-diff.ts`**

```ts
"use client";
import { useRef } from "react";

/**
 * Build a stable cell key from (event_id, book, market, outcome, point)
 * matching the backend primary key tuple.
 */
export function cellKey(parts: {
  event_id: string;
  bookmaker_key: string;
  market_key: string;
  outcome_name: string;
  point: number | null;
}): string {
  return [
    parts.event_id,
    parts.bookmaker_key,
    parts.market_key,
    parts.outcome_name,
    parts.point ?? "",
  ].join("|");
}

export function useDiffMap<T>(value: T): { prev: T | null; current: T } {
  const ref = useRef<T | null>(null);
  const prev = ref.current;
  ref.current = value;
  return { prev, current: value };
}
```

- [ ] **Step 5: Commit**

```bash
git add web/components/odds-grid/ web/lib/use-flash-diff.ts
git commit -m "feat(web): odds-grid building blocks (market tabs, cell flash, best cell)"
```

---

### Task 4.2: Odds grid table

**Files:**
- Create: `web/components/odds-grid/index.tsx`

- [ ] **Step 1: `web/components/odds-grid/index.tsx`**

```tsx
"use client";
import { useMemo, useState } from "react";
import clsx from "clsx";

import type { Game, Market, MarketOutcome } from "@/lib/api";
import { formatAmerican, formatBookAbbrev } from "@/lib/format";
import { MarketTabs, type MarketKey } from "./market-tabs";
import { BestCell } from "./best-cell";
import { CellFlash } from "./cell-flash";
import { cellKey } from "@/lib/use-flash-diff";


const BOOK_ORDER = [
  "draftkings", "fanduel", "betmgm", "caesars",
  "fanatics", "hardrockbet", "espnbet", "pointsbetus",
];

function findMarket(game: Game, key: MarketKey): Market | undefined {
  return game.markets?.find(m => m.market_key === key);
}

function priceAtBook(outcome: MarketOutcome | undefined, bookKey: string) {
  return outcome?.prices.find(p => p.bookmaker_key === bookKey);
}

function primaryOutcome(market: Market | undefined, game: Game): MarketOutcome | undefined {
  if (!market) return undefined;
  if (market.market_key === "h2h" || market.market_key === "spreads") {
    return market.outcomes.find(o => o.outcome_name === game.home_team) ?? market.outcomes[0];
  }
  if (market.market_key === "totals") {
    return market.outcomes.find(o => o.outcome_name === "Over") ?? market.outcomes[0];
  }
  return market.outcomes[0];
}

export function OddsGrid({ games }: { games: Game[] }) {
  const [market, setMarket] = useState<MarketKey>("h2h");

  const books = useMemo(() => {
    const present = new Set<string>();
    for (const g of games) for (const m of g.markets ?? [])
      for (const o of m.outcomes) for (const p of o.prices) present.add(p.bookmaker_key);
    return BOOK_ORDER.filter(b => present.has(b)).concat(
      [...present].filter(b => !BOOK_ORDER.includes(b)).sort()
    );
  }, [games]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-4">
        <MarketTabs value={market} onChange={setMarket} />
        <div className="text-xs text-text-3 tabular">{games.length} games</div>
      </div>

      <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
        <table className="w-full text-xs">
          <thead className="bg-bg-1 text-text-2">
            <tr>
              <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px]">Game</th>
              <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Best</th>
              {books.map(b => (
                <th key={b} className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">
                  {formatBookAbbrev(b)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {games.length === 0 && (
              <tr>
                <td colSpan={2 + books.length} className="text-center py-12 text-text-3">
                  No MLB odds cached yet. Waiting for fetcher...
                </td>
              </tr>
            )}
            {games.map(g => {
              const m = findMarket(g, market);
              const out = primaryOutcome(m, g);
              const best = out?.best_price;
              return (
                <tr key={g.event_id} className="border-t border-border-subtle hover:bg-bg-1/40">
                  <td className="px-3 py-2 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <span className="text-text-1 font-medium">{abbrev(g.away_team)} @ {abbrev(g.home_team)}</span>
                      {g.is_live ? (
                        <span className="text-price-down text-[10px] font-semibold uppercase tracking-wide">· live</span>
                      ) : (
                        <span className="text-text-3 text-[11px]">
                          · {new Date(g.commence_time).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="text-right px-2 py-2 tabular">
                    {best ? <BestCell price={best.price_american} book={best.bookmaker_key} /> : <span className="text-text-3">—</span>}
                  </td>
                  {books.map(b => {
                    const p = priceAtBook(out, b);
                    if (!p) return <td key={b} className="text-right px-2 py-2 text-text-3 tabular">—</td>;
                    const isBest = best && p.bookmaker_key === best.bookmaker_key && p.price_american === best.price_american;
                    const key = cellKey({
                      event_id: g.event_id,
                      bookmaker_key: p.bookmaker_key,
                      market_key: market,
                      outcome_name: out!.outcome_name,
                      point: (p.point ?? null) as number | null,
                    });
                    return (
                      <td key={b} className={clsx("text-right px-2 py-2 tabular", isBest ? "text-price-up font-semibold" : "text-text-1")}>
                        <CellFlash value={p.price_american} flashKey={key}>
                          {formatAmerican(p.price_american)}
                        </CellFlash>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function abbrev(team: string): string {
  // MLB team abbrevs map — fallback to first 3 letters upper-cased
  const map: Record<string, string> = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS", "Chicago Cubs": "CHC", "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers": "DET", "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY", "Oakland Athletics": "OAK", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "Seattle Mariners": "SEA",
    "San Francisco Giants": "SF", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
  };
  return map[team] ?? team.split(" ").map(w => w[0]).join("").slice(0, 3).toUpperCase();
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/odds-grid/index.tsx
git commit -m "feat(web): odds grid table"
```

---

### Task 4.3: `/odds/mlb` page

**Files:**
- Create: `web/app/odds/mlb/page.tsx`

- [ ] **Step 1: Write the page**

```tsx
"use client";
import useSWR from "swr";
import { apiPaths, type OddsResponse } from "@/lib/api";
import { intervals } from "@/lib/swr";
import { OddsGrid } from "@/components/odds-grid";
import { StaleIndicator } from "@/components/stale-indicator";

export default function OddsMlbPage() {
  const { data, error, isLoading } = useSWR<OddsResponse>(
    apiPaths.odds,
    { refreshInterval: intervals.odds }
  );

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold">MLB Odds</h1>
          <span className="text-xs text-text-3 tabular">
            {data ? `${new Date().toLocaleDateString([], { month: "short", day: "numeric" })}` : ""}
          </span>
        </div>
        <div>{data && <StaleIndicator staleSeconds={data.stale_seconds ?? 0} />}</div>
      </header>

      {error && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && <div className="text-text-2 text-sm">Loading odds…</div>}
      {data && <OddsGrid games={data.games ?? []} />}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/app/odds/mlb/page.tsx
git commit -m "feat(web): /odds/mlb page"
```

---

## Phase 5 — Picks Page

### Task 5.1: Tier badge + expanded row

**Files:**
- Create: `web/components/picks-table/tier-badge.tsx`
- Create: `web/components/picks-table/expanded-row.tsx`

- [ ] **Step 1: `tier-badge.tsx`**

```tsx
import clsx from "clsx";
import type { components } from "@/types/api";

type Tier = components["schemas"]["PickTier"];

const TIER_CLASSES: Record<string, string> = {
  high: "bg-price-up/15 text-price-up",
  sweet: "bg-violet-accent/15 text-violet-accent",
  lean: "bg-flash/15 text-flash",
};

const TIER_LABELS: Record<string, string> = {
  high: "High",
  sweet: "Sweet",
  lean: "Lean",
};

export function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span className={clsx(
      "inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide",
      TIER_CLASSES[tier]
    )}>
      {TIER_LABELS[tier]}
    </span>
  );
}
```

- [ ] **Step 2: `expanded-row.tsx`**

```tsx
import type { Pick } from "@/lib/api";

export function ExpandedRow({ pick }: { pick: Pick }) {
  return (
    <div className="border-l-2 border-accent pl-4 py-3 bg-bg-1/50 text-xs">
      <div className="flex gap-4 mb-2 flex-wrap">
        {pick.stats?.map(s => (
          <span key={s.label} className="text-text-2">
            {s.label} <span className="text-text-1 font-semibold">{s.value}</span>
          </span>
        ))}
      </div>
      <p className="text-text-2 leading-relaxed max-w-3xl">{pick.reasoning}</p>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add web/components/picks-table/
git commit -m "feat(web): picks table — tier badge + expanded row"
```

---

### Task 5.2: Picks table

**Files:**
- Create: `web/components/picks-table/index.tsx`

- [ ] **Step 1: Write**

```tsx
"use client";
import { useState, Fragment } from "react";
import clsx from "clsx";

import type { Pick } from "@/lib/api";
import { formatAmerican, formatPct, formatUnits } from "@/lib/format";
import { TierBadge } from "./tier-badge";
import { ExpandedRow } from "./expanded-row";


export function PicksTable({ picks }: { picks: Pick[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (picks.length === 0) {
    return (
      <div className="text-center text-text-3 py-16 text-sm">
        The agent hasn't produced picks for today yet.
      </div>
    );
  }

  return (
    <div className="border border-border-subtle rounded-md overflow-hidden bg-bg-0">
      <table className="w-full text-xs">
        <thead className="bg-bg-1 text-text-2">
          <tr>
            <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px]">Tier</th>
            <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Game</th>
            <th className="text-left px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Pick</th>
            <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Odds</th>
            <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Prob</th>
            <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Edge</th>
            <th className="text-right px-2 py-2 font-medium uppercase tracking-wide text-[11px]">Stake</th>
            <th className="text-left px-3 py-2 font-medium uppercase tracking-wide text-[11px]">Agent · 30d</th>
          </tr>
        </thead>
        <tbody>
          {picks.map(p => {
            const open = expandedId === p.id;
            return (
              <Fragment key={p.id}>
                <tr
                  onClick={() => setExpandedId(open ? null : p.id)}
                  className={clsx(
                    "border-t border-border-subtle cursor-pointer transition-colors",
                    open ? "bg-bg-1" : "hover:bg-bg-1/40"
                  )}
                >
                  <td className="px-3 py-2"><TierBadge tier={p.tier} /></td>
                  <td className="px-2 py-2 text-text-1">{p.game_label}</td>
                  <td className="px-2 py-2 text-text-1">{p.market_label}</td>
                  <td className="px-2 py-2 text-right tabular">{formatAmerican(p.odds_american)}</td>
                  <td className="px-2 py-2 text-right tabular font-semibold">{formatPct(p.probability_pct)}</td>
                  <td className="px-2 py-2 text-right tabular font-semibold text-price-up">
                    {formatPct(p.edge_pct, true)}
                  </td>
                  <td className="px-2 py-2 text-right tabular text-accent font-semibold">
                    {formatUnits(p.stake_units)}
                  </td>
                  <td className="px-3 py-2 text-text-2">
                    <span className="text-text-1">{p.agent_key}</span>
                    {p.agent_record_30d && <span className="text-text-3"> · {p.agent_record_30d}</span>}
                  </td>
                </tr>
                {open && (
                  <tr className="bg-bg-1/30">
                    <td colSpan={8} className="px-3 py-0"><ExpandedRow pick={p} /></td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/components/picks-table/index.tsx
git commit -m "feat(web): picks table with expand-on-click"
```

---

### Task 5.3: `/picks/mlb` page

**Files:**
- Create: `web/app/picks/mlb/page.tsx`

- [ ] **Step 1: Write**

```tsx
"use client";
import useSWR from "swr";
import { apiPaths, type PicksResponse } from "@/lib/api";
import { intervals } from "@/lib/swr";
import { PicksTable } from "@/components/picks-table";

export default function PicksMlbPage() {
  const { data, error, isLoading } = useSWR<PicksResponse>(
    apiPaths.picks,
    { refreshInterval: intervals.picks }
  );

  return (
    <div className="flex flex-col gap-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold">MLB Picks</h1>
          {data?.bet_card_date && (
            <span className="text-xs text-text-3 tabular">Bet card: {data.bet_card_date}</span>
          )}
          {data?.status === "no_picks_today" && (
            <span className="text-xs text-flash">No picks today</span>
          )}
        </div>
        <div className="text-xs text-text-3">
          Agent: <span className="text-text-1">baseball-agents</span>
        </div>
      </header>

      {error && (
        <div className="text-price-down text-sm">
          Backend unreachable. Is the FastAPI server running on :8000?
        </div>
      )}
      {isLoading && !data && <div className="text-text-2 text-sm">Loading picks…</div>}
      {data && <PicksTable picks={data.picks ?? []} />}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add web/app/picks/mlb/page.tsx
git commit -m "feat(web): /picks/mlb page"
```

---

## Phase 6 — Verification & Polish

### Task 6.1: Backend test suite green

- [ ] **Step 1: Run full backend suite**

```bash
source /Users/mikeborucki/personal_workspace/betting-site/.venv/bin/activate
pytest server/tests -v
```

Expected: all tests pass.

- [ ] **Step 2: If any fail, fix root cause and re-run. Do not skip.**

---

### Task 6.2: Frontend typecheck + build smoke

- [ ] **Step 1: Typecheck**

```bash
cd web
npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 2: Production build**

```bash
cd web
npm run build
```

Expected: build succeeds.

- [ ] **Step 3: If either fails, fix and re-run.**

---

### Task 6.3: End-to-end: both services boot and render

- [ ] **Step 1: Start backend**

```bash
cd /Users/mikeborucki/personal_workspace/betting-site
source .venv/bin/activate
uvicorn server.main:app --host 127.0.0.1 --port 8000 &
echo $! > /tmp/betting-backend.pid
sleep 3
```

- [ ] **Step 2: Start frontend**

```bash
cd web
npm run dev > /tmp/betting-frontend.log 2>&1 &
echo $! > /tmp/betting-frontend.pid
sleep 6
```

- [ ] **Step 3: Verify endpoints + pages**

```bash
curl -sf http://127.0.0.1:8000/api/health >/dev/null && echo "backend OK"
curl -sf http://127.0.0.1:8000/api/odds/mlb >/dev/null && echo "odds OK"
curl -sf http://127.0.0.1:8000/api/picks/mlb >/dev/null && echo "picks OK"
curl -sf http://127.0.0.1:3000/odds/mlb >/dev/null && echo "frontend /odds/mlb OK"
curl -sf http://127.0.0.1:3000/picks/mlb >/dev/null && echo "frontend /picks/mlb OK"
```

Expected: 5 "OK" lines.

- [ ] **Step 4: Write README with run instructions**

Create `README.md`:

```markdown
# Betting Site — MLB MVP

Personal odds aggregator + picks viewer. Laptop-only, local-only, no auth.

## Run

```bash
# 1. Backend (terminal A)
source .venv/bin/activate
uvicorn server.main:app --host 127.0.0.1 --port 8000

# 2. Frontend (terminal B)
cd web
npm run dev
```

Open http://localhost:3000 — redirects to `/odds/mlb`.

## Env

Edit `.env` (copy from `.env.example`). Requires `ODDS_API_KEY`.

## Tests

```bash
pytest server/tests -v        # backend
cd web && npx tsc --noEmit    # frontend typecheck
```
```

- [ ] **Step 5: Final commit**

```bash
git add README.md
git commit -m "docs: README with run/test instructions"
```

- [ ] **Step 6: Leave services running for the user to open in browser**

The backend is on PID in `/tmp/betting-backend.pid`, frontend in `/tmp/betting-frontend.pid`. User opens `http://localhost:3000`.

---

## Done. Report back with:
- Number of backend tests passing
- Frontend typecheck + build status
- URL to open
- Known follow-ups (e.g., if Odds API key was missing, fetcher is idle and grid will show empty state — that's expected)
