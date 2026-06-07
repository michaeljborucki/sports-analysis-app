# MiroFish Pipeline: Parallelization + Full Market Coverage

**Date:** 2026-03-22
**Status:** Design
**Scope:** Restructure the pipeline to run all steps concurrently and expand from 5 bet types to 19 by adding team totals, quarter markets, first-half spread, and player props.

---

## 1. Problem Statement

The pipeline currently times out (>10 min) because it processes games sequentially: 5 games x (5 NBA API calls + 1 LLM screen) = 30+ blocking calls, then N games x full ensemble (7-43 LLM calls each). Additionally, the pipeline only bets on 5 market types despite The Odds API offering 47+ NBA markets, many of which are structurally less efficient than the full-game lines we currently trade.

## 2. Goals

1. **Parallelization:** Process all games concurrently across data gathering, screening, and full ensemble phases. Target: full 5-game slate completes in <3 minutes.
2. **Full market coverage:** Expand to team totals, quarter lines, first-half spread, and player props (points, rebounds, assists, threes, PRA). Add edge detection and Kelly sizing for each new market.
3. **Two-tier LLM prediction:** Game-level predictions (expanded) via the existing 6-model ensemble, plus a dedicated lightweight player-prop prediction pass.

## 3. Architecture Overview

### 3.1 Pipeline Phases (All Parallel)

```
Phase 1 — Data Gathering (3 calls in parallel, ~2s)
├── get_todays_games()
├── get_nba_odds_bulk()          # bulk endpoint: h2h, spreads, totals + event IDs
└── get_injuries()

Phase 2 — Extended Odds (parallel per game, ~3s)
├── Game 1: get_event_odds(event_id)  ─┐
├── Game 2: get_event_odds(event_id)   ├── all games concurrently
└── ...                                ─┘  (H1, H2, Q1-Q4, team totals, player props)

Phase 3 — Per-Game Enrichment (parallel across games, ~5s)
├── Game 1: [team_profile x2, rest x2, matchup]  ─┐
├── Game 2: [team_profile x2, rest x2, matchup]   ├── all games concurrently
└── ...                                            ─┘  (5 calls per game, also concurrent)

Phase 4 — Screening (parallel across games, ~30s)
├── Game 1: run_plan_b(brief)  ─┐
├── Game 2: run_plan_b(brief)   ├── all screens concurrently
└── ...                        ─┘

Phase 5 — Full Ensemble (parallel across flagged games, ~90s)
├── Game A: run_mirofish(brief)  ─┐
├── Game B: run_mirofish(brief)   ├── games concurrently
└── ...                           ─┘
    (within each game, Phase 1/2 of ensemble already parallelize models)

Phase 6 — Player Prop Predictions (parallel across flagged games, ~30s)
├── Game A: run_prop_ensemble(brief, prop_lines)  ─┐
├── Game B: run_prop_ensemble(brief, prop_lines)   ├── games concurrently
└── ...                                            ─┘
    (3-model lightweight ensemble: kimi, gpt4o, deepseek)
```

### 3.2 Implementation Approach

Use `asyncio` as the orchestration layer with `asyncio.to_thread()` for blocking calls (NBA API via `requests`, existing `ThreadPoolExecutor` code in ensemble). The main `daily` command becomes an async function.

The `daily_runner.py` will call the pipeline directly (not as subprocess) to eliminate subprocess overhead and the 10-minute timeout issue. Keep a configurable per-game timeout of 300s (existing `GAME_TIMEOUT`).

**Concurrent output:** Use `logging` (already configured) instead of `click.echo()` for concurrent phases. `click.echo()` is not async-safe and will garble output when multiple games run in parallel. Use a per-game log prefix (e.g., `[BOS@NYK]`) for disambiguation. Reserve `click.echo()` for sequential summary output at the end.

### 3.3 Concurrency Limits

- NBA API calls: max 5 concurrent (rate-limited)
- Odds API calls: max 5 concurrent (30 req/sec limit)
- LLM calls (OpenRouter): max 12 concurrent (6 per game x 2 games, or uncapped for screening)
- Total per-game ensemble calls: existing `MAX_CALLS_PER_GAME = 50` cap preserved

