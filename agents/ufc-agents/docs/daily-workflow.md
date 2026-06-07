# MiroFish Daily Workflow

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

Scrapes schedule, pitchers, odds, lineups, injuries → screens all games for edge → runs full MiroFish simulation on flagged games → logs bets.

```bash
python main.py daily
# or for a specific date:
python main.py daily --date 2026-03-18
```

**What happens under the hood:**
1. Fetch schedule + probable pitchers
2. Fetch odds from The Odds API
3. Fetch confirmed lineups
4. Fetch injuries
5. Build briefings and run screen pass (Plan B quick sim)
   - Games with edge >= 3% get flagged for full simulation
6. Run full MiroFish ensemble simulation on flagged games
   - 6 models: Kimi, Claude, GPT-4o, Gemini, DeepSeek, Maverick
   - 3 simulation runs per game
   - Consensus voting (min 3 votes)
   - Edge detection across moneyline, run line, total, F5 ML, F5 total

### 4. Review the Bet Card

```bash
python main.py card
# or for a specific date:
python main.py card --date 2026-03-18
```

### 5. Analyze a Single Game (Optional)

```bash
python main.py game NYY BOS
python main.py game NYY BOS --date 2026-03-18
python main.py game NYY BOS --away-pitcher "Gerrit Cole" --home-pitcher "Brayan Bello"
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
| Run line edge | 6% | Min edge to signal a run line bet |
| Total edge | 5% | Min edge to signal a total bet |

---

## Data Files

- `data/bets.csv` — all logged bets and results
- `data/model_weights.json` — ensemble model weights (updated by optimizer)
- `data/model_predictions.csv` — per-model prediction log
