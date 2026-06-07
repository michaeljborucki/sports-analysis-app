# Handedness-Aware Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce handedness-aware PA sampling, handedness-split park factors, continuous TTO fatigue, a RISP context bump, and a forward-compat catcher-framing hook, all gated behind `SIM_V2_ENABLED`.

**Architecture:** `simulation/pa_engine.py:sample_pa` gets a new signature accepting a `park_factors` dict, `pitcher_hand` / `batter_hand`, `runners_on_scoring_position`, `pitcher_pa_count`, `catcher_framing_z`, and an optional `rng`. Rate lookup resolves to per-side splits sourced from `scrapers/player_stats.py:get_batter_splits` / `get_pitcher_splits` (cached 1-day TTL). `config.PARK_FACTORS` is rewritten from scalar `runs`/`hr` to four split keys per team. `simulation/game_sim.py` tracks per-pitcher PA counts, detects RISP, and threads handedness through every `sample_pa` call. A `SIM_V2_ENABLED` env flag gates the new path so Spec 1 can A/B v1 vs v2.

**Tech Stack:** `pybaseball` (statcast_batter/statcast_pitcher), `pandas`, `pytest`, `threading.Lock`, Python 3.11+ stdlib (`random.Random`, `json`, `os`).

**Spec:** `docs/superpowers/specs/2026-04-17-handedness-aware-sim-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `config.py` | Modify | Rewrite `PARK_FACTORS` (lines 99-130) to split schema between sentinel comments; add `park_factor_runs_for`/`park_factor_hr_for`/`park_factors_dict_for` accessors; add `SIM_RISP_MULTIPLIERS`; add `SIM_V2_ENABLED` flag. |
| `simulation/pa_engine.py` | Modify | Refactor `sample_pa` signature; add `_rates_for_side`, `_apply_tto_fatigue`, `_apply_risp_multipliers`, `_apply_framing` helpers; accept injectable `rng: random.Random`. |
| `simulation/game_sim.py` | Modify | Add `pitcher_pa_count`/`batter_seen_count` to `GameState` (~line 45-54); increment per PA (~line 281); detect RISP; resolve switch-hitters; thread handedness + `park_factors` into `sample_pa`. |
| `simulation/monte_carlo.py` | Modify | Update `sample_pa` call sites to new signature; accept `park_factors` dict. |
| `simulation/props_edge.py` | Modify | Update every `sample_pa` call site to new signature. |
| `scrapers/player_stats.py` | Modify | Add `get_batter_splits` / `get_pitcher_splits` with file-locked 1-day cache + Bayesian shrinkage; add `LEAGUE_PLATOON_COEF_*` constants. |
| `scrapers/lineups.py` | Read-only | Already emits `bats`; no code change. |
| `scripts/update_park_factors.py` | Create | Fetch Savant park-factor CSV (L and R), shrink noisy splits, rewrite `PARK_FACTORS` dict. |
| `data/player_splits_cache.json` | Create (gitignored) | Splits cache. |
| `tests/test_pa_engine_platoon.py` | Create | Platoon routing, sum-to-1 property, TTO monotone, RISP shift, framing no-op. |
| `tests/test_park_factors.py` | Create | Accessor coverage for L/R/None/legacy fallback. |
| `tests/test_game_sim_golden.py` | Create | Seeded golden-game regression + v1-vs-v2 divergence smoke. |
| `tests/test_player_splits.py` | Create | Mock `pybaseball.statcast_*`, assert rates + regression + TTL. |
| `tests/test_update_park_factors.py` | Create | Pure helpers (`_shrink_to_overall`, `_normalize_savant_rows`, `_render_park_factors_block`). |
| `tests/test_pa_engine.py` | Modify | Add `_rates_for_side` tests; assert backward-compat shim. |
| `tests/test_game_sim.py` | Modify | PA-count state, park-factors dict kwarg, RISP smoke. |
| `tests/test_props_edge.py` | Modify | New signature assertions. |

---

## Pre-flight

- [ ] **Step 0: Verify clean start**

Run: `git status --short && pytest tests/ -x -q`
Expected: known in-progress files only; tests green (or document pre-existing failures — don't attribute them to this plan).

- [ ] **Step 0.1: Confirm Specs 1 and 2 prerequisites live**

Run: `grep -rn "model_variant" ensemble/ tracker.py`
Expected: at least one match (if not, coordinate with Spec 1 author before Task 16).

---

## Phase A — Handedness-split park factors

### Task 1: Savant refresh script + pure-helper tests

**Files:** Create `scripts/update_park_factors.py`, `scripts/__init__.py`, `tests/test_update_park_factors.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_update_park_factors.py`:

```python
import pytest
import pandas as pd
from scripts.update_park_factors import (
    _shrink_to_overall, _normalize_savant_rows, _render_park_factors_block,
)

def test_shrink_within_cap():
    assert _shrink_to_overall(1.10, 1.05, overall=1.08, cap=0.15) == (1.10, 1.05)

def test_shrink_beyond_cap():
    lhh, rhh = _shrink_to_overall(1.40, 0.80, overall=1.00, cap=0.15)
    assert lhh == pytest.approx(1.20) and rhh == pytest.approx(0.90)

def test_normalize_rows():
    lhh = pd.DataFrame([{"Team": "NYY", "R": 108, "HR": 125}])
    rhh = pd.DataFrame([{"Team": "NYY", "R": 102, "HR": 105}])
    ov = pd.DataFrame([{"Team": "NYY", "R": 105, "HR": 115}])
    out = _normalize_savant_rows(lhh, rhh, ov)
    assert out["NYY"]["runs_lhh"] == pytest.approx(1.08)
    assert out["NYY"]["hr_lhh"] == pytest.approx(1.25)

def test_render_block_has_sentinels():
    text = _render_park_factors_block({"NYY": {"name": "Yankee Stadium",
        "runs_lhh": 1.08, "runs_rhh": 1.02, "hr_lhh": 1.25, "hr_rhh": 1.05,
        "roof": "open"}})
    assert "# BEGIN AUTO-GENERATED PARK FACTORS" in text
    assert "# END AUTO-GENERATED PARK FACTORS" in text
    assert '"runs_lhh": 1.08' in text
```

- [ ] **Step 2: Verify it fails**

Run: `pytest tests/test_update_park_factors.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create script**

```bash
mkdir -p scripts && [ -f scripts/__init__.py ] || : > scripts/__init__.py
```

Create `scripts/update_park_factors.py`:

```python
"""Refresh PARK_FACTORS in config.py from Baseball Savant (quarterly refresh)."""
import argparse, re
from io import StringIO
from pathlib import Path
import pandas as pd
import requests

SAVANT_URL = ("https://baseballsavant.mlb.com/leaderboard/statcast-park-factors"
              "?type=year&year={year}&batSide={side}&condition=All&rolling={window}&csv=true")
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.py"
SENTINEL_START = "    # BEGIN AUTO-GENERATED PARK FACTORS"
SENTINEL_END = "    # END AUTO-GENERATED PARK FACTORS"

PARK_NAMES = {  # team -> stadium name. Mirrors config; update both if teams change.
    "ARI": "Chase Field", "ATL": "Truist Park", "BAL": "Camden Yards",
    "BOS": "Fenway Park", "CHC": "Wrigley Field", "CWS": "Guaranteed Rate Field",
    "CIN": "Great American Ball Park", "CLE": "Progressive Field",
    "COL": "Coors Field", "DET": "Comerica Park", "HOU": "Minute Maid Park",
    "KC": "Kauffman Stadium", "LAA": "Angel Stadium", "LAD": "Dodger Stadium",
    "MIA": "loanDepot Park", "MIL": "American Family Field",
    "MIN": "Target Field", "NYM": "Citi Field", "NYY": "Yankee Stadium",
    "OAK": "Oakland Coliseum", "PHI": "Citizens Bank Park", "PIT": "PNC Park",
    "SD": "Petco Park", "SF": "Oracle Park", "SEA": "T-Mobile Park",
    "STL": "Busch Stadium", "TB": "Tropicana Field", "TEX": "Globe Life Field",
    "TOR": "Rogers Centre", "WSH": "Nationals Park",
}
ROOF = {"ARI": "retractable", "HOU": "retractable", "MIA": "retractable",
        "MIL": "retractable", "SEA": "retractable", "TEX": "retractable",
        "TOR": "retractable", "TB": "dome"}


def _fetch_savant(year, window, side):
    r = requests.get(SAVANT_URL.format(year=year, side=side, window=window), timeout=30)
    r.raise_for_status()
    return pd.read_csv(StringIO(r.text))


def _shrink_to_overall(lhh, rhh, overall, cap=0.15):
    if abs(lhh - overall) > cap: lhh = 0.5 * (lhh + overall)
    if abs(rhh - overall) > cap: rhh = 0.5 * (rhh + overall)
    return round(lhh, 3), round(rhh, 3)


def _normalize_savant_rows(lhh_df, rhh_df, overall_df):
    out = {}
    for team in PARK_NAMES:
        l, r, o = lhh_df.loc[lhh_df["Team"] == team], rhh_df.loc[rhh_df["Team"] == team], overall_df.loc[overall_df["Team"] == team]
        if l.empty or r.empty or o.empty: continue
        r_l, r_r, r_o = float(l.iloc[0]["R"])/100, float(r.iloc[0]["R"])/100, float(o.iloc[0]["R"])/100
        hr_l, hr_r, hr_o = float(l.iloc[0]["HR"])/100, float(r.iloc[0]["HR"])/100, float(o.iloc[0]["HR"])/100
        r_l, r_r = _shrink_to_overall(r_l, r_r, r_o)
        hr_l, hr_r = _shrink_to_overall(hr_l, hr_r, hr_o)
        out[team] = {"name": PARK_NAMES[team], "runs_lhh": r_l, "runs_rhh": r_r,
                     "hr_lhh": hr_l, "hr_rhh": hr_r, "roof": ROOF.get(team, "open")}
    return out


def _render_park_factors_block(data):
    lines = [SENTINEL_START, "    PARK_FACTORS = {"]
    for t, r in data.items():
        lines.append(f'        "{t}": {{"name": "{r["name"]}", '
                     f'"runs_lhh": {r["runs_lhh"]:.3f}, "runs_rhh": {r["runs_rhh"]:.3f}, '
                     f'"hr_lhh": {r["hr_lhh"]:.3f}, "hr_rhh": {r["hr_rhh"]:.3f}, '
                     f'"roof": "{r["roof"]}"}},')
    lines += ["    }", SENTINEL_END]
    return "\n".join(lines)


def _rewrite_config(block):
    src = CONFIG_PATH.read_text()
    pat = re.compile(rf"{re.escape(SENTINEL_START)}.*?{re.escape(SENTINEL_END)}", re.DOTALL)
    if not pat.search(src):
        raise RuntimeError("Sentinel comments not found in config.py — did Task 2 run?")
    CONFIG_PATH.write_text(pat.sub(block.replace("\\", "\\\\"), src))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--window", type=int, default=3)
    a = ap.parse_args()
    lhh = _fetch_savant(a.year, a.window, "L")
    rhh = _fetch_savant(a.year, a.window, "R")
    ov  = _fetch_savant(a.year, a.window, "All")
    data = _normalize_savant_rows(lhh, rhh, ov)
    _rewrite_config(_render_park_factors_block(data))
    print(f"Updated {len(data)} parks in config.py")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests + commit**

```bash
pytest tests/test_update_park_factors.py -v   # expect PASS
git add scripts/update_park_factors.py scripts/__init__.py tests/test_update_park_factors.py
git commit -m "feat: add Savant park-factor refresh script + tests"
```

---

### Task 2: Rewrite `PARK_FACTORS` to handedness-split schema

**Files:** Modify `config.py:97-130`, create `tests/test_park_factors.py`.

- [ ] **Step 1: Write failing test**

Create `tests/test_park_factors.py`:

```python
import pytest
import config
from config import park_factor_runs_for, park_factor_hr_for, TEAM_ABBREVS

