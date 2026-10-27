# NBA possession-efficiency projections (`/nba`)

Sibling of `/cfb` (see `2026-10-15-cfb-ppp-projections.md`) — same layout, NBA data.

## Model (user-specified)

For team A vs team B:

    off_est = pace_A × off_eff_A
    def_est = pace_A × def_eff_B
    proj_A  = (off_est + def_est) / 2

- pace = possessions per game; possessions = FGA − OREB + total turnovers + 0.44 × FTA (box score)
- off_eff = points ÷ own possessions; def_eff = points allowed ÷ opponent possessions
- No home-court or strength-of-schedule adjustment.

Worked example from the user (BOS @ DET, last season): BOS 1.159 / 1.085 / 98.5, DET 1.124 / 1.054 / 103.1 →
BOS 108.99 (the original note says 108.88 — arithmetic slip), DET 113.87. Pinned in `test_user_example_bos_at_det`.

**Pace-matched check** (shown beside the model on the game page, not the headline): both teams over one
shared pace = avg(pace_A, pace_B), proj_A = shared_pace × (off_eff_A + def_eff_B) / 2. The specified model
scores each team at its own pace, which pushes the spread toward the faster team (BOS @ DET 2026-10-20:
model DET −5.6, pace-matched DET −0.3, market BOS −1.5).

## Decisions

- **Data:** ESPN public site API (free, keyless, unmetered). Monthly scoreboards (`dates=YYYYMM`) for schedule +
  finals, one game summary per completed game for FGA/FTA/OREB/TOV. Scoreboard stats lack OREB/TOV, so summaries
  are required.
- **Sample:** regular season only (season type 2), excluding the All-Star round robin (ESPN files it as regular
  season, competition type `ALLSTAR`). The NBA Cup final is kept (a real game).
- **Early season:** a team with < 10 games this season is rated on last season's full regular season
  (`source = last_season`, "last season" chip). Each team switches over on its own.
- **No look-ahead:** a day's projections use only games that tipped before 10:00Z that day.
- **Cache:** `server/data/nba_boxscores_<season>.json` (gitignored) — box counts + slimmed past-month scoreboards
  (~1.2 MB/season). Stores held in memory after first load; file I/O off the event loop. First-ever build pulls
  ~1,230 summaries (~15 s). Projections memoized 5 min per date; market lines re-read per request.
- **Market comparison:** consensus main spread / total from the odds snapshot (`nba`), matched by team pair AND
  tip-off within 6 h (teams meet 2–4×/season — pair alone attached future lines to past games).

## Files

- `server/nba/efficiency.py` — math; `server/nba/service.py` — ESPN loader + slate; `server/api/nba.py` —
  `GET /api/nba/predictions?date=YYYY-MM-DD`
- `web/app/nba/page.tsx` (day stepper, Games / Teams), `web/app/nba/game/[eventId]/page.tsx` (breakdown),
  `web/components/nba/*`, `web/lib/nba.ts`; nav section `nba`. Reuses `TeamLogo` / `SearchBox` from
  `components/cfb/cfb-bits.tsx`.
- Tests: `server/tests/test_nba_efficiency.py`

## Baseline accuracy — 2025-26 regular season backtest (no look-ahead)

| Sample | n | Total MAE | Total bias | Margin MAE | Winner |
|---|---|---|---|---|---|
| All games — model | 1,231 | 15.5 | +0.3 | 12.5 | 60.7% |
| All games — pace-matched | 1,231 | 15.5 | — | 11.9 | 66.4% |
| On last-season ratings (opening weeks) — model | 155 | 14.9 | −5.7 | 11.9 | 62.6% |
| On this-season ratings — model | 1,076 | 15.6 | +1.2 | 12.6 | 60.4% |

Notes: pace-matched beats the specified model on margin / winner over the full season (11.9 vs 12.5 MAE, 66.4%
vs 60.7%). Opening weeks on last-season numbers ran 5.7 pts low on totals (league scoring rose year over year).
No historical market lines in the backtest, so model-vs-market leans are unvalidated — treat them as
screening, not edges.

## Update 2026-10-20 — SGP screener (`/nba?view=sgp`)

User's three-step same-game-parlay method, as a third view on `/nba` (`GET /api/nba/sgp?date=`):

1. **Usage ≥ 24%** — box-score usage over the sample:
   100 × Σ(FGA + 0.44 FTA + TOV) / Σ(MIN ÷ (team MIN/5) × (team FGA + 0.44 team FTA + team TOV)).
2. **Opponent bottom-10 vs the position** — fantasy points allowed per game to G / F / C (ESPN listed position),
   FanDuel scoring without bonuses (PTS + 1.2 REB + 1.5 AST + 3 STL + 3 BLK − TOV). Rank 1 = allows the most;
   qualifies at rank ≤ 10. Opponent's this-season table once it has 10 games, else last season.
3. **Alt-line legs** — the highest points (10, 15, … 50), rebounds (3+ …) and assists (2+ …) rung each hit in
   ≥ 93% of sample games. Sample = this season once the player has 10 games, else last season; a player needs
   ≥ 10 sample games to pass (a 1-for-1 rookie is not "100%").

Combined probability = **empirical joint rate** (games where all three hit together), not the product — the legs
share minutes. Also returned: product, union floor (1 − Σ misses), conservative = one-sided 90% Wilson lower bound
on the joint rate. Break-even American price for each; **"Beat" headlines the conservative price** (see backtest).

- Upcoming games: ESPN current roster + injury status. Finished games: the players who actually played, their
  real lines, and Hit/Miss — so any past day can be audited.
- SGP prices exist only in each book's slip (no feed), so the screen ends at the break-even; the price check is
  manual.
- Player lines come from the same game summaries as the team model (`players` in the season store).
- Files: `server/nba/sgp.py` (math), `NbaPredictionService.get_sgp` / `_build_sgp`, `web/components/nba/nba-sgp.tsx`.
  Tests: `server/tests/test_nba_sgp.py`.

### Backtest — 2025-26 regular season, screened each day on prior games only

| Sample | n | Raw joint (predicted) | Conservative | Actually hit |
|---|---|---|---|---|
| Qualifying (all 3 steps) | 209 | 90.6% | 82.2% | **81.3%** |
| — on this-season sample | 161 | 90.6% | 81.8% | 80.1% |
| — on last-season sample (opening weeks) | 48 | 90.5% | 83.4% | 85.4% |
| Usage + legs, matchup NOT bottom-10 | 430 | 90.0% | 81.8% | 78.4% |
| Qualifying, raw 80–90% | 107 | 87.0% | 78.4% | 84.1% |
| Qualifying, raw 90–95% | 66 | 92.1% | 84.2% | 80.3% |
| Qualifying, raw 95–100% | 36 | 98.2% | 89.8% | 75.0% |

Takeaways: the raw hit rate overstates the true rate by ~9 pts (selection on past outcomes + small samples), worst
at the top — the "safest-looking" parlays hit least. The conservative bound is calibrated (82.2% vs 81.3%). At
81.3% the break-even is about −435, so the −900 the method implies would have lost money. The matchup filter adds
~3 pts (81.3% vs 78.4%) — directionally right, not significant at these n. No SGP prices in the backtest, so actual
ROI is unmeasured.
