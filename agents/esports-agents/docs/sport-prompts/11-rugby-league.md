# MiroFish Rugby League Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for rugby league (NRL — Australia's National Rugby League, and Super League — UK/Europe). The system uses a 6-model LLM ensemble with adversarial challenge to predict match outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes.

IMPORTANT CONTEXT: Rugby League scored 4.95 in validated analysis. The key advantage: academic research confirms models outperform bookmakers, and commercial tipping services (Winning Edge Investments) have documented 9-12% ROI over 8+ seasons. The key risks: no free data API (data availability is 3/10), and practical execution from the US is challenging (Australian/UK markets, thin international liquidity). This is a NICHE play for bettors who can access Australian sportsbooks.

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Round Schedule
- Source: NRL.com / SuperLeague.co.uk (scrape)
- Returns: this round's matches with home/away teams, venue, kickoff time, round number

### scrapers/team_stats.py — Team Season Stats
- Source: NRL.com stats page (scrape) or Zero Tackle
- Per team, return:
  - Ladder position, record (W-L-D), points differential
  - Points scored per game, points conceded per game
  - Completion rate (sets completed without error %)
  - Tackle efficiency %
  - Offloads per game
  - Line breaks per game (attacking) and conceded (defensive)
  - Kick meters gained
  - Penalty count per game
  - Home record vs away record
  - Last 5 form

### scrapers/players.py — Key Player Availability
- Source: NRL.com team lists (released Tuesday for weekend games) or club websites
- Per team, return:
  - Named 21-man squad (17 starters + 4 interchange)
  - Key ins/outs from last week
  - Halfback/five-eighth pairing (most important positions)
  - Fullback (second most important)
  - Injury list with return timeline
  - State of Origin players (relevant during Origin period — June/July)

### scrapers/odds.py — Betting Odds
- Source: The Odds API (ODDS_API_KEY) or direct from Sportsbet/TAB
- Sport key: `rugbyleague_nrl` (if available) or scrape Australian bookmakers
- Fetch: head-to-head (moneyline), line (handicap), total points
- Return OddsData dataclass with:
  - home, away
  - moneyline: {home: price, away: price}
  - handicap: {home: point, home_odds: price, away: point, away_odds: price}
  - total: {line: XX.5, over_odds: price, under_odds: price}
  - implied_probs: {home: prob, away: prob}

### scrapers/context.py — Match Context
- Source: NRL news sites, team announcements
- Returns per match:
  - State of Origin impact (are key players missing for Origin duty? — affects 3 rounds in Jun-Jul)
  - Travel/distance (NRL teams span Brisbane to Auckland to Melbourne)
  - Rivalry flag (classic rivalries like Souths vs Roosters, Manly vs Parra)
  - Weather forecast (relevant for UK Super League especially — rain changes game dynamics)
  - Venue type (home ground advantage vs neutral venue)

### scrapers/scores.py — Final Scores
- Source: NRL.com or ESPN
- Returns per completed match:
  - home, away, home_score, away_score
  - total_points
  - half_time_score (home_h1, away_h1)

---

## Layer 2: Briefing Template

```
RUGBY LEAGUE MATCH PREDICTION ANALYSIS
==============================
{league} Round {round} — {date}
{away} at {home}
{venue} | Kickoff: {time}

BETTING LINES:
  Head-to-Head: {home} {ml_home} / {away} {ml_away}
  Handicap: {home} {hc_home} ({hc_home_odds}) / {away} {hc_away} ({hc_away_odds})
  Total Points: {total_line} (Over {over_odds} / Under {under_odds})
  Implied Win Prob: {home} {prob_home:.1%} / {away} {prob_away:.1%}

== TEAM PROFILES ==

{away} — {position_away} on ladder | {record_away} | PD: {pd_away}
  Points: {ppg_away} scored / {pcg_away} conceded per game
  Completion Rate: {comp_away}% | Tackle Efficiency: {tackle_away}%
  Line Breaks: {lb_for_away} for / {lb_against_away} against per game
  Offloads/Game: {offloads_away} | Penalties/Game: {pens_away}
  Away Record: {away_record_away}
  Form (Last 5): {form_away}

{home} — {position_home} on ladder | {record_home} | PD: {pd_home}
  [same structure with home_record]

== TEAM LISTS ==
{away} Named Squad:
  1. {fullback} (Fullback) | 6. {five_eighth} | 7. {halfback}
  Key Changes from Last Week: {changes_away}
  Missing: {missing_away}

{home} Named Squad:
  [same structure]

== MATCH CONTEXT ==
  State of Origin Impact: {origin_context}
  Travel: {travel_context}
  Rivalry: {rivalry_flag}
  Weather: {weather}
  Venue: {venue_context}

== HEAD-TO-HEAD ==
  Season Series: {h2h_season}
  Last 5 Meetings: {h2h_last5}

== PREDICTION TASK ==
Analyze this match from multiple expert perspectives and provide predictions for ALL of the following:

1. MATCH WINNER: Win probability for each team. Which side has head-to-head value?
2. HANDICAP ({home} {hc_home}): Will the favorite cover the line? Factor in squad quality gap, home ground, and Origin absences.
3. TOTAL POINTS (O/U {total_line}): Projected total points. Factor in completion rates, defensive quality, and weather impact.

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel

```
You are an elite rugby league prediction system analyzing an NRL/Super League match.
Simulate a panel of 6 expert analysts:

