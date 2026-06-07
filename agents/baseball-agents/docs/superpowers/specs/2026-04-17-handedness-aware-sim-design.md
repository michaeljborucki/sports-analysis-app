# Handedness-Aware Simulation — Design Spec

**Status:** Draft
**Date:** 2026-04-17
**Author:** MiroFish / Baseball Agents
**Spec sequence:** 3 of 4 (follows `2026-04-14-cache-breakeven-clv-design.md` and the betting-layer hardening spec; precedes the Statcast/umpire/catcher enrichment spec)

---

## 1. Overview

The current plate-appearance (PA) simulator at `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/pa_engine.py:17-89` combines a batter's and pitcher's overall season rates via a log5 odds-ratio combiner. It is *handedness-blind*: a left-handed slugger facing a left-handed pitcher gets the same projected HR% as he would vs. a right-handed pitcher, even though real-world platoon splits are worth roughly 25 wOBA points for position players and can exceed 80 points for extreme platoon guys. The game simulator at `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/game_sim.py:212-401` similarly applies a single `park_factor_runs` / `park_factor_hr` pair that does not distinguish between left- and right-handed batters — an obvious problem for ballparks like Yankee Stadium (short right field boosts LHH HR% far more than RHH) and Fenway Park (Green Monster boosts RHH 2B%).

The simulator also has no explicit times-through-the-order (TTO) penalty. It switches the starter to a league-average reliever when `pitches > avg_pitch_count * 1.1` (`game_sim.py:361-382`), but while the starter is in the game, his rates do not decay between the 1st and 3rd times through the order. Published research (Brill et al. 2022, "A Bayesian analysis of the time through the order penalty in baseball," arXiv:2210.06724) shows roughly a 10-point wOBA increase from the first to the third time through, even after controlling for quality-of-opposition. Modeling this as a continuous rate adjustment alongside the existing pitcher-hook gives the sim both a pitcher-fatigue curve *and* a manager-decision cliff, which together match observed play better than either alone.

Finally, there is no explicit RISP (runners-in-scoring-position) context effect. Empirically, K% drops about 7% and BB% rises about 8% with runners on 2B/3B and fewer than 2 outs — pitchers nibble and batters shorten their swings. Small adjustment, but it materially shifts run-scoring distributions in high-leverage states.

This spec introduces:

1. **Platoon-split batter/pitcher profiles** (`vs_lhp`, `vs_rhp`, `overall`) with a disk cache.
2. **Handedness-aware `sample_pa`** that picks the right rate dict based on the defender's hand.
3. **Handedness-split park factors** (`runs_lhh`, `runs_rhh`, `hr_lhh`, `hr_rhh`) replacing the current scalar pair.
4. **Continuous TTO fatigue curves** on top of the existing pitcher-hook rule (which we keep).
5. **RISP context bump** in `sample_pa` when the state has a runner on 2B/3B with < 2 outs.
6. **Forward-compat catcher-framing hook** (K-resample) — no-op until Spec 4 delivers catcher data.

A feature flag `SIM_V2_ENABLED` gates the whole change so Spec 1's calibration/CLV loop can A/B predictions against the current simulator.

---

## 2. Goals / Non-goals

### Goals

- G1. Handedness-aware PA sampling — every PA call threads `pitcher_hand` and `batter_hand` through `sample_pa`, and rate lookups resolve to the correct split when available.
- G2. Split park factors per handedness side, seeded from Baseball Savant Statcast 3-year rolling data, so Coors and Yankee Stadium LHH HR boost are correctly modeled.
- G3. A continuous TTO penalty applied during the starter's outing, independent of but layered with the existing pitch-count hook.
- G4. A small, tunable RISP rate multiplier triggered by base/out state.
- G5. A forward-compatible catcher-framing hook that is a no-op today but can be activated by Spec 4 without further sim refactors.
- G6. Graceful fallback everywhere — missing splits, missing handedness data, or missing park dict keys all degrade to the existing behavior without raising.
- G7. Deterministic, replayable tests: seeded PA sims and a "golden game" total comparison.

### Non-goals

- NG1. **Pinch-hitting / tactical substitutions.** Handling LOOGY usage, double-switches, and late-game pinch hitters is its own multi-week project and deliberately deferred.
- NG2. **OPS-weighted platoon regression schemes** beyond plain log5. The existing log5 odds-ratio is adequate once we feed it the correct split-specific rates.
- NG3. **Catcher pop-time, umpire zone, or full Statcast ingestion.** Spec 4 owns these. We only add the *plumbing* (one optional argument) in this spec.
- NG4. **Bullpen fatigue / reliever TTO.** Relievers rarely see a batter twice; their TTO effect is dwarfed by day-to-day workload, which is a future spec.
- NG5. **Switch-hitter re-routing during the sim.** Switch-hitters will use the batting side opposite the pitcher's hand, which is already how lineups publish them for that matchup. We do not re-route mid-PA based on whether the pitcher throws a specific pitch type.

