# Market Expansion Design: Phase 1 (Game-Level) + Phase 2 (PA-Level Props)

## Summary

Expand from 5 betting markets to 22 by adding 7 game-level markets (Phase 1) and 10 player prop markets (Phase 2). Phase 1 extends the existing LLM ensemble architecture. Phase 2 introduces a new statistical Monte Carlo PA simulation engine.

## Current State

**5 markets**: moneyline, run_line, total, first_5_ml, first_5_total

**Architecture**: LLM ensemble (6 models) → consensus → challenger → edge detection → Kelly sizing

**Key files**: config.py, scrapers/odds.py (OddsData), simulate.py (system prompt), briefing.py, edge.py, ensemble/consensus.py, ensemble/orchestrator.py, ensemble/weights.py, tracker.py

## Key Architecture Decision: OddsData Through the Pipeline

Currently `main.py` passes `game_data["odds"]` as a plain dict to edge detection. To cleanly support the new fields, we pass the `OddsData` dataclass directly through the pipeline instead. All edge checkers will accept `odds: OddsData` and use attribute access. The existing edge checkers will be updated to use `odds.moneyline`, `odds.run_line`, etc. instead of `odds.get("moneyline")`. This is a small refactor that enables clean Phase 1/2 integration.

## API Budget Management

Per-event Odds API calls cost the same credits as bulk calls. With 15 games/day and 2 per-event calls each (Phase 1 markets + Phase 2 props), that is ~31 API calls/day total. Before making per-event calls, check `x-requests-remaining` header from the bulk call. If remaining < 100, skip per-event calls for that day and only use bulk markets. Cache per-event responses in `data/odds_cache/{date}/` with 15-minute TTL to avoid duplicate calls on retries.

---

## Phase 1: Game-Level Market Expansion

### New Markets (7)

| Market | API Key | Edge Threshold | Prediction Source |
|--------|---------|----------------|-------------------|
| Team Totals (home) | `team_totals` | 5% | Existing predicted_score.home |
| Team Totals (away) | `team_totals` | 5% | Existing predicted_score.away |
| F5 Run Line | `spreads_1st_5_innings` | 5% | Existing F5 win prob + new tie prob |
| NRFI/YRFI | `totals_1st_1_innings` | 6% | New first_inning section in sim output |
| F1 Run Line | `spreads_1st_1_innings` | 6% | New first_inning section + tie prob |
| F3 Moneyline | `h2h_1st_3_innings` | 5% | New first_3 section in sim output |
| F3 Totals | `totals_1st_3_innings` | 5% | New first_3 section |
| F3 Run Line | `spreads_1st_3_innings` | 5% | New first_3 section + tie prob |

### File Changes

#### 1. `config.py`

Add to EDGE_THRESHOLDS:
```python
EDGE_THRESHOLDS = {
    # existing
    "moneyline": 0.05,
    "run_line": 0.06,
    "total": 0.05,
    "first_5_ml": 0.05,
    "first_5_total": 0.05,
    # Phase 1 new
    "team_total_home": 0.05,
    "team_total_away": 0.05,
    "first_5_rl": 0.05,
    "nrfi": 0.06,
    "first_1_rl": 0.06,
    "first_3_ml": 0.05,
    "first_3_total": 0.05,
    "first_3_rl": 0.05,
}
```

#### 2. `scrapers/odds.py`

**OddsData dataclass** — add 7 new fields:
```python
@dataclass
class OddsData:
    # existing fields unchanged
    home: str
    away: str
    commence_time: str
    moneyline: dict = field(default_factory=dict)
    run_line: dict = field(default_factory=dict)
    total: dict = field(default_factory=dict)
    f5_moneyline: dict = field(default_factory=dict)
    f5_total: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)
    # Phase 1 new fields
    team_total_home: dict = field(default_factory=dict)   # {"line": 4.5, "over_odds": -110, "under_odds": -110}
    team_total_away: dict = field(default_factory=dict)   # same structure
    f5_spread: dict = field(default_factory=dict)         # {"home": -0.5, "home_odds": -120, "away": 0.5, "away_odds": 100}
    f1_total: dict = field(default_factory=dict)          # {"line": 0.5, "over_odds": -120, "under_odds": 100}  (NRFI/YRFI)
    f1_spread: dict = field(default_factory=dict)         # {"home": -0.5, "home_odds": X, "away": 0.5, "away_odds": X}
    f3_moneyline: dict = field(default_factory=dict)      # {"home": -130, "away": 110}
    f3_total: dict = field(default_factory=dict)          # {"line": 2.5, "over_odds": -110, "under_odds": -110}
    f3_spread: dict = field(default_factory=dict)         # {"home": -0.5, "home_odds": X, "away": 0.5, "away_odds": X}
```