## 4. Odds Fetching Architecture

### 4.1 Two-Phase Fetch

**Phase 1 — Bulk endpoint** (1 API call):
```
GET /v4/sports/basketball_nba/odds?markets=h2h,spreads,totals&regions=us&oddsFormat=american
```
Returns all games with core lines. **Important:** Extract `event_id = event["id"]` from each event during bulk parse and store in `OddsData.event_id`. This is required for Phase 2 per-event calls. The current `get_nba_odds()` does not read this field — it must be added.

Also implement bookmaker preference ordering: sort bookmakers by `["draftkings", "fanduel", "betmgm"]` priority and take the first match. The current code takes the first bookmaker with moneyline data (arbitrary order via `break` on line 116 of `odds.py`), which does not guarantee consistent pricing.

**Phase 2 — Per-event endpoint** (1 call per game, parallel):
```
GET /v4/sports/basketball_nba/events/{eventId}/odds?markets=
  h2h_h1,spreads_h1,totals_h1,
  h2h_h2,spreads_h2,totals_h2,
  h2h_q1,spreads_q1,totals_q1,
  totals_q2,totals_q3,totals_q4,
  team_totals,
  alternate_spreads,alternate_totals,
  player_points,player_rebounds,player_assists,
  player_threes,player_points_rebounds_assists
```

### 4.2 API Cost

Per run: 1 (bulk) + N (per-event) calls. With ~20 markets returned per event call and 1 region, cost is approximately 20 credits per event + 3 for the bulk = ~103 credits for a 5-game slate. At 99K remaining, this supports ~960 full runs.

### 4.3 Expanded OddsData Model

```python
@dataclass
class OddsData:
    home: str
    away: str
    event_id: str                                          # NEW
    commence_time: str
    # Full game (existing)
    moneyline: dict = field(default_factory=dict)
    spread: dict = field(default_factory=dict)
    total: dict = field(default_factory=dict)
    # Half markets
    h1_moneyline: dict = field(default_factory=dict)       # existing
    h1_spread: dict = field(default_factory=dict)          # existing
    h1_total: dict = field(default_factory=dict)           # existing
    h2_moneyline: dict = field(default_factory=dict)       # NEW
    h2_spread: dict = field(default_factory=dict)          # NEW
    h2_total: dict = field(default_factory=dict)           # NEW
    # Quarter markets (NEW)
    q1_moneyline: dict = field(default_factory=dict)
    q1_spread: dict = field(default_factory=dict)
    q1_total: dict = field(default_factory=dict)
    q2_moneyline: dict = field(default_factory=dict)
    q2_spread: dict = field(default_factory=dict)
    q2_total: dict = field(default_factory=dict)
    q3_moneyline: dict = field(default_factory=dict)
    q3_spread: dict = field(default_factory=dict)
    q3_total: dict = field(default_factory=dict)
    q4_moneyline: dict = field(default_factory=dict)
    q4_spread: dict = field(default_factory=dict)
    q4_total: dict = field(default_factory=dict)
    # Team totals (NEW)
    team_totals: dict = field(default_factory=dict)        # {home: {line, over_odds, under_odds}, away: {...}}
    # Alternate lines (NEW)
    alt_spreads: list = field(default_factory=list)         # [{point, home_odds, away_odds}, ...]
    alt_totals: list = field(default_factory=list)          # [{line, over_odds, under_odds}, ...]
    # Player props (NEW)
    player_props: dict = field(default_factory=dict)        # {player_name: {points: {line, over, under}, ...}}
    # Implied probs (existing)
    implied_probs: dict = field(default_factory=dict)
```

### 4.4 Player Props Structure

```python
player_props = {
    "Jayson Tatum": {
        "points": {"line": 26.5, "over_odds": -115, "under_odds": -105},
        "rebounds": {"line": 8.5, "over_odds": -110, "under_odds": -110},
        "assists": {"line": 5.5, "over_odds": +100, "under_odds": -120},
        "threes": {"line": 3.5, "over_odds": -105, "under_odds": -115},
        "pra": {"line": 40.5, "over_odds": -110, "under_odds": -110},
    },
    "Jaylen Brown": { ... },
}
```