---

## 3. Components

### 3.1 Platoon splits in batter and pitcher profiles

**Files touched:**
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/player_stats.py` (add new functions, keep existing)
- New file: `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/player_splits_cache.json`

**New public functions:**

```python
def get_batter_splits(player_id: int, season: int = None) -> dict:
    """Return {'vs_lhp': {...rates}, 'vs_rhp': {...rates}, 'overall': {...rates},
                'pa_vs_lhp': int, 'pa_vs_rhp': int, 'pa_overall': int}."""

def get_pitcher_splits(player_id: int, season: int = None) -> dict:
    """Same shape, keys 'vs_lhb', 'vs_rhb', 'overall'."""
```

Each inner rate dict has the seven keys used by `pa_engine.py:6-14`: `k_pct`, `bb_pct`, `hr_pct`, `single_pct`, `double_pct`, `triple_pct`, `out_pct`, plus `pa` (sample size) for regression decisions.

**Implementation approach:** Use `pybaseball.statcast_batter(start_dt, end_dt, player_id)` filtered by `p_throws` to build the split-specific plate appearances, then aggregate into the same seven rate stats. Fall back to `pybaseball.batting_stats_bref(season)` if Statcast is unavailable. Pitcher side uses `statcast_pitcher(..., player_id)` filtered by `stand`.

**Regression to mean per split:** The existing code in `scrapers/player_stats.py:31-35` regresses to a league mean with weight `sample_size / (sample_size + regress_n)`. For splits, use per-split regression: a batter with 40 PA vs LHP gets `40/(40+200) = 16.7%` weight on his observed vs-LHP rates, 83.3% on the *split-adjusted league average*. The split-adjusted league averages come from MLB-wide platoon coefficients:

- League batter vs LHP K% ≈ overall K% * 1.06, BB% * 0.97, HR% * 0.95 (RHB skew)
- League batter vs RHP K% ≈ overall K% * 0.98, BB% * 1.01, HR% * 1.02
- (Mirrored coefficients for LHB)

These coefficients are constants in `pa_engine.py` named `LEAGUE_PLATOON_COEF_BATTER_VS_LHP`, `..._VS_RHP`, `LEAGUE_PLATOON_COEF_PITCHER_VS_LHB`, `..._VS_RHB`. When splits fetch fails entirely, `get_batter_splits` synthesizes `vs_lhp` and `vs_rhp` dicts by multiplying the overall rates by these coefficients (this is the ~0.25 platoon-coefficient fallback referenced in the scope).

**Caching:** New file `data/player_splits_cache.json` with structure:

```json
{
  "2026": {
    "660271": {
      "fetched_at": "2026-04-17T12:33:00Z",
      "vs_lhp":  {"k_pct": 0.18, "bb_pct": 0.11, ...},
      "vs_rhp":  {"k_pct": 0.22, "bb_pct": 0.09, ...},
      "overall": {"k_pct": 0.21, "bb_pct": 0.10, ...},
      "pa_vs_lhp": 62, "pa_vs_rhp": 188, "pa_overall": 250
    }
  }
}
```

TTL = 1 day; `fetched_at` is compared against `date.today().isoformat()`. Concurrency: reuse the `_player_map_lock` pattern from `scrapers/player_stats.py:13`.

**Signature additions (no breaking change to existing callers):** `get_batter_stats` and `get_pitcher_stats` remain as they are. Callers that want splits call the new `*_splits` functions and attach the result under a `"splits"` key in the profile dict.

### 3.2 Handedness-aware `sample_pa`

**File:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/pa_engine.py`

**New signature:**

```python
def sample_pa(
    batter: dict,
    pitcher: dict,
    park_factors: dict | None = None,   # NEW: dict, not scalar pair
    pitcher_hand: str | None = None,     # "L" or "R"
    batter_hand: str | None = None,      # "L" or "R" (post-switch-hitter resolution)
    runners_on_scoring_position: bool = False,  # §3.5
    pitcher_pa_count: int = 0,           # §3.4 — how many PAs this pitcher has faced this game
    catcher_framing_z: float = 0.0,      # §3.6 — forward-compat, no-op by default
    # LEGACY positional compat:
    park_factor_runs: float | None = None,
    park_factor_hr: float | None = None,
) -> str:
```

