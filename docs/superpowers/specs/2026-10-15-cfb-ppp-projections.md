# CFB points-per-play projections (`/cfb`)

## Model (user-specified)

For team A vs team B:

    off_est = plays_A × off_ppp_A
    def_est = plays_A × def_ppp_B
    proj_A  = (off_est + def_est) / 2

- plays = season-average offensive plays per game (pass attempts + rush attempts; college rushes include sacks)
- off_ppp = points scored ÷ own offensive plays
- def_ppp = points allowed ÷ opponents' offensive plays
- Final scores are used as-is (defensive/return TDs count toward the scoring team) — deliberate simplification.
- No home-field, neutral-site, or strength-of-schedule adjustment.

## Decisions

- **Data:** ESPN public site API (free, keyless, unmetered). Scoreboard per regular-season week (`groups=80`, games with an FBS team) + one game summary per completed game for attempts. ESPN's season-stats endpoint was rejected: it returns 0 for points allowed.
- **Cache:** completed box scores + fully-completed past-week scoreboards in `server/data/cfb_boxscores_<season>.json` (gitignored). Projections memoized 10 min; market lines re-read per request.
- **No look-ahead:** a week's projections use only games from earlier weeks, so past weeks show what the model said going in (predicted vs final side by side).
- **Market comparison:** consensus main spread / total from the odds snapshot (most-quoted point in `spreads` / `totals`), matched to ESPN teams via `server/systems/team_names.TeamIndex`. Lean chips appear at ≥ 0.5 pts.
- **Small sample:** teams with < 3 games flagged (mostly FCS teams with only their FBS games in the data).

## Files

- `server/cfb/ppp.py` — math; `server/cfb/service.py` — ESPN loader + slate; `server/api/cfb.py` — `GET /api/cfb/predictions?week=`
- `web/app/cfb/page.tsx`, `web/components/cfb/*`, `web/lib/cfb.ts`; nav section `cfb`
- Tests: `server/tests/test_cfb_ppp.py`

## Baseline accuracy

Week 6 2026 (58 games, ratings from 390 prior games): mean absolute error 13.5 pts on totals, 14.0 pts on margin.

## Update 2026-10-15 — per-game layout

- `/cfb` Games view is now a grid of per-game cards (`web/components/cfb/cfb-game-card.tsx`,
  `cfb-games-grid.tsx`): each team's projected score, the inline formula
  (plays × off PPP, plays × opponent def PPP → avg), final score once played, and
  model vs market total/spread.
- New per-game page `/cfb/game/[eventId]?week=N`: projected scoreboard, step-by-step
  derivation per team, season-to-date stats side by side, model vs market with leans.
  Reuses `/api/cfb/predictions?week=N` — no new API.

## Update 2026-10-16 — FCS games

- Service loads ESPN `groups=81` (FCS) scoreboards alongside `groups=80` (FBS). groups=81
  repeats FBS-vs-FCS games, so events are de-duplicated (FBS copy wins). FCS scoreboards are
  cached under `"fcs:<week>"` keys; FBS keys unchanged.
- One rating pool across both divisions: FCS teams' rates now include their FCS-vs-FCS games.
  Verified: FBS-vs-FBS projections identical before/after (wk7 59/59, wk6 58/58); only
  FBS-vs-FCS games shift (wk7: 3).
- Games/teams carry `division` ("fbs" = at least one FBS team; "fcs" = FCS vs FCS). Teams that
  played an FCS-vs-FCS game are tagged fcs — includes a few non-D1 opponents.
- UI: All / FBS / FCS filter (`?div=`), FCS chip on cards, game-page Prev/Next within division.
- Week 7: 62 FBS + 56 FCS games, 808 games in the pool (4 skipped, no box score), 54/56 FCS
  games matched a market line. Week 6 backtest: FBS n=58 MAE total 13.5 / margin 14.0;
  FCS n=49 MAE total 17.1 / margin 12.9.