**New function**: `get_additional_odds(event_id: str) -> dict`
- Calls per-event endpoint: `/v4/sports/baseball_mlb/events/{eventId}/odds`
- Markets param: `team_totals,spreads_1st_5_innings,totals_1st_1_innings,spreads_1st_1_innings,h2h_1st_3_innings,totals_1st_3_innings,spreads_1st_3_innings`
- Returns parsed dict of additional market data
- Falls back gracefully if any market unavailable

**Updated `get_mlb_odds()`**:
- First call: bulk endpoint for existing 5 markets (unchanged)
- Second call: per-event endpoint for each game's additional markets
- Merge additional data into OddsData objects
- Store event_id on OddsData for per-event lookups

**New field on OddsData**:
```python
event_id: str = ""  # The Odds API event ID for per-event queries
```

#### 3. `simulate.py`

**Expand MLB_SYSTEM_PROMPT** to request additional predictions:

Add to the expected JSON output format:
```json
{
  "predictions": {
    "first_inning": {
      "f1_home_score_prob": 0.XX,
      "f1_away_score_prob": 0.XX,
      "nrfi_prob": 0.XX,
      "f1_home_lead_prob": 0.XX,
      "f1_away_lead_prob": 0.XX,
      "f1_tie_prob": 0.XX,
      "confidence": "low|medium|high"
    },
    "first_3": {
      "f3_home_win_prob": 0.XX,
      "f3_away_win_prob": 0.XX,
      "f3_projected_total": X.X,
      "f3_home_lead_prob": 0.XX,
      "f3_away_lead_prob": 0.XX,
      "f3_tie_prob": 0.XX,
      "f3_ml_value": "home|away|none",
      "f3_total_value": "over|under|none",
      "confidence": "low|medium|high"
    },
    "first_5": {
      "f5_home_win_prob": 0.XX,
      "f5_away_win_prob": 0.XX,
      "f5_projected_total": X.X,
      "f5_home_lead_prob": 0.XX,
      "f5_away_lead_prob": 0.XX,
      "f5_tie_prob": 0.XX,
      "f5_ml_value": "home|away|none",
      "f5_total_value": "over|under|none",
      "confidence": "low|medium|high"
    }
  }
}
```

Add to the `total` section for team total consensus voting:
```json
"total": {
  "projected_total": X.X,
  "over_prob": 0.XX,
  "under_prob": 0.XX,
  "value_side": "over|under|none",
  "home_total_value": "over|under|none",
  "away_total_value": "over|under|none",
  "confidence": "low|medium|high"
}
```

Add value_side fields for new spread/inning markets:
```json
"first_inning": {
  ...existing fields...,
  "nrfi_value": "nrfi|yrfi|none",
  "f1_rl_value": "home|away|none"
},
"first_3": {
  ...existing fields...,
  "f3_rl_value": "home|away|none"
},
"first_5": {
  ...existing fields...,
  "f5_rl_value": "home|away|none"
}
```

Key additions:
- `first_inning` section with NRFI probability and per-team first-inning scoring probs
- `first_3` section mirroring first_5 structure
- Tie probabilities for F1/F3/F5 (critical for spread edge detection)
- Team-level predicted scores already exist in `predicted_score` — team totals use these directly
- `home_total_value` and `away_total_value` in total section for team total consensus voting
- `f1_rl_value`, `f3_rl_value`, `f5_rl_value` for spread consensus voting
- `nrfi_value` for NRFI consensus voting

**Update `_average_results()` in simulate.py**:
Add the new sections (`first_inning`, `first_3`) to the averaging logic alongside the existing `moneyline`, `run_line`, `total`, `first_5` sections. Average all probability fields across runs.

#### 4. `briefing.py`

