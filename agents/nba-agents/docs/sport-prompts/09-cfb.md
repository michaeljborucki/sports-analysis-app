# MiroFish CFB (College Football) Pipeline — Build Prompt

## What To Build

Build a sports betting prediction pipeline for NCAA FBS college football. The system uses a 6-model LLM ensemble with adversarial challenge to predict game outcomes, detect edge vs market odds, and output a bet card with Kelly-criterion sizing.

The architecture follows a 6-layer pipeline: SCRAPE → BRIEFING → SCREEN → ENSEMBLE → EDGE → BET.

I have a working reference implementation for MLB baseball at ../baseball-agents/ that you should use as the structural template. The ensemble engine, orchestrator, challenger, consensus, weights, tracker, and agent layers are sport-agnostic and should transfer with minimal changes. The sport-specific layers (scrapers, briefing, system prompt, bet slots, edge detection, results grader) need to be rebuilt for college football.

IMPORTANT CONTEXT: CFB scored 6.65 in validated analysis. Key advantages: 130+ FBS teams create information gaps (like NCAAB), strong market inefficiency in Group of 5 and early season, and the CFBD API is excellent and cheap. Key risk: only ~850 games/season and 12 games per team = very small sample sizes. Season runs September-January. Natural seasonal complement to NCAAB (Sep-Jan before NCAAB peaks Jan-Mar).

---

## Layer 1: Scrapers To Build

### scrapers/schedule.py — Weekly Schedule
- Source: CollegeFootballData.com API (CFBD) — free tier 1,000 calls/month, $10/mo for 75K
- Python package: `pip install cfbd`
- Returns: list of this week's games with home/away teams, venue, conference, TV, weather forecast

### scrapers/team_stats.py — Team Efficiency Ratings
- Source: CFBD API (advanced stats endpoint)
- Per team, return:
  - SP+ rating (or equivalent composite — offensive, defensive, special teams)
  - EPA per play (offense and defense)
  - Success rate (offense and defense)
  - Explosiveness (big play rate)
  - Havoc rate (TFLs, fumbles forced, INTs on defense)
  - Finishing drives (red zone offense/defense)
  - Record (overall, conference, home, away)
  - Scoring offense/defense (points per game)
  - Yards per play (offense and defense)
  - Turnover margin
  - Conference standing