Bookmaker preference order: DraftKings > FanDuel > BetMGM > first available. One bookmaker per game for consistency.

## 5. LLM Prompt Architecture

### 5.1 Tier 1 — Game-Level Predictions (Expanded)

The existing `NBA_SYSTEM_PROMPT` in `simulate.py` is extended to request additional prediction sections. The 6-analyst panel and JSON-only format remain unchanged.

**New JSON output sections added to existing prompt:**

```json
{
  "predictions": {
    "moneyline": { ... },                    // existing
    "spread": { ... },                       // existing
    "total": { ... },                        // existing
    "first_half": {                          // existing, EXPANDED
      "h1_home_win_prob": 0.55,
      "h1_away_win_prob": 0.45,
      "h1_projected_total": 112.0,
      "h1_favorite_cover_prob": 0.53,        // NEW — for first_half_spread
      "h1_ml_value": "home|away|none",
      "h1_total_value": "over|under|none",
      "h1_spread_value": "favorite|underdog|none",  // NEW
      "confidence": "low|medium|high"
    },
    "second_half": {                         // NEW
      "h2_home_win_prob": 0.56,
      "h2_projected_total": 109.5
    },
    "q1": {                                  // NEW
      "q1_home_win_prob": 0.54,
      "q1_projected_total": 56.5,
      "q1_favorite_cover_prob": 0.52,
      "q1_ml_value": "home|away|none",
      "q1_spread_value": "favorite|underdog|none",
      "q1_total_value": "over|under|none"
    },
    "team_totals": {                         // NEW
      "home_projected": 114.5,
      "away_projected": 107.0,
      "home_value": "over|under|none",
      "away_value": "over|under|none"
    },
    "predicted_score": { ... },              // existing
    "key_factors": [ ... ]                   // existing
  }
}
```

**Quarter derivation (Q2-Q4):** Rather than asking models to predict all 4 quarters (research shows LLMs are bad at this), derive Q2-Q4 mathematically from stronger predictions:
- Q2 projected total = H1 projected total - Q1 projected total
- H2 projected total = game total - H1 projected total
- Q3 projected total = H2 projected total * 0.52 (Q3 typically higher-scoring than Q4)
- Q4 projected total = H2 projected total * 0.48 (late-game pace variability)
- Quarter ML probs derived from game ML + reversion to 50% based on quarter length

**Q2-Q4 edge detection uses derived projections vs actual bookmaker odds.** The Odds API does serve Q2-Q4 odds lines (totals_q2, totals_q3, totals_q4 via per-event endpoint). These bookmaker lines provide the implied probabilities needed for edge calculation. The model's projection is derived; the market's line comes from the API.

### 5.2 Tier 2 — Player Prop Predictions (New, Separate Pass)

Runs AFTER the game-level ensemble, only for games that pass screening. Uses a lighter 3-model ensemble (kimi, gpt4o, deepseek — cheapest models with positive edge signals).

**System prompt:**
```
You are an NBA player prop prediction system. Given a game briefing and
sportsbook player prop lines, predict whether each player's stat line will
go OVER or UNDER their posted line.

Consider: projected minutes, matchup quality, pace, injury context,
role/usage changes, defensive matchup (rim protector vs perimeter),
and recent form (last 5 games).

Respond in valid JSON only:
{
  "player_props": {
    "Player Name": {
      "points": {"over_prob": 0.XX, "projected": XX.X},
      "rebounds": {"over_prob": 0.XX, "projected": X.X},
      "assists": {"over_prob": 0.XX, "projected": X.X},
      "threes": {"over_prob": 0.XX, "projected": X.X},
      "pra": {"over_prob": 0.XX, "projected": XX.X}
    }
  }
}
```

**User prompt includes:** Full game briefing + formatted player prop lines from odds API.

**Ensemble:** Simple parallel 3-model call, average probabilities. No Phase 2/3 expansion (cost control). Cost: ~$1-2 per game.

### 5.3 Briefing Expansion

`build_briefing()` adds new sections:

```
== TEAM TOTALS ==
  {home} O/U: {line} (Over {over_odds} / Under {under_odds})
  {away} O/U: {line} (Over {over_odds} / Under {under_odds})

== QUARTER 1 LINES ==
  Q1 ML: {home} {odds} / {away} {odds}
  Q1 Spread: {home} {point} ({odds})
  Q1 Total: {line} (Over {odds} / Under {odds})
```