**Expand betting lines section** to include new markets when available:
```
BETTING LINES:
  Moneyline: HOME -130 / AWAY +110
  Run Line: HOME -1.5 (-110) / AWAY +1.5 (-110)
  Total: O/U 8.5 (Over -110 / Under -110)
  Team Totals: HOME O/U 4.5 (-110/-110) / AWAY O/U 3.5 (-110/-110)
  F5 ML: HOME -120 / AWAY +100
  F5 Total: O/U 4.5 (-110/-110)
  F5 RL: HOME -0.5 (-130) / AWAY +0.5 (+110)
  NRFI/YRFI: O/U 0.5 (NRFI -135 / YRFI +115)
  F1 RL: HOME -0.5 (-110) / AWAY +0.5 (-110)
  F3 ML: HOME -125 / AWAY +105
  F3 Total: O/U 2.5 (-110/-110)
  F3 RL: HOME -0.5 (-115) / AWAY +0.5 (-105)
```

Only include lines that are available (graceful fallback).

#### 5. `edge.py`

**7 new edge checker functions**, all following the existing pattern:

```python
def _poisson_over_prob(predicted: float, line: float) -> float:
    """Calculate P(over line) using Poisson distribution.

    More accurate than linear heuristic for run-scoring markets.
    Baseball run scoring approximates Poisson (slightly overdispersed).
    """
    from math import exp, factorial
    # P(X > line) = 1 - P(X <= floor(line))
    k_max = int(line)  # e.g., line=4.5 → sum P(0)+P(1)+P(2)+P(3)+P(4)
    cdf = sum(
        (predicted ** k) * exp(-predicted) / factorial(k)
        for k in range(k_max + 1)
    )
    return max(0.01, min(0.99, 1 - cdf))

def check_team_total_home_edge(sim: dict, odds: OddsData) -> dict | None:
    """Compare predicted home runs to team total line using Poisson CDF."""
    predicted = sim.get("predictions", {}).get("predicted_score", {}).get("home")
    tt = odds.team_total_home
    if not predicted or not tt or "line" not in tt:
        return None
    line = tt["line"]
    over_prob = _poisson_over_prob(predicted, line)
    under_prob = 1 - over_prob
    # Compare to implied odds, return edge if threshold met
    ...

def check_team_total_away_edge(sim: dict, odds: OddsData) -> dict | None:
    """Same pattern for away team total."""

def check_f5_rl_edge(sim: dict, odds: OddsData) -> dict | None:
    """F5 run line using tie probability.

    Key insight: F5 ML pushes on ties, F5 RL resolves them.
    P(home -0.5) = f5_home_lead_prob (not f5_home_win_prob)
    P(away +0.5) = f5_away_lead_prob + f5_tie_prob
    """
    f5 = sim.get("predictions", {}).get("first_5", {})
    spread = odds.f5_spread
    if not f5 or not spread:
        return None
    home_lead = f5.get("f5_home_lead_prob", f5.get("f5_home_win_prob", 0))
    tie = f5.get("f5_tie_prob", 0.20)  # default 20% if not provided
    away_lead = f5.get("f5_away_lead_prob", f5.get("f5_away_win_prob", 0))
    # -0.5 side: must be leading (ties lose)
    # +0.5 side: leading OR tied (ties win)
    ...

def check_nrfi_edge(sim: dict, odds: OddsData) -> dict | None:
    """NRFI: no runs in first inning (under 0.5).

    Uses nrfi_prob from first_inning predictions.
    """

def check_f1_rl_edge(sim: dict, odds: OddsData) -> dict | None:
    """F1 run line. ~55-58% of games tied after 1 inning.

    Massive probability redistribution vs F1 ML.
    """

def check_f3_ml_edge(sim: dict, odds: OddsData) -> dict | None:
    """F3 moneyline. Isolates first pass through order."""

def check_f3_total_edge(sim: dict, odds: OddsData) -> dict | None:
    """F3 total. Over/under first 3 innings runs."""

def check_f3_rl_edge(sim: dict, odds: OddsData) -> dict | None:
    """F3 run line. ~27-30% tied after 3 innings."""
```

**Update `analyze_all_edges()`** to call all 12 checkers (5 existing + 7 new).

#### 6. `ensemble/consensus.py`

Add to BET_SLOT_FIELDS:
```python
BET_SLOT_FIELDS = {
    # existing
    "moneyline": ("moneyline", "value_side"),
    "run_line": ("run_line", "value_side"),
    "total": ("total", "value_side"),
    "first_5_ml": ("first_5", "f5_ml_value"),
    "first_5_total": ("first_5", "f5_total_value"),
    # Phase 1 new
    "team_total_home": ("total", "home_total_value"),
    "team_total_away": ("total", "away_total_value"),
    "first_5_rl": ("first_5", "f5_rl_value"),
    "nrfi": ("first_inning", "nrfi_value"),
    "first_1_rl": ("first_inning", "f1_rl_value"),
    "first_3_ml": ("first_3", "f3_ml_value"),
    "first_3_total": ("first_3", "f3_total_value"),
    "first_3_rl": ("first_3", "f3_rl_value"),
}
```

