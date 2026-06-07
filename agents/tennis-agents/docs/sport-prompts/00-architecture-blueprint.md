# MiroFish Architecture Blueprint

This is the reference architecture that all sport-specific pipelines follow. Each sport adapts the sport-specific layers (scrapers, briefing, system prompt, bet slots, edge thresholds) while keeping the core engine (ensemble, orchestrator, challenger, edge framework, tracker, agents) identical.

## 6-Layer Pipeline

```
SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET
```

### Layer 1: Scrapers
- Fetch structured data from sport-specific APIs
- Each scraper returns a dict or dataclass
- Scrapers: schedule, matchup-specific stats, odds, injuries, environment/context

### Layer 2: Briefing
- Compile all scraped data into a single structured text prompt
- Sections: header, betting lines, matchup analysis, injuries, context factors, prediction task
- The briefing IS the input to all LLM calls

### Layer 3: Screen Pass (Plan B)
- Single cheap model (Kimi K2.5) at ~$0.06/event
- Parse structured JSON prediction from response
- Run edge detection on screen result
- If max edge >= SCREEN_EDGE_THRESHOLD (3%), flag for full ensemble
- Otherwise discard

### Layer 4: Ensemble (MiroFish)
- 6 models via OpenRouter: Kimi, Claude Sonnet 4, GPT-4o, Gemini 2.5 Flash, DeepSeek R1, Llama 4 Maverick
- Phase 1: All 6 in parallel at temp 0.7 → consensus classification per bet slot
  - Strong (5+ agree) → skip Phase 2
  - Soft (3-4 agree) → expand in Phase 2
  - None (<3 agree) → remove slot
- Phase 2: Temperature expansion (0.5, 0.7, 0.9 x 2 runs) on disagreeing models. Confirming runs (2x) on agreeing models. Stability bonus for consistent models.
- Phase 3: Claude Sonnet 4 adversarial challenger reviews all surviving slots, returns approve/kill per slot
- Final assembly: highest-weighted model as base structure, overlay weighted-average probabilities, remove killed/no-consensus slots

### Layer 5: Edge Detection
- Formula: edge = sim_prob - market_implied_prob
- Per bet slot: if edge >= threshold, signal bet
- Kelly criterion sizing: kelly_fraction * (b*p - q) / b, capped at quarter-Kelly (0.25)
- Output: list of bet signals with type, side, odds, edge, kelly_pct

### Layer 6: Tracking & Optimization
- CSV bet log: date, event, bet_type, side, odds, edge, kelly_pct, result, profit
- Results grader: matches pending bets against final scores, settles W/L/P
- P&L summary: record, profit units, ROI
- Self-optimizer: Brier score per model per bet type → update model_weights.json

### Supporting Agents
- daily_runner: 4-step orchestrator (health → grade yesterday → pipeline → bet card)
- health_check: validate all API connections before running
- results_grader: settle yesterday's bets
- bet_card: formatted ASCII summary of today's picks
- self_optimizer: performance analysis + weight/threshold tuning

### Config Structure
- API keys (ODDS_API_KEY, OPENROUTER_API_KEY, sport-specific API keys)
- API base URLs
- Model configuration (ENSEMBLE_MODELS, ENSEMBLE_CHALLENGER)
- Consensus settings (CONSENSUS_MIN_VOTES=3, MAX_CALLS_PER_GAME=50)
- Kelly fraction (0.25)
- Edge thresholds per bet type
- Sport-specific reference data (teams, venues, etc.)

### System Prompt Structure
The LLM system prompt instructs the model to simulate a panel of 6 domain-expert analysts, each with a specific perspective. The analysts debate, then the model outputs a structured JSON prediction covering all bet types with probabilities, value assessments, and confidence levels.

### JSON Output Schema (adapted per sport)
```json
{
  "analyst_assessments": [
    {"role": "analyst_name", "pick": "SIDE", "reasoning": "..."}
  ],
  "predictions": {
    "bet_slot_1": {
      "prob_field_a": 0.XX,
      "prob_field_b": 0.XX,
      "value_side": "side_a|side_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_score": {"side_a": X, "side_b": X},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
```
