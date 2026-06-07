# MiroFish T20 Cricket Daily Workflow

## Quick Start (One Command)

```bash
python -m agents.daily_runner --grade-yesterday
```

This runs the full workflow: health check → grade yesterday → pipeline → bet card.

---

## Step-by-Step Breakdown

### 1. Health Check

Verify all API connections are working before running anything.

```bash
python main.py health
```

Checks:
- Cricket API (CricketData.org) — CRITICAL
- The Odds API — CRITICAL
- OpenRouter (ensemble LLMs) — CRITICAL
- OpenWeatherMap — OPTIONAL

### 2. Grade Yesterday's Results

Pull final scores and settle any pending bets from the previous day.

```bash
python main.py results
# or for a specific date:
python main.py results --date 2026-03-17
```

Bet types graded:
- **match_winner** (moneyline): team_a win or team_b win
- **total_runs**: over/under on combined innings runs — automatically voided (push) if DLS was applied

### 3. Run the Daily Pipeline

Scrapes schedule, odds, squad updates, toss info, venue stats → screens all matches for edge → runs full MiroFish ensemble simulation on flagged matches → logs bets.

```bash
python main.py daily
# or for a specific date:
python main.py daily --date 2026-03-18
# or for a specific league:
python main.py daily --league ipl
```

**`--league` flag** restricts the pipeline to a single competition. Available leagues:

| Key | League | Season |
|-----|--------|--------|
| `ipl` | Indian Premier League | Mar–May |
| `bbl` | Big Bash League | Dec–Jan |
| `cpl` | Caribbean Premier League | Aug–Sep |
| `psl` | Pakistan Super League | Feb–Mar |
| `hundred` | The Hundred | Jul–Aug |
| `sa20` | SA20 | Jan–Feb |
| `bpl` | Bangladesh Premier League | Jan–Feb |
| `ilt20` | International League T20 | Jan–Feb |

**What happens under the hood:**
1. Fetch schedule for the day's T20 fixtures
2. Fetch odds from The Odds API (American format)
3. Fetch squad/availability updates
4. Fetch toss data and venue stats
5. Build match briefings and run screen pass
   - Matches with edge >= 3% get flagged for full simulation
6. Run full MiroFish ensemble simulation on flagged matches
   - 6 models: Kimi, Claude, GPT-4o, Gemini, DeepSeek, Maverick
   - 3 simulation runs per match
   - Consensus voting (min 3 votes)
   - Edge detection: match winner + total runs only

### 4. Review the Bet Card

```bash
python main.py card
# or for a specific date:
python main.py card --date 2026-03-18
```

---

## Bet Types

MiroFish signals two bet types for T20 cricket:

| Bet Type | Description | Notes |
|----------|-------------|-------|
| `moneyline` | Match winner (team_a / team_b) | American odds |
| `total_runs` | Over/under combined runs | Voided if DLS applied |

Run line and first-5 bets are not supported for T20 cricket.

---

## Key Thresholds (config.py)

| Setting | Value | Meaning |
|---------|-------|---------|
| `SCREEN_EDGE_THRESHOLD` | 3% | Minimum edge to trigger full sim |
| `KELLY_FRACTION` | 0.125 | Eighth-Kelly sizing (T20 volatility) |
| Moneyline edge | 6% | Min edge to signal a moneyline bet |
| Total runs edge | 6% | Min edge to signal a total runs bet |

---

## Data Files

- `data/bets.csv` — all logged bets and results
- `data/model_weights.json` — ensemble model weights (updated by optimizer)
- `data/model_predictions.csv` — per-model prediction log
- `data/cricsheet/` — historical Cricsheet ball-by-ball data (optional)