Player prop lines are passed only to the Tier 2 prompt, not the main briefing (to avoid prompt bloat).

## 6. Edge Detection Expansion

### 6.1 Bet Types (19 total)

**Game-level ensemble slots (14):** These go through the full 3-phase ensemble with consensus voting, temperature expansion, and adversarial challenge.

```python
GAME_BET_SLOTS = [
    # Full game (existing)
    "moneyline", "spread", "total",
    # First half (existing + new)
    "first_half_ml", "first_half_total", "first_half_spread",
    # Quarter 1 (new, LLM-predicted)
    "q1_ml", "q1_spread", "q1_total",
    # Quarters 2-4 (new, derived from LLM predictions)
    "q2_total", "q3_total", "q4_total",
    # Team totals (new)
    "team_total_home", "team_total_away",
]
```

**Player prop slots (5):** These use the Tier 2 lightweight ensemble (3 models, no consensus/challenger). Each slot can produce 0-N bets (one per player).

```python
PROP_BET_SLOTS = [
    "player_points", "player_rebounds", "player_assists",
    "player_threes", "player_pra",
]

BET_SLOTS = GAME_BET_SLOTS + PROP_BET_SLOTS  # 19 total
```

### 6.2 Edge Thresholds (Tiered by Market Efficiency)

```python
EDGE_THRESHOLDS = {
    # Full game — most efficient, highest thresholds
    "moneyline": 0.05,
    "spread": 0.06,
    "total": 0.05,
    # Half markets
    "first_half_ml": 0.05,
    "first_half_total": 0.05,
    "first_half_spread": 0.05,
    # Quarter 1 — less efficient, lower thresholds
    "q1_ml": 0.04,
    "q1_spread": 0.05,
    "q1_total": 0.04,
    # Quarters 2-4 — derived predictions, higher uncertainty
    "q2_total": 0.05,
    "q3_total": 0.05,
    "q4_total": 0.05,
    # Team totals — independently priced, structural inefficiency
    "team_total_home": 0.04,
    "team_total_away": 0.04,
    # Player props — least efficient, most opportunity
    "player_points": 0.04,
    "player_rebounds": 0.03,
    "player_assists": 0.03,
    "player_threes": 0.05,       # high variance needs bigger edge
    "player_pra": 0.03,
}
```

### 6.3 New Edge Check Functions

Each follows the same pattern as existing checks (compare sim_prob vs implied_prob, apply Kelly):

- `check_first_half_spread_edge()` — mirrors `check_spread_edge()` with H1 odds
- `check_q1_ml_edge()` — mirrors `check_moneyline_edge()` with Q1 odds
- `check_q1_spread_edge()` — mirrors `check_spread_edge()` with Q1 odds
- `check_q1_total_edge()` — mirrors `check_total_edge()` with Q1 odds
- `check_quarter_total_edge(quarter)` — for Q2-Q4 using derived projections
- `check_team_total_edge(side)` — over/under on team-specific total
- `check_player_prop_edge(prop_type)` — iterates all players for a given prop type, returns 0-N bets

### 6.4 Edge Detection Integration

**Game-level bets** use the existing `analyze_all_edges(sim, odds)` pattern — one checker per slot, each returning 0 or 1 bet. Expand the checkers list to include all 14 game-level slots.

**Player prop bets** use a separate entry point since they return multiple bets per slot:

```python
def analyze_prop_edges(prop_predictions: dict, odds: dict) -> list[dict]:
    """Run prop edge checks. Returns 0-N bets across all players and prop types.

    prop_predictions comes from Tier 2 ensemble (separate from game-level sim).
    odds contains player_props dict from OddsData.
    """
    bets = []
    for prop_type in PROP_BET_SLOTS:
        prop_bets = check_player_prop_edge(prop_predictions, odds, prop_type)
        bets.extend(prop_bets)
    return bets
```

The main pipeline calls both: `analyze_all_edges()` for game bets, then `analyze_prop_edges()` for props. Results are combined before logging.

