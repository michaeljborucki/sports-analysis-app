# MLB → Cricket T20 Migration Design Spec

## Goal

Convert the MiroFish prediction pipeline from MLB baseball to T20 cricket franchise leagues. Remove all MLB code. Keep the sport-agnostic ensemble engine intact. Build new cricket-specific scrapers, briefing, system prompt, and config for all 8 major T20 leagues.

## Decisions

- **Approach:** Clean replace — delete all MLB artifacts, write cricket from scratch
- **Data sources:** CricketData.org API (live/schedule) + Cricsheet (historical ball-by-ball)
- **Leagues at launch:** All 8 — IPL, BBL, CPL, PSL, The Hundred, SA20, BPL, ILT20
- **Bet types:** Match winner (moneyline) + total runs (over/under) — only 2 reliable T20 markets
- **Edge thresholds:** 6% for both (higher than MLB due to T20 volatility)
- **Kelly fraction:** 0.125 (eighth-Kelly for high-variance T20)
- **Execution:** Two-phase parallel sub-agents, respecting dependency chain

## What Gets Deleted

Files removed entirely (MLB-only, no salvageable code):

- `scrapers/pitchers.py` — MLB probable starters
- `scrapers/lineups.py` — MLB confirmed lineups
- `scrapers/bullpen.py` — MLB bullpen state
- `scrapers/ballpark.py` — MLB park factors + weather
- `tests/test_pitchers.py`
- `tests/test_lineups.py`
- `tests/test_bullpen.py`
- `tests/test_ballpark.py`
- `docs/superpowers/plans/2026-03-17-mlb-prediction-pipeline.md`

## What Gets Rewritten In-Place

Same file path, new cricket content:

### config.py

Replace MLB teams, park factors, park coords, and API base URL with:

```python
CRICKET_API_BASE = "https://api.cricketdata.org/v1"
CRICSHEET_DATA_DIR = "data/cricsheet"

LEAGUES = {
    "ipl": {
        "name": "Indian Premier League",
        "odds_key": "cricket_ipl",
        "season": "Mar-May",
        "teams": ["CSK", "MI", "RCB", "KKR", "DC", "PBKS", "RR", "SRH", "GT", "LSG"],
        "team_names": {"Chennai Super Kings": "CSK", "Mumbai Indians": "MI", ...},
    },
    "bbl": {
        "name": "Big Bash League",
        "odds_key": "cricket_big_bash_league",
        "season": "Dec-Jan",
        "teams": ["ADS", "BBH", "HBH", "MLS", "MRS", "PST", "SSX", "SST"],
        "team_names": {...},
    },
    # ... cpl, psl, hundred, sa20, bpl, ilt20
}

BET_SLOTS = ["moneyline", "total_runs"]

EDGE_THRESHOLDS = {
    "moneyline": 0.06,
    "total_runs": 0.06,
}

KELLY_FRACTION = 0.125
```

### briefing.py

Replace MLB briefing template with T20 template from `docs/sport-prompts/08-cricket-t20.md`. Sections:

- Header: league, match number, date, teams, venue, day/night
- Betting lines: match winner + total runs
- Venue & conditions: avg scores, chase win%, pitch type, dew, boundaries, weather
- Toss impact: bat-first vs chase win rates at venue
- Team profiles: record, NRR, powerplay/death rates, form, key players
- Head-to-head: overall record, venue-specific, last 3 meetings
- Match context: league stage, playoff implications
- Prediction task: match winner + total runs

### simulate.py

Replace `MLB_SYSTEM_PROMPT` with the cricket 6-analyst panel from the T20 spec:

1. Pitch & Conditions Analyst (most important for T20)
2. Batting Analyst
3. Bowling Analyst
4. Toss & Chase Analyst
5. Market Analyst
6. Contrarian

JSON output schema changes to match cricket predictions (moneyline + total_runs only, plus predicted_result with projected_scores for batting_first/chasing).

### edge.py

- Remove: `check_run_line_edge()`, `check_f5_ml_edge()`, `check_f5_total_edge()`
- Keep: `american_to_decimal()`, `kelly_criterion()`, `check_moneyline_edge()`, `check_total_edge()`
- Update: `analyze_all_edges()` to only dispatch moneyline + total_runs
- Update: `EDGE_THRESHOLDS` to 6% for both