**Backward-compat shim:** If `park_factors is None` but `park_factor_runs` / `park_factor_hr` are provided (old call sites), synthesize `park_factors = {"runs_lhh": park_factor_runs, "runs_rhh": park_factor_runs, "hr_lhh": park_factor_hr, "hr_rhh": park_factor_hr}` so existing tests don't break. Every new call site inside the repo must migrate to the dict form.

**Inside `_build_matchup_probs` — rate selection:**

```python
def _rates_for_side(profile: dict, opp_hand: str | None, role: str) -> dict:
    """role is 'batter' or 'pitcher'. opp_hand is the *opponent's* throwing/batting hand."""
    if opp_hand is None or "splits" not in profile:
        return profile  # existing behavior — use flat rates
    if role == "batter":
        split_key = "vs_lhp" if opp_hand == "L" else "vs_rhp"
    else:
        split_key = "vs_lhb" if opp_hand == "L" else "vs_rhb"
    split = profile["splits"].get(split_key)
    if split is None:
        return profile
    return {**profile, **split}  # merge: splits override overall keys
```

Then in `_build_matchup_probs`:

```python
b_rates = _rates_for_side(batter, pitcher_hand, "batter")
p_rates = _rates_for_side(pitcher, batter_hand, "pitcher")
```

Park factor application becomes handedness-selective:

```python
pf_runs = park_factors.get(f"runs_{'lhh' if batter_hand == 'L' else 'rhh'}", 1.0)
pf_hr   = park_factors.get(f"hr_{'lhh' if batter_hand == 'L' else 'rhh'}",   1.0)
```

**Math sanity check:** `matchup_probability` in `pa_engine.py:17-34` already handles extreme rates via log-odds. With split rates plugged in, the combiner produces, e.g., for a LHB (career .240/.315/.480 overall, .200/.280/.350 vs LHP) facing a LHP with overall K% 24%, league K% 22.4%:

- Overall path: log5(0.23, 0.24, 0.224) → 0.246
- Split path:   log5(0.28, 0.24, 0.224) → 0.298

That ~5-point K% delta is the whole point of this spec; it shows up directly in the sim's K/PA distribution and, by extension, in the K-prop pricing done in `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/props_edge.py`.

### 3.3 Handedness-split park factors

**File:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/config.py:99-130`

**Before:**

```python
PARK_FACTORS = {
    "COL": {"name": "Coors Field", "runs": 1.35, "hr": 1.30, "roof": "open"},
    "NYY": {"name": "Yankee Stadium", "runs": 1.05, "hr": 1.15, "roof": "open"},
    ...
}
```

**After:**

```python
PARK_FACTORS = {
    "COL": {
        "name": "Coors Field",
        "runs_lhh": 1.35, "runs_rhh": 1.35,
        "hr_lhh":   1.28, "hr_rhh":   1.32,
        "roof": "open",
    },
    "NYY": {
        "name": "Yankee Stadium",
        "runs_lhh": 1.08, "runs_rhh": 1.02,
        "hr_lhh":   1.25, "hr_rhh":   1.05,
        "roof": "open",
    },
    "BOS": {
        "name": "Fenway Park",
        "runs_lhh": 1.06, "runs_rhh": 1.13,
        "hr_lhh":   0.88, "hr_rhh":   1.00,  # Green Monster eats RHH flies; LHH lose short RF
        "roof": "open",
    },
    ...
}
```

Seed values come from the Baseball Savant Statcast Park Factors leaderboard (3-year rolling, 2023-2025 for the 2026 season). For parks with small directional asymmetry (Kauffman, Target, Minute Maid post-renovation) LHH and RHH values may be identical — this is fine.

**Accessor helpers** (new, in `config.py`):

```python
def park_factor_runs_for(team: str, batter_hand: str | None) -> float:
    pf = PARK_FACTORS.get(team, {})
    if batter_hand == "L":
        return pf.get("runs_lhh", pf.get("runs", 1.0))
    if batter_hand == "R":
        return pf.get("runs_rhh", pf.get("runs", 1.0))
    # Unknown hand: average the two sides, or fall through to legacy scalar
    lhh = pf.get("runs_lhh")
    rhh = pf.get("runs_rhh")
    if lhh is not None and rhh is not None:
        return (lhh + rhh) / 2
    return pf.get("runs", 1.0)

def park_factor_hr_for(team: str, batter_hand: str | None) -> float:
    # Symmetric to above, with "hr_lhh" / "hr_rhh" / "hr" fallback.
    ...
```

The fallback to the legacy `"runs"` / `"hr"` scalars means any park dict not yet migrated still works — important during the roll-out.

**Migration script:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scripts/update_park_factors.py`. It fetches the Savant CSV (`https://baseballsavant.mlb.com/leaderboard/statcast-park-factors?type=year&year=2026&batSide=L` and `...batSide=R`), normalizes to the schema above, and writes the updated dict back into `config.py` between sentinel comments `# BEGIN AUTO-GENERATED PARK FACTORS` / `# END AUTO-GENERATED PARK FACTORS`. Default values stay baked in so the pipeline works offline — the script is for quarterly refresh, not a runtime dependency.