1. ATTACK ANALYST: Evaluates attacking quality — line breaks, offloads,
   completion rate, kick-chase effectiveness, and points-scoring ability.
   How does the attacking structure compare? Which team creates more
   opportunities through the ruck?
2. DEFENSE ANALYST: Evaluates defensive structure — tackle efficiency,
   missed tackles, line speed, edge defense, and ability to absorb pressure.
   Which team's defense is more likely to crack?
3. HALVES & SPINE ANALYST: Evaluates the key positions — halfback, five-eighth,
   fullback, and hooker. These four positions control the game. A dominant
   halfback pairing is the biggest single advantage in rugby league.
   Kicking game, game management, and clutch performance.
4. SITUATIONAL ANALYST: Evaluates State of Origin impact (3 rounds in June-July
   where rep players miss club games), travel fatigue, home ground advantage,
   weather, and scheduling context. A team missing 5 players to Origin is
   dramatically weakened.
5. MARKET ANALYST: Evaluates the betting lines for value. NRL attracts less
   sharp money than US sports — are lines efficiently set? Is a team's recent
   form masking underlying weaknesses? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. Is a top-4 team coasting into finals?
   Is a bottom-4 team actually competitive based on underlying stats? Is the
   Origin disruption being overweighted or underweighted by the market?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "attack", "pick": "TEAM", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "home_win_prob": 0.XX,
      "away_win_prob": 0.XX,
      "value_side": "home|away|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "handicap": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total": {
      "projected_total": XX.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "predicted_score": {"home": XX, "away": XX},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
BET_SLOTS = ["moneyline", "handicap", "total"]

EDGE_THRESHOLDS = {
    "moneyline": 0.06,    # 6% min edge
    "handicap": 0.06,     # 6% min edge
    "total": 0.06,        # 6% min edge
}

KELLY_FRACTION = 0.25  # quarter-Kelly (team sport, moderate variance)
```

---

## Config Adaptations

```python
NRL_BASE = "https://www.nrl.com"
SUPER_LEAGUE_BASE = "https://www.superleague.co.uk"
ODDS_SPORT_KEY = "rugbyleague_nrl"

# NRL: 17 teams, 27 rounds + finals (Mar-Oct)
# Super League: 12-14 teams, 27 rounds + playoffs (Feb-Oct)

NRL_TEAMS = [
    "Broncos", "Bulldogs", "Cowboys", "Dolphins", "Dragons",
    "Eels", "Knights", "Panthers", "Rabbitohs", "Raiders",
    "Roosters", "Sea Eagles", "Sharks", "Storm", "Titans",
    "Warriors", "Wests Tigers"
]

HOME_ADVANTAGE = 3.0  # points (approximate)
GAME_TIMEOUT = 180
```

---

## Key Differences From MLB

1. **State of Origin period is unique**: During 3 rounds in June-July, each NRL team loses 2-7 players to representative duty. Teams with heavy Origin representation are dramatically weakened. This is a massive, predictable, and sometimes mispriced factor. No equivalent in any American sport.
2. **Halves control everything**: The halfback-five eighth combination is the most important factor in rugby league. It's like having a QB AND offensive coordinator on the field. Injuries to halves swing lines by 10+ points.
3. **Completion rate is the key stat**: Teams that complete their sets (6-tackle possessions without errors) at 80%+ dramatically outperform. It's the rugby league equivalent of turnover margin.
4. **Data availability is poor**: No free API. Scraping NRL.com is the only free option. Stats Perform has the official data but it's commercial. This is the biggest practical barrier.
5. **Australian sportsbook access**: Best odds are on Australian books (Sportsbet, TAB, Ladbrokes AU). International books offer NRL but with wider margins. Pinnacle covers NRL.
6. **Team lists released Tuesday**: NRL teams name squads on Tuesday for weekend games. Lines move between Tuesday and Friday as final team lists are confirmed. Betting after team list confirmation captures the most information.
7. **Weather matters in Super League**: UK winter conditions (rain, cold, wind) significantly impact scoring in Super League. NRL is mostly played in Australian summer/autumn.
8. **Lower scoring than NFL/NBA but higher than soccer/NHL**: NRL averages ~40-50 total points per game. Totals are typically set at 38.5-48.5. This provides moderate variance.
