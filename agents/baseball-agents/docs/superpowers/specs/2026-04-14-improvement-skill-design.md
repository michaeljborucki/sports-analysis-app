# MiroFish Improvement Skill Design

**Date:** 2026-04-14
**Status:** Draft
**Author:** Claude + Mike Borucki

## Overview

An on-demand skill (`/improve`) that launches a parallel swarm of specialized sub-agents to analyze the MiroFish betting system's historical performance, validate its mathematical models, and research external techniques -- then synthesizes everything into a prioritized improvement report.

## Goals

1. **Bet selection quality** -- Identify which bets, thresholds, and filters are working or not
2. **Mathematical rigor** -- Validate probability models, Kelly sizing, calibration, and simulation assumptions
3. **External research** -- Find cutting-edge techniques from academia and sharp bettors that we're not using

## Non-Goals

- Automatically implementing changes (report only, user decides)
- Real-time or scheduled execution (on-demand only)
- Modifying any production code or config during the analysis

## Invocation

```
/improve
```

No arguments. Always analyzes the full current dataset in `data/bets.csv` and `data/model_weights.json`.

## Output

A markdown report saved to `docs/superpowers/reports/YYYY-MM-DD-improvement-report.md`.

### Report Structure

```
# MiroFish Improvement Report -- YYYY-MM-DD

## Executive Summary
- 3-5 bullet points, most important findings

## 1. Bet Selection Quality
### 1a. Performance by Edge Bucket
### 1b. Performance by Bet Type
### 1c. Threshold Optimization Results
### 1d. Portfolio Allocation Recommendations

## 2. Model & Ensemble Performance
### 2a. Model Accuracy by Bet Slot
### 2b. Weight Adjustment Recommendations
### 2c. Challenger Kill Rate Analysis

## 3. Mathematical Model Validation
### 3a. Negative Binomial Dispersion Check
### 3b. Log5 Matchup Validation
### 3c. Base Running Probability Check
### 3d. Edge Cap Assessment
### 3e. Kelly Fraction Optimization

## 4. Prop Market Analysis
### 4a. Prop Performance by Type
### 4b. Systematic Biases
### 4c. Monte Carlo Accuracy

## 5. External Research Findings
### 5a. Academic Research
### 5b. Sharp Bettor Intelligence

## 6. Priority Action List
| Rank | Recommendation | Expected Impact | Confidence | Effort |
|------|---------------|-----------------|------------|--------|
| 1    | ...           | ...             | ...        | ...    |
```

## Architecture: Parallel Research Swarm

All 8 sub-agents launch simultaneously via the Agent tool. After all complete, a 9th Synthesis Agent assembles the report.

```
/improve invoked
    |
    +---> [Agent 1: Quant Analyst]--------+
    +---> [Agent 2: Threshold Optimizer]--+
    +---> [Agent 3: Model Weight Auditor]-+
    +---> [Agent 4: Simulation Validator]-+---> [Agent 9: Synthesis] ---> Report
    +---> [Agent 5: Academic Researcher]--+
    +---> [Agent 6: Sharp Bettor Intel]---+
    +---> [Agent 7: Prop Market Analyst]--+
    +---> [Agent 8: Bet Type Profiler]----+
```

### Agent 1: Quant Analyst

**Tools:** Read, Bash (Python)
**Mandate:** Cross-cutting statistical analysis of historical bet performance. Focus on patterns that span bet types -- leave per-type breakdowns to Agent 8.

Analyses to run:
- ROI by edge bucket (3-5%, 5-8%, 8-12%, 12-15%) -- do higher edges produce higher ROI?
- ROI by model agreement level (strong vs soft consensus) if data available
- Calibration curve: win rate vs predicted probability, binned by decile
- Profit breakdown by day of week, home/away, odds range (heavy juice vs plus money)
- Streak analysis: are losses clustered or random?
- Unit-weighted vs Kelly-weighted P&L comparison
- Data gap note: closing odds are not currently logged. Recommend whether to add CLV tracking.

**Output:** Structured findings with tables and specific numbers.

### Agent 2: Threshold Optimizer

**Tools:** Read, Bash (Python)
**Mandate:** Find optimal edge thresholds and Kelly fraction via historical backtesting.

Analyses to run:
- For each of all 23 bet types (13 game-level + 10 prop types), simulate alternative edge thresholds (1% increments from 3% to 15%)
- For each threshold, compute: number of bets that would have been taken, win rate, ROI, total profit
- Identify the threshold that maximizes ROI per type
- Test Kelly fractions from 0.10 to 0.50 in 0.05 increments against historical results
- Test whether the 15% edge cap is leaving money on the table or protecting us

**Output:** Optimal threshold table (all 23 types), Kelly fraction recommendation, edge cap recommendation.

### Agent 3: Model Weight Auditor

**Tools:** Read, Bash (Python)
**Mandate:** Evaluate ensemble model accuracy and recommend weight adjustments.

**Data sources:** `data/model_predictions.csv` (per-model, per-bet-type, per-temperature predictions) joined against `data/bets.csv` on date+game+bet_type to correlate predictions with outcomes. Note: bet_type naming may differ between files -- agent must handle mapping.

Analyses to run:
- Compare per-model predictions to outcomes per bet slot using model_predictions.csv
- If join is not possible, fall back to analyzing which bet types have best/worst ROI as a proxy for ensemble quality
- Check challenger kill rate: how many killed bets would have won vs lost?
- Analyze whether Phase 2 (temperature expansion) improves or hurts accuracy