#### 7. `ensemble/orchestrator.py`

Add probability fields for weighted averaging:
```python
PROB_FIELDS = {
    # existing
    "moneyline": ["home_win_prob", "away_win_prob"],
    "run_line": ["favorite_cover_prob"],
    "total": ["over_prob", "under_prob", "projected_total"],
    "first_5_ml": ["f5_home_win_prob", "f5_away_win_prob"],
    "first_5_total": ["f5_projected_total"],
    # Phase 1 new
    "team_total_home": ["predicted_score.home"],
    "team_total_away": ["predicted_score.away"],
    "first_5_rl": ["f5_home_lead_prob", "f5_tie_prob"],
    "nrfi": ["nrfi_prob"],
    "first_1_rl": ["f1_home_lead_prob", "f1_tie_prob"],
    "first_3_ml": ["f3_home_win_prob", "f3_away_win_prob"],
    "first_3_total": ["f3_projected_total"],
    "first_3_rl": ["f3_home_lead_prob", "f3_tie_prob"],
}

PRIMARY_FIELDS = {
    # existing
    "moneyline": "home_win_prob",
    "run_line": "favorite_cover_prob",
    "total": "over_prob",
    "first_5_ml": "f5_home_win_prob",
    "first_5_total": "f5_projected_total",
    # Phase 1 new
    "team_total_home": "predicted_score.home",
    "team_total_away": "predicted_score.away",
    "first_5_rl": "f5_home_lead_prob",
    "nrfi": "nrfi_prob",
    "first_1_rl": "f1_home_lead_prob",
    "first_3_ml": "f3_home_win_prob",
    "first_3_total": "f3_projected_total",
    "first_3_rl": "f3_home_lead_prob",
}

# Maps bet slot → prediction section key (for extracting probs)
SLOT_SECTION = {
    # existing
    "moneyline": "moneyline",
    "run_line": "run_line",
    "total": "total",
    "first_5_ml": "first_5",
    "first_5_total": "first_5",
    # Phase 1 new
    "team_total_home": "total",
    "team_total_away": "total",
    "first_5_rl": "first_5",
    "nrfi": "first_inning",
    "first_1_rl": "first_inning",
    "first_3_ml": "first_3",
    "first_3_total": "first_3",
    "first_3_rl": "first_3",
}
```

**Challenger kill logic** — extend `build_ensemble_result` to handle new sections:
- Slots sharing a section are killed independently (e.g., killing `nrfi` does not kill `first_1_rl`)
- Kill removes the slot's value_side from the prediction (sets to "none") and zeros its edge
- New sections `first_inning` and `first_3` follow the same pattern as existing `first_5`

#### 8. `ensemble/weights.py`

Update BET_SLOTS:
```python
BET_SLOTS = [
    "moneyline", "run_line", "total", "first_5_ml", "first_5_total",
    "team_total_home", "team_total_away", "first_5_rl", "nrfi",
    "first_1_rl", "first_3_ml", "first_3_total", "first_3_rl",
]
```

`default_weights()` auto-generates 1.0 for all slots — no other change needed.

#### 9. Tests

New test files:
- `tests/test_edge_phase1.py` — edge detection for all 7 new markets
- `tests/test_odds_additional.py` — per-event API parsing
- `tests/test_consensus_phase1.py` — vote extraction for new slots

Update existing:
- `tests/test_ensemble_orchestrator.py` — add new prob fields
- `tests/test_briefing.py` — new odds in briefing output

---

## Phase 2: PA-Level Monte Carlo Prop Engine

### Architecture

```
scrapers/player_stats.py     # Fetch per-player stats from MLB Stats API
    ↓
simulation/pa_engine.py      # Single PA outcome sampling
    ↓
simulation/game_sim.py       # Full 9-inning game with state tracking
    ↓
simulation/monte_carlo.py    # Run 5,000 iterations, aggregate distributions
    ↓
simulation/props_edge.py     # Compare distributions to book lines
    ↓
scrapers/odds.py             # Fetch prop lines (per-event endpoint)
```

### New Markets (10)