### main.py

- Remove all MLB scraper imports (pitchers, lineups, bullpen, ballpark)
- Add cricket scraper imports (schedule, team_stats, players, venue, toss, odds, scores)
- Update `game_data` dict building to use cricket data structure
- Update CLI commands: `game TEAM_A TEAM_B --league ipl` instead of `game AWAY HOME`
- Add `--league` flag to filter by league

### scrapers/odds.py

- Keep: `american_to_implied_prob()`
- Replace: `get_mlb_odds()` → `get_cricket_odds(league: str)`
- Sport keys map from league config: `LEAGUES[league]["odds_key"]`
- Markets: h2h (match winner) + totals (total runs) only
- Return `OddsData` dataclass with moneyline + total_runs fields

### scrapers/scores.py

- Replace MLB Stats API calls with CricketData.org match results
- Return per completed match: teams, winner, scores (with wickets/overs), toss winner/decision, total runs, DLS method flag

### scrapers/team_stats.py

- Replace MLB team profile with cricket team stats
- Per team per league: win rate (overall, bat first, chasing), avg scores, powerplay/death rates, NRR, standing, last 5 results

### scrapers/news.py

- Replace MLB injury API with cricket-relevant sources
- Focus on squad announcements, injury updates, availability

### agents/results_grader.py

- Remove: run_line grading, first_5 grading
- Keep: moneyline grading, total grading
- Update score parsing for cricket format (team scores with wickets)
- Handle DLS-affected matches

### agents/health_check.py

- Replace: `check_mlb_api()` → `check_cricket_api()` (ping CricketData.org)
- Keep: odds, openrouter, weather checks unchanged

## New Files

### scrapers/schedule.py

- Source: CricketData.org API
- `get_upcoming_matches(league: str = None)` — returns list of matches
- Each match: team_a, team_b, league, venue, date/time, toss_time
- If league is None, fetch across all configured leagues

### scrapers/players.py

- Source: CricketData.org + Cricsheet
- `get_key_players(team: str, league: str)` — returns top 5-6 players
- Per player: role (batsman/bowler/all-rounder/keeper), batting stats (avg, SR, tournament runs), bowling stats (econ, avg, tournament wickets), recent form (last 5), venue record

### scrapers/venue.py

- Source: Cricsheet historical + weather API
- `get_venue_conditions(venue: str, league: str)` — returns venue profile
- Fields: avg 1st/2nd innings scores, chase win%, pitch type, pitch degradation, dew factor, boundary size, weather (temp, humidity, wind), day/night flag

### scrapers/toss.py

- Source: Cricsheet historical data
- `get_toss_analysis(venue: str)` — returns toss impact at venue
- Fields: toss→bat first %, toss→chase %, win rate batting first vs chasing, dew assessment

### requirements.txt

- Remove: `pybaseball>=2.3.0` (MLB-only)
- Add any cricket-specific libraries needed for Cricsheet CSV parsing

### docs/daily-workflow.md

- Full rewrite: replace MLB-specific instructions (pitchers, lineups, run line, F5 bets) with cricket workflow (leagues, venues, toss, match winner, total runs)

### agents/daily_runner.py

- Review subprocess call to `main.py daily` — if CLI args change (e.g. `--league` flag), update the invocation

### agents/bet_card.py

- Verify odds formatting works for cricket markets (American odds format assumed via `f"{int(bet['odds']):+4d}"`)

## Ensemble Updates

The ensemble engine requires more updates than just constants. The following files contain MLB-specific field names, bet slot lists, and mappings:

### ensemble/weights.py (CRITICAL)
- `BET_SLOTS` is defined here (not in orchestrator) — update from 5 MLB types to:
  ```python
  BET_SLOTS = ["moneyline", "total_runs"]
  ```
- `default_weights()` reads from `BET_SLOTS` so it will auto-adapt

### ensemble/orchestrator.py (CRITICAL)
- `BET_SLOTS` is imported from `ensemble/weights.py` — no local change needed
- `PROB_FIELDS` — rewrite from 5 MLB mappings to:
  ```python
  PROB_FIELDS = {
      "moneyline": ["team_a_win_prob", "team_b_win_prob"],
      "total_runs": ["over_prob", "under_prob", "projected_total"],
  }
  ```