### scrapers/roster.py — Roster Composition
- Source: CFBD API (roster + transfer portal endpoints) + 247Sports
- Per team, return:
  - Returning production % (from Bill Connelly's SP+)
  - Transfer portal additions with previous school and stats
  - Key departures (NFL draft, transfer out)
  - Starting QB: name, stats, experience level (freshman/transfer/multi-year starter)
  - Recruiting class ranking (current freshmen class)
  - Coaching staff: HC, OC, DC with tenure

### scrapers/weather.py — Game Day Weather (CRITICAL for football)
- Source: OpenWeatherMap API (WEATHER_API_KEY) or CFBD weather endpoint
- Returns:
  - Temperature, wind speed/direction, precipitation %
  - Indoor/outdoor/dome classification
  - Wind impact classification for passing game
  - Rain/snow flag

### scrapers/odds.py — Betting Odds
- Source: The Odds API (ODDS_API_KEY)
- Sport key: `americanfootball_ncaaf`
- Fetch: spread, moneyline, total, 1st half spread, 1st half total, team totals
- Return OddsData dataclass with:
  - home, away
  - spread: {home: point, home_odds: price, away: point, away_odds: price}
  - moneyline: {home: price, away: price}
  - total: {line: XX.5, over_odds: price, under_odds: price}
  - h1_spread: {home: point, home_odds: price, away: point, away_odds: price}
  - h1_total: {line: XX.5, over_odds: price, under_odds: price}
  - team_total_home: {line: XX.5, over_odds: price, under_odds: price}
  - team_total_away: {line: XX.5, over_odds: price, under_odds: price}
  - implied_probs: {ml_home: prob, ml_away: prob}

### scrapers/scores.py — Final Scores
- Source: CFBD API
- Returns per completed game:
  - home, away, home_score, away_score
  - home_score_h1, away_score_h1
  - total_points, total_points_h1

---

## Layer 2: Briefing Template

```
CFB GAME PREDICTION ANALYSIS
==============================
{away} ({away_record}) at {home} ({home_record})
{venue} | {conference_context} | {kickoff_time} | {tv_network}
Weather: {temp}°F, Wind {wind}mph, Precip {precip}%

BETTING LINES:
  Spread: {home} {spread_home} ({spread_home_odds}) / {away} {spread_away} ({spread_away_odds})
  Moneyline: {home} {ml_home} / {away} {ml_away}
  Total: {total_line} (Over {over_odds} / Under {under_odds})
  1H Spread: {home} {h1_spread_home} ({h1_spread_home_odds})
  1H Total: {h1_total_line}
  Team Totals: {home} {tt_home} / {away} {tt_away}
  Implied Win Prob: {home} {prob_home:.1%} / {away} {prob_away:.1%}

== TEAM PROFILES ==

{away} — SP+: #{sp_rank_away} | EPA/play Off: {epa_off_away} | EPA/play Def: {epa_def_away}
  Record: {record_away} | Conf: {conf_record_away} | Away: {away_away_record}
  Scoring: {ppg_away} PPG / {ppg_allowed_away} allowed
  Success Rate: Off {sr_off_away}% | Def {sr_def_away}%
  Explosiveness: {expl_away} | Havoc Rate: {havoc_away}
  Turnover Margin: {to_margin_away}
  QB: {qb_away} — {qb_stats_away}

{home} — SP+: #{sp_rank_home} | EPA/play Off: {epa_off_home} | EPA/play Def: {epa_def_home}
  Record: {record_home} | Conf: {conf_record_home} | Home: {home_home_record}
  [same structure]

== ROSTER CONTEXT ==
{away}:
  Returning Production: {ret_prod_away}%
  Key Transfers In: {transfers_in_away}
  Key Departures: {departures_away}
  Coach: {coach_away} (Year {tenure_away}) | OC: {oc_away} | DC: {dc_away}
  Recruiting: #{recruit_rank_away} class

{home}:
  [same structure]

== WEATHER IMPACT ==
  Conditions: {weather_summary}
  Wind Impact on Passing: {wind_impact}
  Rain/Snow: {precip_flag}
  Indoor/Outdoor: {venue_type}

== GAME CONTEXT ==
  Conference Game: {conf_game_flag}
  Rivalry: {rivalry_flag}
  Week: {week_number} | Season Stage: {early_season|conference_play|rivalry_week|bowl|cfp}
  Power 4 vs Group of 5: {p4_g5_flag}
  FBS vs FCS: {fcs_flag}
  CFP/Bowl Implications: {postseason_context}
  Bye Week: {away} {bye_away} | {home} {bye_home}
  Travel: {travel_context}

== PREDICTION TASK ==
Analyze this matchup from multiple expert perspectives and provide predictions for ALL of the following:

1. GAME WINNER: Win probability for each team. Which side has moneyline value?
2. SPREAD ({home} {spread_home}): Will the favorite cover? Factor in SP+ gap, weather, home field, and situational context.
3. TOTAL (O/U {total_line}): Projected total points. Factor in offensive/defensive efficiency, pace, weather impact on scoring, and game script.
4. FIRST HALF: Who leads at halftime? What's the projected 1H total?

For each bet type, provide:
  - Your probability estimate
  - Whether the market price offers value
  - Confidence level (low/medium/high)
  - Key factors driving the assessment
```

---

## Layer 3: System Prompt — Expert Panel

```
You are an elite college football prediction system analyzing an FBS game.
Simulate a panel of 6 expert analysts:

1. SP+ / EPA ANALYST: Evaluates advanced efficiency metrics — EPA per play,
   success rate, explosiveness, and havoc rate on offense and defense. How
   do the SP+ profiles match up? What is the projected scoring margin based
   on efficiency differential alone?
2. QUARTERBACK & SCHEME ANALYST: Evaluates the starting QB matchup,
   offensive scheme (Air Raid, RPO, triple option, pro-style), and how the
   scheme matches against the defensive scheme. Is this a bad stylistic
   matchup? A mobile QB against a blitz-heavy defense?
3. ROSTER & PORTAL ANALYST: Evaluates transfer portal impact, returning
   production, coaching continuity, and early-season roster questions.
   How many starts has the QB made? Are new transfers integrated?
   In WEEKS 1-4, this analyst carries extra weight because statistical
   models have limited data on rebuilt rosters.
4. WEATHER & SITUATIONAL ANALYST: Evaluates weather impact (wind kills
   passing games, rain creates turnovers), home field advantage (stronger
   in CFB than any other sport), rivalry dynamics, bye week advantage,
   and lookahead/letdown spots.
5. MARKET ANALYST: Evaluates the betting lines for value. Are Group of 5
   teams being dismissed? Is a ranked team overvalued from preseason
   rankings that haven't updated? Is the public piling on Alabama/Ohio State
   regardless of matchup? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. Is last year's success misleading
   for a team that lost 8 starters? Is a new coach's scheme change being
   underestimated? Is the "trap game before rivalry week" narrative real
   or just noise?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "sp_epa", "pick": "TEAM", "reasoning": "..."},
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
    "spread": {
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
    "first_half": {
      "h1_home_win_prob": 0.XX,
      "h1_away_win_prob": 0.XX,
      "h1_projected_total": XX.X,
      "h1_ml_value": "home|away|none",
      "h1_total_value": "over|under|none",
      "confidence": "low|medium|high"
    },
    "predicted_score": {"away": XX, "home": XX},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only.
```

---

## Layer 5: Bet Slots & Edge Thresholds

```python
BET_SLOTS = ["moneyline", "spread", "total", "first_half_ml", "first_half_total"]

EDGE_THRESHOLDS = {
    "moneyline": 0.05,
    "spread": 0.05,
    "total": 0.05,
    "first_half_ml": 0.06,
    "first_half_total": 0.06,
}

KELLY_FRACTION = 0.25  # quarter-Kelly
```

---

## Config Adaptations

```python
CFBD_API_KEY = os.getenv("CFBD_API_KEY", "")
CFBD_BASE = "https://api.collegefootballdata.com"
ODDS_SPORT_KEY = "americanfootball_ncaaf"

# 134 FBS teams — load dynamically from CFBD
# Conference classification:
POWER_4 = ["SEC", "Big Ten", "Big 12", "ACC"]
GROUP_OF_5 = ["AAC", "Conference USA", "MAC", "Mountain West", "Sun Belt"]

HOME_FIELD_ADVANTAGE = 3.5  # points (stronger than NFL's ~2.5)
GAME_TIMEOUT = 300

# Season: late August through mid-January
# Weekly cadence: primarily Saturdays (50-65 games), some Tuesday/Wednesday MACtion, Thursday nights
# Bowl season: December-January (~40 games + CFP)
```

---

## Key Differences From MLB

1. **Weather matters enormously**: Wind >15mph reduces pass yards ~12%. Rain creates turnovers. Snow favors run-heavy teams. No dome protection for most teams. Weather scraper is critical.
2. **Home field advantage is the strongest**: ~3.5 points in CFB (vs ~3 in NBA, ~0.5 in MLB). Hostile environments (Death Valley, The Swamp, Beaver Stadium) can be worth 5-7 points. 100,000+ capacity stadiums create real crowd effects.
3. **Transfer portal is the dominant roster variable**: ~13,000 career starts entered the portal in 2025. A team can completely transform between seasons. Early-season assessment of "new" rosters is where LLMs add the most value.
4. **Only 12 games per team**: Statistical models don't converge until mid-October (game 5-6). Weeks 1-4 are where LLM qualitative assessment of roster changes, coaching hires, and scheme fits provides the biggest edge.
5. **Massive talent mismatches**: FBS vs FCS, Power 4 vs Group of 5. Spreads of -30 to -45 are common. These large spreads are historically mispriced (underdogs cover more than expected).
6. **Saturday concentration**: 50-65 games on a single Saturday. Unlike MLB's daily 15 games, CFB requires batch processing once per week.
7. **QB is the most valuable single player**: One player impacts ~65% of offensive plays. QB injuries or transfers swing lines 7-14 points. Monitor QB situation closely.
8. **CFBD API is excellent and nearly free**: Play-by-play, EPA, recruiting, transfers, weather — all in one API. $10/month for full access.
