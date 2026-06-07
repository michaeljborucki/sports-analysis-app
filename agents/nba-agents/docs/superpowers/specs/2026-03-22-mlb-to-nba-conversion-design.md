# MLB-to-NBA Pipeline Conversion — Design Spec

## Overview

Convert the MiroFish prediction pipeline from MLB baseball to NBA basketball. The architecture (SCRAPE > BRIEFING > SCREEN > ENSEMBLE > EDGE > BET) is preserved. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and transfer with minimal changes. The sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) are rebuilt for NBA.

All MLB-specific code, terminology, and references are removed from the codebase.

## Data Source

**`nba_api`** (swar/nba_api) — Python wrapper for NBA.com endpoints. Free, no API key needed. Replaces `pybaseball` and the MLB Stats API.

Odds continue to come from The Odds API with sport key `basketball_nba`.

---

## 1. Files to Delete (MLB-Only)

These files have no NBA equivalent and are removed entirely, along with their tests:

| File | Reason |
|------|--------|
| `scrapers/pitchers.py` | No pitcher concept in NBA |
| `scrapers/bullpen.py` | No bullpen concept in NBA |
| `scrapers/ballpark.py` | No park factors / weather in indoor NBA |
| `scrapers/lineups.py` | Replaced by `nba_api` schedule/roster data |
| `scrapers/news.py` | Replaced by `scrapers/injuries.py` |
| `tests/test_pitchers.py` | |
| `tests/test_bullpen.py` | |
| `tests/test_ballpark.py` | |
| `tests/test_lineups.py` | |
| `tests/test_news.py` | |

---

## 2. New Scrapers to Create

### 2a. `scrapers/schedule.py` — Daily Schedule

- **Source**: `nba_api.stats.endpoints.ScoreboardV3` or `leaguegamefinder.LeagueGameFinder`
- **Function**: `get_todays_games(game_date: str = None) -> list[dict]`
- **Returns** per game:
  ```python
  {
      "game_id": str,
      "home_team": "BOS",  # abbreviation
      "away_team": "LAL",
      "game_time": "7:30 PM ET",
      "arena": "TD Garden",
      "home_team_id": int,
      "away_team_id": int,
  }
  ```
- Uses `TEAM_NAME_TO_ABBREV` from config to normalize team names.

### 2b. `scrapers/team_stats.py` — Team Season Stats (Rewrite)

- **Source**: `nba_api.stats.endpoints.LeagueDashTeamStats`, `TeamDashboardByGeneralSplits`
- **Function**: `get_team_profile(team_abbrev: str, season: str = None) -> dict`
- **Returns**:
  ```python
  {
      "record": "45-20",
      "home_record": "25-8",
      "away_record": "20-12",
      "ortg": 115.2,       # offensive rating
      "drtg": 108.5,       # defensive rating
      "net_rtg": 6.7,
      "pace": 99.5,        # possessions per 48
      "efg_pct": 0.548,    # effective FG%
      "tov_pct": 0.125,    # turnover rate
      "oreb_pct": 0.285,   # offensive rebound rate
      "ft_rate": 0.255,    # free throw rate
      "three_rate": 0.385, # 3PT attempt rate
      "three_pct": 0.372,  # 3PT accuracy
      "last_10": "7-3",
      "trend": "W3",       # current streak
      "ppg": 114.5,
      "opp_ppg": 108.2,
      "pythagorean_win_pct": 0.632,
  }
  ```
- Keep `pythagorean_win_pct()` formula (works for any sport — use exponent ~14 for NBA instead of ~1.83 for MLB).

### 2c. `scrapers/injuries.py` — Injury Report (New)

- **Source**: NBA official injury report or `nba_api` CommonAllPlayers + manual status checks
- **Function**: `get_injuries() -> list[dict]`
- **Returns** per player:
  ```python
  {
      "team": "LAL",
      "player": "LeBron James",
      "status": "Out",        # Out / Doubtful / Questionable / Probable
      "reason": "Left ankle",
      "impact_tier": "star",   # star / rotation / bench
  }
  ```
- **Critical**: flag when a top-5 minutes player is OUT — biggest line mover in NBA.

### 2d. `scrapers/matchup.py` — Matchup-Specific Data (New)