def test_nyy_lhh_runs_beats_rhh():
    assert park_factor_runs_for("NYY", "L") > park_factor_runs_for("NYY", "R")

def test_nyy_lhh_hr_beats_rhh():
    assert park_factor_hr_for("NYY", "L") > park_factor_hr_for("NYY", "R")

def test_bos_rhh_hr_beats_lhh():
    assert park_factor_hr_for("BOS", "R") > park_factor_hr_for("BOS", "L")

def test_unknown_hand_averages():
    nyy = config.PARK_FACTORS["NYY"]
    assert park_factor_runs_for("NYY", None) == pytest.approx((nyy["runs_lhh"] + nyy["runs_rhh"]) / 2)

def test_unknown_team_neutral():
    assert park_factor_runs_for("ZZZ", "L") == 1.0
    assert park_factor_hr_for("ZZZ", "R") == 1.0

def test_legacy_scalar_fallback(monkeypatch):
    monkeypatch.setitem(config.PARK_FACTORS, "XXX",
        {"name": "Legacy", "runs": 1.07, "hr": 1.11, "roof": "open"})
    assert park_factor_runs_for("XXX", "L") == 1.07
    assert park_factor_hr_for("XXX", None) == 1.11

def test_every_team_has_split_keys():
    for team in TEAM_ABBREVS:
        pf = config.PARK_FACTORS[team]
        for k in ("runs_lhh", "runs_rhh", "hr_lhh", "hr_rhh"):
            assert k in pf and 0.5 < pf[k] < 2.0
```

- [ ] **Step 2: Verify it fails**

Run: `pytest tests/test_park_factors.py -v` → expect accessor ImportError + split-key AssertionError.

- [ ] **Step 3: Rewrite `PARK_FACTORS` in `config.py`**

Replace lines 97-130 of `config.py` with:

```python
# Park factors: keyed by team abbreviation. Per-handedness split factors
# (runs_lhh / runs_rhh / hr_lhh / hr_rhh), seeded from Baseball Savant 3-year
# rolling Statcast Park Factors (2023-2025). Regenerated by
# `python scripts/update_park_factors.py --year 2026 --window 3`.
    # BEGIN AUTO-GENERATED PARK FACTORS
PARK_FACTORS = {
    "ARI": {"name": "Chase Field", "runs_lhh": 1.05, "runs_rhh": 1.05, "hr_lhh": 1.05, "hr_rhh": 1.05, "roof": "retractable"},
    "ATL": {"name": "Truist Park", "runs_lhh": 1.00, "runs_rhh": 1.00, "hr_lhh": 1.03, "hr_rhh": 1.07, "roof": "open"},
    "BAL": {"name": "Camden Yards", "runs_lhh": 1.07, "runs_rhh": 1.03, "hr_lhh": 1.15, "hr_rhh": 1.05, "roof": "open"},
    "BOS": {"name": "Fenway Park", "runs_lhh": 1.06, "runs_rhh": 1.13, "hr_lhh": 0.88, "hr_rhh": 1.00, "roof": "open"},
    "CHC": {"name": "Wrigley Field", "runs_lhh": 1.05, "runs_rhh": 1.05, "hr_lhh": 1.05, "hr_rhh": 1.05, "roof": "open"},
    "CWS": {"name": "Guaranteed Rate Field", "runs_lhh": 1.05, "runs_rhh": 1.05, "hr_lhh": 1.10, "hr_rhh": 1.10, "roof": "open"},
    "CIN": {"name": "Great American Ball Park", "runs_lhh": 1.15, "runs_rhh": 1.15, "hr_lhh": 1.28, "hr_rhh": 1.22, "roof": "open"},
    "CLE": {"name": "Progressive Field", "runs_lhh": 0.95, "runs_rhh": 0.95, "hr_lhh": 0.95, "hr_rhh": 0.95, "roof": "open"},
    "COL": {"name": "Coors Field", "runs_lhh": 1.35, "runs_rhh": 1.35, "hr_lhh": 1.28, "hr_rhh": 1.32, "roof": "open"},
    "DET": {"name": "Comerica Park", "runs_lhh": 0.95, "runs_rhh": 0.95, "hr_lhh": 0.88, "hr_rhh": 0.92, "roof": "open"},
    "HOU": {"name": "Minute Maid Park", "runs_lhh": 1.05, "runs_rhh": 1.05, "hr_lhh": 1.08, "hr_rhh": 1.12, "roof": "retractable"},
    "KC": {"name": "Kauffman Stadium", "runs_lhh": 1.00, "runs_rhh": 1.00, "hr_lhh": 0.95, "hr_rhh": 0.95, "roof": "open"},
    "LAA": {"name": "Angel Stadium", "runs_lhh": 0.95, "runs_rhh": 0.95, "hr_lhh": 1.00, "hr_rhh": 1.00, "roof": "open"},
    "LAD": {"name": "Dodger Stadium", "runs_lhh": 0.95, "runs_rhh": 0.95, "hr_lhh": 0.95, "hr_rhh": 0.95, "roof": "open"},
    "MIA": {"name": "loanDepot Park", "runs_lhh": 0.90, "runs_rhh": 0.90, "hr_lhh": 0.85, "hr_rhh": 0.85, "roof": "retractable"},
    "MIL": {"name": "American Family Field", "runs_lhh": 1.05, "runs_rhh": 1.05, "hr_lhh": 1.12, "hr_rhh": 1.08, "roof": "retractable"},
    "MIN": {"name": "Target Field", "runs_lhh": 1.00, "runs_rhh": 1.00, "hr_lhh": 1.00, "hr_rhh": 1.00, "roof": "open"},
    "NYM": {"name": "Citi Field", "runs_lhh": 0.95, "runs_rhh": 0.95, "hr_lhh": 0.95, "hr_rhh": 0.95, "roof": "open"},
    "NYY": {"name": "Yankee Stadium", "runs_lhh": 1.08, "runs_rhh": 1.02, "hr_lhh": 1.25, "hr_rhh": 1.05, "roof": "open"},
    "OAK": {"name": "Oakland Coliseum", "runs_lhh": 0.90, "runs_rhh": 0.90, "hr_lhh": 0.85, "hr_rhh": 0.85, "roof": "open"},
    "PHI": {"name": "Citizens Bank Park", "runs_lhh": 1.12, "runs_rhh": 1.08, "hr_lhh": 1.18, "hr_rhh": 1.12, "roof": "open"},
    "PIT": {"name": "PNC Park", "runs_lhh": 0.93, "runs_rhh": 0.97, "hr_lhh": 0.85, "hr_rhh": 0.95, "roof": "open"},
    "SD": {"name": "Petco Park", "runs_lhh": 0.90, "runs_rhh": 0.90, "hr_lhh": 0.90, "hr_rhh": 0.90, "roof": "open"},
    "SF": {"name": "Oracle Park", "runs_lhh": 0.82, "runs_rhh": 0.88, "hr_lhh": 0.75, "hr_rhh": 0.85, "roof": "open"},
    "SEA": {"name": "T-Mobile Park", "runs_lhh": 0.90, "runs_rhh": 0.90, "hr_lhh": 0.90, "hr_rhh": 0.90, "roof": "retractable"},
    "STL": {"name": "Busch Stadium", "runs_lhh": 0.95, "runs_rhh": 0.95, "hr_lhh": 0.95, "hr_rhh": 0.95, "roof": "open"},
    "TB": {"name": "Tropicana Field", "runs_lhh": 0.95, "runs_rhh": 0.95, "hr_lhh": 0.95, "hr_rhh": 0.95, "roof": "dome"},
    "TEX": {"name": "Globe Life Field", "runs_lhh": 1.00, "runs_rhh": 1.00, "hr_lhh": 1.05, "hr_rhh": 1.05, "roof": "retractable"},
    "TOR": {"name": "Rogers Centre", "runs_lhh": 1.07, "runs_rhh": 1.03, "hr_lhh": 1.12, "hr_rhh": 1.08, "roof": "retractable"},
    "WSH": {"name": "Nationals Park", "runs_lhh": 1.00, "runs_rhh": 1.00, "hr_lhh": 1.07, "hr_rhh": 1.03, "roof": "open"},
}
    # END AUTO-GENERATED PARK FACTORS
