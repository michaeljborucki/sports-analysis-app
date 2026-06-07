# MiroFish Boxing Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for professional boxing (major promotional cards from Top Rank, Matchroom, PBC, DAZN). The system uses a 6-model LLM ensemble with adversarial challenge to predict fight outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes.

IMPORTANT CONTEXT: Boxing scored 4.95 in validated analysis. The LLM unique advantage is strong (7/10 — deeply narrative sport, poor statistical infrastructure), but data availability is the worst of all sports evaluated (2/10 — no free API, BoxRec blocks scraping) and volume is low (~400 bettable fights/year). Boxing is a HIGH-CONVICTION, LOW-VOLUME play. Only bet when the ensemble has strong consensus.

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Fight Card Schedule
- Source: Scrape boxing news sites (BoxingScene, ESPN Boxing) or use paid APIs
- Returns: upcoming fight cards with fighter names, weight class, rounds (8/10/12), title fight flag, venue, promotion

### scrapers/fighters.py — Fighter Profiles
- Source: BoxRec (scrape cautiously — they block aggressive scraping), Wikipedia fight records, or manual database
- Per fighter, return:
  - Record: W-L-D (KO wins, KO losses)
  - Weight class and natural weight
  - Age, height, reach
  - Stance: orthodox/southpaw
  - Activity: days since last fight, fights in last 12 months
  - Resume quality: notable wins and losses (ranked opponents beaten)
  - Current ranking (WBA/WBC/IBF/WBO/Ring Magazine)
  - Knockout rate: KO% of wins
  - Recent form: last 5 fights (opponent, result, method, round)
  - Rounds fought in career (durability indicator)

### scrapers/compubox.py — Punch Statistics (BEST EFFORT)
- Source: CompuBox data (limited free access) or fight-level stats from news reports
- Per fighter (when available):
  - Punches landed per round
  - Total punch accuracy %
  - Jab accuracy %
  - Power punch accuracy %
  - Punches received per round (defensive metric)
- NOTE: This data is extremely hard to get for free. Many fights have no CompuBox data.

### scrapers/odds.py — Betting Odds
- Source: The Odds API (ODDS_API_KEY)
- Sport key: `boxing_boxing`
- Fetch: moneyline, total rounds (over/under), method of victory (if available)
- Return OddsData dataclass with:
  - fighter_a, fighter_b
  - moneyline: {fighter_a: price, fighter_b: price}
  - total_rounds: {line: X.5, over_odds: price, under_odds: price}
  - implied_probs: {fighter_a: prob, fighter_b: prob}

### scrapers/news.py — Fight Context (WHERE LLMs ADD THE MOST VALUE)
- Source: Boxing news sites (BoxingScene, ESPN, DAZN News, The Athletic), social media
- Returns per fight:
  - Training camp reports and sparring rumors
  - Weight cut history and weigh-in assessment
  - Trainer/corner changes
  - Promotional context (mandatory defense, catchweight, grudge match)
  - Injury reports
  - Motivation assessment (legacy fight vs tune-up vs money fight)
  - Expert predictions and analysis summaries

---

## Layer 2: Briefing Template

```
BOXING FIGHT PREDICTION ANALYSIS
==============================
{event_name} — {date} | {venue}
{fighter_a} vs {fighter_b}
{weight_class} | {rounds} Rounds | {title_context}

BETTING LINES:
  Moneyline: {fighter_a} {ml_a} / {fighter_b} {ml_b}
  Total Rounds: {line} (Over {over_odds} / Under {under_odds})
  Implied Win Prob: {fighter_a} {prob_a:.1%} / {fighter_b} {prob_b:.1%}

== FIGHTER PROFILES ==

{fighter_a} — Record: {record_a} ({ko_wins_a} KOs)
  KO Rate: {ko_pct_a}% | Been KO'd: {ko_losses_a} times
  Age: {age_a} | Height: {height_a} | Reach: {reach_a}"
  Stance: {stance_a}
  Days Since Last Fight: {layoff_a} | Fights Last 12mo: {activity_a}
  Rankings: {rankings_a}
  Punch Stats (if available):
    Landed/Round: {landed_per_rd_a} | Accuracy: {accuracy_a}%
    Power Punch %: {power_pct_a} | Received/Round: {received_per_rd_a}
  Last 5 Fights:
    {date} vs {opp} ({record}): {result} via {method} R{round}
    ...
  Notable Wins: {notable_wins_a}
  Notable Losses: {notable_losses_a}

{fighter_b} — Record: {record_b} ({ko_wins_b} KOs)
  [same structure]

== STYLE MATCHUP ANALYSIS ==
  {fighter_a} Style: {style_desc_a}
  {fighter_b} Style: {style_desc_b}
  Reach Advantage: {reach_diff}" to {fighter_with_reach}
  Stance Matchup: {stance_matchup} (orthodox vs southpaw creates angles)
  Historical Pattern: {style_vs_style_history}

== FIGHT CONTEXT ==
  Title Fight: {title_context}
  Promotion: {promotion}
  Mandatory/Voluntary: {mandatory_flag}
  Camp Reports: {camp_notes}
  Weight Cut: {weight_notes}
  Trainer: {fighter_a} trained by {trainer_a} | {fighter_b} trained by {trainer_b}
  Trainer Changes: {trainer_change_notes}
  Ring Rust: {ring_rust_assessment}

== PREDICTION TASK ==
Analyze this fight from multiple expert perspectives and provide predictions for ALL of the following:

1. FIGHT WINNER: Win probability for each fighter. Which side has moneyline value?
2. TOTAL ROUNDS (O/U {line}): Will this go the distance or end early? Factor in KO rates, chin durability, and pace.
3. METHOD OF VICTORY: Most likely method (KO/TKO, Decision — UD/SD/MD). Where does the value lie?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel

```
You are an elite boxing prediction system analyzing a professional fight.
Simulate a panel of 6 expert analysts:

1. TECHNICAL ANALYST: Evaluates boxing skill — jab, footwork, ring
   generalship, combination punching, inside fighting ability, and
   defensive technique (head movement, blocking, distance management).
   Who is the more technically skilled fighter?
2. POWER & DURABILITY ANALYST: Evaluates punch power, KO rate, chin
   durability (how many times been hurt/dropped/stopped), and how power
   translates at this weight class. Can one fighter hurt the other?
3. STYLE MATCHUP ANALYST: Evaluates how the specific styles interact.
   Boxer vs puncher, pressure fighter vs counter-puncher, southpaw dynamics.
   Reach and height advantages. Who controls distance and range?
4. CONDITIONING & ACTIVITY ANALYST: Evaluates cardio, fight pace
   sustainability, ring rust from long layoffs, and championship-rounds
   endurance (rounds 9-12 in title fights). Age-related decline.
   A fighter returning after 14 months off is a different fighter.
5. MARKET ANALYST: Evaluates the betting lines for value. Boxing has the
   thinnest markets in major sports — casual money creates systematic
   mispricing. Is a big name overvalued? Is the underdog's style being
   dismissed? Where is the market inefficient?
6. CONTRARIAN: Challenges the consensus. Is the favorite declining and
   hiding it with soft opposition? Is the underdog's record padded with
   journeymen? Is the promotion building a narrative that doesn't match
   the actual skill gap? Is a southpaw advantage being overlooked?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "technical", "pick": "FIGHTER", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "fighter_a_win_prob": 0.XX,
      "fighter_b_win_prob": 0.XX,
      "value_side": "fighter_a|fighter_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_rounds": {
      "projected_rounds": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "method": {
      "ko_tko_prob": 0.XX,
      "decision_prob": 0.XX,
      "most_likely": "KO/TKO|UD|SD",
      "value_method": "ko|decision|none",
      "confidence": "low|medium|high"
    },
    "predicted_result": {"winner": "FIGHTER", "method": "METHOD", "round": X},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
BET_SLOTS = ["moneyline", "total_rounds", "method"]

EDGE_THRESHOLDS = {
    "moneyline": 0.07,        # 7% min edge (thin markets but high variance)
    "total_rounds": 0.07,     # 7% min edge
    "method": 0.10,           # 10% min edge (hardest to predict)
}

# Eighth-Kelly — boxing is high variance (single punch can end a fight)
KELLY_FRACTION = 0.125
```

---

## Key Differences From MLB and UFC

1. **Worst data availability of any sport**: No free API. BoxRec blocks scraping. CompuBox is proprietary. The briefing will rely more on news/narrative context than structured stats. This is WHERE LLMs shine — synthesizing fight previews, expert analysis, and camp reports.
2. **Very low volume**: ~400 bettable fights/year across all major promotions. Only ~40-50 qualifying bets/year after edge filtering. This is a patience game.
3. **Boxing ≠ MMA**: Boxing has only hands (no kicks, takedowns, submissions). Style matchups are narrower but deeper — southpaw angles, jab quality, inside fighting ability matter enormously.
4. **12-round championship fights**: Unlike UFC's 3-5 rounds, boxing title fights go 12 rounds. Conditioning and late-round ability is a much bigger factor. The total rounds market is more interesting.
5. **Judging variance**: Controversial decisions happen more in boxing than MMA. The "hometown decision" and corrupt judging are real risks. Model for this by increasing decision-method uncertainty.
6. **Promotional matchmaking**: Unlike UFC where the organization makes fights, boxing promoters control matchmaking. Fighters are often fed "tune-up" opponents. Assess whether the underdog is a legitimate threat or a hand-picked opponent.
7. **No unified rankings**: Four sanctioning bodies (WBA, WBC, IBF, WBO) each have their own rankings and mandatory challengers. This creates confusion the market sometimes misprices.