- **Source**: `nba_api.stats.endpoints.TeamVsPlayer`, `LeagueGameLog`
- **Function**: `get_matchup_data(home_abbrev: str, away_abbrev: str, season: str = None) -> dict`
- **Returns**:
  ```python
  {
      "h2h_record": "2-1",        # season series
      "last_meeting": "LAL 112, BOS 108 (Jan 15)",
      "pace_matchup": {
          "projected_pace": 100.2,
          "projected_possessions": 100,
          "mismatch": "Both teams play at similar pace",
      },
  }
  ```

### 2e. `scrapers/rest.py` — Rest & Travel (New)

- **Source**: Computed from schedule data via `nba_api`
- **Function**: `get_rest_data(team_abbrev: str, game_date: str) -> dict`
- **Returns**:
  ```python
  {
      "days_rest": 1,           # 0 = back-to-back
      "is_b2b": False,
      "games_last_7": 3,
      "road_trip_length": 0,    # consecutive away games
      "travel_miles": 0,        # from last game city
      "tz_change": 0,           # time zone shifts
  }
  ```
- Back-to-back detection is the primary edge signal. Teams on 0 rest lose ~2-3 points of efficiency.

---

## 3. Files to Edit (Surgical Conversion)

### 3a. `config.py`

**Remove**:
- `MLB_API_BASE` URL
- `WEATHER_API_KEY` and `WEATHER_API_BASE`
- `PARK_FACTORS` dict (30 MLB parks)
- `PARK_COORDS` dict (30 MLB coordinates)
- All 30 MLB team abbreviations and name mappings

**Add**:
- `ODDS_SPORT_KEY = "basketball_nba"`
- `HOME_COURT_ADVANTAGE = 3.0` (approximate points)
- 30 NBA `TEAM_ABBREVS` (see Section 6)
- `TEAM_NAME_TO_ABBREV` mapping — must cover Odds API names (e.g., "Los Angeles Lakers" -> "LAL", "LA Clippers" -> "LAC") and nba_api names
- `nba_season(game_date: str) -> str` helper — converts date to NBA season format (e.g., "2026-03-22" -> "2025-26") since `nba_api` expects this format. Logic: if month >= 10, season is `"{year}-{year+1}"`, else `"{year-1}-{year}"`

**Rename in EDGE_THRESHOLDS**:
- `"run_line"` -> `"spread"` (threshold stays 0.06)
- `"first_5_ml"` -> `"first_half_ml"` (threshold stays 0.05)
- `"first_5_total"` -> `"first_half_total"` (threshold stays 0.05)

**Keep unchanged**: Logging config, `ODDS_API_KEY`, `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`, `KIMI_MODEL`, `SCREEN_EDGE_THRESHOLD`, `GAME_TIMEOUT`, `KELLY_FRACTION`, ensemble config, data directory paths.

### 3b. `scrapers/odds.py`

**Changes**:
- Rename `OddsData` fields: `run_line` -> `spread`, `f5_moneyline` -> `h1_moneyline`, `f5_total` -> `h1_total`
- Rename function: `get_mlb_odds()` -> `get_nba_odds()`
- Sport keys: `["basketball_nba"]` (no preseason fallback needed)
- Markets string: `"h2h,spreads,totals,h2h_h1,totals_h1,spreads_h1"` (verify exact key names against The Odds API docs for `basketball_nba` — NBA uses `h2h_h1`/`totals_h1` format, not `h2h_1st_half`)
- Market key parsing: `"h2h_1st_5_innings"` -> `"h2h_h1"`, `"totals_1st_5_innings"` -> `"totals_h1"`
- Add `h1_spread` field to `OddsData` for briefing display (fetched from `spreads_h1` market), though no edge detection is performed on it in v1
- Spread parsing: remove default `-1.5`/`1.5` (NBA spreads vary widely)
- Implied prob calc for spread: `rl_home`/`rl_away` -> `spread_home`/`spread_away`

**Keep**: `american_to_implied_prob()`, `OddsData` dataclass pattern, bookmaker parsing loop, vig removal.

### 3c. `scrapers/scores.py`

**Changes**:
- Data source: `nba_api.stats.endpoints.ScoreboardV2` or `LeagueGameFinder`
- Remove MLB API URL and innings-based parsing
- Rename fields: `away_score_5`/`home_score_5` -> `away_score_h1`/`home_score_h1`, `total_runs` -> `total_points`, `total_runs_5` -> `total_points_h1`
- Parse quarter/half scores instead of inning scores

