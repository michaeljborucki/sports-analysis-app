# MiroFish Improvement Ideas

Brainstormed 2026-03-19. Grouped by expected impact on betting edge.

> **Status legend:** ✅ Done · 🚧 Active spec/plan · 🆕 New spec/plan (2026-04-19)
>
> Triaged 2026-04-19 against git history + current code.

---

## High Impact — More/Better Data

### 1. Umpire Data  🚧
- **Status:** Covered by active spec/plan `2026-04-17-statcast-umpire-catcher-enrichment`.
- **Source:** MLB Stats API or Retrosheet
- **Why:** Home plate umpire has measurable effect on K rate, walk rate, and run scoring. Some umps have 10%+ variance in runs/game.
- **Use:** Feed umpire tendencies into briefing for totals and F5 predictions.
- **Priority:** Top 3

### 2. Statcast / Barrel Rate Data  🚧
- **Status:** Covered by the same active spec/plan `2026-04-17-statcast-umpire-catcher-enrichment`.
- **Source:** pybaseball (already a dependency)
- **Why:** Expected stats (xERA, xwOBA, barrel%, hard-hit%) are more predictive than traditional stats, especially early season when small samples make ERA noisy.
- **Use:** Enhance pitcher and hitter profiles in briefing.

### 3. Lineup-Specific Batter vs. Pitcher Splits  🆕
- **Status:** New spec/plan `2026-04-19-contextual-enrichment-phase-2` (§1 BvP history).
- **Source:** pybaseball `statcast_batter` / `batting_stats`
- **Why:** Cross-referencing BvP matchup data flags games where a lineup has historically crushed a pitcher's pitch mix.
- **Use:** Especially useful for totals and F5 bets.

### 4. Vegas Line Movement / Reverse Line Movement  🆕
- **Status:** New spec/plan `2026-04-19-reverse-line-movement` (Top 3 priority).
- **Source:** The Odds API (already integrated — poll at multiple times)
- **Why:** Sharp money moves lines. If a line moves against the public, that's a signal.
- **Use:** Detect RLM by comparing opening vs. current odds. Flag sharp-side alignment or divergence.
- **Priority:** Top 3

---

## Medium Impact — Process Improvements

### 5. Bankroll Tracking & Drawdown Protection  🆕
- **Status:** New spec/plan `2026-04-19-bankroll-drawdown-protection`.
  - Note: per-game correlation cap is already covered by the active `2026-04-17-betting-layer-hardening` spec; this new spec covers the cumulative trailing-window drawdown gate.
- **Why:** Kelly sizing exists but no circuit breaker. Need guardrails for losing streaks.
- **What:** Max daily exposure, max drawdown threshold (e.g., pause after -10 units/week), streak-based confidence adjustments.

### 6. Closing Line Value (CLV) Tracking  ✅ / 🚧
- **Status:** Partially shipped (commit 886e959: `clv_cents` / `clv_pct` columns + `scrapers/closing_lines.py`). Further deepened by the active `2026-04-17-calibration-clv-loop` spec.
- **Source:** The Odds API (record closing line at game time)
- **Why:** CLV is the single best predictor of long-term profitability — better than actual W/L. Tells you if you're beating the market independent of variance.
- **What:** Record closing line, compare to bet line, track CLV over time.
- **Priority:** Top 3

### 7. Public Betting Percentages  🆕
- **Status:** New spec/plan `2026-04-19-contextual-enrichment-phase-2` (§2 public betting).
- **Source:** Action Network or similar
- **Why:** Contrarian plays against heavy public sides have historical edge. "85% of bets on the Yankees" helps the contrarian analyst role.
- **Use:** Feed public % into briefing context. Also unlocks strong `classify_rlm` in the RLM spec.

### 8. Same-Game Correlation Awareness  🚧
- **Status:** Covered by active spec `2026-04-17-betting-layer-hardening` (`sizing.py` + `cap_same_game_exposure`).
- **Why:** Betting ML + total on the same game = correlated exposure.
- **What:** Track and limit correlated bets per game. Adjust Kelly sizing for correlated positions.

---

## Lower Impact — Easy Wins

### 9. Travel / Rest Schedule  🆕
- **Status:** New spec/plan `2026-04-19-contextual-enrichment-phase-2` (§3 schedule context).
- **Source:** MLB Stats API (already integrated — derive from schedule)
- **Why:** West coast team playing a day game after a night game, game 4 of a road trip, timezone shifts.
- **What:** Compute days since last off day and timezone shifts per team.

### 10. Platoon Splits (L/R)  🚧
- **Status:** Covered by active spec/plan `2026-04-17-handedness-aware-sim`.
- **Source:** pybaseball
- **Why:** Some lineups are dramatically worse against LHP. Knowing starter handedness + lineup composition = platoon advantage signal.

### 11. Day/Night & Surface Splits  🆕
- **Status:** New spec/plan `2026-04-19-contextual-enrichment-phase-2` (§4 day/night + home/away splits).
- **Source:** pybaseball
- **Why:** Some pitchers have significant day/night or home/away splits. Easy to pull and include.

---

## Top 3 Priorities

1. **Umpire data** — highest bang for buck, especially for totals  🚧
2. **CLV tracking** — tells you if the system is actually sharp (not just lucky)  ✅ / 🚧
3. **Line movement detection** — already have the API, just need to poll twice and diff  🆕
