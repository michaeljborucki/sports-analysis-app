# Tennis Pipeline Design Spec

## Overview

Convert the MiroFish MLB prediction pipeline to a tennis-only (ATP + WTA) prediction pipeline. Remove all MLB-specific code. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and transfer with minimal changes. Sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) are rebuilt for tennis.

## Design Decisions

- **Tennis-only**: No multi-sport support. Clean replacement.
- **Data sources**: Sackmann GitHub repos for historical/profile data, API-Tennis for live schedule.
- **Approach**: Big bang. Delete MLB code first, build tennis from scratch.
- **ATP + WTA from day one**: A `tour` parameter (`"atp"` or `"wta"`) threads through the pipeline. Tour-specific config values live in a `TOUR_CONFIG` dict.
- **3 bet types**: moneyline, game_handicap, total_games (replacing 5 MLB bet types).

## Architecture

The 6-layer pipeline is preserved: SCRAPE -> BRIEFING -> SCREEN -> ENSEMBLE -> EDGE -> BET.

### Layer 1: Scrapers

#### scrapers/schedule.py (NEW)
- Source: API-Tennis (api-tennis.com)
- Env var: `API_TENNIS_KEY`
- Fetches upcoming matches for ATP or WTA
- Returns list of dicts: `{player_a, player_b, tournament, round, surface, indoor_outdoor, draw_size, start_time, match_id}`
- Tour parameter selects ATP vs WTA events

#### scrapers/players.py (NEW)
- Source: Jeff Sackmann's GitHub CSVs (tennis_atp / tennis_wta)
- Downloads and caches CSVs locally in `data/sackmann/`
- Per player returns: ranking, ranking_points, elo (overall + surface-specific), season record (overall + by surface), serve stats (1st serve %, 1st serve win %, 2nd serve win %, ace rate, df rate), return stats (return pts won %, bp conversion %), last 10 matches, surface career record, h2h vs opponent, age, height, handedness, backhand type, days since last match, tournament history
- Functions: `get_player_profile(name, tour, surface)`, `get_head_to_head(player_a, player_b, tour)`

#### scrapers/odds.py (REWRITE)
- Source: The Odds API (same key)
- Sport keys: `tennis_atp` / `tennis_wta` from `TOUR_CONFIG`
- Markets: h2h (moneyline), spreads (game handicap), totals (total games)
- No F5 markets
- OddsData dataclass fields: `player_a, player_b, moneyline: {player_a: price, player_b: price}, game_handicap: {player_a_point, player_a_odds, player_b_point, player_b_odds}, total_games: {line, over_odds, under_odds}, implied_probs: {player_a: prob, player_b: prob}`
- Function: `get_tennis_odds(tour)` returns `list[OddsData]`

#### scrapers/conditions.py (NEW)
- Source: Weather API (for outdoor events) + tournament metadata
- Returns: `{surface, indoor_outdoor, temperature, humidity, wind, altitude, session (day/night), ball_type}`
- Indoor events skip weather fetch

#### scrapers/news.py (REWRITE)
- Source: Tennis news APIs or web scraping
- Returns per player: injury reports, withdrawal history, coaching changes, motivation context (defending points, ranking implications)
- Function: `get_player_news(player_name)` returns list of news items

#### scrapers/scores.py (REWRITE)
- Source: Sackmann repos or API-Tennis
- Returns per completed match: `{player_a, player_b, score (e.g. "6-4 3-6 7-5"), winner, total_games, sets_won_a, sets_won_b, retired: bool}`
- Function: `get_match_results(game_date, tour)` returns list of score dicts

### Layer 2: Briefing (briefing.py REWRITE)

Template from the tennis spec. Key sections:
- Match header (tournament, round, surface, indoor/outdoor, best-of)
- Betting lines (moneyline, game handicap, total games, implied probs)
- Player A profile (rank, Elo, surface Elo, season record, serve stats, return stats, hand, backhand, freshness, tournament history, last 10)
- Player B profile (same structure)
- Head-to-head (overall, on surface, last 3 meetings)
- Conditions (surface, weather, altitude, session)
- Context (tournament category, defending points, stakes, draw path)
- Injuries/fitness
- Prediction task (3 bet types: match winner, game handicap, total games)

Function: `build_briefing(match_data: dict) -> str`

### Layer 3: System Prompt (simulate.py REWRITE)

Replace `MLB_SYSTEM_PROMPT` with `TENNIS_SYSTEM_PROMPT` using the 6 tennis expert analysts from the spec:
1. Serve Analyst
2. Return & Rally Analyst
3. Surface & Conditions Analyst
4. Form & Fitness Analyst
5. Market Analyst
6. Contrarian

JSON output structure changes:
- `moneyline`: `{player_a_win_prob, player_b_win_prob, value_side, edge, confidence}`
- `game_handicap`: `{favorite_cover_prob, value_side, edge, confidence}`
- `total_games`: `{projected_games, over_prob, under_prob, value_side, edge, confidence}`
- `predicted_result`: `{winner, score}`
- `key_factors`: list

No `first_5` section. No `run_line` section.

### Layer 4: Edge Detection (edge.py REWRITE)

3 checkers (down from 5):
- `check_moneyline_edge(sim, odds)` — player_a/player_b instead of home/away
- `check_game_handicap_edge(sim, odds)` — same pattern as run_line but with game spread
- `check_total_games_edge(sim, odds)` — same pattern as total

Kelly fraction is tour-aware: `TOUR_CONFIG[tour]["kelly_fraction"]` (0.25 ATP, 0.125 WTA).

Function: `analyze_all_edges(sim, odds, tour)` returns 0-3 bet signals.

