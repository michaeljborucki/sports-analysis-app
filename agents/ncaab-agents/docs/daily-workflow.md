# MiroFish NCAAB Daily Workflow

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

### 2. Grade Yesterday's Results

Pull final scores and settle any pending bets from the previous day.

```bash
python main.py results
# or for a specific date:
python main.py results --date 2026-03-17
```

### 3. Run the Daily Pipeline

Scrapes schedule, team efficiency stats, odds, injuries → screens all games for edge → runs full MiroFish simulation on flagged games → logs bets.

```bash
python main.py daily
# or for a specific date:
python main.py daily --date 2026-03-18
```

**What happens under the hood:**
1. Fetch schedule from ESPN
2. Fetch odds from The Odds API
3. Fetch team efficiency ratings from CBBData/Bart Torvik
4. Fetch injuries (best-effort — NCAA has no mandatory reporting)
5. Build briefings and run screen pass (Plan B quick sim)
   - Games with edge >= 3% get flagged for full simulation
6. Run full MiroFish ensemble simulation on flagged games
   - 6 models: Kimi, Claude, GPT-4o, Gemini, DeepSeek, Maverick
   - 3-phase adaptive ensemble with adversarial challenge
   - Consensus voting (min 3 votes)
   - Edge detection across moneyline, spread, total, 1H ML, 1H total

### 4. Review the Bet Card

```bash
python main.py card
# or for a specific date:
python main.py card --date 2026-03-18
```

### 5. Analyze a Single Game (Optional)

```bash
python main.py game "Duke" "North Carolina"
python main.py game "Duke" "North Carolina" --date 2026-03-18
```

---

## Weekly / Periodic

### Check P&L

```bash
python main.py report
```

### Run the Self-Optimizer

Analyzes performance by bet type, edge bucket, and odds range. Recommends threshold adjustments. Needs 30+ settled bets to run.

```bash
python main.py optimize
python main.py optimize --min-bets 20
```

---

## Key Thresholds (config.py)

| Setting | Value | Meaning |
|---|---|---|
| `SCREEN_EDGE_THRESHOLD` | 3% | Minimum edge to trigger full sim |
| `KELLY_FRACTION` | 0.25 | Quarter-Kelly sizing |
| Moneyline edge | 5% | Min edge to signal a moneyline bet |
| Spread edge | 5% | Min edge to signal a spread bet |
| Total edge | 5% | Min edge to signal a total bet |
| 1H ML edge | 5% | Min edge to signal a first half ML bet |
| 1H Total edge | 5% | Min edge to signal a first half total bet |

---

## Data Files

- `data/bets.csv` — all logged bets and results
- `data/model_weights.json` — ensemble model weights (updated by optimizer)
- `data/model_predictions.csv` — per-model prediction log