- `SLOT_SECTION` — rewrite:
  ```python
  SLOT_SECTION = {
      "moneyline": "moneyline",
      "total_runs": "total_runs",
  }
  ```
- `PRIMARY_PROB_FIELD` — rewrite:
  ```python
  PRIMARY_PROB_FIELD = {
      "moneyline": "team_a_win_prob",
      "total_runs": "over_prob",
  }
  ```
- `build_ensemble_result()` — update `predicted_score` averaging from `home`/`away` keys to `batting_first`/`chasing`; remove first_5 kill logic and hardcoded MLB section keys

### ensemble/runner.py (CRITICAL)
- Imports `MLB_SYSTEM_PROMPT` from `simulate.py` — rename import to `CRICKET_SYSTEM_PROMPT` (or generic `SYSTEM_PROMPT`) after simulate.py is updated

### ensemble/consensus.py
- `BET_SLOT_FIELDS` updated:
  ```python
  BET_SLOT_FIELDS = {
      "moneyline": ("moneyline", "value_side"),
      "total_runs": ("total_runs", "value_side"),
  }
  ```
- Remove run_line-specific vote normalization logic in `extract_vote()`

### ensemble/challenger.py
- System prompt: change "MLB" references to "T20 cricket"

## Field Name Migration: home/away → team_a/team_b

Cricket does not have home/away in the same way as baseball (toss winner chooses batting order). All code must migrate from `home`/`away` to `team_a`/`team_b` terminology. This cascades through:

- `scrapers/odds.py` — `OddsData` dataclass fields
- `edge.py` — `check_moneyline_edge()` references `home_win_prob`/`away_win_prob` → `team_a_win_prob`/`team_b_win_prob`; implied prob keys `ml_home`/`ml_away` → `ml_team_a`/`ml_team_b`
- `check_total_edge()` — reads from `predictions.total` → must read from `predictions.total_runs`
- `simulate.py` — `_average_results()` prob_fields dict uses MLB field names (`home_win_prob`, `away_win_prob`, `favorite_cover_prob`, `f5_*`); replace with cricket fields (`team_a_win_prob`, `team_b_win_prob`, `over_prob`, `under_prob`, `projected_total`)
- `ensemble/orchestrator.py` — `build_ensemble_result()` predicted_score keys
- `main.py` — game_data dict structure
- `briefing.py` — template field references

## Additional Config Notes

- Add `CRICKET_API_KEY = os.getenv("CRICKET_API_KEY", "")` to config.py (CricketData.org free tier requires API key)
- Add `.env.example` entry for `CRICKET_API_KEY`
- Head-to-head data: sourced from `scrapers/team_stats.py` (combined with Cricsheet historical data)
- The Hundred uses 100-ball format (not 20 overs) — initial implementation treats identically to T20, note for future refinement

## Test Updates

### Delete MLB-specific tests:
- `test_pitchers.py`, `test_lineups.py`, `test_bullpen.py`, `test_ballpark.py`

### Rewrite for cricket:
- `test_odds.py` — mock cricket odds responses
- `test_scores.py` — mock cricket match results
- `test_team_stats.py` — mock cricket team profiles
- `test_news.py` — mock cricket availability data
- `test_results_grader.py` — cricket bet grading (moneyline + total_runs)
- `test_health_check.py` — cricket API endpoint check

### New test files:
- `test_schedule.py` — schedule scraper
- `test_players.py` — player profile scraper
- `test_venue.py` — venue conditions scraper
- `test_toss.py` — toss analysis

### Update existing:
- `test_edge.py` — remove first_5 and run_line tests, update field names, keep moneyline + total_runs
- `test_simulate.py` — update system prompt references and `_average_results` field names
- `test_briefing.py` — update to cricket briefing format
- `test_config.py` — update to cricket config structure
- `ensemble_fixtures.py` — update MOCK_PREDICTION and MOCK_ODDS to cricket format (team_a/team_b, 2 bet slots)
- `test_ensemble_weights.py` — update BET_SLOTS assertions from 5 to 2
- `test_ensemble_consensus.py` — update BET_SLOT_FIELDS assertions, remove run_line vote normalization tests
- `test_ensemble_orchestrator.py` — update PROB_FIELDS, SLOT_SECTION, PRIMARY_PROB_FIELD references
- `test_ensemble_runner.py` — update system prompt import name
- `test_ensemble_challenger.py` — update sport references in prompts
- `test_ensemble_integration.py` — update MOCK_PREDICTION with cricket fields
- `test_ensemble_logger.py` — update game label fixtures from MLB format
- `test_self_optimizer.py` — verify BET_SLOTS import works with 2 cricket slots
- `test_bet_card.py` — verify odds formatting