| Market | API Key | Edge Threshold | Distribution Source |
|--------|---------|----------------|---------------------|
| Pitcher Ks O/U | `pitcher_strikeouts` | 5% | K count distribution |
| Pitcher ER O/U | `pitcher_earned_runs` | 5% | ER count distribution |
| Pitcher Outs O/U | `pitcher_outs` | 5% | Outs recorded distribution |
| Pitcher Hits O/U | `pitcher_hits_allowed` | 5% | Hits allowed distribution |
| Batter TB O/U | `batter_total_bases` | 5% | Total bases distribution |
| Batter RBI O/U | `batter_rbis` | 5% | RBI count distribution |
| Batter Hits O/U | `batter_hits` | 5% | Hit count distribution |
| Batter Runs O/U | `batter_runs_scored` | 5% | Runs scored distribution |
| Batter H+R+RBI O/U | `batter_hits_runs_rbis` | 5% | Composite distribution |
| Batter Ks O/U | `batter_strikeouts` | 5% | K count distribution |

### File Details

#### 1. `scrapers/player_stats.py`

**Purpose**: Fetch per-player season stats from the free MLB Stats API.

```python
def get_batter_stats(player_id: int, season: int) -> dict:
    """Fetch batter season stats.

    Returns:
        {
            "name": str,
            "player_id": int,
            "pa": int,           # plate appearances
            "k_pct": float,      # strikeout rate
            "bb_pct": float,     # walk rate
            "hr_pct": float,     # home run rate per PA
            "single_pct": float, # single rate per PA
            "double_pct": float,
            "triple_pct": float,
            "out_pct": float,    # out (non-K) rate per PA
            "bat_side": str,     # "L", "R", "S"
        }
    """

def get_pitcher_stats(player_id: int, season: int) -> dict:
    """Fetch pitcher season stats.

    Returns:
        {
            "name": str,
            "player_id": int,
            "ip": float,
            "k_pct": float,      # K rate per batter faced
            "bb_pct": float,
            "hr_pct": float,
            "single_pct": float,
            "double_pct": float,
            "triple_pct": float,
            "out_pct": float,    # out (non-K) rate per batter faced
            "pitch_hand": str,   # "L", "R"
            "avg_pitch_count": float,  # average pitches per start
        }
    """

def get_lineup(game_pk: int) -> dict:
    """Fetch confirmed lineup for a game.

    Returns:
        {
            "home": [player_id, ...],  # 9 batters in order
            "away": [player_id, ...],
            "home_pitcher": player_id,
            "away_pitcher": player_id,
        }
    """

LEAGUE_AVERAGES = {
    "k_pct": 0.224,
    "bb_pct": 0.084,
    "hr_pct": 0.033,
    "single_pct": 0.152,
    "double_pct": 0.044,
    "triple_pct": 0.004,
    "out_pct": 0.459,
}
```

Stats are cached per-day in `data/player_stats/` to avoid redundant API calls.

#### 2. `simulation/pa_engine.py`

**Purpose**: Sample a single plate appearance outcome.

**Odds-ratio method** (standard approach for combining batter/pitcher rates):
```python
def matchup_probability(batter_rate: float, pitcher_rate: float, league_rate: float) -> float:
    """Combine batter and pitcher rates using odds-ratio method.

    Formula: (batter_rate * pitcher_rate) / league_rate
    Then normalize across all outcomes to sum to 1.0.
    """

def sample_pa(batter_stats: dict, pitcher_stats: dict) -> str:
    """Sample a single PA outcome.

    Returns one of: "K", "BB", "1B", "2B", "3B", "HR", "OUT"

    Steps:
    1. Compute matchup probability for each outcome using odds-ratio
    2. Normalize probabilities to sum to 1.0
    3. Sample from the distribution using random.random()
    """
```

#### 3. `simulation/game_sim.py`

**Purpose**: Simulate a full baseball game with state tracking.