**Keep**: `get_final_scores()` function signature and return structure pattern.

### 3d. `edge.py`

**Changes**:
- Rename `check_run_line_edge()` -> `check_spread_edge()` — same logic, different bet type name
  - `"run_line"` -> `"spread"` in all output dicts
  - Remove hardcoded `-1.5`/`1.5` defaults (NBA spreads vary)
- Rename `check_f5_ml_edge()` -> `check_h1_ml_edge()`
  - `"first_5_ml"` -> `"first_half_ml"` in output
  - `"f5_home_win_prob"`/`"f5_away_win_prob"` -> `"h1_home_win_prob"`/`"h1_away_win_prob"`
  - Read from `sim["predictions"]["first_half"]` instead of `"first_5"`
  - Odds key: `"h1_moneyline"` instead of `"f5_moneyline"`
- Rename `check_f5_total_edge()` -> `check_h1_total_edge()`
  - `"first_5_total"` -> `"first_half_total"` in output
  - `"f5_projected_total"` -> `"h1_projected_total"`
  - Odds key: `"h1_total"` instead of `"f5_total"`
  - Adjust heuristic multiplier: change `delta * 0.10` to `delta * 0.05` (NBA 1H totals ~105-115 vs MLB F5 totals ~4-6, so each 1.0 point delta ~ 5% shift)
- Update `analyze_all_edges()` checker list with new names
- **Fix existing bug**: `h1_total` odds keys should use `"over_odds"`/`"under_odds"` consistently (current code stores `"over"`/`"under"` for F5 totals but edge.py expects `"over_odds"`/`"under_odds"`)

**Keep**: `american_to_decimal()`, `kelly_criterion()`, `check_moneyline_edge()`, `check_total_edge()` — all unchanged.

### 3e. `simulate.py`

**Replace `MLB_SYSTEM_PROMPT` with `NBA_SYSTEM_PROMPT`**:

6-expert panel (from the NBA guide):
1. **OFFENSIVE ANALYST**: Offensive efficiency, shot selection, spacing, 3PT shooting, pace-adjusted scoring projections
2. **DEFENSIVE ANALYST**: Defensive rating, rim protection, perimeter defense, transition defense
3. **PACE & TEMPO ANALYST**: Pace matchup, projected possessions, tempo impact on total. Critical for O/U
4. **REST & SCHEDULE ANALYST**: Rest days, B2Bs, travel, fatigue — drives spread and total adjustments
5. **MARKET ANALYST**: Line value, public money flow, market inefficiency
6. **CONTRARIAN**: Challenges consensus, questions narratives

**JSON output structure** — rename fields:
- `"run_line"` -> `"spread"` with same `favorite_cover_prob`, `value_side`, `edge`, `confidence`
- `"first_5"` -> `"first_half"` with `h1_home_win_prob`, `h1_away_win_prob`, `h1_projected_total`, `h1_ml_value`, `h1_total_value`
- `predicted_score`: values now ~95-125 range instead of 2-8

**Update `_average_results()`**: rename `prob_fields` keys from `"run_line"` -> `"spread"`, `"first_5"` -> `"first_half"`, and field names accordingly.

**Keep**: `parse_simulation_result()`, `run_plan_b()`, `run_mirofish()` — all architecturally unchanged.

### 3f. `briefing.py` — Full Rewrite

Replace the MLB briefing template with the NBA template from the guide:

```
NBA GAME PREDICTION ANALYSIS
==============================
{away} ({away_record}) at {home} ({home_record})
{arena} | {game_time}

BETTING LINES:
  Moneyline / Spread / Total / 1H Spread / 1H Total / Implied Win Prob

== TEAM PROFILES ==
  Per team: Off Rtg, Def Rtg, Net, Pace, eFG%, TOV%, 3PT Rate/%, L10, Trend, Rest, B2B, Travel

== PACE MATCHUP ==
  Projected Pace / Possessions / Mismatch description

== INJURIES ==
  Per team injury list with status and impact tier

== REST & SCHEDULE CONTEXT ==
  Rest advantage, recent schedule per team

== HEAD-TO-HEAD ==
  Season series, last meeting

== PREDICTION TASK ==
  4 bet types: Game Winner, Spread, Total, First Half
```

