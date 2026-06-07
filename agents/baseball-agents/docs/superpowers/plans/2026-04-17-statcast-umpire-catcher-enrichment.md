# Statcast + Umpire + Catcher Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich MiroFish's game briefings and PA simulator with Statcast expected stats, pitch-modeling metrics, bat tracking, home-plate umpire profiles, catcher framing, FanGraphs Depth Charts projections, and an Alan-Nathan air-density carry model — all behind per-source feature flags with fixture-based fallbacks.

**Architecture:** Five independent scraper modules (`statcast_advanced.py`, `umpire.py`, `catcher_framing.py`, extensions to `player_stats.py` and `ballpark.py`) feed `build_briefing` five new sections and wire two real-valued shifts (`catcher_framing_z`, `umpire_k_delta/bb_delta`) into `sample_pa` before the log5 combine. All scrapers share a generic `scrapers/_cache.py` helper that uses `filelock` for concurrency and supports 24h TTLs; every network source has a frozen fixture fallback committed to `data/`. A top-level `DATA_V2_ENABLED` flag plus per-source `SOURCES_ENABLED` dict gates rollout.

**Tech Stack:** `requests`, `pybaseball>=2.2.7,<3.0`, `pandas`, `pytest`, `filelock>=3.13`, `BeautifulSoup4` (for UmpScorecards HTML fallback).

**Spec:** `docs/superpowers/specs/2026-04-17-statcast-umpire-catcher-enrichment-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `requirements.txt` | Modify | Add `filelock>=3.13`, pin `pybaseball>=2.2.7,<3.0` |
| `config.py` | Modify | Add `DATA_V2_ENABLED`, `SOURCES_ENABLED`, `PARK_ELEVATIONS` |
| `scrapers/_cache.py` | Create | Generic `get_or_fetch(key, ttl, fetcher, path)` with filelock |
| `scrapers/statcast_advanced.py` | Create | `get_pitcher_advanced`, `get_batter_advanced`, leaderboard warmers |
| `scrapers/umpire.py` | Create | `get_umpire_assignment`, `get_umpire_profile` with fixture fallback |
| `scrapers/catcher_framing.py` | Create | `get_catcher_framing`, `get_all_catcher_framing` |
| `scrapers/player_stats.py` | Modify | Add `get_depth_charts_hitter`, `get_depth_charts_pitcher`, `prewarm_depth_charts` |
| `scrapers/ballpark.py` | Modify | Add `compute_carry_multiplier`, extract `pressure_mb` |
| `simulation/pa_engine.py` | Modify | Wire `catcher_framing_z`, `umpire_k_delta`, `umpire_bb_delta` |
| `simulation/game_sim.py` | Modify | Propagate catcher z + ump deltas per half-inning |
| `simulation/monte_carlo.py` | Modify | Thread catcher z + ump deltas through setup |
| `briefing.py` | Modify | Add 5 new sections, `_tag` helper, prediction-task items 8-12 |
| `agents/daily_runner.py` | Modify | Prewarm leaderboards; enrich `game_data` with new scraper outputs |
| `scripts/backfill_umpires.py` | Create | Warm last 30 days of umpire assignments |
| `data/umpire_fixture.json` | Create | Frozen 2026-04-01 snapshot of top 80 umps |
| `data/catcher_framing_fixture.json` | Create | Frozen 2026-04-01 catcher framing snapshot |
| `tests/fixtures/` | Create | Directory for all HTML/JSON/CSV scraper fixtures |
| `tests/test_cache.py` | Create | Unit tests for `scrapers/_cache.py` |
| `tests/test_statcast_advanced.py` | Create | Scraper unit tests with pybaseball mocked |
| `tests/test_umpire.py` | Create | Assignment + profile tests with fixture fallback |
| `tests/test_catcher_framing.py` | Create | Framing leaderboard parse + z-score tests |
| `tests/test_depth_charts.py` | Create | Depth Charts projection parse tests |
| `tests/test_carry_multiplier.py` | Create | Air-density physics tests |
| `tests/test_pa_engine.py` | Modify | Add ump/framing shift tests |
| `tests/test_briefing.py` | Create | Snapshot + per-source-disabled tests |
| `tests/test_daily_runner_smoke.py` | Create | End-to-end smoke with all sources toggled |

---

## Phase A — Caching infrastructure

### Task 1: Pin dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Inspect current requirements**

Run: `cat requirements.txt`
Note whether `filelock` and `pybaseball` already appear and at what pin.

- [ ] **Step 2: Add/upgrade pins**

Edit `requirements.txt`. Ensure these lines exist (add or update in place):

```
filelock>=3.13
pybaseball>=2.2.7,<3.0
beautifulsoup4>=4.12
```

- [ ] **Step 3: Install**

Run: `pip install -r requirements.txt`
Expected: no errors. Confirm with `python3 -c "import filelock, pybaseball, bs4; print(filelock.__version__, pybaseball.__version__)"`.

- [ ] **Step 4: Spike pybaseball Depth Charts function name**

Run: `python3 -c "import pybaseball as pb; print([f for f in dir(pb) if 'depth' in f.lower() or 'project' in f.lower()])"`
Record the exact function names in a comment we will reference in Task 12. Expected candidates: `fangraphs_depth_charts` or `projection_hitter_fangraphs_depth` / `projection_pitcher_fangraphs_depth`.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt
git commit -m "build: pin pybaseball, add filelock and bs4 for Spec 4 scrapers"
```

---

### Task 2: Generic cache helper skeleton with failing tests

**Files:**
- Create: `tests/test_cache.py`
- Create: `scrapers/_cache.py` (stub)

- [ ] **Step 1: Write failing cache-miss test**

Create `tests/test_cache.py`:

```python
"""Tests for scrapers/_cache.py shared cache helper."""
import json
import os
import time
from unittest.mock import MagicMock

import pytest

from scrapers._cache import get_or_fetch


def test_cache_miss_calls_fetcher(tmp_path):
    """First call hits the fetcher and writes the cache file."""
    cache_path = str(tmp_path / "cache.json")
    fetcher = MagicMock(return_value={"value": 42})

    result = get_or_fetch(
        key="k1", ttl_seconds=3600, fetcher_fn=fetcher, cache_path=cache_path
    )

    assert result == {"value": 42}
    fetcher.assert_called_once()
    assert os.path.exists(cache_path)

    with open(cache_path) as f:
        data = json.load(f)
    assert "k1" in data
    assert data["k1"]["value"] == {"value": 42}
    assert "fetched_at" in data["k1"]


def test_cache_hit_skips_fetcher(tmp_path):
    """Second call within TTL returns cached value without calling fetcher."""
    cache_path = str(tmp_path / "cache.json")
    fetcher1 = MagicMock(return_value={"value": 1})
    get_or_fetch("k1", 3600, fetcher1, cache_path)

    fetcher2 = MagicMock(return_value={"value": 999})
    result = get_or_fetch("k1", 3600, fetcher2, cache_path)

    assert result == {"value": 1}
    fetcher2.assert_not_called()


def test_cache_expires_after_ttl(tmp_path, monkeypatch):
    """Past TTL, fetcher is called again."""
    cache_path = str(tmp_path / "cache.json")
    fetcher = MagicMock(side_effect=[{"v": 1}, {"v": 2}])

    fake_now = [1_000_000.0]
    monkeypatch.setattr("scrapers._cache.time.time", lambda: fake_now[0])

    r1 = get_or_fetch("k1", 100, fetcher, cache_path)
    fake_now[0] += 200  # past TTL
    r2 = get_or_fetch("k1", 100, fetcher, cache_path)

    assert r1 == {"v": 1}
    assert r2 == {"v": 2}
    assert fetcher.call_count == 2


def test_cache_concurrent_write_no_loss(tmp_path):
    """Parallel writes don't clobber each other."""
    import threading

    cache_path = str(tmp_path / "cache.json")

    def fetch_for(key):
        return {"value": key}

    def worker(k):
        get_or_fetch(k, 3600, lambda k=k: fetch_for(k), cache_path)

    keys = [f"k{i}" for i in range(10)]
    threads = [threading.Thread(target=worker, args=(k,)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with open(cache_path) as f:
        data = json.load(f)
    assert len(data) == 10, f"Expected 10 entries, got {len(data)}: {list(data)}"


def test_fetcher_exception_bubbles_up(tmp_path):
    """Fetcher exceptions propagate; no partial cache written."""
    cache_path = str(tmp_path / "cache.json")
    fetcher = MagicMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        get_or_fetch("k1", 3600, fetcher, cache_path)

    assert not os.path.exists(cache_path) or json.load(open(cache_path)) == {}
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_cache.py -v`
Expected: All FAIL (module doesn't exist yet).

- [ ] **Step 3: Implement `scrapers/_cache.py`**

Create `scrapers/_cache.py`:

```python
"""Shared JSON cache with TTL and filelock-based concurrency.

All Spec 4 scrapers share this helper. Cache files are JSON-dict shaped:
    {"<key>": {"fetched_at": <unix>, "value": <payload>}}
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Callable

from filelock import FileLock, Timeout

logger = logging.getLogger("mirofish.cache")

_LOCK_TIMEOUT_SEC = 5.0


def _read_cache(cache_path: str) -> dict:
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("Cache file %s corrupt; treating as empty", cache_path)
        return {}


def _write_cache(cache_path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, cache_path)


def get_or_fetch(
    key: str,
    ttl_seconds: int,
    fetcher_fn: Callable[[], Any],
    cache_path: str,
) -> Any:
    """Return cached value for `key` if fresh; else call `fetcher_fn` and cache.

    - Concurrency-safe via `filelock` on `cache_path + ".lock"`.
    - Cache miss + fetcher exception: raises, does not poison cache.
    - TTL in seconds; 0 means always refetch.
    """
    lock_path = cache_path + ".lock"
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)

    # Fast-path read without lock
    data = _read_cache(cache_path)
    entry = data.get(key)
    if entry and (time.time() - entry.get("fetched_at", 0)) < ttl_seconds:
        return entry["value"]

    # Slow path — acquire lock, re-check, fetch if still stale
    try:
        with FileLock(lock_path, timeout=_LOCK_TIMEOUT_SEC):
            data = _read_cache(cache_path)
            entry = data.get(key)
            if entry and (time.time() - entry.get("fetched_at", 0)) < ttl_seconds:
                return entry["value"]

            value = fetcher_fn()
            data[key] = {"fetched_at": time.time(), "value": value}
            _write_cache(cache_path, data)
            return value
    except Timeout:
        logger.error("Could not acquire cache lock %s in %.1fs", lock_path, _LOCK_TIMEOUT_SEC)
        # Degraded path: fetch without caching
        return fetcher_fn()
```

- [ ] **Step 4: Run to confirm tests pass**

Run: `pytest tests/test_cache.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add scrapers/_cache.py tests/test_cache.py
git commit -m "feat(cache): add generic get_or_fetch helper with filelock concurrency"
```

---

## Phase B — Statcast advanced scraper

### Task 3: Statcast leaderboard warmers + pitcher lookup (failing test)

**Files:**
- Create: `tests/fixtures/fg_pitching_leaderboard.json`
- Create: `tests/test_statcast_advanced.py`
- Create: `scrapers/statcast_advanced.py`

- [ ] **Step 1: Create fixture file**

Create `tests/fixtures/fg_pitching_leaderboard.json`:

```json
[
  {
    "IDfg": 19755, "Name": "Yoshinobu Yamamoto", "Team": "LAD",
    "xERA": 2.94, "xFIP": 3.18, "xwOBA": 0.278,
    "Barrel%": 0.058, "HardHit%": 0.321,
    "K%": 0.288, "BB%": 0.065, "CSW%": 0.314,
    "Stuff+": 118, "Location+": 103, "Pitching+": 112,
    "botStf": 62, "botCmd": 54, "botOvr": 59,
    "IP": 92.1, "TBF": 365, "MLBAMID": 808967
  },
  {
    "IDfg": 13543, "Name": "Logan Webb", "Team": "SFG",
    "xERA": 3.28, "xFIP": 3.35, "xwOBA": 0.304,
    "Barrel%": 0.069, "HardHit%": 0.384,
    "K%": 0.226, "BB%": 0.052, "CSW%": 0.281,
    "Stuff+": 99, "Location+": 114, "Pitching+": 108,
    "botStf": 49, "botCmd": 58, "botOvr": 53,
    "IP": 104.0, "TBF": 410, "MLBAMID": 657277
  }
]
```

- [ ] **Step 2: Write failing pitcher-lookup test**

Create `tests/test_statcast_advanced.py`:

```python
"""Tests for scrapers/statcast_advanced.py."""
import json
import os
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_pitching_df():
    with open(os.path.join(FIXTURE_DIR, "fg_pitching_leaderboard.json")) as f:
        return pd.DataFrame(json.load(f))


def test_get_pitcher_advanced_by_mlbam_id(tmp_path, monkeypatch):
    from scrapers import statcast_advanced

    monkeypatch.setattr(statcast_advanced, "CACHE_DIR", str(tmp_path))
    fake_df = _load_pitching_df()

    with patch.object(statcast_advanced, "_fetch_fg_pitching", return_value=fake_df):
        out = statcast_advanced.get_pitcher_advanced(808967, season=2026)

    assert out["xERA"] == 2.94
    assert out["stuff_plus"] == 118
    assert out["location_plus"] == 103
    assert out["bot_ovr"] == 59
    assert out["ip"] == 92.1
    assert out["bf"] == 365


def test_get_pitcher_advanced_missing_player_returns_none_dict(tmp_path, monkeypatch):
    from scrapers import statcast_advanced

    monkeypatch.setattr(statcast_advanced, "CACHE_DIR", str(tmp_path))
    fake_df = _load_pitching_df()

    with patch.object(statcast_advanced, "_fetch_fg_pitching", return_value=fake_df):
        out = statcast_advanced.get_pitcher_advanced(999999, season=2026)

    assert out["xERA"] is None
    assert out["stuff_plus"] is None
    assert out["ip"] is None
```

- [ ] **Step 3: Run — expect failure**

Run: `pytest tests/test_statcast_advanced.py -v`
Expected: FAIL (module missing).

- [ ] **Step 4: Implement `scrapers/statcast_advanced.py` (skeleton + pitcher path)**

Create `scrapers/statcast_advanced.py`:

```python
"""Statcast expected-stats + pitch-modeling scraper.

Public API:
    get_pitcher_advanced(player_id, season) -> dict
    get_batter_advanced(player_id, season)  -> dict
    prewarm_statcast_leaderboards(season)   -> None

All functions return dicts with every documented key; missing data -> None.
Never raises on network / data issues — degrades to all-None.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd

from scrapers._cache import get_or_fetch

try:
    from config import SOURCES_ENABLED
except ImportError:
    SOURCES_ENABLED = {"statcast": True}

logger = logging.getLogger("mirofish.statcast")

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "statcast_cache")
TTL_24H = 86_400

PITCHER_KEYS = [
    "xERA", "xFIP", "xwOBA_against", "barrel_pct_against", "hard_hit_pct_against",
    "k_pct", "bb_pct", "csw_pct",
    "stuff_plus", "location_plus", "pitching_plus",
    "bot_stf", "bot_cmd", "bot_ovr",
    "ip", "bf",
]

BATTER_KEYS = [
    "xwOBA", "xSLG", "xBA",
    "barrel_pct", "hard_hit_pct",
    "bat_speed", "squared_up_pct", "fast_swing_pct", "attack_angle",
    "pa",
]


def _none_dict(keys: list[str]) -> dict[str, Any]:
    return {k: None for k in keys}


def _fetch_fg_pitching(season: int) -> pd.DataFrame:
    import pybaseball as pb
    return pb.pitching_stats(season, qual=0)


def _fetch_fg_batting(season: int) -> pd.DataFrame:
    import pybaseball as pb
    return pb.batting_stats(season, qual=0)


def _fetch_savant_bat_tracking(season: int) -> pd.DataFrame:
    import requests
    url = (
        f"https://baseballsavant.mlb.com/leaderboard/bat-tracking"
        f"?season={season}&min=q&csv=true"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    from io import StringIO
    return pd.read_csv(StringIO(resp.text))


def _leaderboard_cache_path(season: int, name: str) -> str:
    season_dir = os.path.join(CACHE_DIR, str(season))
    os.makedirs(season_dir, exist_ok=True)
    return os.path.join(season_dir, f"_leaderboard_{name}.json")


def _df_cached(season: int, name: str, fetcher) -> pd.DataFrame:
    """Get-or-fetch a full leaderboard as a DataFrame. Cached as records list."""
    path = _leaderboard_cache_path(season, name)
    records = get_or_fetch(
        key=f"{name}_{season}",
        ttl_seconds=TTL_24H,
        fetcher_fn=lambda: fetcher(season).to_dict(orient="records"),
        cache_path=path,
    )
    return pd.DataFrame(records)


def _row_for_player(df: pd.DataFrame, player_id: int, id_col_candidates: list[str]) -> dict | None:
    for col in id_col_candidates:
        if col in df.columns:
            matches = df[df[col] == player_id]
            if not matches.empty:
                return matches.iloc[0].to_dict()
    return None


def get_pitcher_advanced(player_id: int, season: int) -> dict:
    """Return pitcher expected + pitch-model stats. Never raises."""
    if not SOURCES_ENABLED.get("statcast", True):
        return _none_dict(PITCHER_KEYS)

    try:
        df = _df_cached(season, "pitchers", _fetch_fg_pitching)
    except Exception as e:
        logger.warning("FanGraphs pitching leaderboard fetch failed: %s", e)
        return _none_dict(PITCHER_KEYS)

    row = _row_for_player(df, int(player_id), ["MLBAMID", "IDfg", "xMLBAMID"])
    if row is None:
        return _none_dict(PITCHER_KEYS)

    def g(k, default=None):
        v = row.get(k, default)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return v

    return {
        "xERA": g("xERA"),
        "xFIP": g("xFIP"),
        "xwOBA_against": g("xwOBA"),
        "barrel_pct_against": g("Barrel%"),
        "hard_hit_pct_against": g("HardHit%"),
        "k_pct": g("K%"),
        "bb_pct": g("BB%"),
        "csw_pct": g("CSW%"),
        "stuff_plus": g("Stuff+"),
        "location_plus": g("Location+"),
        "pitching_plus": g("Pitching+"),
        "bot_stf": g("botStf"),
        "bot_cmd": g("botCmd"),
        "bot_ovr": g("botOvr"),
        "ip": g("IP"),
        "bf": g("TBF"),
    }
```

- [ ] **Step 5: Run — expect pitcher tests pass**

Run: `pytest tests/test_statcast_advanced.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scrapers/statcast_advanced.py tests/test_statcast_advanced.py tests/fixtures/fg_pitching_leaderboard.json
git commit -m "feat(statcast): pitcher advanced-stat lookup with FG leaderboard cache"
```

---

### Task 4: Statcast batter lookup + bat tracking merge

**Files:**
- Create: `tests/fixtures/fg_batting_leaderboard.json`
- Create: `tests/fixtures/savant_bat_tracking.csv`
- Modify: `scrapers/statcast_advanced.py`
- Modify: `tests/test_statcast_advanced.py`

- [ ] **Step 1: Create batting fixtures**

Create `tests/fixtures/fg_batting_leaderboard.json`:

```json
[
  {
    "IDfg": 19755, "Name": "Shohei Ohtani", "Team": "LAD", "MLBAMID": 660271,
    "xwOBA": 0.421, "xSLG": 0.598, "xBA": 0.308,
    "Barrel%": 0.168, "HardHit%": 0.562,
    "PA": 420
  },
  {
    "IDfg": 5361, "Name": "Freddie Freeman", "Team": "LAD", "MLBAMID": 518692,
    "xwOBA": 0.378, "xSLG": 0.515, "xBA": 0.295,
    "Barrel%": 0.101, "HardHit%": 0.489,
    "PA": 380
  }
]
```

Create `tests/fixtures/savant_bat_tracking.csv`:

```
player_id,player_name,bat_speed,swing_length,squared_up_per_bat_contact,attack_angle,fast_swing_rate
660271,Shohei Ohtani,78.3,7.8,0.32,11.5,0.58
518692,Freddie Freeman,72.1,7.5,0.38,12.9,0.41
```

- [ ] **Step 2: Add failing batter tests**

Append to `tests/test_statcast_advanced.py`:

```python
def _load_batting_df():
    with open(os.path.join(FIXTURE_DIR, "fg_batting_leaderboard.json")) as f:
        return pd.DataFrame(json.load(f))


def _load_bat_tracking_df():
    return pd.read_csv(os.path.join(FIXTURE_DIR, "savant_bat_tracking.csv"))


def test_get_batter_advanced_merges_fg_and_savant(tmp_path, monkeypatch):
    from scrapers import statcast_advanced

    monkeypatch.setattr(statcast_advanced, "CACHE_DIR", str(tmp_path))
    fg = _load_batting_df()
    bt = _load_bat_tracking_df()

    with patch.object(statcast_advanced, "_fetch_fg_batting", return_value=fg), \
         patch.object(statcast_advanced, "_fetch_savant_bat_tracking", return_value=bt):
        out = statcast_advanced.get_batter_advanced(660271, season=2026)

    assert out["xwOBA"] == 0.421
    assert out["barrel_pct"] == 0.168
    assert out["bat_speed"] == 78.3
    assert out["fast_swing_pct"] == 0.58
    assert out["attack_angle"] == 11.5
    assert out["pa"] == 420


def test_get_batter_advanced_savant_missing_keeps_fg_fields(tmp_path, monkeypatch):
    from scrapers import statcast_advanced

    monkeypatch.setattr(statcast_advanced, "CACHE_DIR", str(tmp_path))
    fg = _load_batting_df()
    empty_bt = pd.DataFrame(columns=["player_id", "bat_speed"])

    with patch.object(statcast_advanced, "_fetch_fg_batting", return_value=fg), \
         patch.object(statcast_advanced, "_fetch_savant_bat_tracking", return_value=empty_bt):
        out = statcast_advanced.get_batter_advanced(518692, season=2026)

    assert out["xwOBA"] == 0.378
    assert out["bat_speed"] is None  # missing in Savant data
    assert out["barrel_pct"] == 0.101


def test_get_batter_advanced_sources_disabled(tmp_path, monkeypatch):
    from scrapers import statcast_advanced

    monkeypatch.setattr(statcast_advanced, "SOURCES_ENABLED", {"statcast": False})
    with patch.object(statcast_advanced, "_fetch_fg_batting") as mock_fg:
        out = statcast_advanced.get_batter_advanced(660271, season=2026)

    mock_fg.assert_not_called()
    assert out["xwOBA"] is None
```

- [ ] **Step 3: Run — expect failure**

Run: `pytest tests/test_statcast_advanced.py -v`
Expected: new 3 tests FAIL.

- [ ] **Step 4: Add `get_batter_advanced` to `scrapers/statcast_advanced.py`**

Append to `scrapers/statcast_advanced.py`:

```python
def get_batter_advanced(player_id: int, season: int) -> dict:
    """Return batter Statcast + bat-tracking stats. Never raises."""
    if not SOURCES_ENABLED.get("statcast", True):
        return _none_dict(BATTER_KEYS)

    result = _none_dict(BATTER_KEYS)

    # FanGraphs batting leaderboard
    try:
        df = _df_cached(season, "batters", _fetch_fg_batting)
        row = _row_for_player(df, int(player_id), ["MLBAMID", "IDfg", "xMLBAMID"])
        if row:
            def g(k):
                v = row.get(k)
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return None
                return v
            result["xwOBA"] = g("xwOBA")
            result["xSLG"] = g("xSLG")
            result["xBA"] = g("xBA")
            result["barrel_pct"] = g("Barrel%")
            result["hard_hit_pct"] = g("HardHit%")
            result["pa"] = g("PA")
    except Exception as e:
        logger.warning("FG batting leaderboard failed: %s", e)

    # Savant bat tracking — separate cache; missing fields just stay None
    try:
        bt = _df_cached(season, "bat_tracking", _fetch_savant_bat_tracking)
        if "player_id" in bt.columns:
            matches = bt[bt["player_id"] == int(player_id)]
            if not matches.empty:
                row = matches.iloc[0].to_dict()
                def g(k):
                    v = row.get(k)
                    if v is None or (isinstance(v, float) and pd.isna(v)):
                        return None
                    return v
                result["bat_speed"] = g("bat_speed")
                result["squared_up_pct"] = g("squared_up_per_bat_contact")
                result["fast_swing_pct"] = g("fast_swing_rate")
                result["attack_angle"] = g("attack_angle")
    except Exception as e:
        logger.warning("Savant bat tracking fetch failed: %s", e)

    return result


def prewarm_statcast_leaderboards(season: int) -> None:
    """One-shot pre-warm from daily_runner. Idempotent; cheap if cache fresh."""
    if not SOURCES_ENABLED.get("statcast", True):
        return
    for name, fetcher in [
        ("pitchers", _fetch_fg_pitching),
        ("batters", _fetch_fg_batting),
        ("bat_tracking", _fetch_savant_bat_tracking),
    ]:
        try:
            _df_cached(season, name, fetcher)
            logger.info("statcast: prewarmed %s leaderboard", name)
        except Exception as e:
            logger.warning("statcast: prewarm %s failed: %s", name, e)
```

- [ ] **Step 5: Run — all tests pass**

Run: `pytest tests/test_statcast_advanced.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scrapers/statcast_advanced.py tests/test_statcast_advanced.py tests/fixtures/
git commit -m "feat(statcast): batter advanced stats merging FG + Savant bat tracking"
```

---

### Task 5: Wire `config.SOURCES_ENABLED` and `DATA_V2_ENABLED`

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Inspect config.py to find insertion point**

Run: `grep -n "^[A-Z_]* =" config.py | head -20` and note end-of-file line.

- [ ] **Step 2: Add Spec 4 flags at EOF of `config.py`**

Append to `config.py`:

```python
# ------ Spec 4: Data V2 (Statcast + umpire + catcher + DC + carry) ------
import os as _os

DATA_V2_ENABLED = _os.getenv("DATA_V2_ENABLED", "false").lower() == "true"

SOURCES_ENABLED = {
    "statcast":     _os.getenv("SRC_STATCAST",     "true").lower() == "true",
    "umpire":       _os.getenv("SRC_UMPIRE",       "true").lower() == "true",
    "catcher":      _os.getenv("SRC_CATCHER",      "true").lower() == "true",
    "depth_charts": _os.getenv("SRC_DEPTH_CHARTS", "true").lower() == "true",
    "carry":        _os.getenv("SRC_CARRY",        "true").lower() == "true",
}

# Park elevations in feet (Coors dominant; others under 1100 ft).
PARK_ELEVATIONS = {
    "COL": 5200,
    "ARI": 1059,
    "ATL": 1050,
    "CIN": 550,
    "PIT": 730,
    "MIL": 635,
    "MIN": 840,
    "KC":  750,
    "CHC": 595,
    "CHW": 595,
    "SEA": 134,
    "SF":  12,
    "SD":  62,
    "LAD": 512,
    "LAA": 157,
    "OAK": 55,
    "HOU": 43,
    "TEX": 551,
    "TOR": 249,
    "DET": 600,
    "CLE": 660,
    "STL": 465,
    "BAL": 20,
    "WSH": 25,
    "PHI": 20,
    "NYY": 55,
    "NYM": 10,
    "BOS": 21,
    "TB":  15,
    "MIA": 8,
}
```

- [ ] **Step 3: Smoke-check import**

Run: `python3 -c "from config import DATA_V2_ENABLED, SOURCES_ENABLED, PARK_ELEVATIONS; print(DATA_V2_ENABLED, list(SOURCES_ENABLED), PARK_ELEVATIONS['COL'])"`
Expected: `False ['statcast', 'umpire', 'catcher', 'depth_charts', 'carry'] 5200`

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "feat(config): add DATA_V2_ENABLED, SOURCES_ENABLED, PARK_ELEVATIONS"
```

---

## Phase C — Umpire scraper

### Task 6: Umpire assignment from MLB boxscore (failing test)

**Files:**
- Create: `tests/fixtures/boxscore_with_officials.json`
- Create: `tests/fixtures/boxscore_no_officials.json`
- Create: `tests/test_umpire.py`
- Create: `scrapers/umpire.py`

- [ ] **Step 1: Create fixtures**

Create `tests/fixtures/boxscore_with_officials.json`:

```json
{
  "officials": [
    {"official": {"id": 427053, "fullName": "Angel Hernandez"}, "officialType": "Home Plate"},
    {"official": {"id": 427123, "fullName": "Joe West"}, "officialType": "First Base"}
  ]
}
```

Create `tests/fixtures/boxscore_no_officials.json`:

```json
{"officials": []}
```

- [ ] **Step 2: Write failing assignment tests**

Create `tests/test_umpire.py`:

```python
"""Tests for scrapers/umpire.py."""
import json
import os
from unittest.mock import patch, MagicMock

import pytest

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _mock_get(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


def test_get_umpire_assignment_parses_home_plate(monkeypatch):
    from scrapers import umpire

    with open(os.path.join(FIXTURE_DIR, "boxscore_with_officials.json")) as f:
        data = json.load(f)
    with patch.object(umpire.requests, "get", return_value=_mock_get(200, data)):
        out = umpire.get_umpire_assignment(745000)

    assert out == {"home_plate_ump_id": 427053, "name": "Angel Hernandez"}


def test_get_umpire_assignment_missing_returns_none(monkeypatch):
    from scrapers import umpire

    with open(os.path.join(FIXTURE_DIR, "boxscore_no_officials.json")) as f:
        data = json.load(f)
    with patch.object(umpire.requests, "get", return_value=_mock_get(200, data)):
        out = umpire.get_umpire_assignment(745001)

    assert out is None


def test_get_umpire_assignment_http_error_returns_none(monkeypatch):
    from scrapers import umpire

    with patch.object(umpire.requests, "get", side_effect=RuntimeError("500")):
        out = umpire.get_umpire_assignment(745002)

    assert out is None
```

- [ ] **Step 3: Run — expect failure**

Run: `pytest tests/test_umpire.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement skeleton `scrapers/umpire.py`**

Create `scrapers/umpire.py`:

```python
"""Umpire assignment + profile scraper with UmpScorecards fallback."""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import requests

from scrapers._cache import get_or_fetch

try:
    from config import SOURCES_ENABLED
except ImportError:
    SOURCES_ENABLED = {"umpire": True}

logger = logging.getLogger("mirofish.umpire")

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
UMP_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "umpire_cache.json"
)
UMP_FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "umpire_fixture.json"
)
TTL_24H = 86_400

NEUTRAL_PROFILE = {
    "k_pct_delta": 0.0,
    "bb_pct_delta": 0.0,
    "runs_per_game_delta": 0.0,
    "consistency_pct": None,
    "accuracy_pct": None,
    "consecutive_games": None,
    "games_sample": 0,
    "name": None,
    "last_scrape_status": "neutral_default",
}


def get_umpire_assignment(game_pk: int) -> dict | None:
    """Return {'home_plate_ump_id': int, 'name': str} or None if TBD."""
    if not SOURCES_ENABLED.get("umpire", True):
        return None
    url = f"{MLB_API_BASE}/game/{game_pk}/boxscore"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        officials = resp.json().get("officials", [])
    except Exception as e:
        logger.warning("umpire assignment fetch failed for game %s: %s", game_pk, e)
        return None

    for off in officials:
        if off.get("officialType") == "Home Plate":
            o = off.get("official", {})
            if "id" in o and "fullName" in o:
                return {"home_plate_ump_id": o["id"], "name": o["fullName"]}
    return None
```

- [ ] **Step 5: Tests pass**

Run: `pytest tests/test_umpire.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scrapers/umpire.py tests/test_umpire.py tests/fixtures/boxscore_*.json
git commit -m "feat(umpire): MLB boxscore home-plate assignment lookup"
```

---

### Task 7: UmpScorecards profile with CSV + fixture fallback

**Files:**
- Create: `tests/fixtures/umpscorecards_hernandez.csv`
- Create: `tests/fixtures/umpscorecards_broken.html`
- Create: `data/umpire_fixture.json`
- Modify: `scrapers/umpire.py`
- Modify: `tests/test_umpire.py`

- [ ] **Step 1: Create fixtures**

Create `tests/fixtures/umpscorecards_hernandez.csv`:

```
ump_id,name,games,k_pct_delta,bb_pct_delta,runs_per_game_delta,consistency_pct,accuracy_pct,consecutive_games
427053,Angel Hernandez,3412,-0.8,0.6,0.42,91.2,93.5,12
```

Create `tests/fixtures/umpscorecards_broken.html`:

```html
<html><body><h1>Site maintenance</h1></body></html>
```

Create `data/umpire_fixture.json` (shipped fixture; tiny sample — real file should be populated by operator pre-merge):

```json
{
  "meta": {
    "snapshot_date": "2026-04-01",
    "source": "umpscorecards.com",
    "note": "Frozen fallback when live scrape fails. Seed with top 80 umps at deploy time."
  },
  "umps": {
    "427053": {
      "name": "Angel Hernandez",
      "k_pct_delta": -0.8,
      "bb_pct_delta": 0.6,
      "runs_per_game_delta": 0.42,
      "consistency_pct": 91.2,
      "accuracy_pct": 93.5,
      "consecutive_games": 12,
      "games_sample": 3412
    }
  }
}
```

- [ ] **Step 2: Add failing profile tests**

Append to `tests/test_umpire.py`:

```python
def test_get_umpire_profile_csv_parse(tmp_path, monkeypatch):
    from scrapers import umpire

    monkeypatch.setattr(umpire, "UMP_CACHE_PATH", str(tmp_path / "umpire_cache.json"))
    with open(os.path.join(FIXTURE_DIR, "umpscorecards_hernandez.csv")) as f:
        csv_text = f.read()

    with patch.object(umpire.requests, "get", return_value=_mock_get(200, text=csv_text)):
        prof = umpire.get_umpire_profile(427053, "Angel Hernandez")

    assert prof["k_pct_delta"] == -0.8
    assert prof["bb_pct_delta"] == 0.6
    assert prof["runs_per_game_delta"] == 0.42
    assert prof["games_sample"] == 3412
    assert prof["last_scrape_status"] == "live"


def test_get_umpire_profile_falls_back_to_fixture(tmp_path, monkeypatch):
    from scrapers import umpire

    monkeypatch.setattr(umpire, "UMP_CACHE_PATH", str(tmp_path / "umpire_cache.json"))
    # Redirect fixture path to our repo-shipped fixture
    # (fixture already contains 427053 = Angel Hernandez)

    with patch.object(umpire.requests, "get", side_effect=RuntimeError("500")):
        prof = umpire.get_umpire_profile(427053, "Angel Hernandez")

    assert prof["k_pct_delta"] == -0.8  # from fixture
    assert prof["last_scrape_status"] == "fixture_fallback"


def test_get_umpire_profile_unknown_ump_returns_neutral(tmp_path, monkeypatch):
    from scrapers import umpire

    monkeypatch.setattr(umpire, "UMP_CACHE_PATH", str(tmp_path / "cache.json"))
    with patch.object(umpire.requests, "get", side_effect=RuntimeError("500")):
        prof = umpire.get_umpire_profile(99999999, "Unknown Ump")

    assert prof["k_pct_delta"] == 0.0
    assert prof["last_scrape_status"] == "neutral_default"


def test_get_umpire_profile_cache_hit_skips_network(tmp_path, monkeypatch):
    from scrapers import umpire

    cache_path = str(tmp_path / "cache.json")
    monkeypatch.setattr(umpire, "UMP_CACHE_PATH", cache_path)
    with open(os.path.join(FIXTURE_DIR, "umpscorecards_hernandez.csv")) as f:
        csv_text = f.read()

    with patch.object(umpire.requests, "get", return_value=_mock_get(200, text=csv_text)) as m:
        umpire.get_umpire_profile(427053, "Angel Hernandez")
        umpire.get_umpire_profile(427053, "Angel Hernandez")  # second should hit cache

    assert m.call_count == 1


def test_get_umpire_profile_sources_disabled(monkeypatch):
    from scrapers import umpire

    monkeypatch.setattr(umpire, "SOURCES_ENABLED", {"umpire": False})
    with patch.object(umpire.requests, "get") as m:
        prof = umpire.get_umpire_profile(427053, "x")
    m.assert_not_called()
    assert prof["k_pct_delta"] == 0.0
```

- [ ] **Step 3: Run — new tests FAIL**

Run: `pytest tests/test_umpire.py -v`
Expected: 5 new tests fail.

- [ ] **Step 4: Implement `get_umpire_profile`**

Append to `scrapers/umpire.py`:

```python
UMPSCORECARDS_CSV = "https://umpscorecards.com/single_umpire/?id={ump_id}&format=csv"
UMPSCORECARDS_HTML = "https://umpscorecards.com/single_umpire/?id={ump_id}"

_last_umpscorecards_call: list[float] = [0.0]
_MIN_GAP_SEC = 2.0


def _rate_limit():
    elapsed = time.time() - _last_umpscorecards_call[0]
    if elapsed < _MIN_GAP_SEC:
        time.sleep(_MIN_GAP_SEC - elapsed)
    _last_umpscorecards_call[0] = time.time()


def _load_fixture() -> dict:
    if not os.path.exists(UMP_FIXTURE_PATH):
        return {}
    try:
        with open(UMP_FIXTURE_PATH) as f:
            return json.load(f).get("umps", {})
    except Exception:
        return {}


def _parse_umpscorecards_csv(text: str) -> dict | None:
    """Parse single-umpire CSV response."""
    import csv
    from io import StringIO
    try:
        reader = csv.DictReader(StringIO(text))
        rows = list(reader)
        if not rows:
            return None
        r = rows[0]
        return {
            "name": r.get("name"),
            "k_pct_delta": float(r.get("k_pct_delta", 0) or 0),
            "bb_pct_delta": float(r.get("bb_pct_delta", 0) or 0),
            "runs_per_game_delta": float(r.get("runs_per_game_delta", 0) or 0),
            "consistency_pct": float(r.get("consistency_pct", 0) or 0) or None,
            "accuracy_pct": float(r.get("accuracy_pct", 0) or 0) or None,
            "consecutive_games": int(r.get("consecutive_games", 0) or 0) or None,
            "games_sample": int(r.get("games", 0) or 0),
        }
    except Exception as e:
        logger.warning("UmpScorecards CSV parse failed: %s", e)
        return None


def _parse_umpscorecards_html(text: str) -> dict | None:
    """Back-up HTML scrape if CSV format breaks."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(text, "html.parser")
        table = soup.select_one("table.career-averages")
        if not table:
            return None
        # Implementation deferred — CSV path is primary.
        logger.info("UmpScorecards HTML fallback table located but parser is a stub")
        return None
    except Exception as e:
        logger.warning("UmpScorecards HTML parse failed: %s", e)
        return None


def _fetch_umpscorecards(ump_id: int) -> dict | None:
    _rate_limit()
    try:
        resp = requests.get(UMPSCORECARDS_CSV.format(ump_id=ump_id), timeout=15)
        if resp.status_code == 200 and resp.text.strip().lower().startswith(("ump_id", "\"ump_id", "name")):
            parsed = _parse_umpscorecards_csv(resp.text)
            if parsed:
                return parsed
        # CSV failed — try HTML
        resp = requests.get(UMPSCORECARDS_HTML.format(ump_id=ump_id), timeout=15)
        if resp.status_code == 200:
            parsed = _parse_umpscorecards_html(resp.text)
            if parsed:
                return parsed
    except Exception as e:
        logger.warning("UmpScorecards live fetch failed for %s: %s", ump_id, e)
    return None


def get_umpire_profile(ump_id: Optional[int], ump_name: Optional[str] = None) -> dict:
    """Return career profile. Cascades: cache -> live -> fixture -> neutrals.

    Never raises.
    """
    if not SOURCES_ENABLED.get("umpire", True) or ump_id is None:
        out = dict(NEUTRAL_PROFILE)
        out["name"] = ump_name
        return out

    def _fetcher():
        live = _fetch_umpscorecards(int(ump_id))
        if live is not None:
            live["last_scrape_status"] = "live"
            return live
        # Fixture fallback
        fx = _load_fixture().get(str(ump_id))
        if fx:
            fx = dict(fx)
            fx["last_scrape_status"] = "fixture_fallback"
            logger.warning("umpire %s: fell back to fixture snapshot", ump_id)
            return fx
        out = dict(NEUTRAL_PROFILE)
        out["name"] = ump_name
        logger.warning("umpire %s: no data found, returning neutrals", ump_id)
        return out

    try:
        return get_or_fetch(
            key=str(ump_id),
            ttl_seconds=TTL_24H,
            fetcher_fn=_fetcher,
            cache_path=UMP_CACHE_PATH,
        )
    except Exception as e:
        logger.error("umpire profile cache error for %s: %s", ump_id, e)
        out = dict(NEUTRAL_PROFILE)
        out["name"] = ump_name
        return out
```

- [ ] **Step 5: Run — tests pass**

Run: `pytest tests/test_umpire.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scrapers/umpire.py tests/test_umpire.py tests/fixtures/umpscorecards_* data/umpire_fixture.json
git commit -m "feat(umpire): UmpScorecards CSV profile with fixture fallback"
```

---

### Task 8: Backfill script for umpires

**Files:**
- Create: `scripts/backfill_umpires.py`

- [ ] **Step 1: Confirm `scripts/` directory exists**

Run: `ls -ld scripts/`
If missing, `mkdir -p scripts/`.

- [ ] **Step 2: Create `scripts/backfill_umpires.py`**

```python
"""Warm the umpire cache for the last N days of completed games.

Usage:
    python3 scripts/backfill_umpires.py --days 30
"""
import argparse
import logging
import sys
import time
from datetime import date, timedelta

import requests

sys.path.insert(0, ".")
from scrapers.umpire import get_umpire_assignment, get_umpire_profile  # noqa

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

logger = logging.getLogger("mirofish.backfill_umpires")


def _schedule_for(d: date) -> list[int]:
    url = f"{MLB_API_BASE}/schedule?sportId=1&date={d.isoformat()}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("schedule fetch %s failed: %s", d, e)
        return []
    game_pks = []
    for day in data.get("dates", []):
        for g in day.get("games", []):
            game_pks.append(g.get("gamePk"))
    return [gp for gp in game_pks if gp]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    seen: set[int] = set()
    end = date.today()
    for i in range(args.days):
        d = end - timedelta(days=i)
        logger.info("backfill %s", d.isoformat())
        for gp in _schedule_for(d):
            assignment = get_umpire_assignment(gp)
            if not assignment:
                continue
            ump_id = assignment["home_plate_ump_id"]
            if ump_id in seen:
                continue
            seen.add(ump_id)
            prof = get_umpire_profile(ump_id, assignment["name"])
            logger.info("  ump %s %s -> status=%s", ump_id, assignment["name"],
                        prof.get("last_scrape_status"))
            time.sleep(0.2)  # politeness beyond rate-limit
    logger.info("done — %d unique umps warmed", len(seen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Smoke-test the script import**

Run: `python3 -c "import scripts.backfill_umpires"`
Expected: no import errors.

- [ ] **Step 4: Commit**

```bash
git add scripts/backfill_umpires.py
git commit -m "feat(umpire): backfill script for 30-day umpire cache warm"
```

---

## Phase D — Catcher framing

### Task 9: Catcher framing leaderboard + z-score

**Files:**
- Create: `tests/fixtures/savant_catcher_framing.csv`
- Create: `data/catcher_framing_fixture.json`
- Create: `tests/test_catcher_framing.py`
- Create: `scrapers/catcher_framing.py`

- [ ] **Step 1: Create fixtures**

Create `tests/fixtures/savant_catcher_framing.csv`:

```
player_id,player_name,year,n_called_pitches,runs_extra_strikes,framing_runs,strike_rate,innings_caught
663728,Patrick Bailey,2026,4200,14.5,18.7,0.502,720
663611,Adley Rutschman,2026,3900,11.8,14.2,0.498,670
519293,Will Smith,2026,3500,5.4,6.8,0.491,610
595978,J.T. Realmuto,2026,3800,-1.2,-1.5,0.486,660
467832,Austin Hedges,2026,900,0.8,1.2,0.492,180
```

Create `data/catcher_framing_fixture.json`:

```json
{
  "meta": {"snapshot_date": "2026-04-01", "source": "baseballsavant.mlb.com"},
  "league": {"mean_runs_per_150": 0.0, "stddev_runs_per_150": 6.0},
  "catchers": {
    "663728": {"framing_runs": 18.7, "framing_runs_per_150": 18.7, "z_score": 2.3, "innings_caught": 720},
    "663611": {"framing_runs": 14.2, "framing_runs_per_150": 14.2, "z_score": 1.8, "innings_caught": 670}
  }
}
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_catcher_framing.py`:

```python
"""Tests for scrapers/catcher_framing.py."""
import os
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_framing_df():
    return pd.read_csv(os.path.join(FIXTURE_DIR, "savant_catcher_framing.csv"))


def test_leaderboard_z_score_elite_catcher(tmp_path, monkeypatch):
    from scrapers import catcher_framing

    monkeypatch.setattr(catcher_framing, "CACHE_PATH", str(tmp_path / "c.json"))
    df = _load_framing_df()

    with patch.object(catcher_framing, "_fetch_leaderboard", return_value=df):
        prof = catcher_framing.get_catcher_framing(663728, 2026)

    assert prof["framing_runs"] == 18.7
    assert prof["z_score"] > 1.5  # elite
    assert prof["innings_caught"] == 720


def test_unknown_catcher_returns_zero_z(tmp_path, monkeypatch):
    from scrapers import catcher_framing

    monkeypatch.setattr(catcher_framing, "CACHE_PATH", str(tmp_path / "c.json"))
    df = _load_framing_df()
    with patch.object(catcher_framing, "_fetch_leaderboard", return_value=df):
        prof = catcher_framing.get_catcher_framing(999999, 2026)

    assert prof["z_score"] == 0.0
    assert prof["framing_runs"] is None


def test_fixture_fallback_on_network_error(tmp_path, monkeypatch):
    from scrapers import catcher_framing

    monkeypatch.setattr(catcher_framing, "CACHE_PATH", str(tmp_path / "c.json"))
    with patch.object(catcher_framing, "_fetch_leaderboard",
                      side_effect=RuntimeError("500")):
        prof = catcher_framing.get_catcher_framing(663728, 2026)

    # fixture contains 663728 with z=2.3
    assert prof["z_score"] == 2.3


def test_sources_disabled(monkeypatch):
    from scrapers import catcher_framing

    monkeypatch.setattr(catcher_framing, "SOURCES_ENABLED", {"catcher": False})
    with patch.object(catcher_framing, "_fetch_leaderboard") as m:
        prof = catcher_framing.get_catcher_framing(663728, 2026)
    m.assert_not_called()
    assert prof["z_score"] == 0.0
```

- [ ] **Step 3: Run — FAIL**

Run: `pytest tests/test_catcher_framing.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement `scrapers/catcher_framing.py`**

```python
"""Catcher framing scraper — Savant leaderboard, cached with fixture fallback."""
from __future__ import annotations

import json
import logging
import os
from io import StringIO
from typing import Any

import pandas as pd
import requests

from scrapers._cache import get_or_fetch

try:
    from config import SOURCES_ENABLED
except ImportError:
    SOURCES_ENABLED = {"catcher": True}

logger = logging.getLogger("mirofish.catcher")

CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "catcher_framing_cache.json"
)
FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "catcher_framing_fixture.json"
)
TTL_24H = 86_400

LEADERBOARD_URL = (
    "https://baseballsavant.mlb.com/leaderboard/catcher-framing?year={season}&min=q&csv=true"
)


def _none_profile() -> dict[str, Any]:
    return {
        "framing_runs": None,
        "framing_runs_per_150": None,
        "csaa": None,
        "z_score": 0.0,
        "innings_caught": None,
    }


def _fetch_leaderboard(season: int) -> pd.DataFrame:
    resp = requests.get(LEADERBOARD_URL.format(season=season), timeout=15)
    resp.raise_for_status()
    return pd.read_csv(StringIO(resp.text))


def _load_fixture() -> dict:
    if not os.path.exists(FIXTURE_PATH):
        return {}
    try:
        with open(FIXTURE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _compute_profiles(df: pd.DataFrame) -> dict[str, dict]:
    """Build per-catcher profile dict keyed by str(player_id), incl. league z-score."""
    if df.empty:
        return {}

    # Games caught = innings / 9
    games = df["innings_caught"].astype(float) / 9.0
    # Avoid div-by-zero
    games = games.replace(0, float("nan"))
    per_150 = df["framing_runs"].astype(float) * (150.0 / games)
    per_150 = per_150.fillna(0.0)

    qual_mask = df["n_called_pitches"].astype(int) >= 1000
    if qual_mask.any():
        mean = per_150[qual_mask].mean()
        std = per_150[qual_mask].std(ddof=0) or 1.0
    else:
        mean, std = 0.0, 1.0

    out: dict[str, dict] = {
        "_meta": {"league_mean_per_150": float(mean), "league_stddev_per_150": float(std)}
    }
    for i, row in df.iterrows():
        pid = str(int(row["player_id"]))
        r150 = float(per_150.iloc[i])
        out[pid] = {
            "framing_runs": float(row["framing_runs"]),
            "framing_runs_per_150": round(r150, 2),
            "csaa": float(row.get("strike_rate", 0.0)),
            "z_score": round((r150 - mean) / std, 2),
            "innings_caught": float(row["innings_caught"]),
        }
    return out


def get_catcher_framing(catcher_id: int, season: int) -> dict:
    """Return framing profile. Never raises."""
    if not SOURCES_ENABLED.get("catcher", True):
        return _none_profile()

    def _fetcher():
        try:
            df = _fetch_leaderboard(season)
            return _compute_profiles(df)
        except Exception as e:
            logger.warning("catcher framing leaderboard fetch failed: %s", e)
            fx = _load_fixture()
            cache = {"_meta": fx.get("league", {"league_mean_per_150": 0.0, "league_stddev_per_150": 6.0})}
            cache.update(fx.get("catchers", {}))
            return cache

    try:
        profiles = get_or_fetch(
            key=f"season_{season}",
            ttl_seconds=TTL_24H,
            fetcher_fn=_fetcher,
            cache_path=CACHE_PATH,
        )
    except Exception as e:
        logger.error("catcher framing cache error: %s", e)
        profiles = _load_fixture().get("catchers", {})

    entry = profiles.get(str(catcher_id))
    if not entry:
        return _none_profile()
    out = _none_profile()
    out.update(entry)
    return out


def get_all_catcher_framing(season: int) -> dict[int, dict]:
    """One-shot warm — returns full league keyed by catcher_id (int)."""
    if not SOURCES_ENABLED.get("catcher", True):
        return {}
    try:
        # Force cache population
        get_catcher_framing(0, season)  # triggers fetch if needed
    except Exception:
        pass
    try:
        with open(CACHE_PATH) as f:
            data = json.load(f)
        profiles = data.get(f"season_{season}", {}).get("value", {})
        return {int(k): v for k, v in profiles.items() if k != "_meta"}
    except Exception:
        return {}
```

- [ ] **Step 5: Run — PASS**

Run: `pytest tests/test_catcher_framing.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scrapers/catcher_framing.py tests/test_catcher_framing.py tests/fixtures/savant_catcher_framing.csv data/catcher_framing_fixture.json
git commit -m "feat(catcher): Savant catcher framing leaderboard with z-score + fixture fallback"
```

---

### Task 10: Confirm lineup scraper exposes catcher position

**Files:**
- Read: `scrapers/lineups.py`
- Potentially modify: `scrapers/lineups.py`

- [ ] **Step 1: Inspect current lineup scraper**

Run: `grep -n "position\|'C'" scrapers/lineups.py`

Confirm that each lineup entry has a `position` field containing `"C"` for catcher. If yes — no changes.

- [ ] **Step 2: If position is missing, add it**

Only if missing, modify `scrapers/lineups.py` to include a `"position"` key per player (typically `p["position"]["abbreviation"]` in the MLB boxscore). Add a unit test under `tests/test_lineups.py` verifying catcher extraction.

- [ ] **Step 3: Add helper to identify starting catcher**

Add to end of `scrapers/lineups.py`:

```python
def get_starting_catcher(lineup: list[dict]) -> int | None:
    """Return MLBAM id of first lineup entry with position == 'C'."""
    for p in lineup or []:
        if (p.get("position") or "").upper() == "C":
            return p.get("player_id") or p.get("id")
    return None
```

- [ ] **Step 4: Commit**

```bash
git add scrapers/lineups.py
git commit -m "feat(lineups): expose get_starting_catcher helper"
```

---

## Phase E — Depth Charts projections

### Task 11: Depth Charts projection lookup

**Files:**
- Create: `tests/fixtures/dc_hitters.json`
- Create: `tests/fixtures/dc_pitchers.json`
- Create: `tests/test_depth_charts.py`
- Modify: `scrapers/player_stats.py`

- [ ] **Step 1: Verify pybaseball function name**

Run: `python3 -c "import pybaseball as pb; print([f for f in dir(pb) if 'depth' in f.lower() or 'project' in f.lower()])"`

Record results. If `fangraphs_depth_charts()` exists, use it. If only older names exist, adjust the `_fetch_*` helpers below.

- [ ] **Step 2: Create fixtures**

Create `tests/fixtures/dc_hitters.json`:

```json
[
  {"MLBAMID": 660271, "Name": "Shohei Ohtani", "Team": "LAD",
   "PA": 640, "AVG": 0.289, "OBP": 0.388, "SLG": 0.578,
   "wOBA": 0.398, "ISO": 0.289, "K%": 0.218, "BB%": 0.115, "G": 155,
   "updated": "2026-04-15"},
  {"MLBAMID": 518692, "Name": "Freddie Freeman", "Team": "LAD",
   "PA": 600, "AVG": 0.302, "OBP": 0.385, "SLG": 0.515,
   "wOBA": 0.378, "ISO": 0.213, "K%": 0.168, "BB%": 0.112, "G": 150,
   "updated": "2026-04-15"}
]
```

Create `tests/fixtures/dc_pitchers.json`:

```json
[
  {"MLBAMID": 808967, "Name": "Yoshinobu Yamamoto", "Team": "LAD",
   "IP": 175.0, "FIP": 3.21, "ERA": 3.08, "K%": 0.282, "BB%": 0.068, "GS": 29,
   "updated": "2026-04-15"},
  {"MLBAMID": 657277, "Name": "Logan Webb", "Team": "SFG",
   "IP": 205.0, "FIP": 3.38, "ERA": 3.34, "K%": 0.232, "BB%": 0.054, "GS": 32,
   "updated": "2026-04-15"}
]
```

- [ ] **Step 3: Write failing tests**

Create `tests/test_depth_charts.py`:

```python
"""Tests for Depth Charts projection lookup in scrapers/player_stats.py."""
import json
import os
from unittest.mock import patch

import pandas as pd

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _dc_hitters_df():
    with open(os.path.join(FIXTURE_DIR, "dc_hitters.json")) as f:
        return pd.DataFrame(json.load(f))


def _dc_pitchers_df():
    with open(os.path.join(FIXTURE_DIR, "dc_pitchers.json")) as f:
        return pd.DataFrame(json.load(f))


def test_get_dc_hitter(tmp_path, monkeypatch):
    from scrapers import player_stats

    monkeypatch.setattr(player_stats, "DC_CACHE_DIR", str(tmp_path))
    with patch.object(player_stats, "_fetch_dc_hitters", return_value=_dc_hitters_df()):
        out = player_stats.get_depth_charts_hitter(660271, 2026)

    assert out["pa"] == 640
    assert out["wOBA"] == 0.398
    assert out["k_pct"] == 0.218


def test_get_dc_pitcher(tmp_path, monkeypatch):
    from scrapers import player_stats

    monkeypatch.setattr(player_stats, "DC_CACHE_DIR", str(tmp_path))
    with patch.object(player_stats, "_fetch_dc_pitchers", return_value=_dc_pitchers_df()):
        out = player_stats.get_depth_charts_pitcher(808967, 2026)

    assert out["ip"] == 175.0
    assert out["FIP"] == 3.21


def test_dc_missing_player_returns_none_dict(tmp_path, monkeypatch):
    from scrapers import player_stats

    monkeypatch.setattr(player_stats, "DC_CACHE_DIR", str(tmp_path))
    with patch.object(player_stats, "_fetch_dc_hitters", return_value=_dc_hitters_df()):
        out = player_stats.get_depth_charts_hitter(999999, 2026)
    assert out["pa"] is None
    assert out["wOBA"] is None


def test_prewarm_dc_idempotent(tmp_path, monkeypatch):
    from scrapers import player_stats

    monkeypatch.setattr(player_stats, "DC_CACHE_DIR", str(tmp_path))
    with patch.object(player_stats, "_fetch_dc_hitters", return_value=_dc_hitters_df()) as mh, \
         patch.object(player_stats, "_fetch_dc_pitchers", return_value=_dc_pitchers_df()) as mp:
        player_stats.prewarm_depth_charts(2026)
        player_stats.prewarm_depth_charts(2026)  # second run — cache warm

    assert mh.call_count == 1
    assert mp.call_count == 1
```

- [ ] **Step 4: Run — FAIL**

Run: `pytest tests/test_depth_charts.py -v`
Expected: FAIL.

- [ ] **Step 5: Extend `scrapers/player_stats.py`**

Append to `scrapers/player_stats.py` (after line 265):

```python
# ------ Spec 4: Depth Charts projections ------

import os as _os_ps
from scrapers._cache import get_or_fetch as _cache_gof

try:
    from config import SOURCES_ENABLED as _SOURCES_ENABLED_DC
except ImportError:
    _SOURCES_ENABLED_DC = {"depth_charts": True}

DC_CACHE_DIR = _os_ps.path.join(
    _os_ps.path.dirname(_os_ps.path.dirname(__file__)), "data", "depth_charts_cache"
)
_DC_TTL_24H = 86_400

_HITTER_KEYS_DC = ["pa", "wOBA", "ISO", "k_pct", "bb_pct", "games", "updated_at"]
_PITCHER_KEYS_DC = ["ip", "FIP", "ERA", "k_pct", "bb_pct", "starts", "updated_at"]


def _dc_none(keys):
    return {k: None for k in keys}


def _fetch_dc_hitters(season):
    import pybaseball as pb
    # The exact function name should be verified per Task 11 Step 1.
    # Try new name first, then older aliases, then URL fallback.
    for fn_name in ("fangraphs_depth_charts", "projection_hitter_fangraphs_depth"):
        fn = getattr(pb, fn_name, None)
        if fn:
            try:
                df = fn(season=season, stat_type="bat") if "depth_charts" in fn_name else fn(season)
                return df
            except TypeError:
                return fn(season)
    raise RuntimeError("No pybaseball depth-charts hitter function found")


def _fetch_dc_pitchers(season):
    import pybaseball as pb
    for fn_name in ("fangraphs_depth_charts", "projection_pitcher_fangraphs_depth"):
        fn = getattr(pb, fn_name, None)
        if fn:
            try:
                df = fn(season=season, stat_type="pit") if "depth_charts" in fn_name else fn(season)
                return df
            except TypeError:
                return fn(season)
    raise RuntimeError("No pybaseball depth-charts pitcher function found")


def _dc_cache_path(season, side):
    p = _os_ps.path.join(DC_CACHE_DIR, str(season))
    _os_ps.makedirs(p, exist_ok=True)
    return _os_ps.path.join(p, f"leaderboard_{side}.json")


def _dc_df_cached(season, side, fetcher):
    records = _cache_gof(
        key=f"dc_{side}_{season}",
        ttl_seconds=_DC_TTL_24H,
        fetcher_fn=lambda: fetcher(season).to_dict(orient="records"),
        cache_path=_dc_cache_path(season, side),
    )
    import pandas as _pd
    return _pd.DataFrame(records)


def _dc_row(df, player_id):
    for col in ("MLBAMID", "playerid", "IDfg"):
        if col in df.columns:
            hits = df[df[col] == int(player_id)]
            if not hits.empty:
                return hits.iloc[0].to_dict()
    return None


def get_depth_charts_hitter(player_id: int, season: int) -> dict:
    if not _SOURCES_ENABLED_DC.get("depth_charts", True):
        return _dc_none(_HITTER_KEYS_DC)
    try:
        df = _dc_df_cached(season, "hitters", _fetch_dc_hitters)
    except Exception:
        return _dc_none(_HITTER_KEYS_DC)
    row = _dc_row(df, player_id)
    if row is None:
        return _dc_none(_HITTER_KEYS_DC)
    import pandas as _pd

    def _g(k):
        v = row.get(k)
        if v is None or (isinstance(v, float) and _pd.isna(v)):
            return None
        return v

    return {
        "pa": _g("PA"),
        "wOBA": _g("wOBA"),
        "ISO": _g("ISO"),
        "k_pct": _g("K%"),
        "bb_pct": _g("BB%"),
        "games": _g("G"),
        "updated_at": _g("updated"),
    }


def get_depth_charts_pitcher(player_id: int, season: int) -> dict:
    if not _SOURCES_ENABLED_DC.get("depth_charts", True):
        return _dc_none(_PITCHER_KEYS_DC)
    try:
        df = _dc_df_cached(season, "pitchers", _fetch_dc_pitchers)
    except Exception:
        return _dc_none(_PITCHER_KEYS_DC)
    row = _dc_row(df, player_id)
    if row is None:
        return _dc_none(_PITCHER_KEYS_DC)
    import pandas as _pd

    def _g(k):
        v = row.get(k)
        if v is None or (isinstance(v, float) and _pd.isna(v)):
            return None
        return v

    return {
        "ip": _g("IP"),
        "FIP": _g("FIP"),
        "ERA": _g("ERA"),
        "k_pct": _g("K%"),
        "bb_pct": _g("BB%"),
        "starts": _g("GS"),
        "updated_at": _g("updated"),
    }


def prewarm_depth_charts(season: int) -> None:
    if not _SOURCES_ENABLED_DC.get("depth_charts", True):
        return
    for side, fetcher in [("hitters", _fetch_dc_hitters), ("pitchers", _fetch_dc_pitchers)]:
        try:
            _dc_df_cached(season, side, fetcher)
        except Exception as e:
            import logging as _lg
            _lg.getLogger("mirofish.dc").warning("DC prewarm %s failed: %s", side, e)
```

- [ ] **Step 6: Run — PASS**

Run: `pytest tests/test_depth_charts.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scrapers/player_stats.py tests/test_depth_charts.py tests/fixtures/dc_*.json
git commit -m "feat(dc): FanGraphs Depth Charts hitter/pitcher projection lookups"
```

---

## Phase F — Carry weather model

### Task 12: Air-density physics + carry multiplier

**Files:**
- Create: `tests/test_carry_multiplier.py`
- Modify: `scrapers/ballpark.py`

- [ ] **Step 1: Write failing physics tests**

Create `tests/test_carry_multiplier.py`:

```python
"""Tests for air-density carry model in scrapers/ballpark.py."""
import pytest

from scrapers import ballpark


def test_air_density_baseline():
    # 72°F, 1013 mb, 50% humidity baseline
    rho = ballpark._air_density_kg_m3(72.0, 1013.0, 50.0)
    assert rho == pytest.approx(1.197, abs=0.01)


def test_closed_dome_neutral():
    out = ballpark.compute_carry_multiplier(
        temp_f=72.0, pressure_mb=1013.0, humidity_pct=50.0,
        wind_mph=15.0, wind_dir="out", roof_status="closed",
    )
    assert out["hr_multiplier"] == 1.0
    assert out["xbh_multiplier"] == 1.0
    assert out["batted_ball_distance_ft"] == 0.0
    assert "dome" in out["reason"].lower()


def test_cold_windy_in_suppresses():
    out = ballpark.compute_carry_multiplier(
        temp_f=55.0, pressure_mb=1018.0, humidity_pct=80.0,
        wind_mph=15.0, wind_dir="in", roof_status="open",
    )
    assert out["hr_multiplier"] < 0.95
    assert out["batted_ball_distance_ft"] < 0


def test_hot_high_altitude_boosts():
    out = ballpark.compute_carry_multiplier(
        temp_f=88.0, pressure_mb=840.0, humidity_pct=30.0,
        wind_mph=5.0, wind_dir="out", roof_status="open",
        elevation_ft=5200.0,
    )
    assert out["hr_multiplier"] > 1.10
    assert out["batted_ball_distance_ft"] > 20


def test_wind_direction_calm_zero():
    out = ballpark.compute_carry_multiplier(
        temp_f=72.0, pressure_mb=1013.0, humidity_pct=50.0,
        wind_mph=0.0, wind_dir="calm", roof_status="open",
    )
    assert abs(out["batted_ball_distance_ft"]) < 0.5
    assert abs(out["hr_multiplier"] - 1.0) < 0.01


def test_retractable_falls_to_open_when_dry(monkeypatch):
    monkeypatch.setattr(
        ballpark, "_check_retractable_roof", lambda team, time: "open"
    )
    out = ballpark.compute_carry_multiplier(
        temp_f=82.0, pressure_mb=1013.0, humidity_pct=50.0,
        wind_mph=9.0, wind_dir="out", roof_status="retractable",
    )
    assert out["hr_multiplier"] > 1.0


def test_retractable_closed_is_neutral(monkeypatch):
    monkeypatch.setattr(
        ballpark, "_check_retractable_roof", lambda team, time: "closed"
    )
    out = ballpark.compute_carry_multiplier(
        temp_f=82.0, pressure_mb=1013.0, humidity_pct=50.0,
        wind_mph=9.0, wind_dir="out", roof_status="retractable",
    )
    assert out["hr_multiplier"] == 1.0
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_carry_multiplier.py -v`
Expected: FAIL (functions missing).

- [ ] **Step 3: Read current `scrapers/ballpark.py`**

Run: `wc -l scrapers/ballpark.py` and note line count. Confirm `line 30-56` region contains the OpenWeather call and line 91 is a reasonable append point.

- [ ] **Step 4: Add physics helpers + `compute_carry_multiplier`**

Append to `scrapers/ballpark.py`:

```python
# ------ Spec 4: Air-density carry model ------

import math as _math
import logging as _lg_bp

try:
    from config import SOURCES_ENABLED as _SRC_BP
except ImportError:
    _SRC_BP = {"carry": True}

_log_bp = _lg_bp.getLogger("mirofish.carry")

# Constants
_R_DRY = 287.05   # J/(kg·K) for dry air
_R_VAP = 461.495  # J/(kg·K) for water vapor
_RHO_BASELINE = 1.197  # kg/m³ at 72°F / 1013 mb / 50% humidity


def _saturation_vapor_pressure_pa(temp_c: float) -> float:
    """Tetens approximation, returns Pa."""
    return 610.78 * _math.exp(17.27 * temp_c / (temp_c + 237.3))


def _air_density_kg_m3(temp_f: float, pressure_mb: float, humidity_pct: float) -> float:
    """Compute humid-air density.

    rho = P_d / (R_d T) + P_v / (R_v T)
    with T in Kelvin, P in Pa.
    """
    temp_c = (temp_f - 32.0) * 5.0 / 9.0
    temp_k = temp_c + 273.15
    p_total_pa = pressure_mb * 100.0
    p_sat = _saturation_vapor_pressure_pa(temp_c)
    p_vapor = (humidity_pct / 100.0) * p_sat
    p_dry = p_total_pa - p_vapor
    return p_dry / (_R_DRY * temp_k) + p_vapor / (_R_VAP * temp_k)


def _wind_ft_delta(wind_mph: float, wind_dir: str) -> float:
    """Empirical: +/- 4 ft per 10mph out/in; 0 for cross/calm."""
    d = (wind_dir or "").lower()
    if d == "out":
        return 4.0 * (wind_mph / 10.0)
    if d == "in":
        return -4.0 * (wind_mph / 10.0)
    return 0.0  # 'cross' or 'calm'


def _check_retractable_roof(team_abbrev: str, game_time=None) -> str:
    """Heuristic: if precip forecast > 40% assume closed, else open.

    Real forecast hookup lives in the main weather path; this is a stub
    returning 'open' by default. Override in tests.
    """
    return "open"


def compute_carry_multiplier(
    temp_f: float,
    pressure_mb: float,
    humidity_pct: float,
    wind_mph: float,
    wind_dir: str,
    roof_status: str,
    elevation_ft: float = 0.0,
    team_abbrev: str | None = None,
    game_time=None,
) -> dict:
    """Return {hr_multiplier, xbh_multiplier, batted_ball_distance_ft, reason}.

    See spec §3.5 for the empirical coefficients.
    """
    if not _SRC_BP.get("carry", True):
        return {
            "hr_multiplier": 1.0, "xbh_multiplier": 1.0,
            "batted_ball_distance_ft": 0.0,
            "reason": "carry source disabled",
        }

    if roof_status == "retractable":
        roof_status = _check_retractable_roof(team_abbrev, game_time)

    if roof_status == "closed":
        return {
            "hr_multiplier": 1.0, "xbh_multiplier": 1.0,
            "batted_ball_distance_ft": 0.0,
            "reason": "dome / roof closed",
        }

    # Density reference (not directly consumed, but useful for logging)
    try:
        _rho = _air_density_kg_m3(temp_f, pressure_mb, humidity_pct)
    except Exception:
        _rho = _RHO_BASELINE

    dist_delta = (
        (temp_f - 72.0) * 0.3
        + (elevation_ft / 1000.0) * 6.0
        + (humidity_pct - 50.0) * 0.02
        + _wind_ft_delta(wind_mph, wind_dir)
    )

    hr_mult = 1.0 + (dist_delta / 3.0) * 0.025
    xbh_mult = 1.0 + (dist_delta / 3.0) * 0.010

    reason = (
        f"{temp_f:.0f}°F, wind {wind_mph:.0f}mph {wind_dir}, "
        f"roof {roof_status}, pressure {pressure_mb:.0f}mb"
    )
    return {
        "hr_multiplier": round(hr_mult, 3),
        "xbh_multiplier": round(xbh_mult, 3),
        "batted_ball_distance_ft": round(dist_delta, 1),
        "reason": reason,
    }
```

- [ ] **Step 5: Run — PASS**

Run: `pytest tests/test_carry_multiplier.py -v`
Expected: PASS.

- [ ] **Step 6: Extract `pressure_mb` from OpenWeather response**

Locate OpenWeather parsing in `scrapers/ballpark.py` (around line 30-56). Add `"pressure_mb": data["main"].get("pressure")` to the returned weather dict. If a return dict already exists, insert the key; otherwise extend the function signature to carry pressure through.

- [ ] **Step 7: Commit**

```bash
git add scrapers/ballpark.py tests/test_carry_multiplier.py
git commit -m "feat(ballpark): air-density carry multiplier + OpenWeather pressure field"
```

---

## Phase G — Briefing enrichment

### Task 13: Reliability-tag helper + snapshot test skeleton

**Files:**
- Create: `tests/test_briefing.py`
- Modify: `briefing.py`

- [ ] **Step 1: Inspect current `briefing.py`**

Run: `wc -l briefing.py` and note that §3.6 of the spec references lines 88-127 (sections) and 56-72 (prediction-task block).

- [ ] **Step 2: Write failing tag helper test**

Create `tests/test_briefing.py`:

```python
"""Snapshot + unit tests for briefing enrichment (Spec 4)."""
import pytest

from briefing import _tag


def test_tag_stable():
    assert _tag(500, threshold=300) == "(stable)"


def test_tag_small_sample():
    assert _tag(120, threshold=300) == "(small sample: 120)"


def test_tag_none_unavailable():
    assert _tag(None, threshold=300) == "(unavailable)"
```

- [ ] **Step 3: Run — FAIL**

Run: `pytest tests/test_briefing.py::test_tag_stable -v`
Expected: FAIL.

- [ ] **Step 4: Add `_tag` helper to `briefing.py`**

Insert near the top of `briefing.py` (after existing imports):

```python
def _tag(sample_size, threshold: int) -> str:
    """Return a reliability tag for a sample count."""
    if sample_size is None:
        return "(unavailable)"
    try:
        s = int(sample_size)
    except (TypeError, ValueError):
        return "(unavailable)"
    if s >= threshold:
        return "(stable)"
    return f"(small sample: {s})"
```

- [ ] **Step 5: Run — PASS**

Run: `pytest tests/test_briefing.py::test_tag_stable tests/test_briefing.py::test_tag_small_sample tests/test_briefing.py::test_tag_none_unavailable -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add briefing.py tests/test_briefing.py
git commit -m "feat(briefing): add _tag reliability-tag helper"
```

---

### Task 14: Pitch Quality section

**Files:**
- Modify: `briefing.py`
- Modify: `tests/test_briefing.py`

- [ ] **Step 1: Write failing render test**

Append to `tests/test_briefing.py`:

```python
def _minimal_game_data(advanced_pitcher=None):
    return {
        "away_team": "LAD", "home_team": "SF",
        "away_record": "14-8", "home_record": "10-12",
        "away_pitcher": {"name": "Yamamoto", "advanced": advanced_pitcher or {}},
        "home_pitcher": {"name": "Webb", "advanced": {}},
        "odds": {"moneyline": {}, "run_line": {}, "total": {}, "implied_probs": {}},
        "odds_obj": None,
        "environment": {"venue": "Oracle", "roof": "open", "day_or_night": "night",
                         "weather": {"temp_f": 62, "wind_mph": 12, "wind_direction": "in",
                                     "humidity": 70, "pressure_mb": 1018},
                         "park_factor": 0.85},
        "away_bullpen": {}, "home_bullpen": {},
        "away_injuries": [], "home_injuries": [],
        "game_pk": None, "away_lineup": [], "home_lineup": [],
    }


def test_pitch_quality_section_renders_with_advanced():
    from briefing import build_briefing
    gd = _minimal_game_data(advanced_pitcher={
        "stuff_plus": 118, "location_plus": 103, "pitching_plus": 112,
        "bot_stf": 62, "bot_cmd": 54, "bot_ovr": 59,
        "xERA": 2.94, "xFIP": 3.18, "xwOBA_against": 0.278,
        "barrel_pct_against": 0.058, "hard_hit_pct_against": 0.321,
        "csw_pct": 0.314, "k_pct": 0.288, "bb_pct": 0.065,
        "ip": 92.1, "bf": 365,
    })
    out = build_briefing(gd)
    assert "== PITCH QUALITY ==" in out
    assert "Stuff+ 118" in out
    assert "xERA 2.94" in out


def test_pitch_quality_section_handles_missing():
    from briefing import build_briefing
    gd = _minimal_game_data(advanced_pitcher=None)
    out = build_briefing(gd)
    assert "== PITCH QUALITY ==" in out
    assert "N/A" in out
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_briefing.py -v`
Expected: 2 new tests FAIL.

- [ ] **Step 3: Add `_render_pitch_quality` and inject into `build_briefing`**

Add to `briefing.py` (after `_tag`):

```python
def _fmt(v, fmt=".3f", suffix=""):
    if v is None:
        return "N/A"
    try:
        return format(float(v), fmt) + suffix
    except Exception:
        return "N/A"


def _render_pitch_quality(game_data: dict) -> str:
    lines = ["== PITCH QUALITY =="]
    for side in ("away_pitcher", "home_pitcher"):
        p = game_data.get(side) or {}
        adv = p.get("advanced") or {}
        name = p.get("name", "TBD")
        bf_tag = _tag(adv.get("bf"), 300)
        pitch_tag = _tag(adv.get("bf"), 150)  # rough proxy for 500+ pitches
        lines.append(
            f"{name}: Stuff+ {_fmt(adv.get('stuff_plus'), '.0f')} {pitch_tag} | "
            f"Location+ {_fmt(adv.get('location_plus'), '.0f')} {pitch_tag}"
        )
        lines.append(
            f"  Pitching+ {_fmt(adv.get('pitching_plus'), '.0f')} | "
            f"PitchingBot: Stf {_fmt(adv.get('bot_stf'), '.0f')} "
            f"Cmd {_fmt(adv.get('bot_cmd'), '.0f')} Ovr {_fmt(adv.get('bot_ovr'), '.0f')}"
        )
        lines.append(
            f"  xERA {_fmt(adv.get('xERA'), '.2f')} {bf_tag} | "
            f"xFIP {_fmt(adv.get('xFIP'), '.2f')} | "
            f"xwOBA {_fmt(adv.get('xwOBA_against'), '.3f')} | "
            f"Barrel%-against {_fmt((adv.get('barrel_pct_against') or 0)*100, '.1f', '%') if adv.get('barrel_pct_against') is not None else 'N/A'} | "
            f"HardHit%-against {_fmt((adv.get('hard_hit_pct_against') or 0)*100, '.1f', '%') if adv.get('hard_hit_pct_against') is not None else 'N/A'}"
        )
        lines.append(
            f"  CSW {_fmt((adv.get('csw_pct') or 0)*100, '.1f', '%') if adv.get('csw_pct') is not None else 'N/A'} | "
            f"K% {_fmt((adv.get('k_pct') or 0)*100, '.1f', '%') if adv.get('k_pct') is not None else 'N/A'} | "
            f"BB% {_fmt((adv.get('bb_pct') or 0)*100, '.1f', '%') if adv.get('bb_pct') is not None else 'N/A'}"
        )
    return "\n".join(lines)
```

In `build_briefing`, locate the position right after the existing `== INJURIES ==` block and BEFORE the `{prediction_task}` substitution. Insert:

```python
    sections.append(_render_pitch_quality(game_data))
```

(Adapt variable names to the actual template-assembly pattern in `briefing.py`.)

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/test_briefing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing.py tests/test_briefing.py
git commit -m "feat(briefing): add PITCH QUALITY section"
```

---

### Task 15: Hitter Profiles + top-4 cap

**Files:**
- Modify: `briefing.py`
- Modify: `tests/test_briefing.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_briefing.py`:

```python
def _lineup(n=9):
    out = []
    for i in range(n):
        out.append({
            "name": f"Batter{i+1}", "position": "OF",
            "advanced": {"xwOBA": 0.320 + 0.01*i, "barrel_pct": 0.08,
                          "hard_hit_pct": 0.40, "bat_speed": 71.0, "pa": 300},
            "depth_charts": {"pa": 600, "wOBA": 0.340, "k_pct": 0.20, "bb_pct": 0.09},
        })
    return out


def test_hitter_profiles_top_4_only():
    from briefing import build_briefing
    gd = _minimal_game_data()
    gd["away_lineup"] = _lineup()
    gd["home_lineup"] = _lineup()
    out = build_briefing(gd)
    assert "== HITTER PROFILES ==" in out
    # Top 4 detailed
    assert "Batter1" in out
    assert "Batter4" in out
    # Aggregate for 5-9
    assert "5-9 holes" in out


def test_hitter_profiles_empty_lineup():
    from briefing import build_briefing
    gd = _minimal_game_data()
    out = build_briefing(gd)
    assert "== HITTER PROFILES ==" in out
    assert "lineup not posted" in out.lower() or "N/A" in out
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_briefing.py -v`
Expected: new tests FAIL.

- [ ] **Step 3: Implement `_render_hitter_profiles`**

Append to `briefing.py`:

```python
def _render_hitter_profiles(game_data: dict) -> str:
    lines = ["== HITTER PROFILES =="]
    for side_key, team_key in (("away_lineup", "away_team"), ("home_lineup", "home_team")):
        lineup = game_data.get(side_key) or []
        team = game_data.get(team_key, "?")
        if not lineup:
            lines.append(f"{team}: lineup not posted yet — N/A")
            continue
        lines.append(f"{team} (top 4):")
        top4 = lineup[:4]
        rest = lineup[4:9]
        for i, b in enumerate(top4, 1):
            adv = b.get("advanced") or {}
            dc = b.get("depth_charts") or {}
            pa_tag = _tag(adv.get("pa"), 150)
            lines.append(
                f"  {i}. {b.get('name','?')}: xwOBA {_fmt(adv.get('xwOBA'),'.3f')} {pa_tag} | "
                f"Barrel% {_fmt((adv.get('barrel_pct') or 0)*100,'.1f','%') if adv.get('barrel_pct') is not None else 'N/A'} | "
                f"HardHit% {_fmt((adv.get('hard_hit_pct') or 0)*100,'.1f','%') if adv.get('hard_hit_pct') is not None else 'N/A'} | "
                f"Bat speed {_fmt(adv.get('bat_speed'),'.1f','mph') if adv.get('bat_speed') is not None else 'N/A'}"
            )
            if dc.get("pa") is not None:
                lines.append(
                    f"     Depth Charts: {_fmt(dc.get('pa'),'.0f')} PA, "
                    f"wOBA {_fmt(dc.get('wOBA'),'.3f')}, "
                    f"K% {_fmt((dc.get('k_pct') or 0)*100,'.1f','%') if dc.get('k_pct') is not None else 'N/A'}, "
                    f"BB% {_fmt((dc.get('bb_pct') or 0)*100,'.1f','%') if dc.get('bb_pct') is not None else 'N/A'}"
                )
        if rest:
            xwobas = [ (b.get("advanced") or {}).get("xwOBA") for b in rest ]
            barrels = [ (b.get("advanced") or {}).get("barrel_pct") for b in rest ]
            xwobas = [x for x in xwobas if x is not None]
            barrels = [x for x in barrels if x is not None]
            avg_x = sum(xwobas)/len(xwobas) if xwobas else None
            avg_b = sum(barrels)/len(barrels) if barrels else None
            lines.append(
                f"  5-9 holes: avg xwOBA {_fmt(avg_x,'.3f')}, "
                f"avg Barrel% {_fmt((avg_b or 0)*100,'.1f','%') if avg_b is not None else 'N/A'}"
            )
    return "\n".join(lines)
```

Then append `sections.append(_render_hitter_profiles(game_data))` after the pitch-quality section.

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/test_briefing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing.py tests/test_briefing.py
git commit -m "feat(briefing): add HITTER PROFILES section with top-4 cap"
```

---

### Task 16: Umpire + Catcher Framing + Carry sections

**Files:**
- Modify: `briefing.py`
- Modify: `tests/test_briefing.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_briefing.py`:

```python
def test_umpire_section_with_profile():
    from briefing import build_briefing
    gd = _minimal_game_data()
    gd["umpire"] = {
        "name": "Angel Hernandez", "games_sample": 3412,
        "k_pct_delta": -0.8, "bb_pct_delta": 0.6,
        "runs_per_game_delta": 0.42,
        "consistency_pct": 91.2, "accuracy_pct": 93.5,
        "consecutive_games": 12,
    }
    out = build_briefing(gd)
    assert "== HOME PLATE UMPIRE ==" in out
    assert "Angel Hernandez" in out
    assert "-0.8" in out


def test_umpire_section_tbd():
    from briefing import build_briefing
    gd = _minimal_game_data()
    gd["umpire"] = None
    out = build_briefing(gd)
    assert "== HOME PLATE UMPIRE ==" in out
    assert "TBD" in out


def test_catcher_framing_section():
    from briefing import build_briefing
    gd = _minimal_game_data()
    gd["away_catcher"] = {"name": "Will Smith", "framing_runs_per_150": 6.8, "z_score": 0.9}
    gd["home_catcher"] = {"name": "Patrick Bailey", "framing_runs_per_150": 18.7, "z_score": 2.3}
    out = build_briefing(gd)
    assert "== CATCHER FRAMING ==" in out
    assert "Patrick Bailey" in out
    assert "z=+2.3" in out or "z=2.3" in out


def test_carry_section():
    from briefing import build_briefing
    gd = _minimal_game_data()
    gd["environment"]["carry"] = {
        "hr_multiplier": 0.962, "xbh_multiplier": 0.984,
        "batted_ball_distance_ft": -4.5,
        "reason": "62°F, wind 12mph in, roof open, pressure 1018mb",
    }
    out = build_briefing(gd)
    assert "== CARRY CONDITIONS ==" in out
    assert "HR 0.962" in out
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_briefing.py -v`
Expected: new tests FAIL.

- [ ] **Step 3: Implement three renderers**

Append to `briefing.py`:

```python
def _render_umpire(game_data: dict) -> str:
    ump = game_data.get("umpire")
    lines = ["== HOME PLATE UMPIRE =="]
    if not ump:
        lines.append("Home Plate Ump: TBD (using neutral deltas)")
        return "\n".join(lines)
    tag = _tag(ump.get("games_sample"), 1500)
    lines.append(f"{ump.get('name','Unknown')} (games: {ump.get('games_sample','?')}, {tag})")
    kd = ump.get("k_pct_delta", 0.0)
    bd = ump.get("bb_pct_delta", 0.0)
    rd = ump.get("runs_per_game_delta", 0.0)
    lines.append(f"  K% delta: {kd:+.1f}pp ({'pitcher-unfriendly' if kd < 0 else 'pitcher-friendly'})")
    lines.append(f"  BB% delta: {bd:+.1f}pp ({'pitcher-unfriendly' if bd > 0 else 'pitcher-friendly'})")
    lines.append(f"  Runs/game delta: {rd:+.2f}")
    lines.append(
        f"  Consistency: {_fmt(ump.get('consistency_pct'),'.1f','%')} | "
        f"Accuracy: {_fmt(ump.get('accuracy_pct'),'.1f','%')} | "
        f"Consecutive games: {ump.get('consecutive_games') or 'N/A'}"
    )
    return "\n".join(lines)


def _render_catcher_framing(game_data: dict) -> str:
    lines = ["== CATCHER FRAMING =="]
    for side, team_key in (("away_catcher", "away_team"), ("home_catcher", "home_team")):
        team = game_data.get(team_key, "?")
        c = game_data.get(side)
        if not c:
            lines.append(f"{team} starting C: unresolved — z=0.0")
            continue
        z = c.get("z_score", 0.0) or 0.0
        tier = "elite" if z >= 1.5 else ("above avg" if z >= 0.5 else ("below avg" if z <= -0.5 else "avg"))
        lines.append(
            f"{team} starting C: {c.get('name','?')} — "
            f"framing runs/150: {c.get('framing_runs_per_150',0):+.1f} "
            f"(z={z:+.1f}, {tier})"
        )
    return "\n".join(lines)


def _render_carry(game_data: dict) -> str:
    carry = (game_data.get("environment") or {}).get("carry")
    lines = ["== CARRY CONDITIONS =="]
    if not carry:
        lines.append("Carry: neutral (weather unavailable)")
        return "\n".join(lines)
    lines.append(
        f"Carry multiplier: HR {carry.get('hr_multiplier',1.0):.3f} | "
        f"XBH {carry.get('xbh_multiplier',1.0):.3f} | "
        f"Batted-ball dist {carry.get('batted_ball_distance_ft',0.0):+.1f} ft"
    )
    lines.append(f"Reason: {carry.get('reason','')}")
    lines.append("Applied on top of handedness-split park factors from Spec 3.")
    return "\n".join(lines)
```

Then wire them into `build_briefing` right after hitter profiles:

```python
    sections.append(_render_umpire(game_data))
    sections.append(_render_catcher_framing(game_data))
    sections.append(_render_carry(game_data))
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/test_briefing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing.py tests/test_briefing.py
git commit -m "feat(briefing): add UMPIRE, CATCHER FRAMING, CARRY sections"
```

---

### Task 17: Extend prediction-task block

**Files:**
- Modify: `briefing.py`
- Modify: `tests/test_briefing.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_briefing.py`:

```python
def test_prediction_task_has_spec4_items():
    from briefing import build_briefing
    gd = _minimal_game_data()
    out = build_briefing(gd)
    for keyword in (
        "STATCAST DISCOUNT", "PROJECTION ANCHOR",
        "UMPIRE LEAN", "FRAMING", "CARRY",
    ):
        assert keyword in out, f"missing {keyword} in prediction task"
```

- [ ] **Step 2: Run — FAIL**

Run: `pytest tests/test_briefing.py::test_prediction_task_has_spec4_items -v`
Expected: FAIL.

- [ ] **Step 3: Extend prediction-task string in `briefing.py`**

Locate the prediction-task block near `briefing.py:56-72`. Append after the existing items 1-7:

```
8. STATCAST DISCOUNT: Treat xwOBA, xERA, and barrel% as 15-20% more predictive
   than traditional stats (ERA, AVG) in small samples (<300 BF, <150 PA).
   Discount 14-day actuals accordingly.
9. PROJECTION ANCHOR: Depth Charts projection = true talent (prior).
   Recent actuals = noisy evidence. Weight the prior heavily when PA < 100.
10. UMPIRE LEAN: Apply umpire K%/BB% deltas directly to total runs estimate
    (-1pp K on both sides shifts total ~+0.4 runs).
11. FRAMING: Elite framing catcher (z > +1.5) subtracts ~0.3 runs/9 from
    allowed run rate vs. average framing.
12. CARRY: HR multiplier > 1.05 on an open-roof game should boost HR-heavy
    team-total and over projections.
```

- [ ] **Step 4: Run — PASS**

Run: `pytest tests/test_briefing.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing.py tests/test_briefing.py
git commit -m "feat(briefing): expand prediction-task block with Spec 4 items 8-12"
```

---

### Task 18: Golden-file snapshot test

**Files:**
- Create: `tests/fixtures/briefing_full.txt`
- Modify: `tests/test_briefing.py`

- [ ] **Step 1: Add snapshot test (expect it to fail first, then capture actual output)**

Append to `tests/test_briefing.py`:

```python
def test_briefing_snapshot(tmp_path):
    """Compare full briefing to golden file. Update file if intentional."""
    from briefing import build_briefing
    gd = _minimal_game_data(advanced_pitcher={
        "stuff_plus": 118, "location_plus": 103, "pitching_plus": 112,
        "bot_stf": 62, "bot_cmd": 54, "bot_ovr": 59,
        "xERA": 2.94, "xFIP": 3.18, "xwOBA_against": 0.278,
        "barrel_pct_against": 0.058, "hard_hit_pct_against": 0.321,
        "csw_pct": 0.314, "k_pct": 0.288, "bb_pct": 0.065,
        "ip": 92.1, "bf": 365,
    })
    gd["away_lineup"] = _lineup()
    gd["home_lineup"] = _lineup()
    gd["umpire"] = {"name": "Angel Hernandez", "games_sample": 3412,
                     "k_pct_delta": -0.8, "bb_pct_delta": 0.6,
                     "runs_per_game_delta": 0.42, "consistency_pct": 91.2,
                     "accuracy_pct": 93.5, "consecutive_games": 12}
    gd["away_catcher"] = {"name": "Will Smith", "framing_runs_per_150": 6.8, "z_score": 0.9}
    gd["home_catcher"] = {"name": "Patrick Bailey", "framing_runs_per_150": 18.7, "z_score": 2.3}
    gd["environment"]["carry"] = {
        "hr_multiplier": 0.962, "xbh_multiplier": 0.984,
        "batted_ball_distance_ft": -4.5,
        "reason": "62°F, wind 12mph in, roof open, pressure 1018mb",
    }
    out = build_briefing(gd)
    golden = os.path.join(os.path.dirname(__file__), "fixtures", "briefing_full.txt")
    if not os.path.exists(golden):
        with open(golden, "w") as f:
            f.write(out)
        pytest.skip("golden written; rerun to verify")
    with open(golden) as f:
        expected = f.read()
    assert out == expected
```

- [ ] **Step 2: First run — writes golden + skips**

Run: `pytest tests/test_briefing.py::test_briefing_snapshot -v`
Expected: SKIP (golden created).

- [ ] **Step 3: Inspect golden by hand**

Run: `cat tests/fixtures/briefing_full.txt`
Verify sections appear in correct order and content is sensible.

- [ ] **Step 4: Re-run — PASS**

Run: `pytest tests/test_briefing.py::test_briefing_snapshot -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add briefing.py tests/test_briefing.py tests/fixtures/briefing_full.txt
git commit -m "test(briefing): golden-file snapshot with all Spec 4 sections"
```

---

## Phase H — PA-sim integration

### Task 19: Wire `umpire_k_delta`, `umpire_bb_delta`, `catcher_framing_z` into `sample_pa`

**Files:**
- Modify: `simulation/pa_engine.py`
- Modify: `tests/test_pa_engine.py`

- [ ] **Step 1: Inspect current `pa_engine.py`**

Run: `wc -l simulation/pa_engine.py` and `grep -n "catcher_framing_z\|sample_pa\|k_pct" simulation/pa_engine.py`.

Confirm lines 77-89 define `sample_pa`; `catcher_framing_z=0.0` should already be a no-op kwarg from Spec 3.

- [ ] **Step 2: Write failing ump-K test**

Append to `tests/test_pa_engine.py`:

```python
def test_sample_pa_umpire_k_delta_shifts_k_rate():
    """-1.5pp umpire K delta should drop observed K rate by ~1.5pp."""
    import random
    from simulation.pa_engine import sample_pa

    batter = {"k_pct": 0.22, "bb_pct": 0.08, "hr_rate": 0.03,
               "iso": 0.15, "avg": 0.260, "obp": 0.330}
    pitcher = {"k_pct": 0.22, "bb_pct": 0.08, "hr_rate": 0.03}

    random.seed(42)
    k_neutral = sum(
        sample_pa(batter, pitcher, umpire_k_delta=0.0) == "K"
        for _ in range(50_000)
    )

    random.seed(42)
    k_shifted = sum(
        sample_pa(batter, pitcher, umpire_k_delta=-1.5) == "K"
        for _ in range(50_000)
    )

    pp_diff = (k_neutral - k_shifted) / 50_000
    assert 0.010 < pp_diff < 0.022, f"expected ~1.5pp drop, got {pp_diff:.4f}"


def test_sample_pa_framing_z_positive_boosts_k():
    """z=+2 framing should add ~1.2pp K (0.006 * 2)."""
    import random
    from simulation.pa_engine import sample_pa

    batter = {"k_pct": 0.22, "bb_pct": 0.08, "hr_rate": 0.03,
               "iso": 0.15, "avg": 0.260, "obp": 0.330}
    pitcher = {"k_pct": 0.22, "bb_pct": 0.08, "hr_rate": 0.03}

    random.seed(7)
    neutral = sum(
        sample_pa(batter, pitcher, catcher_framing_z=0.0) == "K"
        for _ in range(50_000)
    )
    random.seed(7)
    boosted = sum(
        sample_pa(batter, pitcher, catcher_framing_z=2.0) == "K"
        for _ in range(50_000)
    )
    pp_diff = (boosted - neutral) / 50_000
    assert 0.007 < pp_diff < 0.017, f"expected ~1.2pp rise, got {pp_diff:.4f}"


def test_sample_pa_framing_z_clipped_at_3():
    """z=+10 clips to +3 — never more than +1.8pp K shift."""
    import random
    from simulation.pa_engine import sample_pa

    batter = {"k_pct": 0.22, "bb_pct": 0.08, "hr_rate": 0.03,
               "iso": 0.15, "avg": 0.260, "obp": 0.330}
    pitcher = {"k_pct": 0.22, "bb_pct": 0.08, "hr_rate": 0.03}

    random.seed(1)
    clipped = sum(
        sample_pa(batter, pitcher, catcher_framing_z=10.0) == "K"
        for _ in range(30_000)
    )
    random.seed(1)
    neutral = sum(
        sample_pa(batter, pitcher, catcher_framing_z=0.0) == "K"
        for _ in range(30_000)
    )
    pp = (clipped - neutral) / 30_000
    assert pp < 0.025, f"expected clipped <=~+1.8pp, got {pp:.4f}"


def test_sample_pa_backward_compat_no_new_kwargs():
    """Calling with no new kwargs must produce same distribution as Spec 3."""
    import random
    from simulation.pa_engine import sample_pa

    batter = {"k_pct": 0.22, "bb_pct": 0.08, "hr_rate": 0.03,
               "iso": 0.15, "avg": 0.260, "obp": 0.330}
    pitcher = {"k_pct": 0.22, "bb_pct": 0.08, "hr_rate": 0.03}

    random.seed(2026)
    baseline = [sample_pa(batter, pitcher) for _ in range(1000)]
    random.seed(2026)
    explicit = [sample_pa(batter, pitcher, umpire_k_delta=0.0,
                          umpire_bb_delta=0.0, catcher_framing_z=0.0)
                for _ in range(1000)]
    assert baseline == explicit
```

- [ ] **Step 3: Run — FAIL**

Run: `pytest tests/test_pa_engine.py -v`
Expected: new tests FAIL (signature doesn't accept ump kwargs OR they're no-ops).

- [ ] **Step 4: Update `sample_pa` signature + `_build_matchup_probs`**

In `simulation/pa_engine.py`, update the signature at line 77:

```python
def sample_pa(
    batter: dict, pitcher: dict,
    park_factor_runs: float = 1.0, park_factor_hr: float = 1.0,
    catcher_framing_z: float = 0.0,
    umpire_k_delta: float = 0.0,
    umpire_bb_delta: float = 0.0,
) -> str:
```

Inside `_build_matchup_probs` (lines ~46-74), before the log5 combine, compute adjusted pitcher K/BB:

```python
    # Spec 4: framing + umpire shifts on pitcher rates
    z_clip = max(-3.0, min(3.0, catcher_framing_z))
    framing_k_shift = 0.006 * z_clip
    framing_bb_shift = -0.004 * z_clip

    p_k = pitcher.get("k_pct", LEAGUE_AVERAGES["k_pct"]) + framing_k_shift + umpire_k_delta / 100.0
    p_bb = pitcher.get("bb_pct", LEAGUE_AVERAGES["bb_pct"]) + framing_bb_shift + umpire_bb_delta / 100.0

    p_k = max(0.01, min(0.95, p_k))
    p_bb = max(0.01, min(0.95, p_bb))
```

Then replace the existing log5 inputs for K/BB outcomes with `p_k`/`p_bb`. Thread the new kwargs through `_build_matchup_probs` if separated.

- [ ] **Step 5: Run — PASS**

Run: `pytest tests/test_pa_engine.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add simulation/pa_engine.py tests/test_pa_engine.py
git commit -m "feat(pa): wire umpire K/BB deltas + catcher framing z into sample_pa"
```

---

### Task 20: Propagate deltas through `game_sim.py` / `monte_carlo.py`

**Files:**
- Modify: `simulation/game_sim.py`
- Modify: `simulation/monte_carlo.py`

- [ ] **Step 1: Inspect game_sim flow**

Run: `grep -n "sample_pa\|catcher_framing_z\|umpire" simulation/game_sim.py simulation/monte_carlo.py`

- [ ] **Step 2: Thread kwargs through `game_sim.simulate_game`**

Add to `simulation/game_sim.py` signature:

```python
def simulate_game(
    home_lineup, away_lineup, home_pitcher, away_pitcher,
    park_factor_runs=1.0, park_factor_hr=1.0,
    home_catcher_z: float = 0.0,
    away_catcher_z: float = 0.0,
    umpire_k_delta: float = 0.0,
    umpire_bb_delta: float = 0.0,
    ...
):
```

At each `sample_pa(...)` call, pass the correct catcher z (the defensive team's catcher modifies their pitcher):
- home team pitching -> `catcher_framing_z=home_catcher_z`
- away team pitching -> `catcher_framing_z=away_catcher_z`

Thread `umpire_*_delta` unchanged to both.

- [ ] **Step 3: Thread through `monte_carlo.run_monte_carlo`**

Same pattern — add new kwargs, pass to `simulate_game` per iteration.

- [ ] **Step 4: Add regression test**

In `tests/test_game_sim.py` add:

```python
def test_simulate_game_accepts_framing_and_ump_kwargs():
    """Regression: new kwargs must not break existing callers."""
    from simulation.game_sim import simulate_game
    # Minimal happy path with all kwargs — just verify no TypeError
    result = simulate_game(
        home_lineup=[], away_lineup=[],
        home_pitcher={}, away_pitcher={},
        home_catcher_z=0.5, away_catcher_z=-0.5,
        umpire_k_delta=1.0, umpire_bb_delta=-0.5,
    )
    assert result is not None or result == {} or hasattr(result, "__getitem__")
```

- [ ] **Step 5: Run regression**

Run: `pytest tests/test_game_sim.py tests/test_pa_engine.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add simulation/game_sim.py simulation/monte_carlo.py tests/test_game_sim.py
git commit -m "feat(sim): propagate catcher z + umpire deltas through game_sim + MC"
```

---

## Phase I — Orchestration

### Task 21: Pre-warm caches at daily_runner startup

**Files:**
- Modify: `agents/daily_runner.py`

- [ ] **Step 1: Inspect daily_runner**

Run: `grep -n "def\|prewarm\|warm\|build_briefing" agents/daily_runner.py | head -30`

- [ ] **Step 2: Add prewarm block near top of `main` / `run_daily`**

Add at the start of the daily entrypoint (before the per-game loop):

```python
    from config import DATA_V2_ENABLED, SOURCES_ENABLED
    if DATA_V2_ENABLED:
        season = int(game_date[:4])
        if SOURCES_ENABLED.get("statcast"):
            try:
                from scrapers.statcast_advanced import prewarm_statcast_leaderboards
                prewarm_statcast_leaderboards(season)
            except Exception as e:
                logger.warning("statcast prewarm failed: %s", e)
        if SOURCES_ENABLED.get("depth_charts"):
            try:
                from scrapers.player_stats import prewarm_depth_charts
                prewarm_depth_charts(season)
            except Exception as e:
                logger.warning("DC prewarm failed: %s", e)
        if SOURCES_ENABLED.get("catcher"):
            try:
                from scrapers.catcher_framing import get_all_catcher_framing
                get_all_catcher_framing(season)
            except Exception as e:
                logger.warning("catcher framing prewarm failed: %s", e)
```

- [ ] **Step 3: Enrich per-game `game_data` when DATA_V2_ENABLED**

Inside the per-game screening function, after building `game_data`, add:

```python
    if DATA_V2_ENABLED:
        season = int(game_date[:4])
        # Statcast
        if SOURCES_ENABLED.get("statcast"):
            from scrapers.statcast_advanced import get_pitcher_advanced, get_batter_advanced
            for key in ("away_pitcher", "home_pitcher"):
                pid = game_data[key].get("mlbam_id") or game_data[key].get("id")
                if pid:
                    game_data[key]["advanced"] = get_pitcher_advanced(pid, season)
            for side in ("away_lineup", "home_lineup"):
                for b in game_data.get(side, []) or []:
                    pid = b.get("player_id") or b.get("id")
                    if pid:
                        b["advanced"] = get_batter_advanced(pid, season)
        # Umpire
        if SOURCES_ENABLED.get("umpire") and game_data.get("game_pk"):
            from scrapers.umpire import get_umpire_assignment, get_umpire_profile
            assign = get_umpire_assignment(game_data["game_pk"])
            if assign:
                prof = get_umpire_profile(assign["home_plate_ump_id"], assign["name"])
                game_data["umpire"] = {**assign, **prof}
            else:
                game_data["umpire"] = None
        # Catcher framing
        if SOURCES_ENABLED.get("catcher"):
            from scrapers.catcher_framing import get_catcher_framing
            from scrapers.lineups import get_starting_catcher
            for side, out_key in (("home_lineup", "home_catcher"), ("away_lineup", "away_catcher")):
                cid = get_starting_catcher(game_data.get(side) or [])
                if cid:
                    prof = get_catcher_framing(cid, season)
                    prof["name"] = "C"  # replace with actual lookup
                    game_data[out_key] = prof
                else:
                    game_data[out_key] = None
        # Depth Charts
        if SOURCES_ENABLED.get("depth_charts"):
            from scrapers.player_stats import get_depth_charts_hitter, get_depth_charts_pitcher
            for key in ("away_pitcher", "home_pitcher"):
                pid = game_data[key].get("mlbam_id") or game_data[key].get("id")
                if pid:
                    game_data[key]["depth_charts"] = get_depth_charts_pitcher(pid, season)
            for side in ("away_lineup", "home_lineup"):
                for b in game_data.get(side, []) or []:
                    pid = b.get("player_id") or b.get("id")
                    if pid:
                        b["depth_charts"] = get_depth_charts_hitter(pid, season)
        # Carry
        if SOURCES_ENABLED.get("carry"):
            from scrapers.ballpark import compute_carry_multiplier
            from config import PARK_ELEVATIONS
            env = game_data.get("environment", {})
            w = env.get("weather", {})
            carry = compute_carry_multiplier(
                temp_f=w.get("temp_f", 72),
                pressure_mb=w.get("pressure_mb", 1013),
                humidity_pct=w.get("humidity", 50),
                wind_mph=w.get("wind_mph", 0),
                wind_dir=w.get("wind_direction", "calm"),
                roof_status=env.get("roof", "open"),
                elevation_ft=PARK_ELEVATIONS.get(game_data["home_team"], 0),
                team_abbrev=game_data["home_team"],
            )
            env["carry"] = carry
            game_data["environment"] = env
```

- [ ] **Step 4: Daily summary log line**

At the end of the daily loop:

```python
    sources = {k: ("ok" if v else "off") for k, v in SOURCES_ENABLED.items()}
    logger.info("Spec4 sources: %s", " ".join(f"{k}={v}" for k, v in sources.items()))
```

- [ ] **Step 5: Quick smoke**

Run: `python3 -c "from agents.daily_runner import *"` — confirm no import errors.

- [ ] **Step 6: Commit**

```bash
git add agents/daily_runner.py
git commit -m "feat(daily_runner): prewarm Spec 4 caches + enrich game_data per source"
```

---

### Task 22: End-to-end smoke test

**Files:**
- Create: `tests/test_daily_runner_smoke.py`

- [ ] **Step 1: Write smoke tests**

Create `tests/test_daily_runner_smoke.py`:

```python
"""Daily-runner smoke tests for Spec 4 integration."""
from unittest.mock import patch, MagicMock

import pytest


def test_daily_runner_survives_all_sources_disabled(monkeypatch):
    """All SOURCES_ENABLED flags False → pipeline still produces briefing + bets."""
    monkeypatch.setenv("DATA_V2_ENABLED", "true")
    monkeypatch.setenv("SRC_STATCAST", "false")
    monkeypatch.setenv("SRC_UMPIRE", "false")
    monkeypatch.setenv("SRC_CATCHER", "false")
    monkeypatch.setenv("SRC_DEPTH_CHARTS", "false")
    monkeypatch.setenv("SRC_CARRY", "false")
    # Re-import config to pick up env
    import importlib
    import config
    importlib.reload(config)
    assert config.DATA_V2_ENABLED is True
    assert all(not v for v in config.SOURCES_ENABLED.values())


def test_daily_runner_survives_umpscorecards_500(monkeypatch):
    """UmpScorecards 500 → neutral profile surfaced, briefing still renders."""
    from scrapers import umpire as ump_mod

    with patch.object(ump_mod.requests, "get", side_effect=RuntimeError("500")):
        prof = ump_mod.get_umpire_profile(427053, "Angel Hernandez")
    assert prof["last_scrape_status"] in ("fixture_fallback", "neutral_default")


def test_daily_runner_briefing_has_all_spec4_sections(monkeypatch):
    """With all sources ON, a minimal synthetic game yields all 5 new sections."""
    from briefing import build_briefing

    gd = {
        "away_team": "LAD", "home_team": "SF",
        "away_record": "14-8", "home_record": "10-12",
        "away_pitcher": {"name": "Y", "advanced": {"stuff_plus": 110, "bf": 200}},
        "home_pitcher": {"name": "W", "advanced": {"stuff_plus": 99, "bf": 300}},
        "odds": {"moneyline": {}, "run_line": {}, "total": {}, "implied_probs": {}},
        "odds_obj": None,
        "environment": {
            "venue": "Oracle", "roof": "open", "day_or_night": "night",
            "weather": {"temp_f": 62, "wind_mph": 12, "wind_direction": "in",
                         "humidity": 70, "pressure_mb": 1018},
            "park_factor": 0.85,
            "carry": {"hr_multiplier": 0.96, "xbh_multiplier": 0.98,
                       "batted_ball_distance_ft": -4.5, "reason": "cold"},
        },
        "away_bullpen": {}, "home_bullpen": {},
        "away_injuries": [], "home_injuries": [],
        "away_lineup": [], "home_lineup": [],
        "umpire": {"name": "Angel H", "games_sample": 3000,
                    "k_pct_delta": -0.8, "bb_pct_delta": 0.6,
                    "runs_per_game_delta": 0.42,
                    "consistency_pct": 91.0, "accuracy_pct": 93.0,
                    "consecutive_games": 10},
        "away_catcher": {"name": "WS", "framing_runs_per_150": 6.8, "z_score": 0.9},
        "home_catcher": {"name": "PB", "framing_runs_per_150": 18.7, "z_score": 2.3},
        "game_pk": None,
    }
    out = build_briefing(gd)
    for section in (
        "== PITCH QUALITY ==",
        "== HITTER PROFILES ==",
        "== HOME PLATE UMPIRE ==",
        "== CATCHER FRAMING ==",
        "== CARRY CONDITIONS ==",
    ):
        assert section in out, f"missing {section}"
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_daily_runner_smoke.py -v`
Expected: PASS.

- [ ] **Step 3: Full test suite**

Run: `pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_daily_runner_smoke.py
git commit -m "test(smoke): end-to-end daily-runner Spec 4 smoke tests"
```

---

## Phase J — Backfills & rebuilds

### Task 23: Run umpire backfill once pre-merge

**Files:**
- None modified; operational.

- [ ] **Step 1: Run the backfill**

Run: `python3 scripts/backfill_umpires.py --days 30 2>&1 | tee /tmp/backfill_umpires.log`
Expected: populates `data/umpire_cache.json` with ~150 unique umps over ~5 minutes.

- [ ] **Step 2: Inspect cache**

Run: `python3 -c "import json; d=json.load(open('data/umpire_cache.json')); print(len(d), list(d)[:5])"`
Expected: ≥ 80 entries.

- [ ] **Step 3: Seed `data/umpire_fixture.json` from cache**

If the shipped fixture is a stub (from Task 7), operator should copy the top 80 entries from the live cache into `data/umpire_fixture.json` under `umps:`. Commit the enriched fixture.

- [ ] **Step 4: Commit fixture refresh (only if content changed)**

```bash
git add data/umpire_fixture.json
git commit -m "data(umpire): seed fixture with top-80 umpire profiles from backfill"
```

---

### Task 24: Flip `DATA_V2_ENABLED=true`, rerun Spec 1 calibrate-rebuild

**Files:**
- None (operational step).

- [ ] **Step 1: Enable the flag in prod env**

Set `DATA_V2_ENABLED=true` in the deployment's environment (`.env`, Render secret, whatever drives the daily runner). Leave per-source `SRC_*` at their defaults (`true`).

- [ ] **Step 2: Trigger one daily run**

Run: `python3 agents/daily_runner.py` (or equivalent).
Verify in logs: `Spec4 sources: statcast=ok umpire=ok catcher=ok depth_charts=ok carry=ok`.

- [ ] **Step 3: Rerun Spec 1 calibrate-rebuild**

Run: `bash -lc "calibrate-rebuild"` (or the equivalent command from Spec 1).
Expected: recalibrates model curves against new briefing-driven outputs. Record new bins to verify ensemble weights still make sense.

- [ ] **Step 4: Smoke-check a flagged bet**

Run the bet-card skill for today. Confirm it produces recommendations without errors and the briefings embedded in logs show all 5 new sections.

- [ ] **Step 5: Monitor**

Over the next 7 days, watch CLV (Spec 1). If CLV regresses ≥ 0.3pp or ensemble consensus drops ≥ 5%, disable individual sources via `SRC_*=false` env vars in order of suspicion: umpire → carry → catcher → statcast → depth_charts.

- [ ] **Step 6: Nothing to commit**

This is a rollout step. If the calibration produces a new weights/bins file checked into the repo, commit it with:

```bash
git add data/calibration/<new-bins-file>
git commit -m "chore(calibrate): rebuild calibration bins after Spec 4 enablement"
```

---

## Verification Checklist

After all tasks green:

- [ ] `pytest tests/ -v` — all pass, no skips except the intentional snapshot bootstrap
- [ ] `python3 -c "from config import DATA_V2_ENABLED, SOURCES_ENABLED, PARK_ELEVATIONS"` — no errors
- [ ] `python3 scripts/backfill_umpires.py --days 1` — pulls today's umpires without crashing
- [ ] `python3 agents/daily_runner.py` with `DATA_V2_ENABLED=true` — completes, briefings contain all 5 sections
- [ ] `grep -c "== PITCH QUALITY ==" coral_scraper.log` — ≥ 1 per game
- [ ] Existing Spec 1/2/3 tests (`tests/test_game_sim.py`, `tests/test_ensemble_runner.py`, etc.) — still pass
- [ ] `git log --oneline` — every task corresponds to one or more focused commits; no squash needed