```python
@dataclass
class GameState:
    inning: int = 1
    half: str = "top"        # "top" or "bottom"
    outs: int = 0
    bases: list = field(default_factory=lambda: [0, 0, 0])  # [1B, 2B, 3B] (0=empty, player_id=occupied)
    score: dict = field(default_factory=lambda: {"away": 0, "home": 0})
    score_by_inning: dict = field(default_factory=lambda: {"away": [], "home": []})

    # Per-player stat accumulators
    pitcher_stats: dict = field(default_factory=dict)   # {player_id: {"k": 0, "bb": 0, "h": 0, "er": 0, "outs": 0, "pitches": 0}}
    batter_stats: dict = field(default_factory=dict)    # {player_id: {"pa": 0, "h": 0, "2b": 0, "3b": 0, "hr": 0, "rbi": 0, "r": 0, "k": 0, "bb": 0, "tb": 0}}

def simulate_game(
    home_lineup: list[dict],       # 9 batter stat dicts
    away_lineup: list[dict],
    home_pitcher: dict,
    away_pitcher: dict,
    park_factor: float = 1.0,
) -> GameState:
    """Simulate one complete game.

    Flow:
    1. Away bats top of each inning, home bats bottom
    2. Each PA: sample outcome via pa_engine.sample_pa()
    3. On hit: advance runners based on hit type
       - 1B: runners advance 1 base (runner on 2B scores)
       - 2B: runners advance 2 bases
       - 3B: all runners score
       - HR: all runners + batter score
       - BB: forced advance only
    4. Track RBI on scoring plays
    5. Track runs scored for runners who cross home
    6. After 3 outs, switch sides
    7. After 9 innings, if tied, play extras (max 12)
    8. Estimate pitch count: ~4 pitches per PA
    9. Pitcher exit: when pitch count > avg_pitch_count * 1.1

    Returns completed GameState with all stats.
    """

def advance_runners(bases: list, hit_type: str, outs: int) -> tuple[list, int]:
    """Advance runners and return (new_bases, runs_scored).

    Simple runner advancement model:
    - 1B: runner on 1B→2B, 2B→scores (60%), 2B→3B (40%), 3B→scores
    - 2B: 1B→scores (90%), 1B→3B (10%), 2B→scores, 3B→scores
    - 3B: all runners score
    - HR: all runners + batter score
    - BB: forced advances only (1B→2B only if 1B occupied, etc.)
    - OUT: runner advancement on <2 outs (sac fly from 3B, etc.)
    """
```

#### 4. `simulation/monte_carlo.py`

**Purpose**: Run N game simulations and aggregate distributions.

```python
def run_monte_carlo(
    home_lineup: list[dict],
    away_lineup: list[dict],
    home_pitcher: dict,
    away_pitcher: dict,
    park_factor: float = 1.0,
    n_sims: int = 5000,
) -> dict:
    """Run N game simulations and aggregate results.

    Returns:
        {
            "n_sims": int,
            "game_results": {
                "home_wins": int,
                "away_wins": int,
                "avg_total": float,
                "avg_home_score": float,
                "avg_away_score": float,
                "score_by_inning": {  # average per inning
                    "away": [0.4, 0.3, ...],
                    "home": [0.5, 0.4, ...],
                },
                "tied_after_1": float,  # P(tied after 1 inning)
                "tied_after_3": float,
                "tied_after_5": float,
            },
            "pitcher_distributions": {
                player_id: {
                    "k": [0, 0, 0.05, 0.12, 0.18, 0.22, ...],  # P(0K), P(1K), ..., P(12K)
                    "er": [0.15, 0.20, 0.25, ...],
                    "outs": [0.01, 0.02, ...],
                    "h": [...],
                    "bb": [...],
                }
            },
            "batter_distributions": {
                player_id: {
                    "h": [0.30, 0.35, 0.25, 0.08, 0.02],  # P(0H), P(1H), P(2H), P(3H), P(4H)
                    "tb": [0.20, 0.25, 0.20, 0.15, 0.10, 0.05, ...],
                    "hr": [0.85, 0.12, 0.03],  # P(0HR), P(1HR), P(2HR)
                    "rbi": [...],
                    "r": [...],
                    "k": [...],
                    "bb": [...],
                    "h_r_rbi": [...],  # composite
                }
            },
        }
    """
```

#### 5. `simulation/props_edge.py`

**Purpose**: Compare Monte Carlo distributions to sportsbook prop lines.

