# MiroFish Esports Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for esports (starting with CS2 and League of Legends). The system uses a 6-model LLM ensemble with adversarial challenge to predict match outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes. The sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) need to be rebuilt for esports.

Start with CS2 first, then add League of Legends as a second game.

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Match Schedule
- Source: PandaScore API (free tier) or Liquipedia API
- Returns: list of upcoming matches with team names, tournament name, format (Bo1/Bo3/Bo5), tier (S/A/B), date/time
- Filter to Tier 1 and Tier 2 events initially (better data, more liquid markets)

### scrapers/teams.py — Team Profiles (CS2)
- Source: HLTV (via hltv-async-api Python package) or GRID Open Access
- Per team, return:
  - Current HLTV ranking
  - Win rate (last 3 months, last 6 months)
  - Map pool: win rate per map (Mirage, Inferno, Nuke, Ancient, Anubis, Dust2, Vertigo)
  - Recent form: last 10 match results (opponent, score, tournament)
  - Current roster: 5 players + coach
  - Roster change recency (days since last roster move)
  - LAN vs Online win rate split

### scrapers/teams_lol.py — Team Profiles (League of Legends)
- Source: Riot Games API (developer key) or Leaguepedia
- Per team, return:
  - Current league standing (region: LCK, LPL, LEC, LCS, etc.)
  - Win rate (overall, blue side, red side)
  - Average game duration
  - First blood rate, first tower rate, first dragon rate
  - Gold differential at 15 minutes
  - Recent form: last 10 match results
  - Current roster: 5 players + coach
  - Roster change recency

### scrapers/odds.py — Betting Odds
- Source: The Odds API (ODDS_API_KEY) or OddsPapi (free tier, 350+ books)
- Sport key: `esports_csgo` for CS2, `esports_lol` for LoL
- Fetch: match winner (moneyline), map handicap, total maps
- Return OddsData dataclass with:
  - team_a, team_b
  - moneyline: {team_a: price, team_b: price}
  - map_handicap: {team_a: point, team_a_odds: price, team_b: point, team_b_odds: price}
  - total_maps: {line: X.5, over_odds: price, under_odds: price}
  - implied_probs: {team_a: prob, team_b: prob} (vig-removed)

### scrapers/meta.py — Patch & Meta Context
- Source: Game-specific patch notes pages + web search
- Returns:
  - Current patch version and key changes
  - Agent/champion tier list changes
  - Weapon/item balance changes
  - Days since last major patch (freshness indicator)
- This is WHERE LLMs add unique value — parsing natural-language patch notes

### scrapers/news.py — Roster & Context
- Source: Liquipedia, HLTV, team social media
- Returns per match:
  - Roster changes (recent subs, stand-ins, benched players)
  - Player injuries/illness
  - Bootcamp/travel information
  - Online vs LAN flag
  - Notable narratives (rivalries, elimination matches, qualification stakes)

---

## Layer 2: Briefing Template (CS2)

```
CS2 MATCH PREDICTION ANALYSIS
==============================
{tournament_name} — {date} | {format} (Bo{X})
{team_a} vs {team_b} | Tier: {tier}

BETTING LINES:
  Moneyline: {team_a} {ml_a} / {team_b} {ml_b}
  Map Handicap: {team_a} {hc_a} ({hc_a_odds}) / {team_b} {hc_b} ({hc_b_odds})
  Total Maps: {line} (Over {over_odds} / Under {under_odds})
  Implied Win Prob: {team_a} {prob_a:.1%} / {team_b} {prob_b:.1%}

== TEAM PROFILES ==

{team_a} — HLTV Rank #{rank_a}
  Record (3mo): {record_3m_a} | Win Rate: {wr_3m_a}%
  LAN Record: {lan_record_a} | Online Record: {online_record_a}
  Roster: {player1}, {player2}, {player3}, {player4}, {player5}
  Last Roster Change: {days_since_change_a} days ago
  Map Pool:
    {map1}: {wr}% ({games} games) | {map2}: {wr}% | ...
  Recent Form (Last 10):
    {date} vs {opp}: {score} ({tournament})
    ...

{team_b} — HLTV Rank #{rank_b}
  [same structure]

== MAP VETO ANALYSIS ==
  {team_a} likely bans: {ban1}, {ban2}
  {team_b} likely bans: {ban1}, {ban2}
  Likely maps played: {map1}, {map2}, {map3}
  Map pool overlap/advantage: {analysis}

== META & PATCH CONTEXT ==
  Current Patch: {version} (released {days_ago} days ago)
  Key Changes: {summary of recent balance changes}
  Impact on This Match: {how patch affects team playstyles}

== CONTEXT ==
  Tournament Stage: {group stage|playoff|grand final}
  Stakes: {qualification implications, elimination, etc.}
  Online/LAN: {online|LAN}
  Head-to-Head (Last 5): {h2h_record}

== PREDICTION TASK ==
Analyze this match from multiple expert perspectives and provide predictions for ALL of the following:

1. MATCH WINNER: Win probability for each team. Which side has moneyline value?
2. MAP HANDICAP ({team_a} {hc_a}): Will the favored team win by 2+ maps? Factor in map pool depth and veto patterns.
3. TOTAL MAPS (O/U {line}): Will the match be a sweep or go to a decider? Factor in team consistency, recent close matches, and map pool overlap.

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel (CS2)

```
You are an elite CS2 prediction system analyzing a professional match.
Simulate a panel of 6 expert analysts:

1. FRAGGING ANALYST: Evaluates individual player skill, AWP matchup,
   entry fragging capability, clutch statistics, and star player form.
   Who wins the aim duels?
2. TACTICAL ANALYST: Evaluates team strategy, utility usage, site executes,
   default setups, and anti-eco/force-buy management. Which team has the
   tactical edge and better mid-round calling?
3. MAP POOL ANALYST: Evaluates map veto scenarios, per-map win rates,
   comfort picks vs opponent's map pool. Where does each team have an
   advantage and what is the likely map selection?
4. FORM & MOMENTUM ANALYST: Evaluates recent results, tournament runs,
   roster changes, bootcamp status, and LAN vs online performance.
   Who is peaking and who is slumping?
5. MARKET ANALYST: Evaluates the betting lines for value. Where is the
   public money likely flowing? Are odds reflecting HLTV rankings or
   actual current form? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. What upset scenario is being
   overlooked? Is the favorite's recent form on unsustainable maps?
   Is there a stand-in or roster issue the market hasn't fully priced?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "fragging", "pick": "TEAM", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "team_a_win_prob": 0.XX,
      "team_b_win_prob": 0.XX,
      "value_side": "team_a|team_b|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "map_handicap": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total_maps": {
      "projected_maps": X.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_result": {"winner": "TEAM", "score": "2-1"},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
# Bet types for Esports (CS2)
BET_SLOTS = ["moneyline", "map_handicap", "total_maps"]

EDGE_THRESHOLDS = {
    "moneyline": 0.05,       # 5% min edge
    "map_handicap": 0.06,    # 6% min edge
    "total_maps": 0.05,      # 5% min edge
}

# Kelly sizing — quarter-Kelly (same as MLB, team sport variance)
KELLY_FRACTION = 0.25
```

---

## Layer 5: Edge Detection Functions

```python
# check_moneyline_edge(sim, odds) — same as MLB, compare team_a/b win probs vs implied
# check_map_handicap_edge(sim, odds) — same pattern as MLB run_line
#   - Favorite cover prob vs implied from handicap odds
#   - Favorite is the side with negative handicap (e.g., -1.5 maps)
# check_total_maps_edge(sim, odds) — same pattern as MLB total
#   - Over/under on total maps played
```

---

## Layer 6: Results Grader Adaptations

```python
# Grade moneyline: straightforward winner comparison
# Grade map_handicap: actual map score adjusted by handicap
#   - E.g., Team A -1.5 maps, actual score 2-1 → Team A adjusted = 0.5-1 → Team A loses cover
#   - E.g., Team A -1.5 maps, actual score 2-0 → Team A adjusted = 0.5-0 → Team A covers
# Grade total_maps: count maps played vs line
#   - Bo3: 2 maps (sweep) or 3 maps (decider)
#   - Bo5: 3 maps (sweep), 4 maps, or 5 maps (decider)
```

---

## Config Adaptations

```python
# API
HLTV_BASE = "https://www.hltv.org"
PANDASCORE_API_KEY = os.getenv("PANDASCORE_API_KEY", "")
PANDASCORE_BASE = "https://api.pandascore.co"
ODDS_SPORT_KEY_CS2 = "esports_csgo"
ODDS_SPORT_KEY_LOL = "esports_lol"

# No weather, no park factors
# Team identifiers are team names (strings), not abbreviations

GAME_TIMEOUT = 180  # 3 min per match analysis

ENSEMBLE_MODELS = ["kimi", "claude", "gpt4o", "gemini", "deepseek", "maverick"]
ENSEMBLE_CHALLENGER = "claude"
CONSENSUS_MIN_VOTES = 3
MAX_CALLS_PER_GAME = 50
```

---

## Key Differences From MLB

1. **Patch meta is a first-class input**: Game patches change the competitive landscape every 2-4 weeks. The briefing MUST include patch context. This is where LLMs have a unique advantage — reading and reasoning about natural-language patch notes.
2. **Map pool analysis replaces pitching matchup**: In CS2, map veto patterns and per-map win rates are the single biggest predictor. The briefing should prominently feature map pool data.
3. **Roster volatility**: Stand-ins, benched players, and mid-season roster moves are more common than in MLB. Check roster news before every match.
4. **Bo1 vs Bo3 vs Bo5**: Format changes variance dramatically. Bo1 is high-variance (upset-prone), Bo3 is standard. Edge thresholds should be higher for Bo1.
5. **Two games in one pipeline**: CS2 and LoL have different scrapers, briefing templates, and system prompts, but share the ensemble engine and infrastructure.
6. **Year-round**: No offseason. Multiple tournaments per week across regions. Much higher volume than MLB.
7. **Match-fixing awareness**: Flag unusual line movements on lower-tier matches. Focus on Tier 1/2 for reliability.