### Layer 5: Config (config.py REWRITE)

Remove: `MLB_API_BASE`, `TEAM_ABBREVS`, `TEAM_NAME_TO_ABBREV`, `PARK_FACTORS`, `PARK_COORDS`, F5 thresholds, run_line thresholds.

Add:
```python
API_TENNIS_BASE = "https://api-tennis.com/tennis/"
API_TENNIS_KEY = os.getenv("API_TENNIS_KEY", "")

SACKMANN_ATP_REPO = "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master"
SACKMANN_WTA_REPO = "https://raw.githubusercontent.com/JeffSackmann/tennis_wta/master"

TOUR_CONFIG = {
    "atp": {
        "odds_sport_key": "tennis_atp",
        "sackmann_repo": SACKMANN_ATP_REPO,
        "kelly_fraction": 0.25,
    },
    "wta": {
        "odds_sport_key": "tennis_wta",
        "sackmann_repo": SACKMANN_WTA_REPO,
        "kelly_fraction": 0.125,
    },
}

EDGE_THRESHOLDS = {
    "moneyline": 0.05,
    "game_handicap": 0.06,
    "total_games": 0.05,
}

BET_SLOTS = ["moneyline", "game_handicap", "total_games"]
GAME_TIMEOUT = 180  # 3 min per match
```

### Layer 6: Ensemble Changes

The ensemble is mostly sport-agnostic. Changes needed:

- **ensemble/consensus.py**: Update `BET_SLOT_FIELDS` to map 3 tennis bet types instead of 5 MLB types. Update `extract_vote` to handle tennis vote normalization (game_handicap: favorite/underdog based on handicap point).
- **ensemble/orchestrator.py**: Update `BET_SLOTS` import, `PROB_FIELDS`, `SLOT_SECTION`, `PRIMARY_PROB_FIELD` mappings for 3 tennis slots. Remove F5 and run_line references.
- **ensemble/runner.py**: Import `TENNIS_SYSTEM_PROMPT` instead of `MLB_SYSTEM_PROMPT`.
- **ensemble/challenger.py**: Update system prompt from "MLB betting ensemble" to "tennis betting ensemble".
- **ensemble/weights.py**: Update `BET_SLOTS` to tennis slots.
- **ensemble/models.py**: No changes needed (model registry is sport-agnostic).
- **ensemble/logger.py**: No changes needed.

### Layer 7: Agent Changes

- **agents/daily_runner.py**: Update branding from MLB to Tennis. Add `--tour` option.
- **agents/results_grader.py**: Rewrite `grade_bet()` for tennis: moneyline (handle retirements), game_handicap (count total games per player, apply handicap), total_games (count total games vs line). Remove F5 grading.
- **agents/health_check.py**: Replace `check_mlb_api()` with `check_api_tennis()`. Add `check_sackmann()`.
- **agents/bet_card.py**: Update branding. Minimal logic changes.
- **agents/self_optimizer.py**: Update bet type references.

### Layer 8: CLI (main.py REWRITE)

Commands:
- `daily [--date] [--tour atp|wta|both]` — full pipeline for a tour
- `match PLAYER_A PLAYER_B [--date] [--tour]` — analyze single match
- `report` — P&L summary
- `results [--date]` — grade pending bets
- `card [--date]` — bet card
- `health` — health check
- `optimize [--min-bets]` — threshold optimization

Default tour: `both` (runs ATP then WTA).

### Files to Delete

- `scrapers/pitchers.py`
- `scrapers/bullpen.py`
- `scrapers/ballpark.py`
- `scrapers/lineups.py`
- `scrapers/team_stats.py`
- `tests/test_pitchers.py`
- `tests/test_bullpen.py`
- `tests/test_ballpark.py`
- All other MLB-specific test files that test deleted functionality

### Files to Create

- `scrapers/schedule.py`
- `scrapers/players.py`
- `scrapers/conditions.py`

### Files to Rewrite

- `config.py`
- `briefing.py`
- `simulate.py`
- `edge.py`
- `main.py`
- `scrapers/odds.py`
- `scrapers/news.py`
- `scrapers/scores.py`
- `ensemble/orchestrator.py`
- `ensemble/runner.py`
- `ensemble/challenger.py`
- `ensemble/consensus.py`
- `ensemble/weights.py`
- `agents/daily_runner.py`
- `agents/results_grader.py`
- `agents/health_check.py`
- `agents/bet_card.py`
- `agents/self_optimizer.py`

### Files Unchanged

- `tracker.py` (sport-agnostic CSV logging)
- `ensemble/models.py` (model registry)
- `ensemble/logger.py` (prediction CSV logging)
- `calibrate.py`

### Test Strategy

Rewrite all tests to use tennis data. Key test files:
- `tests/test_edge.py` — 3 tennis edge checkers
- `tests/test_briefing.py` — tennis briefing template
- `tests/test_simulate.py` — tennis system prompt
- `tests/test_odds.py` — tennis odds parsing
- `tests/test_scores.py` — tennis score parsing + retirement handling
- `tests/test_results_grader.py` — tennis bet grading
- `tests/test_ensemble_orchestrator.py` — 3 tennis bet slots
- `tests/test_ensemble_consensus.py` — tennis vote normalization
- `tests/test_ensemble_runner.py` — tennis system prompt

### Dependencies

Remove: `pybaseball`
Add: None (Sackmann data is CSV via HTTP, API-Tennis is REST)

### Risks

- Sackmann CSV parsing complexity (multiple CSV files per year, naming conventions)
- API-Tennis free tier rate limits
- Tennis odds availability on The Odds API (may have fewer bookmakers)
- Retirement handling in grading (books have different rules)