### 3.4 Continuous times-through-order fatigue

**File:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/game_sim.py`

**State additions in `GameState`** (lines 45-54):

```python
pitcher_pa_count: dict = field(default_factory=dict)   # {pitcher_id: int}
batter_seen_count: dict = field(default_factory=dict)  # {pitcher_id: {batter_id: int}}
```

**Per-PA bookkeeping** (inside the `while state.outs < 3` loop, around line 281):

```python
state.pitcher_pa_count[pitcher_id] = state.pitcher_pa_count.get(pitcher_id, 0) + 1
state.batter_seen_count.setdefault(pitcher_id, {})
state.batter_seen_count[pitcher_id][batter_id] = (
    state.batter_seen_count[pitcher_id].get(batter_id, 0) + 1
)
```

These counts are passed into `sample_pa` as `pitcher_pa_count=state.pitcher_pa_count[pitcher_id]`.

**Rate adjustment inside `pa_engine._build_matchup_probs`:**

```python
# Excess PAs beyond 18 (≈ 2x through a 9-man order)
excess = max(0, pitcher_pa_count - 18)
k_mult    = max(0.80, 1.0 - 0.002 * excess)   # floor at 20% K% haircut
woba_mult = 1.0 + 0.0008 * excess              # lifts bb/hr/1b/2b/3b
```

Applied to pitcher rates only (batter rates unaffected) *before* log5 combines them:

```python
p_rates = dict(p_rates)
p_rates["k_pct"]      *= k_mult
p_rates["bb_pct"]     *= woba_mult
p_rates["hr_pct"]     *= woba_mult
p_rates["single_pct"] *= woba_mult
p_rates["double_pct"] *= woba_mult
p_rates["triple_pct"] *= woba_mult
# out_pct recomputed in post-normalize; we don't scale it directly
```

The `out_pct` is left alone — after all the other rates are multiplied, `normalize_probs` (pa_engine.py:37-43) renormalizes the distribution, which implicitly pulls `out_pct` down by the same amount `woba_mult` lifted the positives. This is correct behavior: a tired pitcher gives up more of everything except outs.

**Coefficient provenance:** Brill et al. 2022 (arXiv:2210.06724) estimate the 3rd-time-through wOBA bump at roughly +0.010 to +0.015 over 1st-time, with larger effects for starters who lean on a fastball. A batter sees the 3rd time through on PAs 19-27 of the pitcher's outing. Our `woba_mult = 1 + 0.0008 * 9 = 1.0072` at PA 27 gives a ~7% relative bump to positive outcomes, which maps to roughly +0.012 wOBA depending on the pitcher's baseline. Close to the paper.

**The existing hook is kept.** The code at `game_sim.py:361-382` that swaps to `LEAGUE_RELIEVER` when `pitches > avg_pitch_count * 1.1` is unchanged. It models the manager decision cliff. The continuous TTO penalty models the physical fatigue curve. They compose:

- Innings 1-3: no TTO penalty, starter at full strength.
- Innings 4-6: gradual degradation on pitcher rates.
- Innings 6+: pitch count crosses threshold → manager pulls pitcher, reliever takes over at league-average reliever rates, and both counters (`pitcher_pa_count`, `batter_seen_count`) reset implicitly because the reliever has a different `pitcher_id`.

### 3.5 RISP context adjustment

**File:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/pa_engine.py` (applied inside `_build_matchup_probs`) and `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/game_sim.py` (passed through)

**Detection at call site** (`game_sim.py` around line 281):

```python
risp = (state.bases[1] or state.bases[2]) and state.outs < 2
outcome = sample_pa(
    batter, pitcher, park_factors,
    pitcher_hand=..., batter_hand=...,
    runners_on_scoring_position=bool(risp),
    pitcher_pa_count=state.pitcher_pa_count[pitcher_id],
)
```

**Multipliers** (new config block in `config.py`):

```python
SIM_RISP_MULTIPLIERS = {
    "k_pct":      0.93,   # batters shorten up, strike out less
    "bb_pct":     1.08,   # pitchers nibble
    "single_pct": 1.05,   # contact-hitting approach
    # hr_pct, 2B, 3B left at 1.0 — empirically power doesn't move much with RISP
}
```

Exposed to `pa_engine.py` via:

```python
from config import SIM_RISP_MULTIPLIERS
```

Applied to the final `raw` dict before `normalize_probs`:

```python
if runners_on_scoring_position:
    for key, mult in SIM_RISP_MULTIPLIERS.items():
        outcome_key = _RATE_TO_OUTCOME[key]  # "k_pct" -> "K", "single_pct" -> "1B", etc.
        if outcome_key in raw:
            raw[outcome_key] *= mult
```

The dict-driven design means tuning these values (e.g., from observed calibration drift in Spec 1) is a one-line config change, not a code edit.

### 3.6 Catcher framing hook (forward-compat)

**File:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/pa_engine.py`

**New optional parameter:** `catcher_framing_z: float = 0.0` — standardized framing runs (z-score across MLB catchers, positive = better framer).

**Mechanism:** After an outcome is drawn, if the outcome is `"K"` or `"BB"` and `catcher_framing_z != 0`, probabilistically resample:

```python
def _apply_framing(outcome: str, framing_z: float, rng: random.Random) -> str:
    if framing_z == 0 or outcome not in ("K", "BB"):
        return outcome
    # Positive z (good framer): convert a small fraction of BBs into Ks,
    # and keep Ks that would have been resampled as Ks.
    # Negative z (bad framer): opposite.
    eps = 0.015 * framing_z  # empirical rule-of-thumb; positive = pitcher friendly
    if outcome == "BB" and eps > 0 and rng.random() < eps:
        return "K"
    if outcome == "K" and eps < 0 and rng.random() < -eps:
        return "BB"
    return outcome
```

**Why K <-> BB and not rate-level multipliers?** Framing's primary effect is shifting borderline pitches — it does not change whether a ball is hit in play, only whether a 3-ball count becomes a 4-ball walk or a 3-2 strikeout. The outcome-level resample models that more faithfully than scaling `k_pct`/`bb_pct` at rate-calculation time.

**No-op today.** Every call site passes `catcher_framing_z=0.0` (the default), so behavior is identical until Spec 4 wires up real framing data per game. Spec 4 will fetch per-catcher framing runs from Baseball Savant's catcher framing leaderboard and plumb it through the game sim the same way pitcher handedness flows today.

---

## 4. Data shapes

### 4.1 Batter profile (before)

```python
{
    "player_id": 660271,
    "k_pct": 0.207,
    "bb_pct": 0.132,
    "hr_pct": 0.067,
    "single_pct": 0.142,
    "double_pct": 0.051,
    "triple_pct": 0.002,
    "out_pct": 0.399,
}
```

### 4.2 Batter profile (after)

```python
{
    "player_id": 660271,
    # Overall rates still present — used as fallback and for legacy call sites.
    "k_pct": 0.207,
    "bb_pct": 0.132,
    "hr_pct": 0.067,
    "single_pct": 0.142,
    "double_pct": 0.051,
    "triple_pct": 0.002,
    "out_pct": 0.399,
    # NEW:
    "bats": "L",
    "splits": {
        "vs_lhp": {
            "k_pct": 0.241, "bb_pct": 0.098, "hr_pct": 0.048,
            "single_pct": 0.131, "double_pct": 0.042,
            "triple_pct": 0.002, "out_pct": 0.438,
            "pa": 78,
        },
        "vs_rhp": {
            "k_pct": 0.196, "bb_pct": 0.141, "hr_pct": 0.073,
            "single_pct": 0.146, "double_pct": 0.054,
            "triple_pct": 0.002, "out_pct": 0.388,
            "pa": 312,
        },
    },
}
```

### 4.3 Pitcher profile (after)

```python
{
    "player_id": 592789,
    "throws": "R",
    "k_pct": 0.278, "bb_pct": 0.071, "hr_pct": 0.029, ...,
    "avg_pitch_count": 95,
    "splits": {
        "vs_lhb": {"k_pct": 0.244, "bb_pct": 0.083, ..., "pa": 168},
        "vs_rhb": {"k_pct": 0.307, "bb_pct": 0.062, ..., "pa": 241},
    },
}
```

### 4.4 Park factors dict (before)

```python
PARK_FACTORS["COL"] = {"name": "Coors Field", "runs": 1.35, "hr": 1.30, "roof": "open"}
```

### 4.5 Park factors dict (after)

```python
PARK_FACTORS["COL"] = {
    "name": "Coors Field",
    "runs_lhh": 1.35, "runs_rhh": 1.35,
    "hr_lhh":   1.28, "hr_rhh":   1.32,
    "roof": "open",
    # NOTE: legacy "runs" and "hr" keys are dropped once migration is complete.
    # During the transition, the accessors fall back to them if present.
}
```

### 4.6 `sample_pa` call shape (after)

```python
outcome = sample_pa(
    batter=batter_profile,            # dict, may contain "splits"
    pitcher=pitcher_profile,          # dict, may contain "splits"
    park_factors=park_dict,           # dict with runs_lhh / runs_rhh / hr_lhh / hr_rhh
    pitcher_hand="R",                 # "L" / "R" / None
    batter_hand="L",                  # "L" / "R" / None (switch-hitter pre-resolved)
    runners_on_scoring_position=True,
    pitcher_pa_count=22,              # int, tracks TTO
    catcher_framing_z=0.0,            # forward-compat, Spec 4
)
```

---

## 5. Migration

### 5.1 Park factors (one-shot)

1. Run `python scripts/update_park_factors.py --year 2026 --window 3` once.
2. Script pulls Savant Statcast Park Factors with `batSide=L` and `batSide=R` separately.
3. Script rewrites the `PARK_FACTORS` dict in `config.py` between the sentinel comments.
4. Commit the updated `config.py`.
5. Accessors `park_factor_runs_for` / `park_factor_hr_for` immediately see the new keys.

Rollback: revert the `config.py` commit. The accessors fall back to legacy `"runs"` / `"hr"` if only those are present, so a partial revert is safe.

### 5.2 Batter / pitcher splits (lazy)

- No bulk backfill. Splits are fetched on first access through `get_batter_splits` / `get_pitcher_splits` and cached to `data/player_splits_cache.json` with a 1-day TTL.
- Daily cache file stays under ~2 MB for a full MLB roster — well inside acceptable bounds.
- First-day cold-start hits `pybaseball` N times where N ≈ number of unique players in today's lineups × 2 (batter + pitcher). Typical MLB day = ~250 requests, which pybaseball handles in ~30s.
- Tests and local dev inject a prebuilt fixture via dependency injection: `get_batter_splits = fake_splits_provider` in test setup.

### 5.3 Lineup wiring for `batter_hand`

Lineups from `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/lineups.py:32-56` already carry `"bats": p.get("batSide", {}).get("code", "")` (L / R / S). Switch-hitters (`"S"`) are resolved at sim time:

```python
batter_hand = lineup_entry["bats"]
if batter_hand == "S":
    batter_hand = "R" if pitcher_hand == "L" else "L"