**`build_briefing()` input** changes:
- Remove: `away_pitcher`, `home_pitcher`, `environment` (weather/park), `away_bullpen`, `home_bullpen`
- Add: `away_stats`, `home_stats` (team profiles), `rest` (per team), `matchup` (H2H/pace), `arena`, `game_time`

**Keep**: `_format_injuries()`, `_safe_get()` utility functions.
**Remove**: `_format_game_log()` (pitcher game log formatter).

### 3g. `main.py`

**Imports** — remove:
- `scrapers.pitchers` (get_probable_starters, get_starter_profile)
- `scrapers.lineups` (get_confirmed_lineups)
- `scrapers.bullpen` (get_bullpen_state)
- `scrapers.ballpark` (get_game_environment)
- `scrapers.news` (get_injuries)
- `scrapers.odds.get_mlb_odds`

**Imports** — add:
- `scrapers.schedule` (get_todays_games)
- `scrapers.team_stats` (get_team_profile)
- `scrapers.injuries` (get_injuries)
- `scrapers.matchup` (get_matchup_data)
- `scrapers.rest` (get_rest_data)
- `scrapers.odds.get_nba_odds`

**CLI group description**: `"MiroFish MLB Prediction Pipeline"` -> `"MiroFish NBA Prediction Pipeline"`

**`daily` command** — 6-step pipeline rewrite:
1. `get_todays_games(game_date)` — fetch NBA schedule (replaces `get_probable_starters`)
2. `get_nba_odds()` — fetch odds (replaces `get_mlb_odds`)
3. Per-game loop: `get_team_profile()` for both teams (replaces pitcher profiles)
4. Per-game: `get_injuries()`, `get_rest_data()`, `get_matchup_data()`
5. Build `game_data` dict with NBA fields, call `build_briefing()`, screen with `run_plan_b()`
6. Full `run_mirofish()` on flagged games

**`game_data` dict** — new shape:
```python
{
    "away_team": str, "home_team": str,
    "away_record": str, "home_record": str,
    "away_stats": dict, "home_stats": dict,    # team profiles
    "away_rest": dict, "home_rest": dict,       # rest/travel data
    "matchup": dict,                            # H2H + pace matchup
    "arena": str, "game_time": str,
    "odds": {
        "moneyline": {}, "spread": {}, "total": {},
        "h1_moneyline": {}, "h1_total": {},
        "implied_probs": {},
    },
    "away_injuries": [], "home_injuries": [],
}
```

**`game` command** — remove `--away-pitcher`/`--home-pitcher` options. Single-game analysis uses same NBA data flow.

**Odds dict keys** in `game_data`: `run_line` -> `spread`, `f5_moneyline` -> `h1_moneyline`, `f5_total` -> `h1_total`.

**Keep**: CLI structure, `report`, `results`, `card`, `health`, `optimize` commands unchanged. `GameTimeout`, signal handling, step timing/logging all preserved.

### 3h. `agents/results_grader.py`

**Changes**:
- `grade_bet()` case `"run_line"` -> `"spread"` — same logic (score + spread vs opponent)
- `grade_bet()` case `"first_5"` -> `"first_half"`:
  - `score["home_score_5"]` -> `score["home_score_h1"]`
  - `score["away_score_5"]` -> `score["away_score_h1"]`
  - `score["total_runs_5"]` -> `score["total_points_h1"]`
  - Side labels: `"F5 ML"` -> `"H1 ML"`, `"F5 total"` -> `"H1 total"`
- `total_runs` -> `total_points` in total grading

**Keep**: `_match_score()`, `run_results_grader()`, overall grading flow.

### 3i. `ensemble/orchestrator.py`

**Changes** — rename all bet slot references:
- `PROB_FIELDS`: `"run_line"` -> `"spread"`, `"first_5_ml"` / `"first_5_total"` -> `"first_half_ml"` / `"first_half_total"`
- `SLOT_SECTION`: same renames, `"first_5"` -> `"first_half"`
- `PRIMARY_PROB_FIELD`: `"f5_home_win_prob"` -> `"h1_home_win_prob"`, `"f5_projected_total"` -> `"h1_projected_total"`
- `build_ensemble_result()`: all `"first_5"` / `"f5_"` references -> `"first_half"` / `"h1_"`
- Kill slot logic: `"run_line"` -> `"spread"`, `"first_5_ml"` -> `"first_half_ml"`, `"first_5_total"` -> `"first_half_total"`

