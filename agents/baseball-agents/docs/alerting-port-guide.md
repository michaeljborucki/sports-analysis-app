# Four-Channel Discord Alerting — Port Reference

Reference for replicating the MLB project's Discord alerting setup in another
sport's repo. Covers channel responsibilities, config schema, module layout,
unit conventions, guards, hook points, and backfill recipe.

## Channels & Triggers

| # | Config key        | Env var                         | Content                               | Fired by                                                                 |
|---|-------------------|---------------------------------|---------------------------------------|--------------------------------------------------------------------------|
| 1 | `discord`         | `DISCORD_WEBHOOK_URL`           | Today's pre-game bet card             | `main.py daily` → `notify.dispatch.send_notifications`                   |
| 2 | `discord_grades`  | `DISCORD_GRADES_WEBHOOK_URL`    | Graded game-by-game blocks            | `main.py results` → `notify.grades.send_grade_notifications`             |
| 3 | `discord_summary` | `DISCORD_SUMMARY_WEBHOOK_URL`   | Daily record + per-bet-type breakdown | same call as #2 (dual-channel dispatcher)                                |
| 4 | `discord_season`  | `DISCORD_SEASON_WEBHOOK_URL`    | Rolling cumulative "as of X"          | `main.py results` → `notify.season.send_season_notification`             |

## Module Layout (`notify/`)

- `config.py` — loads `data/alerts_config.json`, resolves `${ENV_VAR}` placeholders, exposes `discord_enabled`, `discord_grades_enabled`, `discord_summary_enabled`, `discord_season_enabled`.
- `discord.py` — thin POST wrapper with a 0.5s inter-message pause and 429 retry honoring `retry_after`.
- `format.py` — `format_header`, `_format_bet_line`, `split_to_messages` (picks); `_format_grade_line`, `format_grade_game_block`, `split_grade_blocks`, `format_grade_header`, `format_season_summary`, `unit_profit_and_risk`, `_aggregate`.
- `dispatch.py` — picks dispatcher; dedupes **per bet** in `data/notifications_sent.json`.
- `grades.py` — grades + summary dispatchers in one call; dedupes **per channel per date** in `data/grade_notifications_sent.json` (`{date: {grades: bool, summary: bool}}`).
- `season.py` — season dispatcher; dedupes **per date** in `data/season_notifications_sent.json`.

## Config template (`data/alerts_config.json`)

```json
{
  "discord":         { "enabled": true, "webhook_url": "${DISCORD_WEBHOOK_URL}" },
  "discord_grades":  { "enabled": true, "webhook_url": "${DISCORD_GRADES_WEBHOOK_URL}" },
  "discord_summary": { "enabled": true, "webhook_url": "${DISCORD_SUMMARY_WEBHOOK_URL}" },
  "discord_season":  { "enabled": true, "webhook_url": "${DISCORD_SEASON_WEBHOOK_URL}" },
  "bet_types": ["moneyline", "run_line", "total", "nrfi"],
  "min_edge_pct": 0.0,
  "min_kelly_pct": 0.0
}
```

Replace `bet_types` with the sport's markets.

## Env vars (`.env`)

```
DISCORD_WEBHOOK_URL=...
DISCORD_GRADES_WEBHOOK_URL=...
DISCORD_SUMMARY_WEBHOOK_URL=...
DISCORD_SEASON_WEBHOOK_URL=...
```

## Unit convention (flat 1u stake)

```
Fav W (odds<0): +100/|odds|   | L: -1.00  | stake: 1u
Dog W (odds>0): +odds/100     | L: -1.00  | stake: 1u
Push:           profit=0, risk=0 (excluded from ROI denom)
ROI = Σprofit / Σrisk
```

## Guards baked in

- `send_grade_notifications` and `send_season_notification` no-op when `game_date >= today` (results unsettled same-day).
- Grader skips both dispatchers on `--regrade`.
- Dedupe blocks re-posts unless `force=True` is passed.
- `--no-notify` flag on the results CLI command for silent grading.

## Hook in the grader (`agents/results_grader.py`, after the grading loop)

```python
if notify and not regrade:
    from notify import send_grade_notifications, send_season_notification
    send_grade_notifications(game_date=game_date)
    send_season_notification(through_date=game_date)
```

Click command signature:

```python
@click.command()
@click.option("--date", "game_date", default=None)
@click.option("--regrade", is_flag=True)
@click.option("--no-notify", is_flag=True)
def main(game_date, regrade, no_notify):
    run_results_grader(game_date, regrade=regrade, notify=not no_notify)
```

## Column widths (keep ≤75 chars so Discord desktop code blocks don't wrap)

- Bet row: `TYPE(14) | SIDE(14) | ODDS(5) | MODEL(5) | EDGE(5) | BE(5)`
- Grade row: `TYPE(14) | SIDE(14) | ODDS(5) | RESULT(6) | UNITS(6)`
- Header style: `**Title — DATE**\n_subtitle_\n• \`type      \` W-L-P · +X.XXu · ROI +X.X%` (backticks force monospace alignment in Discord markdown)
- `DISCORD_MAX = 1900` leaves room for triple-backtick fences under the 2000-char per-message limit.

## Backfill recipe

```python
import time
from datetime import date, timedelta
from notify.grades import send_grade_notifications
from notify.season import send_season_notification

d, end = date(2026, 3, 27), date(2026, 4, 17)
while d <= end:
    ds = d.isoformat()
    send_grade_notifications(ds, force=True)    # channels 2 + 3
    send_season_notification(ds, force=True)    # channel 4
    d += timedelta(days=1)
    time.sleep(2.0)
```

A 2s sleep between dates is comfortably under Discord's 30 req/min per-webhook limit.

## Porting checklist

1. Copy `notify/` into the new project. Adjust imports: `config.DATA_DIR`, `tracker.load_bets`, odds helpers (`prob_to_american`, `american_be_with_wiggle`).
2. Copy `data/alerts_config.json` template; swap `bet_types` for the sport's markets.
3. Create four Discord webhooks in the target server; paste URLs into the new project's `.env` using the same var names.
4. Wire `send_notifications` at the end of `main.py daily` (add a `--no-notify` flag).
5. Wire `send_grade_notifications` + `send_season_notification` at the end of the grader (see hook above).
6. Confirm `bets.csv` schema has at minimum: `date, game, bet_type, side, odds, sim_prob, edge, kelly_pct, result, profit, market_prob`.
7. Run one dry-run per channel (`dry_run=True, force=True`) to verify line widths and formatting before flipping `enabled: true` on the config.

## Manual testing snippets

```bash
# Picks dry-run
python main.py notify --date 2026-04-18 --dry-run

# Picks live (respects sent-log; use --force to re-send)
python main.py notify --date 2026-04-18 --force

# Grader auto-fires channels 2/3/4:
python main.py results --date 2026-04-17

# Grader without notifications:
python main.py results --date 2026-04-17 --no-notify
```

```python
# Direct dispatcher dry-runs (any channel, any past date):
from notify.grades  import send_grade_notifications
from notify.season  import send_season_notification
send_grade_notifications("2026-04-17", dry_run=True, force=True)
send_season_notification("2026-04-17", dry_run=True, force=True)
```
