# MiroFish Improvement Ideas

Brainstormed 2026-03-19. Grouped by expected impact on betting edge.

---

## High Impact — More/Better Data

### 1. Umpire Data
- **Source:** MLB Stats API or Retrosheet
- **Why:** Home plate umpire has measurable effect on K rate, walk rate, and run scoring. Some umps have 10%+ variance in runs/game.
- **Use:** Feed umpire tendencies into briefing for totals and F5 predictions.
- **Priority:** Top 3

### 2. Statcast / Barrel Rate Data
- **Source:** pybaseball (already a dependency)
- **Why:** Expected stats (xERA, xwOBA, barrel%, hard-hit%) are more predictive than traditional stats, especially early season when small samples make ERA noisy.
- **Use:** Enhance pitcher and hitter profiles in briefing.

### 3. Lineup-Specific Batter vs. Pitcher Splits
- **Source:** pybaseball `statcast_batter` / `batting_stats`
- **Why:** Cross-referencing BvP matchup data flags games where a lineup has historically crushed a pitcher's pitch mix.
- **Use:** Especially useful for totals and F5 bets.

### 4. Vegas Line Movement / Reverse Line Movement
- **Source:** The Odds API (already integrated — poll at multiple times)
- **Why:** Sharp money moves lines. If a line moves against the public, that's a signal.
- **Use:** Detect RLM by comparing opening vs. current odds. Flag sharp-side alignment or divergence.
- **Priority:** Top 3

---

## Medium Impact — Process Improvements

### 5. Bankroll Tracking & Drawdown Protection
- **Why:** Kelly sizing exists but no circuit breaker. Need guardrails for losing streaks.
- **What:** Max daily exposure, max drawdown threshold (e.g., pause after -10 units/week), streak-based confidence adjustments.

### 6. Closing Line Value (CLV) Tracking
- **Source:** The Odds API (record closing line at game time)
- **Why:** CLV is the single best predictor of long-term profitability — better than actual W/L. Tells you if you're beating the market independent of variance.
- **What:** Record closing line, compare to bet line, track CLV over time.
- **Priority:** Top 3

### 7. Public Betting Percentages
- **Source:** Action Network or similar
- **Why:** Contrarian plays against heavy public sides have historical edge. "85% of bets on the Yankees" helps the contrarian analyst role.
- **Use:** Feed public % into briefing context.

### 8. Same-Game Correlation Awareness
- **Why:** Betting ML + total on the same game = correlated exposure.
- **What:** Track and limit correlated bets per game. Adjust Kelly sizing for correlated positions.

---

## Lower Impact — Easy Wins

### 9. Travel / Rest Schedule
- **Source:** MLB Stats API (already integrated — derive from schedule)
- **Why:** West coast team playing a day game after a night game, game 4 of a road trip, timezone shifts.
- **What:** Compute days since last off day and timezone shifts per team.

### 10. Platoon Splits (L/R)
- **Source:** pybaseball
- **Why:** Some lineups are dramatically worse against LHP. Knowing starter handedness + lineup composition = platoon advantage signal.

### 11. Day/Night & Surface Splits
- **Source:** pybaseball
- **Why:** Some pitchers have significant day/night or home/away splits. Easy to pull and include.

---

## Top 3 Priorities

1. **Umpire data** — highest bang for buck, especially for totals
2. **CLV tracking** — tells you if the system is actually sharp (not just lucky)
3. **Line movement detection** — already have the API, just need to poll twice and diff