**Output:** Per-model, per-slot weight recommendations. Challenger effectiveness assessment.

### Agent 4: Simulation Validator

**Tools:** Read, Bash (Python), WebSearch, WebFetch
**Mandate:** Validate mathematical assumptions in the simulation engine.

**Note:** `bets.csv` does not contain actual game scores -- only W/L/P results. For run distribution analysis, use the MLB Stats API or scrapers to pull historical scores for games in the bet log.

Analyses to run:
- Fetch actual run totals for games in bets.csv via `scrapers/scores.py` and compare against negbin dispersion parameters (1.8 game total, 2.1 team totals, 1.5 F5, 1.3 F3) -- do the observed distributions fit?
- Check if log5 matchup probabilities align with observed win rates (sim_prob vs result in bets.csv)
- Search the web for current MLB base running advancement rates and compare against the Retrosheet 2015 values hardcoded in game_sim.py
- Assess whether the 15% edge cap is statistically justified (what % of uncapped edges would have been profitable?)
- Check devig calibration: when devigged market_prob = X%, do those bets win ~X% of the time?

**Output:** Parameter adjustment recommendations with statistical justification.

### Agent 5: Academic Researcher

**Tools:** WebSearch, WebFetch
**Mandate:** Find relevant academic research on MLB prediction and sports betting.

Search targets:
- Recent papers on MLB game prediction models (Bayesian, neural, Markov chain)
- Sports betting market efficiency research (how efficient are MLB markets?)
- Pitcher fatigue and spin rate modeling
- Optimal bet sizing beyond Kelly (fractional Kelly, risk of ruin)
- Platoon splits and matchup-specific modeling
- Weather impact on MLB run scoring (quantified)
- Closing line value as a predictor of long-term profitability

**Output:** Summary of 5-10 most relevant papers/findings with applicability to our system.

### Agent 6: Sharp Bettor Intel

**Tools:** WebSearch, WebFetch
**Mandate:** Research professional sports betting strategies relevant to MLB.

Search targets:
- Closing line value (CLV) -- how sharps measure edge quality
- Reverse line movement and steam move detection
- Situational angles (day-after-night, travel distance, bullpen usage patterns)
- How professional syndicates approach MLB betting
- Common mistakes recreational bettors make that models can exploit
- Market-making perspective: where do books have the weakest lines?

**Output:** Actionable intelligence on what sharps focus on, with applicability to our pipeline.

### Agent 7: Prop Market Analyst

**Tools:** Read, Bash (Python)
**Mandate:** Deep analysis of player prop bet performance.

Analyses to run:
- ROI by prop type (pitcher_strikeouts, batter_hits, batter_rbis, etc.)
- Directional bias check: are we systematically taking overs or unders? Is that profitable?
- Edge distribution: histogram of prop edges -- are they clustered or spread?
- Compare Monte Carlo sim predictions to actual player stat lines
- Identify specific prop types that are consistently unprofitable and should be dropped
- Check if prop volume is diluting overall ROI

**Output:** Prop-by-prop performance table, bias analysis, drop/keep recommendations.

### Agent 8: Bet Type Profiler

**Tools:** Read, Bash (Python)
**Mandate:** Portfolio-level analysis of bet type allocation.

Analyses to run:
- Current allocation: what % of bets are in each type?
- ROI-weighted allocation: if we scaled bet types by ROI, what would the portfolio look like?
- Correlation analysis: when game-level bets lose, do props in the same game also lose?
- Evaluate correlated bet culling rules: is keeping top 2 of {team_total, F3_total, total} optimal?
- Identify the "efficient frontier" -- which combination of bet types maximizes ROI for a given volume

**Output:** Portfolio rebalancing recommendations, correlation matrix, optimal bet mix.

### Agent 9: Synthesis Agent

**Tools:** Read, Write
**Mandate:** Assemble all agent findings into the final report.

**Input:** The orchestrating skill collects the return values from all 8 Agent tool calls and passes them into Agent 9's prompt as labeled sections (e.g., "## Quant Analyst Findings\n{agent_1_result}"). Agent 9 does not read files -- it receives all findings in its prompt.

Process:
1. Review all 8 agent findings (provided in prompt)
2. Write the Executive Summary (3-5 key takeaways)
3. Organize findings into report sections
4. Resolve conflicts between agents (flag both sides if they disagree)
5. Build the Priority Action List ranked by:
   - **Expected impact** (estimated units/ROI improvement)
   - **Confidence** (high/medium/low based on sample size and evidence)
   - **Effort** (config change / code change / architecture change)
6. Write the report to `docs/superpowers/reports/YYYY-MM-DD-improvement-report.md`

## Skill File

The skill is implemented as a Claude command at `.claude/commands/improve.md`. It contains:

1. Pre-flight check: confirm `data/bets.csv` exists and has graded bets
2. Agent dispatch instructions for all 8 parallel agents with detailed prompts
3. Synthesis step instructions
4. Report writing and display instructions

## Constraints

- **Read-only:** No modifications to production code, config, or data during analysis
- **Best-effort:** Reports recommendations regardless of sample size, but notes sample size for context
- **Cost:** Primarily Claude API usage for sub-agents + web search. No external paid APIs.
- **Runtime:** Expected 3-5 minutes with all agents in parallel

## Success Criteria

- Report identifies at least 3 actionable improvements backed by data
- Each recommendation includes expected impact and implementation effort
- External research surfaces at least 2 techniques not currently in the system
- User can read the report and make informed decisions about what to implement