## Execution Plan: Two-Phase Parallel Sub-Agents

### Phase 1: Delete MLB + Build Foundations (4 parallel agents)

**Agent 1 — Config & Cleanup:**
- Delete all MLB-only files (scrapers/pitchers.py, lineups.py, bullpen.py, ballpark.py + their tests)
- Delete `docs/superpowers/plans/2026-03-17-mlb-prediction-pipeline.md`
- Rewrite `config.py` with all 8 leagues' teams, venues, odds keys, CRICKET_API_KEY
- Update `ensemble/weights.py` — BET_SLOTS to 2 cricket types
- Update `ensemble/orchestrator.py` — PROB_FIELDS, SLOT_SECTION, PRIMARY_PROB_FIELD, build_ensemble_result()
- Update `ensemble/consensus.py` — BET_SLOT_FIELDS, remove run_line vote normalization
- Update `ensemble/challenger.py` — sport reference in prompt
- Remove `pybaseball` from `requirements.txt`

**Agent 2 — Schedule + Team Stats Scrapers:**
- Build `scrapers/schedule.py` with CricketData.org integration
- Rewrite `scrapers/team_stats.py` for cricket team profiles
- Write `tests/test_schedule.py` and update `tests/test_team_stats.py`

**Agent 3 — Players + Venue Scrapers:**
- Build `scrapers/players.py` with player profiles
- Build `scrapers/venue.py` with venue conditions + weather
- Write `tests/test_players.py` and `tests/test_venue.py`

**Agent 4 — Toss + Odds + Scores Scrapers:**
- Build `scrapers/toss.py` with Cricsheet historical analysis
- Rewrite `scrapers/odds.py` for cricket odds
- Rewrite `scrapers/scores.py` for cricket results
- Write `tests/test_toss.py`, update `tests/test_odds.py`, `tests/test_scores.py`

### Phase 2: Wire Everything Together (4 parallel agents)

**Agent 5 — Briefing + System Prompt:**
- Rewrite `briefing.py` with T20 briefing template
- Replace `MLB_SYSTEM_PROMPT` in `simulate.py` with `CRICKET_SYSTEM_PROMPT`; update `_average_results()` field mappings
- Update `ensemble/runner.py` import to match new prompt name
- Update `tests/test_briefing.py` and `tests/test_simulate.py`

**Agent 6 — Edge + Main:**
- Update `edge.py` (remove MLB bet types, update thresholds)
- Rewrite `main.py` with cricket scraper calls and `--league` flag
- Update `tests/test_edge.py`

**Agent 7 — Agents:**
- Update `agents/results_grader.py` for cricket grading
- Update `agents/health_check.py` with cricket API check
- Update `agents/daily_runner.py` if CLI args changed
- Verify `agents/bet_card.py` odds formatting
- Rewrite `scrapers/news.py` for cricket
- Rewrite `docs/daily-workflow.md` for cricket workflow
- Update `tests/test_results_grader.py`, `tests/test_health_check.py`, `tests/test_news.py`

**Agent 8 — Test Fixtures + Integration:**
- Update `ensemble_fixtures.py` with cricket mock data (team_a/team_b, 2 bet slots)
- Update all ensemble tests for 2-slot bet types (weights, consensus, orchestrator, runner, challenger, integration, logger)
- Update `test_config.py`, `test_self_optimizer.py`, `test_bet_card.py`
- Run full test suite and fix any integration issues

## Out of Scope

- Live match tracking / in-play betting
- Player prop bets (top batsman, top bowler)
- First innings score betting
- Cricsheet data download automation (manual download for now)
- UI / dashboard
- Bankroll management beyond Kelly sizing