**Keep**: All orchestration logic — Phase 1/2/3, consensus classification, stability bonuses, weighted averaging.

### 3j. `ensemble/consensus.py`

**Changes**:
- `BET_SLOT_FIELDS`: `"run_line"` -> `"spread"`, `"first_5_ml"` -> `"first_half_ml"`, `"first_5_total"` -> `"first_half_total"`
- Field names: `"f5_ml_value"` -> `"h1_ml_value"`, `"f5_total_value"` -> `"h1_total_value"`
- `extract_vote()`: normalize `"spread"` instead of `"run_line"` (favorite/underdog -> home/away using spread point sign)
  - `"favorite_rl"` -> `"favorite_spread"`, `"underdog_rl"` -> `"underdog_spread"`
  - `"home_rl"` / `"away_rl"` -> `"home_spread"` / `"away_spread"`

**Keep**: `count_votes()`, `check_consensus()`, `weighted_average_prob()`, `apply_stability_bonus()`, `majority_vote()` — all sport-agnostic.

### 3k. `ensemble/runner.py`

**Changes**:
- Import rename: `from simulate import MLB_SYSTEM_PROMPT` -> `from simulate import NBA_SYSTEM_PROMPT`
- Default system prompt: `sys_prompt = system_prompt or MLB_SYSTEM_PROMPT` -> `sys_prompt = system_prompt or NBA_SYSTEM_PROMPT`

**Keep**: All LLM calling logic, token parsing, cost calculation — fully sport-agnostic.

### 3l. `ensemble/challenger.py`

**Changes**:
- Update `CHALLENGER_SYSTEM_PROMPT`: replace `"MLB betting ensemble"` with `"NBA betting ensemble"`
- Update any MLB-specific language in the challenger prompt (e.g., references to "run line", "F5 innings")
- Rename bet slot references in the prompt to match new slot names (spread, first_half_ml, first_half_total)

**Keep**: All challenge logic, verdict parsing, cost tracking.

### 3m. `agents/health_check.py`

**Changes**:
- Remove imports: `WEATHER_API_KEY`, `MLB_API_BASE`, `WEATHER_API_BASE` from config
- Remove `check_mlb_api()` function
- Remove `check_weather_api()` function
- Add `check_nba_api()` — verify `nba_api` package is importable and can reach NBA.com endpoints
- Update `run_health_check()` to call the NBA check instead of MLB/weather checks

**Keep**: `check_odds_api()`, `check_openrouter()`, overall health check pattern.

### 3n. `ensemble/weights.py`

**Changes**:
- `BET_SLOTS` list: `["moneyline", "spread", "total", "first_half_ml", "first_half_total"]`
- Update default weight keys to match new slot names

### 3o. `requirements.txt`

- Replace `pybaseball>=2.3.0` with `nba_api>=1.6.0`

### 3p. `.env.example` / `.env`

- Remove `WEATHER_API_KEY`
- Keep `ODDS_API_KEY`, `OPENROUTER_API_KEY`

---

## 4. Files Unchanged (Sport-Agnostic)

These files require zero changes:

| File | Reason |
|------|--------|
| `tracker.py` | Generic bet logging and P&L |
| `calibrate.py` | Generic calibration |
| `ensemble/logger.py` | Generic CSV prediction logger |
| `ensemble/models.py` | Model registry (no sport references) |
| `agents/bet_card.py` | Generic bet card formatter |
| `agents/self_optimizer.py` | Generic threshold optimizer |
| `agents/daily_runner.py` | Generic pipeline orchestrator |

---

## 5. Test Updates

### Tests to Delete
- `tests/test_pitchers.py`, `tests/test_bullpen.py`, `tests/test_ballpark.py`, `tests/test_lineups.py`, `tests/test_news.py`

### Tests to Create
- `tests/test_schedule.py` — test `get_todays_games()` with mocked `nba_api` responses
- `tests/test_injuries.py` — test injury parsing and impact tier classification
- `tests/test_matchup.py` — test H2H and pace matchup data
- `tests/test_rest.py` — test B2B detection, travel distance, rest calculation