```

This resolution happens inside `simulate_game` just before the `sample_pa` call, using the *current* pitcher's hand (not the game's starter). A switch-hitter facing the LHP starter then flipping to the RHP reliever will correctly switch sides within a single game.

### 5.4 `scrapers/player_stats.py` additions

The existing `get_batter_stats` and `get_pitcher_stats` are untouched. Callers who want splits do:

```python
profile = get_batter_stats(player_id, season)
profile["splits"] = get_batter_splits(player_id, season)  # returns {"vs_lhp": ..., "vs_rhp": ...}
profile["bats"] = lineup_entry["bats"]
```

This composition happens in the orchestrator (`simulation/monte_carlo.py` — not shown here, callers TBD during implementation) so that legacy call sites without the composition step continue to work.

---

## 6. Testing

### 6.1 Deterministic PA sim test (fixed seed, with/without splits)

New file `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_pa_engine_platoon.py` installs a fixture batter with extreme split rates (e.g., `vs_lhp.k_pct = 0.35`, `vs_rhp.k_pct = 0.10`), a league-average pitcher, and a fixed-sequence RNG via `monkeypatch.setattr("random.random", iter([...]).__next__)`. Same RNG sequence + `pitcher_hand="L"` must return `"K"`; `pitcher_hand="R"` must return a non-K outcome, confirming the split dict is actually used.

### 6.2 Property test: `sum(probs) ≈ 1.0`

```python
@pytest.mark.parametrize("batter_hand", ["L", "R"])
@pytest.mark.parametrize("pitcher_hand", ["L", "R"])
@pytest.mark.parametrize("risp", [True, False])
def test_probs_sum_to_one(batter_hand, pitcher_hand, risp):
    probs = _build_matchup_probs(
        batter, pitcher,
        park_factors={"runs_lhh": 1.1, "runs_rhh": 0.9, "hr_lhh": 1.2, "hr_rhh": 0.8},
        pitcher_hand=pitcher_hand, batter_hand=batter_hand,
        runners_on_scoring_position=risp,
        pitcher_pa_count=20,
    )
    assert abs(sum(probs.values()) - 1.0) < 1e-9