### 6.5 Alternate Line Optimization

When a standard-line bet is found with edge, check if an alternate line offers better Kelly-optimal risk/reward:

```python
def optimize_with_alt_lines(bet: dict, alt_lines: list) -> dict:
    """Check if an alternate line improves expected value.

    Example: Model says 'home covers -5.5' with 8% edge.
    Check if alt -3.5 at worse odds still has positive Kelly
    and if alt -7.5 at better odds has higher EV.
    """
    best = bet
    for alt in alt_lines:
        alt_edge = compute_edge(bet["sim_prob"], alt["odds"])
        alt_kelly = kelly_criterion(bet["sim_prob"], american_to_decimal(alt["odds"]))
        if alt_kelly * KELLY_FRACTION > best["kelly_pct"]:
            best = {**bet, "odds": alt["odds"], "side": alt["label"],
                    "edge": alt_edge, "kelly_pct": alt_kelly * KELLY_FRACTION}
    return best
```

## 7. Ensemble & Weight Updates

### 7.1 BET_SLOTS Expansion

`ensemble/weights.py` `BET_SLOTS` expands to include all new bet types. Existing weight files auto-migrate: missing slots get default weight 1.0.

### 7.2 PROB_FIELDS / SLOT_SECTION / PRIMARY_PROB_FIELD Expansion

`ensemble/orchestrator.py` mapping dicts expand. **Important:** These dicts only cover `GAME_BET_SLOTS` (14 slots), not `PROP_BET_SLOTS` (which bypass the ensemble).

```python
PROB_FIELDS = {
    # existing
    "moneyline": ["home_win_prob", "away_win_prob"],
    "spread": ["favorite_cover_prob"],
    "total": ["over_prob", "under_prob", "projected_total"],
    "first_half_ml": ["h1_home_win_prob", "h1_away_win_prob"],
    "first_half_total": ["h1_projected_total"],
    # new
    "first_half_spread": ["h1_favorite_cover_prob"],
    "q1_ml": ["q1_home_win_prob"],
    "q1_spread": ["q1_favorite_cover_prob"],
    "q1_total": ["q1_projected_total"],
    # Q2-Q4 are derived, not from LLM — no PROB_FIELDS entries needed
    # (computed post-ensemble in a derivation step)
    "team_total_home": ["home_projected"],
    "team_total_away": ["away_projected"],
}

SLOT_SECTION = {
    # existing
    "moneyline": "moneyline",
    "spread": "spread",
    "total": "total",
    "first_half_ml": "first_half",
    "first_half_total": "first_half",
    # new
    "first_half_spread": "first_half",
    "q1_ml": "q1",
    "q1_spread": "q1",
    "q1_total": "q1",
    "team_total_home": "team_totals",
    "team_total_away": "team_totals",
}

PRIMARY_PROB_FIELD = {
    # existing
    "moneyline": "home_win_prob",
    "spread": "favorite_cover_prob",
    "total": "over_prob",
    "first_half_ml": "h1_home_win_prob",
    "first_half_total": "h1_projected_total",
    # new
    "first_half_spread": "h1_favorite_cover_prob",
    "q1_ml": "q1_home_win_prob",
    "q1_spread": "q1_favorite_cover_prob",
    "q1_total": "q1_projected_total",
    "team_total_home": "home_projected",
    "team_total_away": "away_projected",
}
```

### 7.3 BET_SLOT_FIELDS Expansion (consensus.py)

**Critical:** `ensemble/consensus.py` `BET_SLOT_FIELDS` maps each slot to `(section_key, vote_field)` for `extract_vote()`. Every new game-level slot needs an entry or `extract_vote()` will `KeyError`.

```python
BET_SLOT_FIELDS = {
    # existing
    "moneyline": ("moneyline", "value_side"),
    "spread": ("spread", "value_side"),
    "total": ("total", "value_side"),
    "first_half_ml": ("first_half", "h1_ml_value"),
    "first_half_total": ("first_half", "h1_total_value"),
    # new
    "first_half_spread": ("first_half", "h1_spread_value"),
    "q1_ml": ("q1", "q1_ml_value"),
    "q1_spread": ("q1", "q1_spread_value"),
    "q1_total": ("q1", "q1_total_value"),
    # Q2-Q4 derived slots don't go through consensus (no LLM votes)
    "team_total_home": ("team_totals", "home_value"),
    "team_total_away": ("team_totals", "away_value"),
}
```