```python
def get_prop_odds(event_id: str) -> dict:
    """Fetch all player prop odds for a game.

    Calls: /v4/sports/baseball_mlb/events/{eventId}/odds
    Markets: pitcher_strikeouts,pitcher_earned_runs,pitcher_outs,
             pitcher_hits_allowed,batter_total_bases,batter_rbis,
             batter_hits,batter_runs_scored,batter_hits_runs_rbis,
             batter_strikeouts

    Returns:
        {
            "pitcher_strikeouts": {
                player_name: {"line": 5.5, "over_odds": -115, "under_odds": -105}
            },
            "batter_total_bases": {
                player_name: {"line": 1.5, "over_odds": -120, "under_odds": 100}
            },
            ...
        }
    """

def distribution_to_over_prob(distribution: list[float], line: float) -> float:
    """Calculate P(over line) from a discrete distribution.

    Example: line=5.5, distribution=[P(0), P(1), ..., P(12)]
    P(over 5.5) = P(6) + P(7) + ... + P(12) = sum(distribution[6:])
    """

def check_prop_edge(
    distribution: list[float],
    line: float,
    over_odds: int,
    under_odds: int,
    threshold: float,
) -> dict | None:
    """Check for edge on a single prop.

    Returns standard bet dict or None if no edge.
    """

def analyze_all_props(mc_results: dict, prop_odds: dict) -> list[dict]:
    """Check all prop edges for a game.

    Maps player names between MC results (by ID) and odds (by name).
    Runs check_prop_edge for each available prop line.
    Returns list of bet dicts meeting threshold.
    """
```

#### 6. Integration with `main.py`

Add prop analysis step after full simulation:
```python
# In the full simulation loop (after run_mirofish):
if mc_engine_available and confirmed_lineups:
    mc_results = run_monte_carlo(
        home_lineup, away_lineup, home_pitcher, away_pitcher,
        park_factor=park_factors.get(home_team, {}).get("runs", 1.0),
        n_sims=5000,
    )
    prop_odds = get_prop_odds(event_id)
    prop_bets = analyze_all_props(mc_results, prop_odds)
    for bet in prop_bets:
        log_bet(bet)
```

The MC engine runs **alongside** the LLM ensemble, not instead of it. Game-level markets use LLM predictions; prop markets use MC distributions.

#### 7. Player Name Matching

**Challenge**: Odds API uses display names ("Shohei Ohtani"), MLB Stats API uses player IDs.

**Solution**: `scrapers/player_stats.py` maintains a name→ID mapping with a concrete fallback chain:
```python
def resolve_player(name: str, team: str = None) -> int | None:
    """Resolve a player display name to MLB player ID.

    Fallback chain:
    1. Exact match in cached data/player_map.json
    2. MLB Stats API search endpoint (exact)
    3. Normalized match: strip accents, remove Jr./Sr./III, lowercase
    4. Fuzzy match using difflib.get_close_matches (cutoff=0.85)
    5. If team provided, filter roster and fuzzy match last name only
    6. Return None — caller skips this player's props

    On match, cache the mapping for future lookups.
    """
```

**Failure handling in `analyze_all_props()`**:
- If `resolve_player` returns None: log warning, skip that player's props entirely
- Never crash the pipeline on a name mismatch
- Track unmatched names in `data/unmatched_players.log` for manual review

### Performance

- Monte Carlo with 5,000 iterations: ~2-5 seconds per game in Python
- 15 games/day: ~30-75 seconds total for all prop simulations
- Player stats API calls: ~30 per game (18 batters + 2 pitchers + lineup), cached per day
- Prop odds API calls: 1 per game (per-event endpoint with all prop markets)

### Error Handling

- If lineup not confirmed: skip MC for that game (props require confirmed lineups)
- If player stats unavailable: use league averages as fallback
- If prop odds unavailable for a player: skip that player's props
- MC engine failure does not affect game-level predictions (independent systems)

---

## Results Grading Updates

### tracker.py
No structural changes needed — the CSV format is already generic (`bet_type`, `side`, `odds`, etc.). New bet types like `nrfi`, `team_total_home`, and prop types like `pitcher_strikeouts` are stored with their bet_type string.

### Grading Strategy by Market Type

| Market Category | Data Needed for Grading | Source |
|----------------|------------------------|--------|
| Game-level (ML, RL, totals) | Final score | Existing `get_scores()` |
| Team totals | Final score per team | Existing `get_scores()` |
| F5/F3/F1 markets | Score by inning | MLB Stats API linescore endpoint |
| NRFI | First inning runs | MLB Stats API linescore endpoint |
| Player props | Box score stats (K, H, TB, RBI, R, ER, IP) | MLB Stats API boxscore endpoint |

**New function**: `scrapers/results.py: get_linescore(game_pk) -> dict`
- Returns inning-by-inning scoring for grading F1/F3/F5 bets
- Already partially available in existing game data