```

All 2 × 2 × 2 = 8 combinations must pass. Include a TTO sweep: `pitcher_pa_count in [0, 9, 18, 27, 36]`.

### 6.3 Golden-game regression test

`/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_game_sim_golden.py`:

Fix a seed (`random.seed(42)`), run `simulate_game` with a known lineup (e.g., 2025 Opening Day Yankees @ Dodgers), assert the final score matches a recorded baseline (± 0 runs — deterministic given the seed). Add a second version that enables the SIM_V2 path (handedness + TTO + RISP + split park factors) and records a *separate* baseline. The two baselines should diverge by a plausible margin — a typical game sim delta of 0-2 runs per side — indicating the new path materially changes output without blowing up.

### 6.4 Park factor accessor tests

```python
def test_park_factor_runs_for_lhh_uses_split():
    assert park_factor_runs_for("NYY", "L") == 1.08
    assert park_factor_runs_for("NYY", "R") == 1.02
    assert park_factor_runs_for("NYY", None) == pytest.approx(1.05)  # midpoint

def test_park_factor_falls_back_to_legacy_scalar():
    with monkeypatch_park({"XXX": {"runs": 1.07, "hr": 1.10}}):
        assert park_factor_runs_for("XXX", "L") == 1.07
```

### 6.5 TTO curve sanity test

```python
def test_tto_multiplier_monotone():
    # K% should monotonically decrease as pitcher_pa_count grows beyond 18
    outcomes = [
        _build_matchup_probs(batter, pitcher, park_factors,
                              pitcher_pa_count=n)["K"]
        for n in [0, 9, 18, 27, 36]
    ]
    assert outcomes[0] >= outcomes[2] > outcomes[3] > outcomes[4]
```

### 6.6 RISP test

```python
def test_risp_boosts_bb_reduces_k():
    base = _build_matchup_probs(batter, pitcher, park_factors,
                                 runners_on_scoring_position=False)
    risp = _build_matchup_probs(batter, pitcher, park_factors,
                                 runners_on_scoring_position=True)
    assert risp["K"] < base["K"]
    assert risp["BB"] > base["BB"]
```

### 6.7 Framing no-op test

With `catcher_framing_z=0.0` (the default) and a fixed seed, `sample_pa` output must be bit-for-bit identical to a call with the same seed and the argument omitted.

---

## 7. Rollout

### 7.1 Feature flag

`config.py` gains:

```python
SIM_V2_ENABLED = os.getenv("SIM_V2_ENABLED", "false").lower() == "true"
```

All `simulate_game` and `sample_pa` call sites branch on this flag:

- **Disabled (default):** the existing code path runs unchanged. `sample_pa` is called with the legacy positional args; `park_factor_runs` / `park_factor_hr` are read from `PARK_FACTORS[team]["runs"]` / `["hr"]` (or the migrated averaged values). No handedness, no TTO, no RISP.
- **Enabled:** the new path runs. `sample_pa` gets the full new signature; splits are fetched and passed in; handedness-split park factors are used; TTO/RISP apply.

### 7.2 A/B comparison via Spec 1 calibration loop

Spec 1's calibration + CLV logger accepts a `model_variant` tag. We log predictions under `variant="sim_v1"` from the legacy path and `variant="sim_v2"` from the new path. Run both in parallel for 2-3 weeks:

- Compare calibration curves at the ensemble output layer (are v2's 60% predictions really 60% outcomes?).
- Compare CLV: does v2 beat v1 on closing-line movement?
- Compare ROI on prop markets specifically — prop pricing should improve more than game lines, since platoon splits matter more per-PA than per-game.

### 7.3 Calibration curve rebuild

When flipping `SIM_V2_ENABLED=true` as the default, Spec 1's isotonic calibration curves must be retrained on v2 predictions only — curves fit on v1 will be miscalibrated for v2. The flip is gated on: "30+ days of v2 predictions logged AND v2 calibration error ≤ v1 calibration error AND v2 ROI ≥ v1 ROI − 0.5%."

### 7.4 Commit sequence

1. Add `park_factor_*_for` accessors and migrated `PARK_FACTORS` dict (spec 3 PR #1).
2. Add `get_batter_splits` / `get_pitcher_splits` scrapers with cache (PR #2).
3. Update `sample_pa` signature + handedness routing (PR #3).
4. Thread handedness through `simulate_game`; add TTO counters; add RISP detection (PR #4).
5. Add `catcher_framing_z` parameter as no-op (PR #5).
6. Add `SIM_V2_ENABLED` flag and wire call sites (PR #6).
7. Tests (interleaved with each PR above).

Each PR is independently revertable. Only PR #6 flips behavior for non-flag users.

---

## 8. Risks

### 8.1 Small-sample platoon rates for part-timers

A bench outfielder with 40 career PAs vs LHP has effectively no information in his split. The regression scheme in §3.1 handles this — at 40 PA, only 16.7% weight goes on observed, 83.3% on the split-adjusted league average for a LHB (or RHB as appropriate). The risk is that **the regression constants are wrong**: if actual platoon-coefficient noise is larger than assumed, the 83.3% weight on "league average vs LHP" is still biased toward whatever direction we picked for the league coefficient.

Mitigation: Spec 1's calibration loop will surface this. If v2 is systematically over-confident on LHP-vs-LHB matchups, the fix is to bump `BATTER_REGRESS_PA` higher for split-specific rates (e.g., 300 instead of 200) and re-run.

### 8.2 Handedness-split park factors have noisy 3-year tails

Savant's 3-year rolling park factors smooth out year-to-year noise well for *overall* runs/HR, but the per-handedness slice has smaller sample size — ~300 LHH PAs in a given park-year vs ~2000 combined. A park's `hr_lhh` can bounce by ±10% year-over-year on pure noise.

Mitigation: seed defaults from 3-year rolling, but blend toward the park's overall factor when `|hr_lhh - hr_overall| > 0.15`. Encoded as a post-processing step in `scripts/update_park_factors.py`:

```python
def _shrink_to_overall(lhh: float, rhh: float, overall: float, cap: float = 0.15) -> tuple:
    if abs(lhh - overall) > cap:
        lhh = 0.5 * (lhh + overall)
    if abs(rhh - overall) > cap:
        rhh = 0.5 * (rhh + overall)
    return lhh, rhh