### Tests to Update
- `tests/ensemble_fixtures.py` — **full rewrite**: replace all MLB field names (`run_line`, `first_5`, `f5_*`), analyst roles (`"pitching"`), MLB-scale values (total 8.5, score 3-5), and `MOCK_ODDS` with NBA equivalents
- `tests/test_odds.py` — update for `get_nba_odds()`, `spread`/`h1_*` fields
- `tests/test_scores.py` — update for NBA score structure (quarters, halves)
- `tests/test_team_stats.py` — update for NBA stats (ORtg, DRtg, pace, etc.)
- `tests/test_briefing.py` — update for NBA briefing template
- `tests/test_edge.py` — update for `spread`, `first_half_ml`, `first_half_total`
- `tests/test_simulate.py` — update for `NBA_SYSTEM_PROMPT` and renamed prediction fields
- `tests/test_results_grader.py` — update for `spread`/`first_half` grading
- `tests/test_config.py` — update for NBA teams, removed park factors
- `tests/test_main.py` — update imports and pipeline flow
- `tests/test_ensemble_orchestrator.py` — update slot names
- `tests/test_ensemble_consensus.py` — update `BET_SLOT_FIELDS`, vote normalization
- `tests/test_ensemble_runner.py` — update `MLB_SYSTEM_PROMPT` import to `NBA_SYSTEM_PROMPT`
- `tests/test_ensemble_weights.py` — update hardcoded `BET_SLOTS` assertion to new slot names
- `tests/test_ensemble_challenger.py` — update for NBA terminology in challenger prompt
- `tests/test_ensemble_integration.py` — update `MOCK_PREDICTION` MLB fields to NBA
- `tests/test_health_check.py` — update for NBA API check (remove MLB/weather checks)

---

## 6. NBA-Specific Design Decisions

### Bet Slots
```python
BET_SLOTS = ["moneyline", "spread", "total", "first_half_ml", "first_half_total"]
```

### Edge Thresholds
```python
EDGE_THRESHOLDS = {
    "moneyline": 0.05,
    "spread": 0.06,          # NBA spreads are sharp
    "total": 0.05,
    "first_half_ml": 0.05,
    "first_half_total": 0.05,
}
```

### Design Decision: 1H Spread Excluded

The NBA guide mentions 1st-half spread as a market to fetch. We intentionally exclude it as a bet slot for v1 — the spread market is already covered for full game, and adding a 6th slot would add complexity across edge.py, consensus, orchestrator, weights, and results grader with limited additional edge. The briefing template still displays the 1H spread line for analyst context, but no edge detection or grading is performed on it. Can be added in a future iteration.

### Key Differences from MLB Implementation
1. **No pitcher matchup** — replaced by team-level ORtg/DRtg + rest/injury context
2. **Spread replaces run line** — NBA spreads range -1.5 to -15+ (vs MLB's fixed -1.5)
3. **First half replaces first 5 innings** — driven by starting lineup efficiency, not starting pitcher
4. **Rest/B2B is the primary edge** — teams on 0 rest lose ~2-3 pts of efficiency
5. **Pace matchup drives totals** — projected possessions x efficiency = projected score
6. **Late injury news** — stars rest 1-2 hours before tip; pipeline should run close to game time
7. **Sharper lines** — NBA closing lines are very sharp; edges will be thinner than MLB

### Team Abbreviations (30 NBA Teams)
```python
TEAM_ABBREVS = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN",
    "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM", "MIA",
    "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX",
    "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]
```

---

## 7. Implementation Order

The recommended build order follows dependency chains:

1. **Config + requirements** — foundation for everything else
2. **Delete MLB-only files** — clean slate for scrapers
3. **New scrapers** — schedule, team_stats, injuries, matchup, rest (can be built in parallel)
4. **Edit scrapers** — odds.py, scores.py
5. **Briefing** — depends on new scraper output shapes
6. **System prompt + simulate.py** — depends on new bet slot names
7. **Edge detection** — rename bet types
8. **Main pipeline** — wire everything together
9. **Results grader + ensemble consensus/orchestrator** — rename bet slot references
10. **Tests** — update all tests to match new code
