# Spec 4: Statcast + Umpire + Catcher Enrichment

**Status:** Design
**Owner:** MiroFish MLB
**Date:** 2026-04-17
**Sequence:** Fourth of four MiroFish MLB upgrades. Assumes Specs 1 (calibration + CLV), 2 (betting-layer hardening), and 3 (handedness-aware simulation) are live in `main`.

---

## 1. Overview

MiroFish's current briefing stops at traditional FanGraphs/MLB-API stats (ERA, FIP, K/9, BB/9, HR/9) plus a coarse park factor and wind classification. Spec 3 introduced handedness-split park factors and a forward-compat hook `sample_pa(catcher_framing_z=0.0)` that is not yet wired to real data. Without Statcast expected stats, pitch-modeling metrics, umpire context, catcher framing, and an air-density-aware carry model, the LLM briefings lean on noisy small-sample traditional stats and miss two of the largest non-lineup edge sources in MLB betting: home-plate umpire K/BB shifts (~±4% on totals) and framing deltas worth 12–18 runs per 150.

This spec adds four independent data sources — Statcast advanced stats, UmpScorecards umpire profiles, Baseball Savant catcher framing, and FanGraphs Depth Charts projections — plus an Alan-Nathan-based air-density carry model. Each source is togglable via a `SOURCES_ENABLED` dict so a single flaky scraper cannot block prediction.

Current briefing (see `/Users/mikeborucki/personal_workspace/agents/baseball-agents/briefing.py:88-127`):
- ballpark name, roof, day/night (line 91)
- temp, wind mph, wind direction, park factor runs (line 92)
- moneyline / run line / total / implied probs (lines 95-98)
- per-starter W-L ERA FIP xFIP WHIP K/9 BB/9 HR/9 + days rest + last 5 starts (lines 102-114)
- bullpen freshness + closer name (lines 117-121)
- injuries (lines 124-125)

After this spec, the briefing gains five new sections (pitch quality, hitter profiles, umpire, catcher framing, carry) totaling ~30 additional lines, a `DATA RELIABILITY` tag on every advanced stat, and two new prompt-task instructions that tell the LLM how to weight priors vs. recent actuals.

The PA simulator (`/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/pa_engine.py:77-89`) gains two new optional kwargs — `catcher_framing_z` and `umpire_k_delta/bb_delta` — that shift `k_pct` and `bb_pct` before the log5 combine.

---

## 2. Goals / Non-Goals

### Goals

1. Pull Statcast expected stats (xERA, xwOBA, barrel%, hard-hit%) and pitch-modeling metrics (Stuff+, Location+, Pitching+, PitchingBot) for both starters.
2. Pull Statcast hitter quality-of-contact and bat tracking (bat speed, squared-up%, fast-swing%, attack angle) for top lineup bats.
3. Assign the home-plate umpire from MLB StatsAPI, then look up their K%/BB%/runs deltas from UmpScorecards.
4. Identify the starting catcher and surface framing runs per 150 + z-score.
5. Compute an air-density carry multiplier on top of Spec 3's handedness-split park factors.
6. Pull FanGraphs Depth Charts projections as true-talent priors shown side-by-side with 14-day and 30-day actuals.
7. Wire catcher framing z-score and umpire K/BB deltas into `sample_pa` so they move simulated outcomes, not just the LLM context.
8. Ship with per-source feature flags (`SOURCES_ENABLED`) and fixture-based fallbacks so any single scraping break is survivable.

### Non-Goals