```

### 8.3 Continuous TTO may over-penalize elite starters

Brill et al.'s paper finds the TTO penalty is *smaller* for elite starters with deep arsenals — Cole, Snell, Strider see ~5 wOBA points 1st-to-3rd, not ~12. Our flat `k_mult = 1 - 0.002 * excess` applies equally to every pitcher.

Mitigation: the floor `max(0.80, ...)` already caps the K% haircut at 20%. If we want pitcher-specific TTO in the future, the hook is already there — swap the constant `0.002` for a per-pitcher value derived from their arsenal depth (number of pitches with >10% usage, from Statcast). This is out of scope for Spec 3 but can be added in a future spec without re-architecting.

Secondary mitigation: the existing `pitches > avg_pitch_count * 1.1` hook still fires at its usual ~100-pitch point, which pulls elite starters at roughly the same point as real-world managers do. The TTO penalty is small over PAs 18-27 (~7% relative woba bump at the outer edge), not large.

### 8.4 Splits cache staleness

1-day TTL means morning runs see yesterday's end-of-night data. For a batter who played last night, his splits include that game. Edge case: games played at midnight PT / 3am ET may not be in pybaseball by the 6am ET pipeline run. Impact is negligible (one game's worth of split data) but worth noting.

### 8.5 Switch-hitter resolution

The late-game pinch hitter / reliever swap can cause a switch-hitter to face opposite-hand pitchers in the same game. The resolution rule (`batter_hand = "R" if pitcher_hand == "L" else "L"`) runs per-PA, which is correct. The risk is that the batter's *splits dict* only has `vs_lhp` and `vs_rhp` keyed by the pitcher's hand — which is exactly what we want. No ambiguity here, but flagging it so future refactors don't break the assumption.

### 8.6 Forward-compat framing hook divergence from Spec 4

If Spec 4 decides framing should scale K% at the rate level (rather than outcome-resample), the signature `catcher_framing_z: float` is still the right interface — only the internals change. The public API is stable.

---

## Appendix A: Full file inventory

| File | Change |
| --- | --- |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/pa_engine.py` | Signature change, handedness routing, TTO multipliers, RISP multipliers, framing hook |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/game_sim.py` | TTO counters in `GameState`, pass `pitcher_hand` / `batter_hand` to `sample_pa`, RISP detection |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/props_edge.py` | Ensure prop-level PA sim also receives handedness + TTO (same call-site migration) |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/player_stats.py` | Add `get_batter_splits`, `get_pitcher_splits` with JSON cache |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/lineups.py` | No change — already emits `bats` field |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/config.py` | Migrate `PARK_FACTORS` to split schema; add `park_factor_*_for` accessors; add `SIM_RISP_MULTIPLIERS`; add `SIM_V2_ENABLED` |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scripts/update_park_factors.py` | NEW — Savant fetch + config rewrite |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/player_splits_cache.json` | NEW — cache file (gitignored) |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_pa_engine_platoon.py` | NEW — platoon routing tests |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_game_sim_golden.py` | NEW — golden-game regression |
| `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_park_factors.py` | NEW — accessor tests |

---

## Appendix B: References

- Brill, R. S. et al. (2022). *A Bayesian analysis of the time through the order penalty in baseball.* arXiv:2210.06724.
- Baseball Savant Statcast Park Factors leaderboard.
- Retrosheet play-by-play (2015) — already used for base advancement probabilities in `game_sim.py:32-38`.
- FanGraphs platoon splits primer; Baseball Prospectus CSAA framing runs (referenced for Spec 4).