```

These seed values are hand-estimated from public Savant data; refresh via `scripts/update_park_factors.py` before production cutover. Do NOT delete the sentinel comments — Task 1's script depends on them.

- [ ] **Step 4: Commit (accessor tests still failing — expected)**

```bash
git add config.py
git commit -m "refactor: rewrite PARK_FACTORS to handedness-split schema"
```

---

### Task 3: Add accessor helpers in `config.py`

**Files:** Modify `config.py` (add functions after the `PARK_FACTORS` block, before `PARK_COORDS`).

- [ ] **Step 1: Confirm accessor tests fail**

Run: `pytest tests/test_park_factors.py::test_nyy_lhh_runs_beats_rhh -v`
Expected: `ImportError`.

- [ ] **Step 2: Add accessors**

Insert after `PARK_FACTORS = { ... # END AUTO-GENERATED ... }`:

```python
def park_factor_runs_for(team: str, batter_hand: str | None) -> float:
    """Runs park factor for given team + batter hand. Falls back to legacy 'runs' scalar,
    then to 1.0."""
    pf = PARK_FACTORS.get(team, {})
    if not pf: return 1.0
    if batter_hand == "L": return pf.get("runs_lhh", pf.get("runs", 1.0))
    if batter_hand == "R": return pf.get("runs_rhh", pf.get("runs", 1.0))
    lhh, rhh = pf.get("runs_lhh"), pf.get("runs_rhh")
    if lhh is not None and rhh is not None: return (lhh + rhh) / 2
    return pf.get("runs", 1.0)


def park_factor_hr_for(team: str, batter_hand: str | None) -> float:
    """HR park factor, symmetric to park_factor_runs_for."""
    pf = PARK_FACTORS.get(team, {})
    if not pf: return 1.0
    if batter_hand == "L": return pf.get("hr_lhh", pf.get("hr", 1.0))
    if batter_hand == "R": return pf.get("hr_rhh", pf.get("hr", 1.0))
    lhh, rhh = pf.get("hr_lhh"), pf.get("hr_rhh")
    if lhh is not None and rhh is not None: return (lhh + rhh) / 2
    return pf.get("hr", 1.0)


def park_factors_dict_for(team: str) -> dict:
    """Full handedness-split park factor dict for sample_pa. Neutral-1.0 defaults
    for missing keys."""
    pf = PARK_FACTORS.get(team, {})
    return {
        "runs_lhh": pf.get("runs_lhh", pf.get("runs", 1.0)),
        "runs_rhh": pf.get("runs_rhh", pf.get("runs", 1.0)),
        "hr_lhh":   pf.get("hr_lhh",   pf.get("hr",   1.0)),
        "hr_rhh":   pf.get("hr_rhh",   pf.get("hr",   1.0)),
        "roof":     pf.get("roof", "open"),
    }
```

- [ ] **Step 3: Run tests + commit**

```bash
pytest tests/test_park_factors.py -v   # expect PASS
git add config.py tests/test_park_factors.py
git commit -m "feat: add park_factor_{runs,hr}_for + park_factors_dict_for accessors"
```

---

## Phase B — Platoon splits scraping

### Task 4: Add `get_batter_splits` / `get_pitcher_splits`

**Files:** Modify `scrapers/player_stats.py`, create `tests/test_player_splits.py`.

- [ ] **Step 1: Write failing tests with mocked pybaseball**

Create `tests/test_player_splits.py`:

```python
import json, os
from datetime import datetime, timedelta
from unittest.mock import patch
import pandas as pd
import pytest


def _batter_frame(n_lhp=80, n_rhp=200):
    rows = [{"p_throws": "L", "events": "strikeout"}] * n_lhp
    rows += [{"p_throws": "R", "events": "single"}] * n_rhp
    return pd.DataFrame(rows)


def _pitcher_frame(n_lhb=120, n_rhb=180):
    rows = [{"stand": "L", "events": "walk"}] * n_lhb
    rows += [{"stand": "R", "events": "strikeout"}] * n_rhb
    return pd.DataFrame(rows)


def test_batter_splits_shape(tmp_path, monkeypatch):
    from scrapers import player_stats
    monkeypatch.setattr(player_stats, "SPLITS_CACHE_FILE", str(tmp_path / "splits.json"))
    with patch.object(player_stats, "_fetch_statcast_batter", return_value=_batter_frame()):
        res = player_stats.get_batter_splits(660271, season=2026, bats="L")
    assert set(res) >= {"vs_lhp", "vs_rhp", "overall", "pa_vs_lhp", "pa_vs_rhp", "pa_overall"}
    assert res["pa_vs_lhp"] == 80 and res["pa_vs_rhp"] == 200
    assert res["vs_lhp"]["k_pct"] > 0.5  # mock is all Ks vs LHP


def test_small_sample_regresses(tmp_path, monkeypatch):
    from scrapers import player_stats
    monkeypatch.setattr(player_stats, "SPLITS_CACHE_FILE", str(tmp_path / "splits.json"))
    with patch.object(player_stats, "_fetch_statcast_batter",
                       return_value=_batter_frame(n_lhp=30, n_rhp=300)):
        res = player_stats.get_batter_splits(660271, season=2026, bats="L")
    # alpha = 30/(30+50) = 0.375 — heavy shrinkage. Observed K=1.0 -> regressed < 0.7
    assert res["vs_lhp"]["k_pct"] < 0.7


def test_cache_hit_skips_fetch(tmp_path, monkeypatch):
    from scrapers import player_stats
    monkeypatch.setattr(player_stats, "SPLITS_CACHE_FILE", str(tmp_path / "splits.json"))
    with patch.object(player_stats, "_fetch_statcast_batter", return_value=_batter_frame()) as m:
        player_stats.get_batter_splits(660271, season=2026, bats="L")
        assert m.call_count == 1
    with patch.object(player_stats, "_fetch_statcast_batter") as m:
        player_stats.get_batter_splits(660271, season=2026, bats="L")
        assert m.call_count == 0


def test_ttl_expires(tmp_path, monkeypatch):
    from scrapers import player_stats
    cache = str(tmp_path / "splits.json")
    monkeypatch.setattr(player_stats, "SPLITS_CACHE_FILE", cache)
    stale = (datetime.utcnow() - timedelta(days=2)).isoformat()
    with open(cache, "w") as f:
        json.dump({"2026": {"660271": {"fetched_at": stale, "vs_lhp": {}, "vs_rhp": {},
                    "overall": {}, "pa_vs_lhp": 0, "pa_vs_rhp": 0, "pa_overall": 0}}}, f)
    with patch.object(player_stats, "_fetch_statcast_batter", return_value=_batter_frame()) as m:
        player_stats.get_batter_splits(660271, season=2026, bats="L")
        assert m.call_count == 1


def test_pitcher_splits_shape(tmp_path, monkeypatch):
    from scrapers import player_stats
    monkeypatch.setattr(player_stats, "SPLITS_CACHE_FILE", str(tmp_path / "splits.json"))
    with patch.object(player_stats, "_fetch_statcast_pitcher", return_value=_pitcher_frame()):
        res = player_stats.get_pitcher_splits(592789, season=2026, throws="R")
    assert set(res) >= {"vs_lhb", "vs_rhb", "overall", "pa_vs_lhb", "pa_vs_rhb", "pa_overall"}
    assert res["pa_vs_lhb"] == 120 and res["pa_vs_rhb"] == 180


def test_fetch_failure_synthesizes_from_overall(tmp_path, monkeypatch):
    from scrapers import player_stats
    monkeypatch.setattr(player_stats, "SPLITS_CACHE_FILE", str(tmp_path / "splits.json"))
    overall = {"k_pct": 0.22, "bb_pct": 0.09, "hr_pct": 0.035,
               "single_pct": 0.15, "double_pct": 0.045, "triple_pct": 0.003,
               "out_pct": 0.457}
    with patch.object(player_stats, "_fetch_statcast_batter",
                       side_effect=RuntimeError("savant down")), \
         patch.object(player_stats, "get_batter_stats", return_value=overall):
        res = player_stats.get_batter_splits(660271, season=2026, bats="L")
    assert res["vs_lhp"]["k_pct"] != overall["k_pct"]  # synthesized via LEAGUE_PLATOON_COEF
```

- [ ] **Step 2: Verify fail**

Run: `pytest tests/test_player_splits.py -v` → expect `AttributeError: get_batter_splits`.

- [ ] **Step 3: Append splits implementation to `scrapers/player_stats.py`**

Add at module level (after `_save_player_map`):

```python
from datetime import datetime, timedelta
import logging

_splits_logger = logging.getLogger("mirofish.scrapers.splits")
SPLITS_CACHE_FILE = os.path.join(DATA_DIR, "player_splits_cache.json")
SPLITS_TTL_HOURS = 24
BATTER_SPLIT_REGRESS_PA = 50
PITCHER_SPLIT_REGRESS_BF = 50
_splits_cache_lock = threading.Lock()

# Event -> rate-key mapping for aggregation
_EVENT_TO_KEY = {"strikeout": "k_pct", "walk": "bb_pct", "home_run": "hr_pct",
                 "single": "single_pct", "double": "double_pct", "triple": "triple_pct"}

# League batter-side platoon coefficients (rate multipliers).
LEAGUE_PLATOON_COEF_BATTER_VS_LHP = {
    "R": {"k_pct": 0.96, "bb_pct": 1.04, "hr_pct": 1.05, "single_pct": 1.02,
          "double_pct": 1.02, "triple_pct": 1.00, "out_pct": 0.99},
    "L": {"k_pct": 1.10, "bb_pct": 0.94, "hr_pct": 0.88, "single_pct": 0.97,
          "double_pct": 0.95, "triple_pct": 1.00, "out_pct": 1.03},
}
LEAGUE_PLATOON_COEF_BATTER_VS_RHP = {
    "R": {"k_pct": 1.02, "bb_pct": 0.98, "hr_pct": 0.97, "single_pct": 0.99,
          "double_pct": 0.98, "triple_pct": 1.00, "out_pct": 1.01},
    "L": {"k_pct": 0.96, "bb_pct": 1.04, "hr_pct": 1.05, "single_pct": 1.02,
          "double_pct": 1.03, "triple_pct": 1.00, "out_pct": 0.99},
}
LEAGUE_PLATOON_COEF_PITCHER_VS_LHB = {
    "L": {"k_pct": 1.08, "bb_pct": 0.94, "hr_pct": 0.90, "single_pct": 0.98,
          "double_pct": 0.97, "triple_pct": 1.00, "out_pct": 1.02},
    "R": {"k_pct": 0.96, "bb_pct": 1.06, "hr_pct": 1.05, "single_pct": 1.02,
          "double_pct": 1.03, "triple_pct": 1.00, "out_pct": 0.98},
}
LEAGUE_PLATOON_COEF_PITCHER_VS_RHB = {
    "R": {"k_pct": 1.06, "bb_pct": 0.95, "hr_pct": 0.94, "single_pct": 0.99,
          "double_pct": 0.98, "triple_pct": 1.00, "out_pct": 1.02},
    "L": {"k_pct": 0.94, "bb_pct": 1.06, "hr_pct": 1.07, "single_pct": 1.01,
          "double_pct": 1.03, "triple_pct": 1.00, "out_pct": 0.98},
}


def _load_splits_cache():
    if not os.path.exists(SPLITS_CACHE_FILE): return {}
    try:
        with open(SPLITS_CACHE_FILE) as f: return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _save_splits_cache(cache):
    os.makedirs(os.path.dirname(SPLITS_CACHE_FILE), exist_ok=True)
    with open(SPLITS_CACHE_FILE, "w") as f: json.dump(cache, f, indent=2)


def _is_fresh(fetched_at):
    try:
        ts = datetime.fromisoformat(fetched_at.replace("Z", ""))
    except Exception:
        return False
    return datetime.utcnow() - ts < timedelta(hours=SPLITS_TTL_HOURS)


def _aggregate_pa_frame(frame, filter_col, filter_val):
    sub = frame[frame[filter_col] == filter_val] if filter_val else frame
    pa = int(len(sub))
    if pa == 0: return {"pa": 0}
    counts = {k: 0 for k in _EVENT_TO_KEY.values()}
    counts["out_pct"] = 0
    for e in sub.get("events", []):
        k = _EVENT_TO_KEY.get(e)
        if k: counts[k] += 1
        elif e: counts["out_pct"] += 1
    rates = {k: v / pa for k, v in counts.items()}
    rates["pa"] = pa
    return rates


def _regress_split(observed, overall, adjusted_league, regress_n):
    """Bayesian shrinkage: alpha = n/(n+regress_n). n<regress_n -> heavy regress."""
    pa = observed.get("pa", 0)
    if pa == 0: return adjusted_league
    alpha = pa / (pa + regress_n)
    out = {k: alpha * observed.get(k, adjusted_league.get(k, 0.0))
              + (1 - alpha) * adjusted_league.get(k, 0.0)
           for k in ("k_pct", "bb_pct", "hr_pct", "single_pct",
                      "double_pct", "triple_pct", "out_pct")}
    out["pa"] = pa
    return out


def _fetch_statcast_batter(player_id, season):
    from pybaseball import statcast_batter
    return statcast_batter(f"{season}-03-20", f"{season}-11-01", player_id)


def _fetch_statcast_pitcher(player_id, season):
    from pybaseball import statcast_pitcher
    return statcast_pitcher(f"{season}-03-20", f"{season}-11-01", player_id)


def _synthesize_batter_splits(overall, bats):
    bats = bats or "R"
    cL = LEAGUE_PLATOON_COEF_BATTER_VS_LHP.get(bats, {})
    cR = LEAGUE_PLATOON_COEF_BATTER_VS_RHP.get(bats, {})
    vs_lhp = {k: overall.get(k, 0.0) * cL.get(k, 1.0) for k in overall if k != "pa"}
    vs_rhp = {k: overall.get(k, 0.0) * cR.get(k, 1.0) for k in overall if k != "pa"}
    vs_lhp["pa"] = 0; vs_rhp["pa"] = 0
    return {"vs_lhp": vs_lhp, "vs_rhp": vs_rhp, "overall": overall,
            "pa_vs_lhp": 0, "pa_vs_rhp": 0, "pa_overall": overall.get("pa", 0)}


def _synthesize_pitcher_splits(overall, throws):
    throws = throws or "R"
    cL = LEAGUE_PLATOON_COEF_PITCHER_VS_LHB.get(throws, {})
    cR = LEAGUE_PLATOON_COEF_PITCHER_VS_RHB.get(throws, {})
    vs_lhb = {k: overall.get(k, 0.0) * cL.get(k, 1.0) for k in overall if k != "pa"}
    vs_rhb = {k: overall.get(k, 0.0) * cR.get(k, 1.0) for k in overall if k != "pa"}
    vs_lhb["pa"] = 0; vs_rhb["pa"] = 0
    return {"vs_lhb": vs_lhb, "vs_rhb": vs_rhb, "overall": overall,
            "pa_vs_lhb": 0, "pa_vs_rhb": 0, "pa_overall": overall.get("pa", 0)}


def get_batter_splits(player_id: int, season: int = None, bats: str | None = None) -> dict:
    """Return {'vs_lhp', 'vs_rhp', 'overall', 'pa_vs_lhp', 'pa_vs_rhp', 'pa_overall',
    'fetched_at'}. Cached with 1-day TTL."""
    if season is None: season = date.today().year
    sk, pk = str(season), str(player_id)
    with _splits_cache_lock:
        cache = _load_splits_cache()
        entry = cache.get(sk, {}).get(pk)
        if entry and _is_fresh(entry.get("fetched_at", "")):
            return entry
    try:
        frame = _fetch_statcast_batter(player_id, season)
        vL = _aggregate_pa_frame(frame, "p_throws", "L")
        vR = _aggregate_pa_frame(frame, "p_throws", "R")
        vO = _aggregate_pa_frame(frame, "p_throws", "")
    except Exception as e:
        _splits_logger.warning("statcast_batter failed for %s: %s", player_id, e)
        overall = get_batter_stats(player_id, season)
        result = _synthesize_batter_splits(overall, bats)
        result["fetched_at"] = datetime.utcnow().isoformat()
        with _splits_cache_lock:
            cache = _load_splits_cache()
            cache.setdefault(sk, {})[pk] = result
            _save_splits_cache(cache)
        return result
    cL = LEAGUE_PLATOON_COEF_BATTER_VS_LHP.get(bats or "R", {})
    cR = LEAGUE_PLATOON_COEF_BATTER_VS_RHP.get(bats or "R", {})
    adjL = {k: vO.get(k, LEAGUE_AVERAGES.get(k, 0.0)) * cL.get(k, 1.0) for k in LEAGUE_AVERAGES}
    adjR = {k: vO.get(k, LEAGUE_AVERAGES.get(k, 0.0)) * cR.get(k, 1.0) for k in LEAGUE_AVERAGES}
    result = {
        "fetched_at": datetime.utcnow().isoformat(),
        "vs_lhp": _regress_split(vL, vO, adjL, BATTER_SPLIT_REGRESS_PA),
        "vs_rhp": _regress_split(vR, vO, adjR, BATTER_SPLIT_REGRESS_PA),
        "overall": vO,
        "pa_vs_lhp": vL.get("pa", 0), "pa_vs_rhp": vR.get("pa", 0),
        "pa_overall": vO.get("pa", 0),
    }
    with _splits_cache_lock:
        cache = _load_splits_cache()
        cache.setdefault(sk, {})[pk] = result
        _save_splits_cache(cache)
    return result


def get_pitcher_splits(player_id: int, season: int = None, throws: str | None = None) -> dict:
    """Mirror of get_batter_splits, keyed by batter stand."""
    if season is None: season = date.today().year
    sk, pk = str(season), f"p_{player_id}"  # namespaced so batter IDs don't collide
    with _splits_cache_lock:
        cache = _load_splits_cache()
        entry = cache.get(sk, {}).get(pk)
        if entry and _is_fresh(entry.get("fetched_at", "")):
            return entry
    try:
        frame = _fetch_statcast_pitcher(player_id, season)
        vL = _aggregate_pa_frame(frame, "stand", "L")
        vR = _aggregate_pa_frame(frame, "stand", "R")
        vO = _aggregate_pa_frame(frame, "stand", "")
    except Exception as e:
        _splits_logger.warning("statcast_pitcher failed for %s: %s", player_id, e)
        overall = get_pitcher_stats(player_id, season)
        result = _synthesize_pitcher_splits(overall, throws)
        result["fetched_at"] = datetime.utcnow().isoformat()
        with _splits_cache_lock:
            cache = _load_splits_cache()
            cache.setdefault(sk, {})[pk] = result
            _save_splits_cache(cache)
        return result
    cL = LEAGUE_PLATOON_COEF_PITCHER_VS_LHB.get(throws or "R", {})
    cR = LEAGUE_PLATOON_COEF_PITCHER_VS_RHB.get(throws or "R", {})
    adjL = {k: vO.get(k, LEAGUE_AVERAGES.get(k, 0.0)) * cL.get(k, 1.0) for k in LEAGUE_AVERAGES}
    adjR = {k: vO.get(k, LEAGUE_AVERAGES.get(k, 0.0)) * cR.get(k, 1.0) for k in LEAGUE_AVERAGES}
    result = {
        "fetched_at": datetime.utcnow().isoformat(),
        "vs_lhb": _regress_split(vL, vO, adjL, PITCHER_SPLIT_REGRESS_BF),
        "vs_rhb": _regress_split(vR, vO, adjR, PITCHER_SPLIT_REGRESS_BF),
        "overall": vO,
        "pa_vs_lhb": vL.get("pa", 0), "pa_vs_rhb": vR.get("pa", 0),
        "pa_overall": vO.get("pa", 0),
    }
    with _splits_cache_lock:
        cache = _load_splits_cache()
        cache.setdefault(sk, {})[pk] = result
        _save_splits_cache(cache)
    return result
```

- [ ] **Step 4: Run tests + commit**

```bash
pytest tests/test_player_splits.py -v   # expect PASS
git add scrapers/player_stats.py tests/test_player_splits.py
git commit -m "feat: add handedness splits scraper with 1-day cache + Bayesian regression"
```

---

### Task 5: gitignore the splits cache

- [ ] **Step 1: Append if missing**

```bash
grep -q "player_splits_cache" .gitignore 2>/dev/null || echo "data/player_splits_cache.json" >> .gitignore
git add .gitignore
git commit -m "chore: gitignore player splits cache"
```

---

## Phase C — Handedness-aware `sample_pa`

### Task 6: Add `_rates_for_side` helper

**Files:** Modify `simulation/pa_engine.py`, modify/create `tests/test_pa_engine.py`.

- [ ] **Step 1: Write failing test**

Append to `tests/test_pa_engine.py` (or create):

```python
from simulation.pa_engine import _rates_for_side

def _batter_with_splits():
    return {"k_pct": 0.20, "bb_pct": 0.10, "hr_pct": 0.04, "single_pct": 0.15,
            "double_pct": 0.05, "triple_pct": 0.005, "out_pct": 0.455,
            "splits": {"vs_lhp": {"k_pct": 0.30}, "vs_rhp": {"k_pct": 0.18}}}

def test_batter_vs_lhp(): assert _rates_for_side(_batter_with_splits(), "L", "batter")["k_pct"] == 0.30
def test_batter_vs_rhp(): assert _rates_for_side(_batter_with_splits(), "R", "batter")["k_pct"] == 0.18
def test_fallback_no_splits(): assert _rates_for_side({"k_pct": 0.25}, "L", "batter")["k_pct"] == 0.25
def test_fallback_unknown_hand(): assert _rates_for_side(_batter_with_splits(), None, "batter")["k_pct"] == 0.20
```

- [ ] **Step 2: Fail → implement → pass**

Run: `pytest tests/test_pa_engine.py -v` → expect ImportError.

Insert into `simulation/pa_engine.py` before `_build_matchup_probs`:

```python
def _rates_for_side(profile: dict, opp_hand: str | None, role: str) -> dict:
    """Resolve the rate dict for a batter/pitcher profile.

    role = 'batter' -> looks at profile["splits"]["vs_lhp"|"vs_rhp"].
    role = 'pitcher' -> profile["splits"]["vs_lhb"|"vs_rhb"].
    opp_hand is the opponent's throwing (batter role) or batting (pitcher role) hand.
    None hand or missing splits -> returns profile unchanged (backward compat).
    """
    if opp_hand is None or "splits" not in profile:
        return profile
    if role == "batter":
        key = "vs_lhp" if opp_hand == "L" else "vs_rhp"
    else:
        key = "vs_lhb" if opp_hand == "L" else "vs_rhb"
    split = profile["splits"].get(key)
    if split is None: return profile
    return {**profile, **split}
```

Run tests + commit:

```bash
pytest tests/test_pa_engine.py -v
git add simulation/pa_engine.py tests/test_pa_engine.py
git commit -m "feat: add _rates_for_side helper for handedness resolution"
```

---

### Task 7: Refactor `sample_pa` with full new signature

**Files:** Modify `simulation/pa_engine.py:46-89`, `config.py`, create `tests/test_pa_engine_platoon.py`.

- [ ] **Step 1: Add `SIM_RISP_MULTIPLIERS` and `SIM_V2_ENABLED` to `config.py`**

Insert after `PARALLEL_GAMES = 4` (~line 30):

```python
# Sim v2: RISP outcome multipliers (runners on 2B/3B, <2 outs). Applied before normalize.
# Empirical targets: K% -7%, BB% +8%, 1B +5%. HR/2B/3B unchanged.
SIM_RISP_MULTIPLIERS = {"k_pct": 0.93, "bb_pct": 1.08, "single_pct": 1.05}

# Sim v2: gates handedness-aware path. Spec 1's calibration loop A/Bs v1 vs v2.
SIM_V2_ENABLED = os.getenv("SIM_V2_ENABLED", "false").lower() == "true"
```

- [ ] **Step 2: Write failing platoon test**

Create `tests/test_pa_engine_platoon.py`:

```python
import random, pytest
from simulation.pa_engine import sample_pa, _build_matchup_probs


def _avg_pitcher():
    return {"k_pct": 0.22, "bb_pct": 0.09, "hr_pct": 0.033, "single_pct": 0.15,
            "double_pct": 0.045, "triple_pct": 0.004, "out_pct": 0.458}


def _extreme_platoon_batter():
    return {"k_pct": 0.22, "bb_pct": 0.09, "hr_pct": 0.033, "single_pct": 0.15,
            "double_pct": 0.045, "triple_pct": 0.004, "out_pct": 0.458,
            "splits": {
                "vs_lhp": {"k_pct": 0.40, "bb_pct": 0.05, "hr_pct": 0.015,
                            "single_pct": 0.13, "double_pct": 0.04,
                            "triple_pct": 0.002, "out_pct": 0.363},
                "vs_rhp": {"k_pct": 0.10, "bb_pct": 0.11, "hr_pct": 0.06,
                            "single_pct": 0.17, "double_pct": 0.06,
                            "triple_pct": 0.004, "out_pct": 0.486}}}


@pytest.mark.parametrize("bh,ph", [("L","L"),("L","R"),("R","L"),("R","R")])
@pytest.mark.parametrize("risp", [True, False])
@pytest.mark.parametrize("tto", [0, 9, 18, 27, 36])
def test_probs_sum_to_one(bh, ph, risp, tto):
    pf = {"runs_lhh": 1.10, "runs_rhh": 0.95, "hr_lhh": 1.20, "hr_rhh": 0.85}
    probs = _build_matchup_probs(_extreme_platoon_batter(), _avg_pitcher(),
        park_factors=pf, pitcher_hand=ph, batter_hand=bh,
        runners_on_scoring_position=risp, pitcher_pa_count=tto)
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_platoon_changes_k():
    pf = {"runs_lhh": 1, "runs_rhh": 1, "hr_lhh": 1, "hr_rhh": 1}
    vL = _build_matchup_probs(_extreme_platoon_batter(), _avg_pitcher(),
        park_factors=pf, pitcher_hand="L", batter_hand="L")
    vR = _build_matchup_probs(_extreme_platoon_batter(), _avg_pitcher(),
        park_factors=pf, pitcher_hand="R", batter_hand="L")
    assert vL["K"] > vR["K"] + 0.10


def test_backward_compat_scalar():
    """Legacy callers with park_factor_runs/park_factor_hr still work."""
    b = {"k_pct": 0.2, "bb_pct": 0.09, "hr_pct": 0.033, "single_pct": 0.15,
         "double_pct": 0.045, "triple_pct": 0.004, "out_pct": 0.459}
    assert sample_pa(b, _avg_pitcher(), park_factor_runs=1.1, park_factor_hr=1.2) \
        in ("K","BB","1B","2B","3B","HR","OUT")


def test_deterministic_rng():
    pf = {"runs_lhh": 1, "runs_rhh": 1, "hr_lhh": 1, "hr_rhh": 1}
    r1, r2 = random.Random(42), random.Random(42)
    s1 = [sample_pa(_extreme_platoon_batter(), _avg_pitcher(), park_factors=pf,
                     pitcher_hand="L", batter_hand="L", rng=r1) for _ in range(30)]
    s2 = [sample_pa(_extreme_platoon_batter(), _avg_pitcher(), park_factors=pf,
                     pitcher_hand="L", batter_hand="L", rng=r2) for _ in range(30)]
    assert s1 == s2


def test_tto_monotone():
    pf = {"runs_lhh": 1, "runs_rhh": 1, "hr_lhh": 1, "hr_rhh": 1}
    ks = [_build_matchup_probs(_extreme_platoon_batter(), _avg_pitcher(),
            park_factors=pf, pitcher_hand="R", batter_hand="L",
            pitcher_pa_count=n)["K"] for n in (0, 9, 18, 27, 36)]
    assert ks[0] == ks[1] == ks[2]
    assert ks[2] > ks[3] > ks[4]


def test_tto_k_floor():
    """K% must not collapse below ~70% of baseline even at extreme PA counts."""
    b, p = _extreme_platoon_batter(), _avg_pitcher()
    p0  = _build_matchup_probs(b, p, pitcher_pa_count=0)
    p500 = _build_matchup_probs(b, p, pitcher_pa_count=500)
    assert p500["K"] >= p0["K"] * 0.7


def test_risp_shift():
    b, p = _extreme_platoon_batter(), _avg_pitcher()
    base = _build_matchup_probs(b, p, pitcher_hand="R", batter_hand="L",
                                  runners_on_scoring_position=False)
    risp = _build_matchup_probs(b, p, pitcher_hand="R", batter_hand="L",
                                  runners_on_scoring_position=True)
    assert risp["K"] < base["K"]
    assert risp["BB"] > base["BB"]


def test_framing_noop_at_zero():
    pf = {"runs_lhh": 1, "runs_rhh": 1, "hr_lhh": 1, "hr_rhh": 1}
    r1, r2 = random.Random(7), random.Random(7)
    s1 = [sample_pa(_extreme_platoon_batter(), _avg_pitcher(), park_factors=pf,
          pitcher_hand="R", batter_hand="L", catcher_framing_z=0.0, rng=r1) for _ in range(50)]
    s2 = [sample_pa(_extreme_platoon_batter(), _avg_pitcher(), park_factors=pf,
          pitcher_hand="R", batter_hand="L", rng=r2) for _ in range(50)]
    assert s1 == s2


def test_framing_positive_z_bumps_k():
    """Large positive framer should measurably increase K% across many samples."""
    pf = {"runs_lhh": 1, "runs_rhh": 1, "hr_lhh": 1, "hr_rhh": 1}
    def _k(z):
        rng = random.Random(123)
        out = [sample_pa(_extreme_platoon_batter(), _avg_pitcher(), park_factors=pf,
               pitcher_hand="R", batter_hand="L", catcher_framing_z=z, rng=rng)
               for _ in range(5000)]
        return out.count("K") / len(out)
    assert _k(2.0) > _k(0.0)


def test_risp_multipliers_loaded():
    from config import SIM_RISP_MULTIPLIERS
    assert SIM_RISP_MULTIPLIERS["k_pct"] < 1.0
    assert SIM_RISP_MULTIPLIERS["bb_pct"] > 1.0
```

- [ ] **Step 3: Replace `_build_matchup_probs` and `sample_pa` in `simulation/pa_engine.py`**

Replace lines 46-89 with:

```python
# Config for RISP (loaded at module-top; callers re-import to refresh)
try:
    from config import SIM_RISP_MULTIPLIERS
except ImportError:
    SIM_RISP_MULTIPLIERS = {}

_RATE_TO_OUTCOME = {"k_pct": "K", "bb_pct": "BB", "hr_pct": "HR",
                    "single_pct": "1B", "double_pct": "2B", "triple_pct": "3B"}


def _apply_tto_fatigue(p_rates: dict, pitcher_pa_count: int) -> dict:
    """Continuous TTO penalty. K% drops up to 20% (floored); wOBA-positive rates
    lift ~7% at PA 27. Brill et al. 2022 (arXiv:2210.06724)."""
    excess = max(0, pitcher_pa_count - 18)
    k_mult = max(0.80, 1.0 - 0.002 * excess)
    woba_mult = 1.0 + 0.0008 * excess
    out = dict(p_rates)
    out["k_pct"] = out.get("k_pct", 0.0) * k_mult
    for k in ("bb_pct", "hr_pct", "single_pct", "double_pct", "triple_pct"):
        out[k] = out.get(k, 0.0) * woba_mult
    return out


def _apply_risp_multipliers(raw: dict) -> dict:
    """Scale K/BB/1B by config.SIM_RISP_MULTIPLIERS; normalization handles out_pct."""
    out = dict(raw)
    for rk, mult in SIM_RISP_MULTIPLIERS.items():
        o = _RATE_TO_OUTCOME.get(rk)
        if o and o in out: out[o] *= mult
    return out


def _apply_framing(outcome: str, framing_z: float, rng) -> str:
    """Forward-compat framing hook (Spec 4 wires real z-scores). No-op at z=0."""
    if framing_z == 0 or outcome not in ("K", "BB"):
        return outcome
    eps = 0.015 * framing_z
    if outcome == "BB" and eps > 0 and rng.random() < eps: return "K"
    if outcome == "K" and eps < 0 and rng.random() < -eps: return "BB"
    return outcome


def _build_matchup_probs(
    batter: dict, pitcher: dict,
    park_factors: dict | None = None,
    pitcher_hand: str | None = None, batter_hand: str | None = None,
    runners_on_scoring_position: bool = False,
    pitcher_pa_count: int = 0,
    # Legacy positional compat
    park_factor_runs: float | None = None,
    park_factor_hr: float | None = None,
) -> dict:
    # Shim legacy scalars into dict
    if park_factors is None:
        park_factors = {
            "runs_lhh": park_factor_runs or 1.0, "runs_rhh": park_factor_runs or 1.0,
            "hr_lhh":   park_factor_hr   or 1.0, "hr_rhh":   park_factor_hr   or 1.0,
        }

    b_rates = _rates_for_side(batter, pitcher_hand, "batter")
    p_rates = _rates_for_side(pitcher, batter_hand, "pitcher")
    if pitcher_pa_count > 0:
        p_rates = _apply_tto_fatigue(p_rates, pitcher_pa_count)

    raw = {}
    for outcome, key in [("K","k_pct"),("BB","bb_pct"),("HR","hr_pct"),
                          ("1B","single_pct"),("2B","double_pct"),
                          ("3B","triple_pct"),("OUT","out_pct")]:
        raw[outcome] = matchup_probability(
            b_rates.get(key, LEAGUE_AVERAGES[key]),
            p_rates.get(key, LEAGUE_AVERAGES[key]),
            LEAGUE_AVERAGES[key])

    # Handedness-selective park factors — None hand defaults to RHH
    side = "lhh" if batter_hand == "L" else "rhh"
    pf_runs = park_factors.get(f"runs_{side}", 1.0)
    pf_hr = park_factors.get(f"hr_{side}", 1.0)
    if pf_hr != 1.0: raw["HR"] *= pf_hr
    if pf_runs != 1.0:
        for h in ("1B", "2B", "3B"): raw[h] *= pf_runs

    if runners_on_scoring_position:
        raw = _apply_risp_multipliers(raw)

    return normalize_probs(raw)


def sample_pa(
    batter: dict, pitcher: dict,
    park_factors: dict | None = None,
    pitcher_hand: str | None = None, batter_hand: str | None = None,
    runners_on_scoring_position: bool = False,
    pitcher_pa_count: int = 0,
    catcher_framing_z: float = 0.0,
    rng: random.Random | None = None,
    park_factor_runs: float | None = None,
    park_factor_hr: float | None = None,
) -> str:
    """Sample one PA outcome. See Spec §3.2 for full signature documentation."""
    probs = _build_matchup_probs(
        batter, pitcher, park_factors=park_factors,
        pitcher_hand=pitcher_hand, batter_hand=batter_hand,
        runners_on_scoring_position=runners_on_scoring_position,
        pitcher_pa_count=pitcher_pa_count,
        park_factor_runs=park_factor_runs, park_factor_hr=park_factor_hr,
    )
    _rng = rng if rng is not None else random
    r = _rng.random()
    cumulative = 0.0
    outcome = OUTCOMES[-1]
    for c in OUTCOMES:
        cumulative += probs[c]
        if r < cumulative:
            outcome = c; break
    return _apply_framing(outcome, catcher_framing_z, _rng)
```

- [ ] **Step 4: Run tests + commit**

```bash
pytest tests/test_pa_engine_platoon.py tests/test_pa_engine.py -v   # expect PASS
git add simulation/pa_engine.py config.py tests/test_pa_engine_platoon.py
git commit -m "feat: handedness-aware sample_pa with TTO, RISP, framing + SIM_V2_ENABLED flag"
```

---

## Phase D — Continuous TTO fatigue wiring in `game_sim.py`

### Task 8: Add `pitcher_pa_count` / `batter_seen_count` counters to `GameState`

**Files:** Modify `simulation/game_sim.py:45-54` + `:281` area; modify `tests/test_game_sim.py`.

- [ ] **Step 1: Write failing test**

Append to `tests/test_game_sim.py`:

```python
def test_game_state_tracks_pa_count():
    """After simulate_game, pitcher_pa_count sums should equal PAs faced."""
    from simulation.game_sim import simulate_game
    import random as rnd
    rnd.seed(42)
    result = simulate_game(
        home_lineup=_FIXTURE_HOME_LINEUP, away_lineup=_FIXTURE_AWAY_LINEUP,
        home_pitcher=_FIXTURE_HOME_PITCHER, away_pitcher=_FIXTURE_AWAY_PITCHER,
        park_factor_runs=1.0, park_factor_hr=1.0)
    assert "pitcher_pa_count" in result
    for pid, count in result["pitcher_pa_count"].items():
        assert count > 0
```

(Reuse existing `_FIXTURE_*` from file or create minimal lineup fixtures if missing.)

- [ ] **Step 2: Extend `GameState` (around line 45-54)**

```python
@dataclass
class GameState:
    inning: int = 1
    half: str = "top"
    outs: int = 0
    bases: list = field(default_factory=lambda: [0, 0, 0])
    score: dict = field(default_factory=lambda: {"away": 0, "home": 0})
    score_by_inning: dict = field(default_factory=lambda: {"away": [], "home": []})
    pitcher_stats: dict = field(default_factory=dict)
    batter_stats: dict = field(default_factory=dict)
    # Sim v2 additions
    pitcher_pa_count: dict = field(default_factory=dict)
    batter_seen_count: dict = field(default_factory=dict)
```

- [ ] **Step 3: Increment counters before the `sample_pa` call (~line 281)**

Insert before `outcome = sample_pa(...)`:

```python
                state.pitcher_pa_count[pitcher_id] = state.pitcher_pa_count.get(pitcher_id, 0) + 1
                state.batter_seen_count.setdefault(pitcher_id, {})
                state.batter_seen_count[pitcher_id][batter_id] = \
                    state.batter_seen_count[pitcher_id].get(batter_id, 0) + 1
```

- [ ] **Step 4: Include counters in `simulate_game` return**

Where the final result dict is built, add:

```python
    result["pitcher_pa_count"] = dict(state.pitcher_pa_count)
    result["batter_seen_count"] = dict(state.batter_seen_count)
```

- [ ] **Step 5: Run tests + commit**

```bash
pytest tests/test_game_sim.py -v   # expect PASS (new + existing)
git add simulation/game_sim.py tests/test_game_sim.py
git commit -m "feat: track pitcher_pa_count + batter_seen_count in GameState"
```

---

### Task 9: Thread handedness + RISP + TTO + `park_factors` into `sample_pa`

**Files:** Modify `simulation/game_sim.py:~281` and `simulate_game` signature.

- [ ] **Step 1: Write failing test**

Append to `tests/test_game_sim.py`:

```python
def test_simulate_game_accepts_park_factors_dict():
    from simulation.game_sim import simulate_game
    import random as rnd
    rnd.seed(42)
    pf = {"runs_lhh": 1.10, "runs_rhh": 1.05, "hr_lhh": 1.25, "hr_rhh": 1.08}
    result = simulate_game(
        home_lineup=_FIXTURE_HOME_LINEUP, away_lineup=_FIXTURE_AWAY_LINEUP,
        home_pitcher=_FIXTURE_HOME_PITCHER, away_pitcher=_FIXTURE_AWAY_PITCHER,
        park_factors=pf)
    assert "score" in result


def test_simulate_game_scalar_backward_compat():
    from simulation.game_sim import simulate_game
    import random as rnd
    rnd.seed(42)
    result = simulate_game(
        home_lineup=_FIXTURE_HOME_LINEUP, away_lineup=_FIXTURE_AWAY_LINEUP,
        home_pitcher=_FIXTURE_HOME_PITCHER, away_pitcher=_FIXTURE_AWAY_PITCHER,
        park_factor_runs=1.05, park_factor_hr=1.10)
    assert "score" in result
```

- [ ] **Step 2: Update `simulate_game` signature**

Add `park_factors` kwarg with shim (near the top of `simulate_game`):

```python
def simulate_game(
    home_lineup, away_lineup, home_pitcher, away_pitcher,
    park_factors: dict | None = None,
    park_factor_runs: float = 1.0, park_factor_hr: float = 1.0,
    home_reliever_id: int = 999991, away_reliever_id: int = 999992,
    # ... preserve remaining existing kwargs
):
    if park_factors is None:
        park_factors = {
            "runs_lhh": park_factor_runs, "runs_rhh": park_factor_runs,
            "hr_lhh":   park_factor_hr,   "hr_rhh":   park_factor_hr,
        }
```

- [ ] **Step 3: Replace the `sample_pa` call (~line 281)**

Replace `outcome = sample_pa(batter, pitcher, park_factor_runs, park_factor_hr)` with:

```python
                pitcher_hand = pitcher.get("throws")
                batter_bats = batter.get("bats") or "R"
                if batter_bats == "S":
                    # Switch-hitter: bat opposite the current pitcher's hand
                    batter_hand = "R" if pitcher_hand == "L" else "L"
                else:
                    batter_hand = batter_bats

                risp = (state.bases[1] or state.bases[2]) and state.outs < 2

                outcome = sample_pa(
                    batter, pitcher,
                    park_factors=park_factors,
                    pitcher_hand=pitcher_hand, batter_hand=batter_hand,
                    runners_on_scoring_position=bool(risp),
                    pitcher_pa_count=state.pitcher_pa_count[pitcher_id],
                    catcher_framing_z=0.0,  # Spec 4 wires real value
                )
```

- [ ] **Step 4: Run tests + commit**

```bash
pytest tests/test_game_sim.py -v
git add simulation/game_sim.py tests/test_game_sim.py
git commit -m "feat: thread handedness + RISP + TTO + park_factors dict into simulate_game"
```

---

### Task 10: Golden-game TTO assertion + v1-vs-v2 divergence smoke

**Files:** Create `tests/test_game_sim_golden.py`.

- [ ] **Step 1: Write test**

Create `tests/test_game_sim_golden.py`:

```python
"""Golden-game regressions for sim v2."""
import random
import pytest
from simulation.pa_engine import sample_pa


def _cy_young(): return {"player_id": 99999, "throws": "R",
    "k_pct": 0.340, "bb_pct": 0.050, "hr_pct": 0.020, "single_pct": 0.130,
    "double_pct": 0.040, "triple_pct": 0.003, "out_pct": 0.417,
    "avg_pitch_count": 95}


def _avg_batter(): return {"player_id": 11111, "bats": "R",
    "k_pct": 0.224, "bb_pct": 0.084, "hr_pct": 0.033, "single_pct": 0.152,
    "double_pct": 0.044, "triple_pct": 0.004, "out_pct": 0.459}


def test_elite_starter_tto_drops_k_pct():
    """Cy-Young-level pitcher K% drops ~1.5pp between PA 0-5 and PA 20-25."""
    pf = {"runs_lhh": 1, "runs_rhh": 1, "hr_lhh": 1, "hr_rhh": 1}
    def _k_rate(lo, hi):
        rng = random.Random(42)
        hits = total = 0
        for _ in range(10000):
            for pa in range(lo, hi):
                o = sample_pa(_avg_batter(), _cy_young(), park_factors=pf,
                               pitcher_hand="R", batter_hand="R",
                               pitcher_pa_count=pa, rng=rng)
                total += 1
                if o == "K": hits += 1
        return hits / total
    early, late = _k_rate(0, 5), _k_rate(20, 25)
    drop_pp = (early - late) * 100
    # Expected ~1.5pp; loose tolerance for Monte Carlo noise
    assert 0.3 < drop_pp < 3.0, f"K drop={drop_pp:.2f}pp outside band"


def test_feature_flag_equivalence_under_neutral_inputs():
    """sample_pa with legacy scalar args vs new dict args + None hand + no splits
    should yield identical outcome sequences under the same seed."""
    b = {"k_pct": 0.22, "bb_pct": 0.09, "hr_pct": 0.033, "single_pct": 0.15,
         "double_pct": 0.045, "triple_pct": 0.004, "out_pct": 0.458}
    p = b
    r1, r2 = random.Random(99), random.Random(99)
    s1 = [sample_pa(b, p, park_factor_runs=1.0, park_factor_hr=1.0, rng=r1)
          for _ in range(50)]
    s2 = [sample_pa(b, p, park_factors={"runs_lhh": 1, "runs_rhh": 1,
                                          "hr_lhh": 1, "hr_rhh": 1},
                     pitcher_hand=None, batter_hand=None,
                     runners_on_scoring_position=False,
                     pitcher_pa_count=0, catcher_framing_z=0.0, rng=r2)
          for _ in range(50)]
    assert s1 == s2


def test_v1_v2_divergence_plausible(monkeypatch):
    """simulate_game with neutral dict park_factors vs scalar should diverge
    within 0-6 runs (reflects TTO + RISP adjustments, not a bug)."""
    from simulation import game_sim
    try:
        from tests.test_game_sim import (_FIXTURE_HOME_LINEUP, _FIXTURE_AWAY_LINEUP,
            _FIXTURE_HOME_PITCHER, _FIXTURE_AWAY_PITCHER)
    except ImportError:
        pytest.skip("game_sim fixtures not available")
    random.seed(777)
    r1 = game_sim.simulate_game(
        home_lineup=_FIXTURE_HOME_LINEUP, away_lineup=_FIXTURE_AWAY_LINEUP,
        home_pitcher=_FIXTURE_HOME_PITCHER, away_pitcher=_FIXTURE_AWAY_PITCHER,
        park_factor_runs=1.0, park_factor_hr=1.0)
    random.seed(777)
    r2 = game_sim.simulate_game(
        home_lineup=_FIXTURE_HOME_LINEUP, away_lineup=_FIXTURE_AWAY_LINEUP,
        home_pitcher=_FIXTURE_HOME_PITCHER, away_pitcher=_FIXTURE_AWAY_PITCHER,
        park_factors={"runs_lhh": 1, "runs_rhh": 1, "hr_lhh": 1, "hr_rhh": 1})
    assert abs(r2["score"]["home"] - r1["score"]["home"]) <= 6
    assert abs(r2["score"]["away"] - r1["score"]["away"]) <= 6
```

- [ ] **Step 2: Run tests + commit**

```bash
pytest tests/test_game_sim_golden.py -v
# If elite-starter drop is outside [0.3, 3.0]pp, do NOT "tune to pass" — record the
# observed drop and coordinate with spec author. Possibly raise sample size to 50k.
git add tests/test_game_sim_golden.py
git commit -m "test: golden-game TTO drop + v1/v2 divergence smoke"
```

---

## Phase E — RISP verification

### Task 11: RISP integration smoke

RISP detection is wired by Task 9; this task adds a behavioral smoke test in the full `simulate_game` loop.

**Files:** Modify `tests/test_game_sim.py`.

- [ ] **Step 1: Write + run test**

Append to `tests/test_game_sim.py`:

```python
def test_risp_frequency_produces_walks():
    """A single-heavy lineup accumulates runners, triggering RISP BB bump."""
    from simulation.game_sim import simulate_game
    import random as rnd
    lineup = [{"player_id": 10000 + i, "bats": "R",
               "k_pct": 0.10, "bb_pct": 0.09, "hr_pct": 0.02,
               "single_pct": 0.30, "double_pct": 0.07,
               "triple_pct": 0.01, "out_pct": 0.41} for i in range(9)]
    pitcher = {"player_id": 77777, "throws": "R",
               "k_pct": 0.22, "bb_pct": 0.08, "hr_pct": 0.033,
               "single_pct": 0.15, "double_pct": 0.045,
               "triple_pct": 0.004, "out_pct": 0.458, "avg_pitch_count": 95}
    rnd.seed(11)
    total_bb = 0
    for _ in range(50):
        res = simulate_game(home_lineup=lineup, away_lineup=lineup,
            home_pitcher=pitcher, away_pitcher=pitcher,
            park_factors={"runs_lhh": 1, "runs_rhh": 1, "hr_lhh": 1, "hr_rhh": 1})
        for s in res.get("pitcher_stats", {}).values():
            total_bb += s.get("bb", 0)
    assert total_bb > 0
```

- [ ] **Step 2: Commit**

```bash
pytest tests/test_game_sim.py::test_risp_frequency_produces_walks -v
git add tests/test_game_sim.py
git commit -m "test: RISP frequency smoke in simulate_game"
```

---

## Phase F — Callers updated (monte_carlo + props_edge)

### Task 12: Migrate `monte_carlo.py` + `props_edge.py` call sites

**Files:** Modify `simulation/monte_carlo.py`, `simulation/props_edge.py`, update tests.

- [ ] **Step 1: Enumerate every `sample_pa` call**

Run: `grep -rn "sample_pa(" simulation/`
Record the exact line numbers.

- [ ] **Step 2: Rewrite each call site**

For legacy calls like `sample_pa(batter, pitcher, park_factor_runs, park_factor_hr)`, rewrite as:

```python
from config import SIM_V2_ENABLED

def _resolve_bat_side(batter, pitcher):
    bats = batter.get("bats") or "R"
    if bats == "S":
        return "R" if pitcher.get("throws") == "L" else "L"
    return bats

outcome = sample_pa(
    batter, pitcher,
    park_factors=park_factors,                          # dict, not scalars
    pitcher_hand=pitcher.get("throws") if SIM_V2_ENABLED else None,
    batter_hand=_resolve_bat_side(batter, pitcher) if SIM_V2_ENABLED else None,
    runners_on_scoring_position=False,                  # MC typically state-free
    pitcher_pa_count=pa_count if SIM_V2_ENABLED else 0,
    catcher_framing_z=0.0,
    rng=rng,                                            # Thread a Random from caller
)
```

For `monte_carlo.py`, add a `park_factors` kwarg to `run_monte_carlo`; keep `park_factor_runs`/`park_factor_hr` for backward compat and shim them into a dict at entry.

For `props_edge.py`, same pattern. Prop-level PA sampling should also use the passed-through `rng` rather than module-level `random` so tests are deterministic.

- [ ] **Step 3: Update affected tests**

Any `test_props_edge.py` / `test_monte_carlo.py` (if present) assertions referencing the old signature should be updated to pass `park_factors=`.

- [ ] **Step 4: Run + commit**

```bash
pytest tests/test_props_edge.py tests/test_pa_engine_platoon.py -v
git add simulation/monte_carlo.py simulation/props_edge.py tests/test_props_edge.py
git commit -m "feat: thread park_factors dict + handedness + rng through monte_carlo and props_edge"
```

---

## Phase G — Orchestrator wiring (`main.py`)

### Task 13: Attach splits + bats + throws to profiles when flag on

**Files:** Modify `main.py` (the `_simulate_game` section where lineups are fetched).

- [ ] **Step 1: Wrap split-fetch in flag check**

In `main._simulate_game`, after the `get_batter_stats` / `get_pitcher_stats` block, add:

```python
from config import SIM_V2_ENABLED, park_factors_dict_for
from scrapers.player_stats import get_batter_splits, get_pitcher_splits

season = int(game_date[:4])
home_abbrev = game_data["home_team"]
park_factors = park_factors_dict_for(home_abbrev)

if SIM_V2_ENABLED:
    # lineup_data must carry per-player bats/throws — if not already surfaced by
    # scrapers/lineups.py, see its `bats` field (scrapers/lineups.py:32-56).
    home_bats_map = lineup_data.get("home_bats", {})
    away_bats_map = lineup_data.get("away_bats", {})
    for bstats, pid in zip(home_lineup, lineup_data["home"]):
        bats = home_bats_map.get(pid)
        bstats["bats"] = bats
        bstats["splits"] = get_batter_splits(pid, season, bats=bats)
    for bstats, pid in zip(away_lineup, lineup_data["away"]):
        bats = away_bats_map.get(pid)
        bstats["bats"] = bats
        bstats["splits"] = get_batter_splits(pid, season, bats=bats)
    hp_stats["throws"] = lineup_data.get("home_pitcher_throws")
    hp_stats["splits"] = get_pitcher_splits(
        lineup_data["home_pitcher"], season, throws=hp_stats.get("throws"))
    ap_stats["throws"] = lineup_data.get("away_pitcher_throws")
    ap_stats["splits"] = get_pitcher_splits(
        lineup_data["away_pitcher"], season, throws=ap_stats.get("throws"))
```

(If `home_bats`/`away_bats`/`home_pitcher_throws` keys are not emitted by `scrapers/lineups.py`, surface them in that scraper — the `bats` field already exists per the reviewer at `scrapers/lineups.py:32-56`, so this is a small addition.)

- [ ] **Step 2: Replace the `PARK_FACTORS.get(...)` scalar dereference**

Replace:
```python
park = PARK_FACTORS.get(home_abbrev, {})
park_factor_runs=park.get("runs", 1.0),
park_factor_hr=park.get("hr", 1.0),
```
with:
```python
park_factors = park_factors_dict_for(home_abbrev)
# Feed new dict, plus scalars for backward-compat path
park_factors=park_factors if SIM_V2_ENABLED else None,
park_factor_runs=park_factors["runs_rhh"] if not SIM_V2_ENABLED else 1.0,
park_factor_hr=park_factors["hr_rhh"] if not SIM_V2_ENABLED else 1.0,
```

- [ ] **Step 3: Smoke test**

```bash
SIM_V2_ENABLED=false pytest tests/ -x -q
SIM_V2_ENABLED=true  pytest tests/ -x -q
SIM_V2_ENABLED=false python -c "from config import SIM_V2_ENABLED; assert SIM_V2_ENABLED is False"
SIM_V2_ENABLED=true  python -c "from config import SIM_V2_ENABLED; assert SIM_V2_ENABLED is True"
```
Expected: both runs green.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: wire SIM_V2_ENABLED in main.py; attach splits/bats/throws when v2 on"
```

---

## Phase H — Calibration rebuild (post-rollout)

### Task 14: Document rollout + calibration rebuild gate

**Files:** Append rollout section to this plan file (or create `docs/handedness-rollout.md`).

- [ ] **Step 1: Append operational checklist**

Append to this plan file the "Rollout checklist" section below (see Appendix C). This section is **non-executable** — it documents the post-merge procedure for the operator flipping the flag.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-17-handedness-aware-sim.md
git commit -m "docs: rollout + calibration-rebuild checklist for sim v2"
```

---

## Final verification

### Task 15: Full-suite green + CLI smoke

- [ ] **Step 1: Full suite**

```bash
pytest tests/ -v
SIM_V2_ENABLED=true pytest tests/ -v
```
Expected: both PASS.

- [ ] **Step 2: Lint / syntax check**

```bash
python -m py_compile simulation/pa_engine.py simulation/game_sim.py \
    config.py scrapers/player_stats.py scripts/update_park_factors.py \
    simulation/monte_carlo.py simulation/props_edge.py
```
Expected: exit 0.

- [ ] **Step 3: CLI smoke**

```bash
python main.py daily --help
```
Expected: help renders, no ImportError.

- [ ] **Step 4: (Optional) run the park-factor refresh script**

```bash
python scripts/update_park_factors.py --year 2026 --window 3
```
Expected: `Updated 30 parks in config.py`. If Savant is unreachable or CSV shape differs, fix the script before relying on it in prod.

- [ ] **Step 5: Final cleanup commit**

```bash
git add -A
git diff --cached --stat
git commit -m "chore: final cleanup after sim v2 implementation" || echo "nothing to commit"
```

---

## Appendix A: Risk register (from Spec §8)

| Risk | Spec ref | Plan mitigation |
|------|----------|-----------------|
| Small-sample platoon rates for bench players | §8.1 | `BATTER_SPLIT_REGRESS_PA = 50` in Task 4; tune via Spec 1 calibration |
| Noisy 3-year handedness park factors | §8.2 | `_shrink_to_overall(cap=0.15)` in Task 1 |
| Continuous TTO over-penalizes elite starters | §8.3 | `max(0.80, …)` floor in `_apply_tto_fatigue` (Task 7); pitch-count hook unchanged |
| Splits cache staleness | §8.4 | 1-day TTL in Task 4; `fetched_at` in every cache entry |
| Switch-hitter resolution mid-game | §8.5 | Per-PA resolution in Task 9 (`if batter_bats == "S":`) |
| Framing hook diverges from Spec 4 design | §8.6 | Interface is `catcher_framing_z: float`; internals are swappable |

---

## Appendix B: Commit sequence summary

| # | Task | Commit message |
|---|------|----------------|
| 1 | 1 | feat: add Savant park-factor refresh script + tests |
| 2 | 2 | refactor: rewrite PARK_FACTORS to handedness-split schema |
| 3 | 3 | feat: add park_factor_{runs,hr}_for + park_factors_dict_for accessors |
| 4 | 4 | feat: add handedness splits scraper with 1-day cache + Bayesian regression |
| 5 | 5 | chore: gitignore player splits cache |
| 6 | 6 | feat: add _rates_for_side helper for handedness resolution |
| 7 | 7 | feat: handedness-aware sample_pa with TTO, RISP, framing + SIM_V2_ENABLED flag |
| 8 | 8 | feat: track pitcher_pa_count + batter_seen_count in GameState |
| 9 | 9 | feat: thread handedness + RISP + TTO + park_factors dict into simulate_game |
| 10 | 10 | test: golden-game TTO drop + v1/v2 divergence smoke |
| 11 | 11 | test: RISP frequency smoke in simulate_game |
| 12 | 12 | feat: thread park_factors dict + handedness + rng through monte_carlo and props_edge |
| 13 | 13 | feat: wire SIM_V2_ENABLED in main.py; attach splits/bats/throws when v2 on |
| 14 | 14 | docs: rollout + calibration-rebuild checklist for sim v2 |
| 15 | 15 | chore: final cleanup after sim v2 implementation |

Tasks 1-6 are purely additive (no behavior change). Task 7 rewrites `sample_pa` but keeps backward compat via shims. Tasks 8-13 change sim behavior but are gated by `SIM_V2_ENABLED=false` default.

---

## Appendix C: Rollout checklist (post-merge)

1. Merge to `main`; deploy. `SIM_V2_ENABLED` defaults to `false` — no behavior change.
2. In production env, set `SIM_V2_ENABLED=true` for one shadow instance only.
3. Shadow tags predictions with `model_variant="sim_v2"`; production keeps `model_variant="sim_v1"`.
4. Run 2-3 weeks of parallel v1/v2 logging; compute calibration, CLV, ROI per variant.
5. Promotion gate (Spec §7.3):
   - 30+ days of v2 predictions logged.
   - v2 calibration error ≤ v1 calibration error.
   - v2 ROI ≥ v1 ROI − 0.5%.
6. When gate passes, flip `SIM_V2_ENABLED=true` system-wide.
7. Immediately after the flip, run:

       python main.py calibrate-rebuild

   (Spec 1 command.) Refits isotonic calibration on v2-only predictions. Curves fit on v1 will be miscalibrated for v2.
8. First-week monitoring: CLV dashboards, ROI smoke, error-rate baseline.
9. Rollback: set `SIM_V2_ENABLED=false`; no code revert required.