**Note:** Q2-Q4 total slots (`q2_total`, `q3_total`, `q4_total`) are derived mathematically, not voted on by models. They must be excluded from the consensus loop in the orchestrator. Add them to a `DERIVED_SLOTS` set that the orchestrator skips during `classify_consensus()` and `build_ensemble_result()`.

### 7.4 Challenger Kill Logic (orchestrator.py)

**Critical:** `build_ensemble_result()` currently has hardcoded kill logic for 5 slots (lines 427-464). Replace with a generalized approach:

```python
for slot in killed_by_challenger:
    section_key = SLOT_SECTION.get(slot)
    if not section_key:
        continue
    # For sub-sections (first_half, q1), remove only the slot's fields
    fields_to_remove = PROB_FIELDS.get(slot, [])
    vote_field = BET_SLOT_FIELDS.get(slot, (None, None))[1]
    section = predictions.get(section_key, {})
    for f in fields_to_remove + ([vote_field] if vote_field else []):
        section.pop(f, None)
    # If all sub-slots in this section are killed, remove entire section
    section_slots = [s for s, sec in SLOT_SECTION.items() if sec == section_key]
    if all(s in killed_by_challenger for s in section_slots):
        predictions.pop(section_key, None)
```

### 7.5 Consensus & Challenger

The ensemble iterates `GAME_BET_SLOTS` (not full `BET_SLOTS`) for consensus voting and adversarial challenge, skipping `DERIVED_SLOTS` and `PROP_BET_SLOTS`.

Player prop bets bypass the full ensemble entirely — they use the Tier 2 lightweight ensemble and go directly to `analyze_prop_edges()` without consensus or challenger phases.

### 7.6 _average_results() Expansion (simulate.py)

The `_average_results()` fallback function must expand its `prob_fields` dict to cover new sections:

```python
prob_fields = {
    "moneyline": ["home_win_prob", "away_win_prob", "edge"],
    "spread": ["favorite_cover_prob", "edge"],
    "total": ["projected_total", "over_prob", "under_prob", "edge"],
    "first_half": ["h1_home_win_prob", "h1_away_win_prob",
                    "h1_projected_total", "h1_favorite_cover_prob"],
    "second_half": ["h2_home_win_prob", "h2_projected_total"],
    "q1": ["q1_home_win_prob", "q1_projected_total", "q1_favorite_cover_prob"],
    "team_totals": ["home_projected", "away_projected"],
}
```

## 8. Tracker & Results Grading

### 8.1 Tracker Updates

`tracker.py` `COLUMNS` adds `confidence`, `market`, and `player` fields:

```python
COLUMNS = [
    "date", "game", "bet_type", "side", "odds", "sim_prob",
    "edge", "kelly_pct", "confidence", "market", "player",
    "result", "profit",
]
```

`market` = "game" or "prop". `player` = player name for props, empty for game bets.

**CSV backward compatibility:** `load_bets()` must handle existing CSV files missing new columns. Use `pd.read_csv()` then add missing columns with defaults:

```python
def load_bets(csv_path=None):
    csv_path = csv_path or BETS_CSV
    _ensure_csv(csv_path)
    df = pd.read_csv(csv_path)
    # Backward compat: add missing columns with defaults
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[COLUMNS]  # reorder to canonical order
```

### 8.2 Results Grading

**Pre-existing bug to fix:** `agents/results_grader.py` line 62 checks `bet_type == "first_half"` but bets are logged as `"first_half_ml"` and `"first_half_total"`. This causes all first-half bets to grade as losses. Fix as prerequisite.

**New grading logic by bet type:**

| Bet Type | Data Source | Grading Logic |
|----------|-------------|---------------|
| `moneyline`, `spread`, `total` | Final scores (existing) | Existing logic (works) |
| `first_half_*` | `ScoreboardV2` line scores | Sum Q1+Q2 scores per team |
| `q1_*` | `ScoreboardV2` line scores | Q1 period scores |
| `q2_total` - `q4_total` | `ScoreboardV2` line scores | Individual quarter scores |
| `team_total_*` | Final scores | Individual team final scores |
| `player_*` | `BoxScoreTraditionalV2` | Player stat lines (PTS, REB, AST, FG3M) |