**New function**: `scrapers/results.py: get_boxscore_stats(game_pk) -> dict`
- Returns per-player box score stats for grading prop bets
- Maps player names to {K, H, 2B, 3B, HR, RBI, R, BB, TB} for batters
- Maps pitcher names to {K, H, BB, ER, IP (as outs)} for pitchers

### Monte Carlo Park Factors

The `simulate_game` function accepts separate park factors:
```python
def simulate_game(
    home_lineup, away_lineup, home_pitcher, away_pitcher,
    park_factor_runs: float = 1.0,
    park_factor_hr: float = 1.0,
) -> GameState:
```
- `park_factor_runs` scales all hit probabilities uniformly
- `park_factor_hr` scales HR probability specifically (e.g., Coors = 1.25)
- Both sourced from existing `PARK_FACTORS` dict in config.py

### Pitch Count Model

Estimate pitches per PA by outcome type rather than flat 4:
```python
PITCHES_PER_PA = {
    "K": 4.8,    # strikeouts average more pitches (full counts)
    "BB": 5.6,   # walks require 4+ balls
    "HR": 3.5,   # HRs often on early-count fastballs
    "1B": 3.3,
    "2B": 3.4,
    "3B": 3.2,
    "OUT": 3.4,
}
```
This produces more realistic pitch count tracking for pitcher outs/exit modeling.

---

## Cross-Phase Bonus: MC Validates LLM Predictions

The Monte Carlo engine produces game-level outputs (win probability, total runs, score by inning) that can cross-validate the LLM ensemble's predictions:
- `tied_after_1/3/5` validates LLM tie probability estimates
- `avg_home_score / avg_away_score` validates predicted_score
- `home_wins / n_sims` validates moneyline probability

This creates a feedback loop: if MC and LLM agree, confidence increases. If they disagree significantly, flag for review. This is a future enhancement, not part of the initial implementation.

---

## Testing Strategy

### Phase 1 Tests
- `test_odds_additional.py`: Per-event API parsing, graceful fallback
- `test_edge_phase1.py`: All 7 new edge checkers with known inputs/outputs
- `test_consensus_phase1.py`: Vote extraction for new slots
- `test_briefing_phase1.py`: New odds appear in briefing text

### Phase 2 Tests
- `test_pa_engine.py`: Odds-ratio calculation, PA outcome sampling distribution
- `test_game_sim.py`: Runner advancement, scoring, inning transitions, pitcher exit
- `test_monte_carlo.py`: Distribution shape, convergence (5K sims should stabilize)
- `test_props_edge.py`: Distribution-to-probability conversion, edge detection
- `test_player_stats.py`: API parsing, caching, name resolution

### Integration Tests
- `test_full_pipeline.py`: End-to-end with mocked APIs (screen → sim → MC → edge → log)

---

## File Summary

### Modified Files (Phase 1)
| File | Change |
|------|--------|
| `config.py` | Add 8 new EDGE_THRESHOLDS entries |
| `scrapers/odds.py` | Add 8 new OddsData fields + event_id, add get_additional_odds() |
| `simulate.py` | Expand system prompt with first_inning, first_3, tie probs |
| `briefing.py` | Display new odds in briefing text |
| `edge.py` | Add 7 new edge checker functions, update analyze_all_edges() |
| `ensemble/consensus.py` | Add 8 new BET_SLOT_FIELDS entries |
| `ensemble/orchestrator.py` | Add prob fields + primary fields for new slots |
| `ensemble/weights.py` | Update BET_SLOTS list |
| `main.py` | Add per-event odds fetching + MC integration |

### New Files (Phase 2)
| File | Purpose |
|------|---------|
| `scrapers/player_stats.py` | Fetch per-player stats from MLB Stats API |
| `simulation/__init__.py` | Package init |
| `simulation/pa_engine.py` | Single PA outcome sampling |
| `simulation/game_sim.py` | Full game simulation with state tracking |
| `simulation/monte_carlo.py` | Run N iterations, aggregate distributions |
| `simulation/props_edge.py` | Compare distributions to book prop lines |

### New Test Files
| File | Tests |
|------|-------|
| `tests/test_edge_phase1.py` | 7 new edge checkers |
| `tests/test_odds_additional.py` | Per-event odds parsing |
| `tests/test_pa_engine.py` | PA outcome sampling |
| `tests/test_game_sim.py` | Game simulation logic |
| `tests/test_monte_carlo.py` | MC distribution convergence |
| `tests/test_props_edge.py` | Prop edge detection |
| `tests/test_player_stats.py` | Player stats API + caching |