- Building a proprietary pitch model. We consume the public Stuff+/Location+/Pitching+ and PitchingBot numbers from FanGraphs; we do not fit our own.
- Turning bat tracking into a physics-based batted-ball distribution model. Bat speed is a briefing-only input for now.
- Live in-game umpire performance feedback (strike-zone accuracy over tonight's first 4 innings). Pre-game profile only.
- Manager-tendency modeling for pitcher pull decisions. Bullpen-pull triggers remain Spec 3's ERA/TBF logic.
- Weather beyond the hour of first pitch. No re-pull after lineups lock.
- Catcher blocking / pop-time / arm strength. Framing runs only.

---

## 3. Components

Eight components, numbered to match the scope list. Each section specifies file path, public signatures, caching strategy, fallback behavior, and integration points.

### 3.1 Statcast advanced pitcher/hitter scraper

**New file:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/statcast_advanced.py`

**Public API:**

```python
def get_pitcher_advanced(name_or_id: str | int, season: int) -> dict:
    """Return dict of expected/pitch-model stats. Missing fields -> None.

    Keys: xERA, xFIP, xwOBA_against, barrel_pct_against, hard_hit_pct_against,
          k_pct, bb_pct, csw_pct, stuff_plus, location_plus, pitching_plus,
          bot_stf, bot_cmd, bot_ovr, ip, bf  # ip/bf drive reliability tags
    """

def get_batter_advanced(name_or_id: str | int, season: int) -> dict:
    """Return dict of Statcast + bat-tracking stats. Missing fields -> None.

    Keys: xwOBA, xSLG, xBA, barrel_pct, hard_hit_pct, bat_speed,
          squared_up_pct, fast_swing_pct, attack_angle, pa  # pa drives reliability tag
    """
```

**Data sources:**

- **FanGraphs leaderboard** via `pybaseball.pitching_stats(season, qual=0)` and `pybaseball.batting_stats(season, qual=0)`. These DataFrames already include `xERA, xFIP, Stuff+, Location+, Pitching+, botStf, botCmd, botOvr, xwOBA, Barrel%, HardHit%, K%, BB%, CSW%` when `qual=0`. Filter by name or `IDfg`/MLBAM ID.
- **Baseball Savant bat tracking leaderboard:** `https://baseballsavant.mlb.com/leaderboard/bat-tracking?season={season}&min=q&csv=true`. Returns CSV with `bat_speed, swing_length, squared_up_per_bat_contact, squared_up_per_swing, attack_angle, fast_swing_rate`. Keyed by `player_id` (MLBAM).
- **Savant expected stats:** `https://baseballsavant.mlb.com/leaderboard/expected_statistics?type=batter&year={season}&csv=true` for `xBA, xSLG, xwOBA` at MLBAM-id granularity (used as a cross-check against FanGraphs).

**Caching:**

- Directory: `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/statcast_cache/<season>/`
- One JSON file per player ID: `p_<mlbam_id>.json` for pitchers, `b_<mlbam_id>.json` for batters.
- TTL: 24h. `mtime < now - 86400` triggers refetch.
- Concurrency: `filelock.FileLock(cache_path + ".lock")` around write, 5s timeout. Reuses the `filelock` pattern already in `player_stats.py:13` (`_player_map_lock`). Add `filelock>=3.12` to `requirements.txt` if not present (the `threading.Lock` pattern is in-process only and insufficient for parallel daily_runner calls).
- Leaderboard pulls (hundreds of players per call) are cached once per season per day at `/data/statcast_cache/<season>/_leaderboard_pitchers.json` and `_leaderboard_batters.json`. Per-player lookups read from the leaderboard cache first.

**Fallback behavior:**

- On network error / 5xx / pybaseball exception: return dict with all keys set to `None`. Log once per run at WARN. Do not raise.
- Briefing renders `None` as `"N/A"` with a `(unavailable)` reliability tag.
- `SOURCES_ENABLED["statcast"] = False` short-circuits to `{}` immediately.

**Reliability tags:**

Computed in the briefing layer, not the scraper, but the scraper exposes the sample size:

| Stat | Stable at | Tag |
| --- | --- | --- |
| xwOBA, xERA, xFIP | 300+ BF / 500+ PA | `(stable)` |
| Stuff+, Location+, Pitching+ | 500+ pitches (~5 starts) | `(stable)` |
| Barrel%, HardHit% | 150+ BBE | `(stable)` |
| Bat speed, attack angle | 50+ competitive swings | `(stable)` |
| K%, BB% | 60 PA / 150 BF | `(stable)` |

Below those thresholds, tag is `(small sample: <N>)`.

**Integration:** called by `agents/daily_runner.py` after Spec 3's `get_handed_splits`, before `build_briefing`. Results added to `game_data["away_pitcher"]["advanced"]`, `game_data["home_pitcher"]["advanced"]`, and per-batter `game_data["away_lineup"][i]["advanced"]`.

---

### 3.2 Umpire scraper

**New file:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/umpire.py`

**Public API:**

```python
def get_umpire_assignment(game_pk: int) -> dict | None:
    """Return {'home_plate_ump_id': int, 'name': str} or None if TBD.

    Source: MLB StatsAPI /game/{game_pk}/boxscore endpoint's `officials` array.
    The home-plate ump is the entry with officialType == 'Home Plate'.
    """

def get_umpire_profile(ump_id: int | None, ump_name: str | None = None) -> dict:
    """Return career profile or neutrals if missing.

    Keys: k_pct_delta, bb_pct_delta, runs_per_game_delta,
          consistency_pct, accuracy_pct, consecutive_games, games_sample
    Deltas are vs league average. Typical range ±1.5pp for K%/BB%,
    ±0.6 runs/game for runs delta.
    """
```

**Assignment endpoint:** `GET {MLB_API_BASE}/game/{game_pk}/boxscore`. The `officials` array is populated usually 2-4 hours before first pitch. Example:

```json
{"officials": [
  {"official": {"id": 427053, "fullName": "Angel Hernandez"}, "officialType": "Home Plate"},
  {"official": {"id": ...}, "officialType": "First Base"},
  ...
]}
```

If `officials` is empty or missing the Home Plate entry, return `None`. Daily runner treats `None` as TBD.

**Profile source:** UmpScorecards public CSV at `https://umpscorecards.com/single_umpire/?id={ump_id}&format=csv` (alt: `https://umpscorecards.com/api/umpires/{ump_id}`). Scraping approach:

1. Prefer `csv` query param — stable and machine-readable.
2. Back off to HTML scrape with `BeautifulSoup` if CSV endpoint 404s. Parse the "Career Averages" table (class `.career-averages` as of last check).
3. Rate limit: one request per 2 seconds (`time.sleep(2)` between umps), max 15 umps per daily run. 15 games * 1 ump = 15 calls, well within a conservative budget.

**Cache:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/umpire_cache.json` — single file, keyed by ump_id, values include a `fetched_at` unix timestamp. TTL 24h. Structure:

```json
{
  "427053": {
    "fetched_at": 1713398400,
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
```

**Fallback behavior:**

- Ump ID not yet assigned → brief shows "Home Plate Ump: TBD" with neutral deltas (0.0). Do not block.
- UmpScorecards 5xx / page-structure break → load `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/umpire_fixture.json` (shipped in repo, frozen 2026-04-01 snapshot of top 80 umps). Return fixture entry if present, else neutrals.
- `SOURCES_ENABLED["umpire"] = False` → return `None`/neutrals.

**Future — crew rotation fallback (Phase 2, out of scope for this spec):** if the HP ump is not yet assigned but crew chief is known, predict tomorrow's HP via 4-man rotation (most crews rotate 1B→HP→3B→2B). Today we return `None` and brief with "TBD".

---

### 3.3 Catcher framing scraper

**New file:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/catcher_framing.py`

**Public API:**

```python
def get_catcher_framing(catcher_id: int, season: int) -> dict:
    """Return framing profile for a catcher.

    Keys: framing_runs, framing_runs_per_150, csaa, z_score, innings_caught
    framing_runs: total runs saved/cost vs average
    framing_runs_per_150: per-150-game pace
    csaa: called-strikes-above-average rate (% of takes)
    z_score: (framing_runs_per_150 - league_mean) / league_stddev
    """

def get_all_catcher_framing(season: int) -> dict[int, dict]:
    """Return dict keyed by MLBAM catcher_id with entries as above.
    One-shot pull for the daily_runner warm-up."""
```

**Source:** Baseball Savant catcher-framing leaderboard. Public CSV endpoint:

```
https://baseballsavant.mlb.com/leaderboard/catcher-framing?year={season}&min=q&csv=true
```

Columns include `player_id, player_name, framing_runs, runs_extra_strikes, n_called_pitches, strike_rate`. Compute `framing_runs_per_150` as `framing_runs * (150 / games_caught)` where `games_caught = innings_caught / 9` (approximation).

Z-score: compute league mean and stddev over all catchers with `n_called_pitches >= 1000` in the pulled DataFrame. Cached alongside the per-catcher rows.

**Cache:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/catcher_framing_cache.json`, single file keyed by `{season}_{catcher_id}`, TTL 24h. Includes a `_meta` entry with league mean/stddev.

**Wire-up:** `agents/daily_runner.py` reads `scrapers/lineups.py` (`/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/lineups.py:32-56`) for each team's lineup, filters to `position == "C"`, picks the first entry. That player ID goes into `get_catcher_framing`. The resulting `z_score` becomes `catcher_framing_z` passed to `sample_pa` when the OTHER team is batting (catchers frame pitches for their own pitchers, so Team A's catcher modifies Team B's PAs).

**Fallback:**

- Catcher not resolved (lineup not posted) → use team's most-used catcher from prior 14 days via `player_stats.get_batter_stats` + position filter. If still unresolved, `z_score = 0.0`.
- Endpoint down → cache-or-fixture: ship `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/catcher_framing_fixture.json` frozen 2026-04-01.
- `SOURCES_ENABLED["catcher"] = False` → `z_score = 0.0`, brief shows "N/A".

---

### 3.4 Depth Charts anchor projection

**Extension:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/player_stats.py` (add new functions after line 265).

**Public API:**

```python
def get_depth_charts_hitter(player_id: int, season: int) -> dict:
    """FanGraphs Depth Charts projected hitter line.

    Keys: pa, wOBA, ISO, k_pct, bb_pct, games, updated_at
    Fallback: all None.
    """

def get_depth_charts_pitcher(player_id: int, season: int) -> dict:
    """FanGraphs Depth Charts projected pitcher line.

    Keys: ip, FIP, ERA, k_pct, bb_pct, starts, updated_at
    """

def prewarm_depth_charts(season: int) -> None:
    """One-shot pull called at daily_runner start — refreshes the
    leaderboard cache. Idempotent, cheap if cache fresh."""
```

**Source:** `pybaseball.projection_hitter_fangraphs_depth()` and `pybaseball.projection_pitcher_fangraphs_depth()`. If those exact names don't exist in the installed pybaseball (verify at implementation time; the API has churned), fall back to the URL `https://www.fangraphs.com/projections.aspx?type=fangraphsdc&stats={bat|pit}&pos=all&team=0&lg=all&season={season}` with `requests` + HTML table parse. Prefer pybaseball to avoid brittle HTML scraping.

**Cache:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/depth_charts_cache/<season>/leaderboard_{hitters|pitchers}.json`. TTL 24h. One file per side because Depth Charts is a full-league table, not per-player. Per-player lookups read from the cached DataFrame.

**Briefing behavior:** `build_briefing` renders projections side-by-side with 14-day and 30-day actuals:

```
FERNANDO TATIS JR. (SD) — .312/.389/.556 (14d) / .288/.361/.520 (30d)
  Depth Charts proj: .275/.350/.495, 610 PA, wOBA .367, 20.8% K, 9.2% BB
```

The prediction-task block adds:

```
Depth Charts projections are PRIORS (true talent regressed to the mean).
14-day and 30-day actuals are NOISY EVIDENCE. Weight accordingly:
- 14-day hitting stats have ~0.3 correlation with true talent
- Depth Charts projections have ~0.6 correlation with rest-of-season performance
```

**Fallback:** all-`None` dict. Briefing shows "projection unavailable" line.

---

### 3.5 Air-density / carry weather model

**Extension:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/ballpark.py` (add after line 91).

**Public API:**

```python
def compute_carry_multiplier(
    temp_f: float,
    pressure_mb: float,
    humidity_pct: float,
    wind_mph: float,
    wind_dir: str,               # 'out' | 'in' | 'cross' | 'calm'
    roof_status: str,            # 'open' | 'closed' | 'retractable'
    elevation_ft: float = 0.0,
) -> dict:
    """Return {hr_multiplier, xbh_multiplier, batted_ball_distance_ft, reason}.

    Physics: drag on a struck ball scales with air density ρ.
    ρ = (P_d / (R_d * T)) + (P_v / (R_v * T))
    where P_d is dry pressure, P_v is vapor pressure, R_d=287.05, R_v=461.495.

    Empirical lever (Alan Nathan):
    - +10°F on fly-ball carry: ~+3 ft distance, ~+2.5% HR rate
    - +1000 ft elevation: ~+6 ft distance, ~+6% HR rate (Coors effect)
    - Wind out at 10 mph: ~+4 ft carry
    - Wind in at 10 mph: ~-4 ft carry
    - Closed roof: hr_multiplier = 1.0 (no wind/temp)
    """
```

**Algorithm sketch:**

```
if roof_status == 'closed':
    return {hr_multiplier: 1.0, xbh_multiplier: 1.0, batted_ball_distance_ft: 0.0, reason: 'dome'}

if roof_status == 'retractable':
    roof_status = _check_retractable_roof(team_abbrev, game_time)  # -> 'open' or 'closed'
    if roof_status == 'closed':
        return ...neutral

# Air density relative to 72°F, 1013 mb, 50% humidity baseline
rho = _air_density_kg_m3(temp_f, pressure_mb, humidity_pct)
rho_baseline = 1.197  # kg/m³ at baseline
density_delta_pct = (rho_baseline - rho) / rho_baseline  # + = lighter air = more carry

# Distance delta (ft) — empirical linear combine
dist_delta = (
    (temp_f - 72) * 0.3          # +3 ft per +10°F
    + elevation_ft / 1000 * 6.0  # +6 ft per 1000 ft elev
    + (humidity_pct - 50) * 0.02 # +1 ft per 50% humidity bump (small, via density)
    + _wind_ft_delta(wind_mph, wind_dir)
)

# HR multiplier — roughly +2.5% per +3 ft of carry near the fence
hr_mult = 1.0 + (dist_delta / 3.0) * 0.025
xbh_mult = 1.0 + (dist_delta / 3.0) * 0.010  # smaller for doubles/triples

return {
    'hr_multiplier': round(hr_mult, 3),
    'xbh_multiplier': round(xbh_mult, 3),
    'batted_ball_distance_ft': round(dist_delta, 1),
    'reason': f'{temp_f}°F, wind {wind_mph}mph {wind_dir}, roof {roof_status}',
}
```

**Retractable roof check:** `_check_retractable_roof(team, game_time)` — short-circuit based on team + forecast rain. Not live-game. Acceptable heuristic: if forecast precip > 40% in hour of first pitch → assume closed, else assume open. MLB doesn't publish roof status in advance on a public feed we can reliably consume. Document this as known imprecision.

**Integration with Spec 3 handedness park factors:**

```python
# Spec 3 provides park_hr_for(team, bat_hand) -> float
# This spec applies carry on top:
effective_hr_factor = park_hr_for(team, bat_hand) * carry['hr_multiplier']
effective_runs_factor = park_runs_for(team, bat_hand) * carry['xbh_multiplier']
```

`game_data['environment']['carry'] = carry_dict` surfaced in briefing.

**Fallback:** weather-API failure → neutral carry (all 1.0). Document that briefing will show "carry: neutral (weather unavailable)".

**Weather data needed:** current OpenWeather call at `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/ballpark.py:30-56` returns `temp_f, humidity, wind_mph, wind_direction`. We need `pressure_mb` added — `data["main"]["pressure"]` in the OpenWeather response (already present, just not extracted). Add that field at line 50.

---

### 3.6 Briefing enrichment

**Extension:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/briefing.py`

**New sections appended after existing "== INJURIES ==" block (current line 125), before `{prediction_task}` (line 127):**

```
== PITCH QUALITY ==
{away_pitcher.name}: Stuff+ 112 (84th%ile, stable) | Location+ 98 (42nd%ile, stable)
  Pitching+ 108 (72nd%ile) | PitchingBot: Stf 58 Cmd 51 Ovr 55
  xERA 3.12 (stable) | xFIP 3.45 | xwOBA .298 | Barrel%-against 7.1% | HardHit%-against 36.4%
  CSW 29.8% | K% 27.3% | BB% 7.1%
{home_pitcher.name}: [same template]

== HITTER PROFILES ==        (top 4 of each lineup, to cap context size)
{away_top4_lineup}:
  1. Ronald Acuña Jr.: xwOBA .412 (stable) | Barrel% 14.2% | HardHit% 54% | Bat speed 76.1mph (elite)
     Depth Charts: .298/.380/.540, 640 PA, wOBA .387
  [...]
{home_top4_lineup}: [same template]

== HOME PLATE UMPIRE ==
{ump_name} (games: 3,412, games sample large)
  K% delta: -0.8pp (pitcher-unfriendly)
  BB% delta: +0.6pp (pitcher-unfriendly)
  Runs/game delta: +0.42 (slight over lean)
  Consistency: 91.2% | Accuracy: 93.5% | Consecutive games: 12

== CATCHER FRAMING ==
{away} starting C: Adley Rutschman — framing runs/150: +14.2 (z=+1.8, elite)
{home} starting C: Patrick Bailey — framing runs/150: +18.7 (z=+2.3, elite)

== CARRY CONDITIONS ==
Carry multiplier: HR 1.041 | XBH 1.016 | Batted-ball dist +4.9 ft
Reason: 82°F, wind 9mph out, roof open, pressure 1015mb
Applied on top of handedness-split park factors from Spec 3.
```

**Reliability tag placement:** inline after each stat where sample size matters. Driven by helper:

```python
def _tag(sample_size: int, threshold: int) -> str:
    if sample_size is None:
        return "(unavailable)"
    if sample_size >= threshold:
        return "(stable)"
    return f"(small sample: {sample_size})"
```

**Prediction-task additions** (append to existing block at `/Users/mikeborucki/personal_workspace/agents/baseball-agents/briefing.py:56-72`):

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

**Pruning for context size:** briefing grows by ~30 lines. To protect 8k-context models in the ensemble:
- Limit `== HITTER PROFILES ==` to top 4 hitters per side (by lineup slot 1-4). Bench/9-hole are briefed as aggregate line: `"5-9 holes: avg xwOBA .308, avg Barrel% 6.8%"`.
- Limit bullpen briefing (unchanged from current, `briefing.py:116-121`) to closer + top 2 relievers by recent leverage.

**Concrete sample (before vs. after):** see §5.

---

### 3.7 Wire catcher framing into PA sim

**Extension:** `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/pa_engine.py:77-89`

Spec 3 added `catcher_framing_z: float = 0.0` as a forward-compat kwarg. This spec makes it functional.

**New signature:**

```python
def sample_pa(
    batter: dict, pitcher: dict,
    park_factor_runs: float = 1.0, park_factor_hr: float = 1.0,
    catcher_framing_z: float = 0.0,
    umpire_k_delta: float = 0.0,   # pp shift, e.g. -0.8 for pitcher-unfriendly ump
    umpire_bb_delta: float = 0.0,
) -> str:
```

**Implementation inside `_build_matchup_probs` (currently `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/pa_engine.py:46-74`):**

```python
# Framing shifts the pitcher's effective K and BB rates before log5.
# Empirical: z=+1.0 ≈ +0.6pp K, -0.4pp BB. Linear clip at z=±3.
framing_k_shift = 0.006 * max(-3.0, min(3.0, catcher_framing_z))
framing_bb_shift = -0.004 * max(-3.0, min(3.0, catcher_framing_z))

pitcher_k = pitcher.get('k_pct', LEAGUE_AVERAGES['k_pct']) + framing_k_shift
pitcher_bb = pitcher.get('bb_pct', LEAGUE_AVERAGES['bb_pct']) + framing_bb_shift

# Umpire K/BB deltas on top of framing. Deltas are in percentage points.
pitcher_k += umpire_k_delta / 100.0
pitcher_bb += umpire_bb_delta / 100.0

# Clip to (0, 1) to avoid log5 blowup
pitcher_k = max(0.01, min(0.95, pitcher_k))
pitcher_bb = max(0.01, min(0.95, pitcher_bb))
```

The shifted `pitcher_k` and `pitcher_bb` replace the `p_rate` inputs for the `"K"` and `"BB"` outcomes in the existing loop at `pa_engine.py:61-65`.

**Important:** framing z applies only when that catcher's team is pitching. The `monte_carlo` driver in `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/monte_carlo.py` selects the correct team's catcher z when setting up each half-inning.

### 3.8 Wire umpire K/BB deltas into PA sim

Covered by 3.7 — the same `sample_pa` signature accepts `umpire_k_delta` and `umpire_bb_delta`. Typical values from UmpScorecards: ±1.5pp K, ±1.0pp BB, both applied to both teams' pitchers for the full game. `game_sim.py` passes them unchanged each half-inning.

---

## 4. Data Sources Table

| Source | URL | License / Terms | Rate Limit | Cache | Staleness |
| --- | --- | --- | --- | --- | --- |
| FanGraphs leaderboards (via pybaseball) | `fangraphs.com/leaders` | Public web, pybaseball user agent. No API key. Be polite. | ≤ 1 call per 3s per table | `data/statcast_cache/<season>/_leaderboard_*.json`, 24h | 24h ok — updates daily ~6am ET |
| Baseball Savant bat tracking | `baseballsavant.mlb.com/leaderboard/bat-tracking?csv=true` | MLB public data | 1 call / 5s | `data/statcast_cache/<season>/_leaderboard_*.json`, 24h | 24h |
| Baseball Savant expected stats | `baseballsavant.mlb.com/leaderboard/expected_statistics?csv=true` | MLB public | 1 call / 5s | same | 24h |
| Baseball Savant catcher framing | `baseballsavant.mlb.com/leaderboard/catcher-framing?csv=true` | MLB public | 1 call / 5s | `data/catcher_framing_cache.json`, 24h | 24h |
| UmpScorecards | `umpscorecards.com/single_umpire/?id={id}&format=csv` | Unofficial public scraper target. **Ship with fixture fallback.** | 1 call / 2s, ≤ 20 calls / run | `data/umpire_cache.json`, 24h | 24h |
| MLB StatsAPI officials | `statsapi.mlb.com/api/v1/game/{pk}/boxscore` | Free public API | No hard limit published; be polite (~1/s) | No cache — called once per game per run | Same-day (umps assigned 2-4h before game) |
| FanGraphs Depth Charts (via pybaseball) | `fangraphs.com/projections.aspx?type=fangraphsdc` | Public web | 1 call / 3s | `data/depth_charts_cache/<season>/`, 24h | 24h — FG updates DC intraday |
| OpenWeather (existing) | `api.openweathermap.org/data/2.5/weather` | API key | 60/min free tier | No cache — fetched per-game | 1 hour |

---

## 5. Briefing Before/After

**Before (current output, trimmed for space):**

```
MLB GAME PREDICTION ANALYSIS
==============================
LAD (14-8) at SF (10-12)
Oracle Park | night
Weather: 62°F, Wind 12mph in | Park Factor: 0.85

BETTING LINES:
  Moneyline: SF +140 / LAD -160
  Run Line: SF +1.5 (-115) / LAD -1.5 (-105)
  Total: 7.5 (Over -108 / Under -112)
  Implied Win Prob: SF 41.7% / LAD 61.5%

== STARTING PITCHING MATCHUP ==
Yoshinobu Yamamoto (LAD) — 3-1, 2.85 ERA
  FIP: 3.02 | xFIP: 3.41 | WHIP: 1.05
  K/9: 10.4 | BB/9: 2.8 | HR/9: 0.8
  Days Rest: 5
  Last 5 Starts: [...]

Logan Webb (SF) — 2-2, 3.12 ERA
  [same template]

== BULLPEN STATE ==
LAD Bullpen: rested
  Closer: Evan Phillips
SF Bullpen: mixed
  Closer: Camilo Doval

== INJURIES ==
LAD: Mookie Betts (DTD)
SF: Jung Hoo Lee (IL-10)

== PREDICTION TASK ==
[1-7 questions]
```

**After (new sections inserted before PREDICTION TASK):**

```
[all previous sections unchanged]

== PITCH QUALITY ==
Yoshinobu Yamamoto: Stuff+ 118 (92nd%ile, stable) | Location+ 103 (61st%ile, stable)
  Pitching+ 112 (84th%ile) | PitchingBot: Stf 62 Cmd 54 Ovr 59
  xERA 2.94 (stable) | xFIP 3.18 | xwOBA .278 | Barrel%-against 5.8% | HardHit%-against 32.1%
  CSW 31.4% | K% 28.8% | BB% 6.5%

Logan Webb: Stuff+ 99 (42nd%ile, stable) | Location+ 114 (88th%ile, stable)
  Pitching+ 108 (72nd%ile) | PitchingBot: Stf 49 Cmd 58 Ovr 53
  xERA 3.28 (stable) | xFIP 3.35 | xwOBA .304 | Barrel%-against 6.9% | HardHit%-against 38.4%
  CSW 28.1% | K% 22.6% | BB% 5.2%

== HITTER PROFILES ==
LAD (top 4):
  1. Shohei Ohtani: xwOBA .421 (stable) | Barrel% 16.8% | HardHit% 56.2% | Bat speed 78.3mph (elite)
     Depth Charts: .289/.388/.578, 640 PA, wOBA .398
  2. Freddie Freeman: xwOBA .378 (stable) | Barrel% 10.1% | HardHit% 48.9% | Bat speed 72.1mph
     Depth Charts: .302/.385/.515, 600 PA, wOBA .378
  3. Will Smith: xwOBA .354 (stable) | Barrel% 9.4% | HardHit% 42.1% | Bat speed 70.8mph
     Depth Charts: .270/.354/.465, 500 PA, wOBA .355
  4. Teoscar Hernandez: xwOBA .361 (stable) | Barrel% 12.3% | HardHit% 47.1% | Bat speed 74.2mph
     Depth Charts: .268/.326/.495, 580 PA, wOBA .351
  5-9 holes: avg xwOBA .312, avg Barrel% 7.1%

SF (top 4):
  [same template]

== HOME PLATE UMPIRE ==
Angel Hernandez (games: 3,412, stable)
  K% delta: -0.8pp (pitcher-unfriendly)
  BB% delta: +0.6pp (pitcher-unfriendly)
  Runs/game delta: +0.42 (slight over lean)
  Consistency: 91.2% | Accuracy: 93.5% | Consecutive games: 12

== CATCHER FRAMING ==
LAD starting C: Will Smith — framing runs/150: +6.8 (z=+0.9, above avg)
SF starting C: Patrick Bailey — framing runs/150: +18.7 (z=+2.3, elite)

== CARRY CONDITIONS ==
Carry multiplier: HR 0.962 | XBH 0.984 | Batted-ball dist -4.5 ft
Reason: 62°F, wind 12mph in, roof open, pressure 1018mb
Applied on top of handedness-split park factors from Spec 3.
Oracle Park marine-layer suppression confirmed.

== PREDICTION TASK ==
[1-12 questions now — questions 8-12 added per §3.6]
```

Delta: ~+30 lines, ~+1,400 chars. Well under OpenRouter's 8k-context floor and completely fine for Kimi/GPT-4o/Claude 4.7.

---

## 6. Migration

Three migration tasks, sequenced in `agents/daily_runner.py` startup:

1. **Pre-warm Statcast cache for active rosters** (one-shot, idempotent):
   - At daily_runner start, if `data/statcast_cache/<season>/_leaderboard_pitchers.json` mtime > 24h ago, fetch full FanGraphs `pitching_stats(season, qual=0)` and `batting_stats(season, qual=0)`. Savant bat tracking leaderboard and catcher-framing leaderboard pulled in same pass.
   - Cost: 4 HTTP calls, ~12 seconds. One-time per day.
   - Logged as `INFO mirofish.statcast: pre-warmed leaderboards (N pitchers, M batters)`.

2. **Backfill 30 days of umpire data**:
   - Migration script: `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scripts/backfill_umpire_cache.py`
   - For each date in last 30 days, pull MLB schedule, for each game pull boxscore, extract HP ump, call `get_umpire_profile(ump_id)`. Populate `umpire_cache.json` and record ump-to-game mapping in `data/umpire_history.json` (useful for Spec 1 CLV attribution).
   - Run once at deploy time. Rate-limited per §4. Estimated 30 days × 15 games × 1 ump = 450 games, ~150 unique umps. At 2s per new-ump lookup: ~5 minutes.
   - Re-run nightly at 03:00 ET via cron to keep cache warm and to catch ump-assignment changes made after game start.

3. **One-shot Depth Charts pull at daily_runner start**:
   - `prewarm_depth_charts(current_season)` called from `agents/daily_runner.py` right after env setup, before per-game loop. Idempotent: checks cache mtime first.
   - Cost: 2 HTTP calls (hitters + pitchers), ~8 seconds.

Migration order at daily_runner start (executed sequentially; concurrent per-source is fine but briefing depends on all):
1. `prewarm_depth_charts`
2. Statcast leaderboard warm
3. Catcher framing leaderboard warm
4. Per-game enrichment (statcast, umpire, framing) inside existing parallel game loop

---

## 7. Testing

All scrapers must be network-mockable. Existing pattern in `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/` uses `unittest.mock.patch` on `requests.get`. Follow that. Add fixtures under `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/fixtures/` (create if missing).

### 7.1 Unit tests per scraper

**`tests/test_statcast_advanced.py`** — NEW
- `test_get_pitcher_advanced_from_fixture`: patch pybaseball to return a DataFrame fixture, assert returned dict has all keys with correct types.
- `test_get_pitcher_advanced_missing_player`: player not in leaderboard → returns all-None dict (not exception).
- `test_get_batter_advanced_bat_speed_cross_source`: assert bat_speed from Savant bat tracking fixture matches expected value.
- `test_cache_ttl_honored`: first call hits network, second call reads cache, patch `time.time` to +25h and verify refetch.
- `test_sources_enabled_false_short_circuits`: `SOURCES_ENABLED["statcast"] = False` → return `{}` with zero network calls (assert mock not called).

**`tests/test_umpire.py`** — NEW
- `test_get_assignment_parses_officials_array`: fixture JSON for `/game/{pk}/boxscore`, assert HP ump extracted.
- `test_get_assignment_missing_officials_returns_none`: empty officials array → None.
- `test_get_profile_from_csv`: fixture UmpScorecards CSV, assert all delta fields parsed.
- `test_get_profile_fallback_to_fixture_file`: mock 500 response → reads `umpire_fixture.json`.
- `test_rate_limit_sleep`: patch `time.sleep`, assert called between 2 ump profile calls.

**`tests/test_catcher_framing.py`** — NEW
- `test_leaderboard_parse`: fixture CSV of Savant framing leaderboard, assert z-score computed correctly.
- `test_catcher_not_found_zero_z`: unknown catcher_id → z_score = 0.0.

**`tests/test_depth_charts.py`** — NEW
- `test_hitter_projection_parse`: fixture DataFrame, assert dict shape.
- `test_prewarm_idempotent`: call twice, network called only once.

**`tests/test_carry_multiplier.py`** — NEW
- `test_closed_dome_neutral`: roof='closed' → all multipliers 1.0.
- `test_cold_windy_against_suppresses_hr`: 55°F, wind 15mph in → hr_multiplier < 0.95.
- `test_hot_high_altitude_boosts`: 85°F, Denver elevation → hr_multiplier > 1.10.
- `test_air_density_formula`: assert `_air_density_kg_m3(72, 1013, 50) ≈ 1.197` (baseline).

### 7.2 PA-sim integration tests

**`tests/test_pa_engine.py`** — EXTEND existing file
- `test_sample_pa_umpire_k_delta_shifts_k_rate`: run 50,000 PAs with `umpire_k_delta=-1.5` vs 0.0, assert observed K rate drops by ~1.5pp (±0.3pp tolerance).
- `test_sample_pa_framing_z_positive_boosts_k`: run 50,000 PAs with `catcher_framing_z=+2.0` vs 0.0, assert observed K rate rises by ~1.2pp (from `0.006 * 2 = 0.012 = 1.2pp`).
- `test_sample_pa_framing_z_clipped`: `catcher_framing_z=+10.0` clipped to +3.0; K shift = 1.8pp, not 6pp.
- `test_sample_pa_backward_compat`: calling without new kwargs produces identical distribution to current (seeded random).

### 7.3 Briefing snapshot tests

**`tests/test_briefing.py`** — NEW (no briefing test file exists today — snapshot pattern is new)
- `test_briefing_with_all_sources_matches_snapshot`: golden file `tests/fixtures/briefing_full.txt`. Fail if output diverges character-for-character.
- `test_briefing_statcast_disabled_shows_na`: `SOURCES_ENABLED["statcast"] = False` → new sections render "N/A".
- `test_briefing_ump_tbd`: ump_id=None → "Home Plate Ump: TBD" + neutral deltas.
- `test_briefing_respects_top_4_hitter_cap`: lineup of 9 → exactly 4 detailed hitter blocks + "5-9 holes" aggregate.

### 7.4 End-to-end smoke test

**`tests/test_daily_runner_smoke.py`** — EXTEND if exists, NEW otherwise
- `test_daily_runner_survives_all_sources_disabled`: set `SOURCES_ENABLED` to all-False, assert pipeline completes and produces a briefing + prediction.
- `test_daily_runner_survives_umpscorecards_500`: patch umpire scraper to raise, assert neutral ump profile surfaced, pipeline completes.

### 7.5 Regression

Existing tests in `tests/test_game_sim.py`, `tests/test_pa_engine.py`, `tests/test_ensemble_runner.py` must continue passing unchanged. Any new kwarg on `sample_pa` defaults to 0.0/neutral so Spec 1/2/3 callers are unaffected.

---

## 8. Rollout

### 8.1 Feature flag

Single top-level flag gates the whole spec: `DATA_V2_ENABLED` in `config.py`. Default: `False` until migration + tests are green on `main`.

```python
# config.py (additions)
DATA_V2_ENABLED = os.getenv("DATA_V2_ENABLED", "false").lower() == "true"

SOURCES_ENABLED = {
    "statcast":     os.getenv("SRC_STATCAST",     "true").lower() == "true",
    "umpire":       os.getenv("SRC_UMPIRE",       "true").lower() == "true",
    "catcher":      os.getenv("SRC_CATCHER",      "true").lower() == "true",
    "depth_charts": os.getenv("SRC_DEPTH_CHARTS", "true").lower() == "true",
    "carry":        os.getenv("SRC_CARRY",        "true").lower() == "true",
}
```

When `DATA_V2_ENABLED = False`: briefing falls back to Spec 3 layout exactly (no new sections); PA sim ignores `catcher_framing_z`/`umpire_*_delta` kwargs (defaults already 0.0 so behavior is already unchanged).

When `DATA_V2_ENABLED = True`: per-source flags toggle individual sections. A broken UmpScorecards page can be isolated with `SRC_UMPIRE=false` without losing Statcast, framing, depth charts, or carry.

### 8.2 Rollout schedule

1. **Day 0:** merge to `main` with `DATA_V2_ENABLED=false`. All tests green. Old briefings unchanged.
2. **Day 1-2:** enable per-source in dev env via env vars; verify scrapers against live endpoints for 3 slates. Watch log for fallback triggers.
3. **Day 3:** flip `DATA_V2_ENABLED=true` in prod, all sources enabled, for one slate. Compare briefing char count distribution (before: ~3500, after: ~5000). Ensure ensemble calls succeed.
4. **Day 4-7:** monitor CLV (Spec 1). If CLV degrades ≥ 0.3pp or ensemble-consensus rate drops ≥ 5%, roll back via env var, triage which source introduced noise.
5. **Day 14:** lock in. Remove `DATA_V2_ENABLED` gate; per-source flags remain for ongoing ops.

### 8.3 Observability

- Log `INFO mirofish.<source>: fetched N records (cache hit=True/False)` on every call.
- Log `WARN mirofish.<source>: fallback triggered (reason=...)` on error path.
- Expose counters through existing `coral_scraper.log` rotation.
- Daily summary line printed by daily_runner: `Spec4 sources: statcast=ok ump=fallback catcher=ok dc=ok carry=ok`.

---

## 9. Risks

### 9.1 UmpScorecards scraping fragility

**Risk:** UmpScorecards is a community-maintained site with no SLA. HTML structure changes have historically broken scrapers within a single game day. Spec-breaking failure here means every briefing shows "TBD" for ump.

**Mitigation:**
- Ship frozen snapshot `data/umpire_fixture.json` covering top 80 umps (80%+ of HP assignments) as of spec-merge date. On 5xx or parse error, fall back to fixture. Fixture stale but non-blocking.
- Prefer the CSV query parameter over HTML scrape — CSV has been stable for 18+ months.
- Monitor for `umpscorecards.com` 4xx/5xx spikes; alert if > 30% fallback rate over 24h.
- Long-term: consider mirroring UmpScorecards data to our own weekly snapshot. Out of scope for this spec.

### 9.2 Depth Charts playing-time lag

**Risk:** FanGraphs Depth Charts projects based on expected playing time. When a regular goes on the IL but DC hasn't refreshed (can lag 6-12 hours), the projection for the IL'd player is still shown and the replacement is under-projected.

**Mitigation:**
- Always override DC player list with confirmed lineup from `scrapers/lineups.py` when available (`/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/lineups.py:32-56`).
- If a projected starter is missing from confirmed lineup: mark "DC projection based on {name}, confirmed starter is {other}, projection may be stale".
- Cross-reference against `scrapers/news.py` injury tags — if a player appears in the injury block, suppress their DC line.

### 9.3 Briefing context explosion

**Risk:** 5 new sections × ~6 lines each = ~30 new lines ≈ 1,400 chars ≈ 350 tokens. Plus reliability tags and expanded prediction-task block. Models with 8k context (some OpenRouter offerings) may start to strain once we add lineup advanced stats × 9 players × 2 teams.

**Mitigation:**
- Hard cap: top-4 hitters per side (§3.6), bench rendered as single aggregate line. Saves ~10 × 2 = 20 lines.
- Bullpen pre-existing cap of closer + top 2 relievers unchanged.
- Token counter logged per briefing; alert if > 6k tokens.
- Consider Phase 2: per-model briefing tailoring (drop reliability tags for 200k-context Claude, keep them for 32k-context Kimi).

### 9.4 Statcast stat sample-size conflation

**Risk:** Barrel% stabilizes at ~50 BBE. Stuff+ at ~500 pitches. xwOBA at ~300 PA. Bat speed at ~50 swings. An LLM seeing all of them without context will weight them uniformly and over-react to a 30-BBE barrel% spike.

**Mitigation:**
- Explicit `(stable)` vs `(small sample: <N>)` tag per stat (§3.1 table + §3.6 `_tag` helper).
- Prediction-task item 8 (§3.6) explicitly tells the LLM to discount small samples.
- Calibration (Spec 1) will quantify whether the discount is actually applied. Monitor post-rollout CLV per bet type.

### 9.5 Air density model over-fitting

**Risk:** Alan Nathan's +3 ft / +10°F coefficient is a population estimate. A hitter with a 25° attack angle gets more carry boost than one with a 10° launch profile. Our model treats all batted balls equally.

**Mitigation:**
- Accept the approximation for now. Per-batter bat-tracking-aware carry is Phase 2.
- Validate against historical: rerun 2025 season with new carry multiplier, check HR rate correlation with predicted vs baseline.

### 9.6 Retractable roof uncertainty

**Risk:** Seven parks have retractable roofs (ARI, HOU, MIA, MIL, SEA, TEX, TOR). Status at first pitch is a game-time call by the home team. No public pre-game feed is reliable.

**Mitigation:**
- Heuristic: forecast precip > 40% → assume closed. Else open.
- Brief explicitly states "roof: projected open/closed" so LLM can hedge.
- On game-day post-mortem (Spec 1 grader), record actual roof status from post-game boxscore for future calibration.

### 9.7 Cache concurrency

**Risk:** Parallel game processing (`config.PARALLEL_GAMES = 4`) with in-process `threading.Lock` misses concurrent writes when daily_runner is invoked twice (rare but happens during manual re-runs).

**Mitigation:** `filelock.FileLock` on every cache write as specified in §3.1. Already used for player_map in `scrapers/player_stats.py:13` precedent — extend pattern to new caches.

### 9.8 pybaseball API churn

**Risk:** pybaseball function signatures change between versions. `projection_hitter_fangraphs_depth` may not exist by that name.

**Mitigation:**
- Pin `pybaseball>=2.2.7,<3.0` in `requirements.txt`.
- Implementation-phase spike: `python -c "import pybaseball; print([f for f in dir(pybaseball) if 'depth' in f.lower() or 'project' in f.lower()])"` before writing the call.
- Fallback to direct HTML scrape of `fangraphs.com/projections.aspx` if pybaseball function is absent.

---

## 10. Out of Scope / Future Work

- Pitch-tunnel overlap & sequencing (requires pitch-by-pitch Savant data and a custom model)
- Catcher blocking, pop-time, arm strength (expand beyond framing)
- Full batter-vs-pitcher (BvP) matchup splits at pitch-type level
- Manager hook tendencies (pull decisions based on TBF / runs allowed)
- Real-time in-game strike-zone monitoring for live-game bet refresh
- Incorporating Stuff+ deltas game-over-game (fatigue signal)
- Weather radar integration for rain-delay probability

---

## 11. Dependencies on Prior Specs

- **Spec 1 (calibration + CLV):** post-rollout monitoring uses Spec 1's CLV tracker to detect regressions per §8.2 step 4.
- **Spec 2 (betting-layer hardening):** none direct, but shared config and logging patterns.
- **Spec 3 (handedness-aware simulation):** this spec multiplies handedness-split park factors by the carry multiplier (§3.5 integration block) and flips on the `catcher_framing_z` forward-compat hook Spec 3 introduced in `sample_pa`.

---

## 12. Appendix: New files / modified files summary

**New files:**
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/statcast_advanced.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/umpire.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/catcher_framing.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scripts/backfill_umpire_cache.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/umpire_fixture.json` (frozen snapshot, committed)
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/data/catcher_framing_fixture.json` (frozen snapshot, committed)
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_statcast_advanced.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_umpire.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_catcher_framing.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_depth_charts.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_carry_multiplier.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/test_briefing.py`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/tests/fixtures/` (new dir for all HTML/JSON/CSV fixtures)

**Modified files:**
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/briefing.py` — add 5 new sections, reliability tag helper, top-4 hitter cap, expanded prediction-task block
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/ballpark.py` — add `compute_carry_multiplier`, extract `pressure_mb` from OpenWeather response
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/scrapers/player_stats.py` — add `get_depth_charts_hitter`, `get_depth_charts_pitcher`, `prewarm_depth_charts`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/pa_engine.py` — wire `catcher_framing_z`, `umpire_k_delta`, `umpire_bb_delta` into `_build_matchup_probs`
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/game_sim.py` — propagate catcher z + ump deltas per half-inning
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/simulation/monte_carlo.py` — thread catcher z + ump deltas through sim setup
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/agents/daily_runner.py` — call migration warmers on startup; enrich `game_data` with new scraper outputs
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/config.py` — `DATA_V2_ENABLED`, `SOURCES_ENABLED`, optional elevation constants per park
- `/Users/mikeborucki/personal_workspace/agents/baseball-agents/requirements.txt` — add `filelock>=3.12`, pin `pybaseball>=2.2.7,<3.0`

**Estimated LoC added:** ~1,800 (scrapers ~900, tests ~600, briefing ~150, sim wiring ~80, config/migration ~70).

**Estimated LoC modified:** ~200.

---

## 13. Open Questions

1. **UmpScorecards CSV format stability** — confirm at implementation time that `?format=csv` on the single-umpire page still returns CSV and not HTML. If changed, prefer their undocumented JSON API or scrape HTML with BeautifulSoup.
2. **Bat speed sample threshold** — Savant lists ~250 "competitive swings" as their qual bar; we're using 50 for reliability tag. Validate against CLV post-rollout; may need to raise.
3. **Umpire rotation prediction** — do we ship the crew-rotation fallback this spec or phase it in? Recommendation: phase in. Spec 4 ships with "TBD" only; a separate Spec 4b adds rotation prediction once we have 3 months of historical assignment data.
4. **Park elevation constants** — need to add `PARK_ELEVATIONS` dict to `config.py`. Coors at 5,200 ft; all other parks under 1,100 ft. Table is static, commit as part of this spec.
5. **Briefing reliability-tag verbosity** — should the tag appear on every stat or only when sample is small? Recommendation: only flag `(small sample)` and `(unavailable)`; stable is the default and needs no marker.
6. **Carry multiplier application timing** — apply in PA engine (per-at-bat HR probability boost) or only in briefing (LLM reads and reasons)? Recommendation: apply in briefing only for this spec; PA-engine carry integration is Phase 2 once Spec 1 CLV confirms the LLM pathway is profitable.