The grader needs a new `grade_player_props()` function that:
1. Fetches box scores via `BoxScoreTraditionalV2` (new `scrapers/player_stats.py`)
2. Matches player names to bet records
3. Compares actual stats to the `side` field (e.g., "over 26.5" → check if PTS > 26.5)

## 9. Configuration Updates

```python
# config.py additions

# Odds API — per-event endpoint
ODDS_EVENT_ENDPOINT = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/events"
ODDS_EVENT_MARKETS = (
    "h2h_h1,spreads_h1,totals_h1,"
    "h2h_h2,spreads_h2,totals_h2,"
    "h2h_q1,spreads_q1,totals_q1,"
    "totals_q2,totals_q3,totals_q4,"
    "team_totals,"
    "alternate_spreads,alternate_totals,"
    "player_points,player_rebounds,player_assists,"
    "player_threes,player_points_rebounds_assists"
)

# Player prop ensemble (lighter, cheaper)
PROP_ENSEMBLE_MODELS = ["kimi", "gpt4o", "deepseek"]

# Pipeline concurrency
MAX_CONCURRENT_GAMES = 6
MAX_CONCURRENT_API_CALLS = 5

# Quarter scoring split (Q3 typically slightly higher-scoring than Q4)
Q3_SCORING_SHARE = 0.52   # of H2 total
Q4_SCORING_SHARE = 0.48   # of H2 total
```

## 10. Files Modified

| File | Change |
|------|--------|
| `main.py` | Rewrite `daily()` as async with parallel phases |
| `scrapers/odds.py` | Add `get_event_odds()`, expand `OddsData`, two-phase fetch |
| `briefing.py` | Add team totals, Q1 lines sections |
| `simulate.py` | Expand `NBA_SYSTEM_PROMPT`, add `PROP_SYSTEM_PROMPT`, add `run_prop_ensemble()` |
| `edge.py` | Add 11 new edge check functions, `optimize_with_alt_lines()`, expand `analyze_all_edges()` |
| `config.py` | Add new thresholds, endpoints, concurrency settings |
| `ensemble/weights.py` | Expand `BET_SLOTS` |
| `ensemble/orchestrator.py` | Expand `PROB_FIELDS`, `SLOT_SECTION`, `PRIMARY_PROB_FIELD`; generalize kill logic |
| `ensemble/consensus.py` | Expand `BET_SLOT_FIELDS` for all new game-level slots |
| `tracker.py` | Add `confidence` and `market` columns |
| `agents/daily_runner.py` | Call pipeline directly instead of subprocess, increase timeout |
| `agents/results_grader.py` | Fix first_half grading bug; add quarter, team total, and player prop grading |

## 11. New Files

| File | Purpose |
|------|---------|
| `scrapers/player_stats.py` | Fetch player box scores for prop grading (using `BoxScoreTraditionalV2`) |

## 12. Risk Mitigations

1. **API quota:** Per-event calls are expensive. Cache odds for 5 minutes to avoid redundant calls on retries.
2. **Prompt length:** Player prop lines for a full game (~20 players x 5 props) could be large. Limit to top 8 players per team by minutes played.
3. **LLM accuracy on props:** This is empirically unproven. Track prop bet performance separately and disable prop betting if ROI goes below -10% after 50 bets.
4. **Rate limiting:** Bound all concurrent API calls. Use `asyncio.Semaphore` for each external service.
5. **Graceful degradation:** If per-event odds call fails for a game, proceed with bulk-endpoint data only (no props/quarters). If prop ensemble fails, skip props for that game.

## 13. Success Criteria

1. Full 5-game slate completes in <3 minutes (down from >10 min timeout)
2. All 47+ Odds API markets are fetched and available for analysis
3. Edge detection runs on 19 bet types per game (14 game-level + 5 player prop categories)
4. Player prop predictions generate bets when edge exists
5. Results grader correctly scores all new bet types
6. No regression in existing bet type performance
