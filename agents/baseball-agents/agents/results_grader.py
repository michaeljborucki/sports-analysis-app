"""Morning-after agent: pulls final scores, grades pending bets W/L/P."""
import difflib
import logging
import click
from datetime import date, timedelta

from scrapers.scores import get_final_scores, get_box_score, get_postponed_games
from tracker import load_bets, update_result, get_summary
from notify import send_grade_notifications, send_season_notification

log = logging.getLogger("mirofish.grader")


def _ensure_clv_for_date(game_date: str) -> int:
    """Fill any missing CLV for graded bets on this date.

    Strategy: count graded bets without `close_odds`; if any exist, run a
    historical backfill for the date (idempotent, deduped by closing-line
    capture key), then re-call update_result on each missing bet — that
    triggers the auto-CLV-attach path in tracker.update_result.

    Returns the number of bets that got CLV attached as a result of this call.
    Does nothing (zero cost) if every graded bet already has CLV.
    """
    df = load_bets()
    day = df[df["date"] == game_date]
    settled = day[day["result"].isin(["W", "L", "P"])]
    if settled.empty:
        return 0

    missing_mask = settled["close_odds"].isna() | \
                   (settled["close_odds"].astype(str).str.strip() == "")
    missing = settled[missing_mask]
    if missing.empty:
        return 0

    log.info("CLV missing for %d/%d graded bets on %s — running historical backfill",
             len(missing), len(settled), game_date)
    try:
        from scrapers.closing_lines import historical_backfill_date
        summary = historical_backfill_date(game_date, include_additional=True)
        log.info("Backfill: %d games, %d new closing-line rows",
                 summary.get("captured_games", 0), summary.get("captured_rows", 0))
    except Exception as e:
        log.warning("Historical backfill failed for %s: %s", game_date, e)
        return 0

    # Re-attach CLV by re-calling update_result with the same result
    # (update_result's lookup_clv reads the freshly-populated closing_lines.csv)
    applied = 0
    for idx, row in missing.iterrows():
        try:
            update_result(idx, row["result"])
            applied += 1
        except Exception as e:
            log.warning("CLV re-apply failed for row %d: %s", idx, e)
    log.info("CLV attached to %d/%d previously-missing bets", applied, len(missing))
    return applied

# Bet types that require box score data for grading
PLAYER_PROP_TYPES = {
    "batter_hits", "batter_runs_scored", "batter_rbis",
    "batter_hits_runs_rbis", "batter_total_bases", "batter_strikeouts",
    "pitcher_strikeouts", "pitcher_hits_allowed", "pitcher_earned_runs",
    "pitcher_outs",
}


def _match_score(game_key: str, scores: list[dict]) -> dict | None:
    """Match a bet's game key (AWAY@HOME) to a final score."""
    parts = game_key.split("@")
    if len(parts) != 2:
        return None
    away, home = parts
    for s in scores:
        if s["away"] == away and s["home"] == home:
            return s
    return None


def _parse_over_under(side: str) -> tuple[str, str, float]:
    """Parse 'Subject over/under X.X' into (subject, direction, line)."""
    tokens = side.rsplit(" ", 2)
    if len(tokens) == 3:
        try:
            return tokens[0], tokens[1], float(tokens[2])
        except ValueError:
            pass
    return "", "", 0.0


def _grade_over_under(actual: float, direction: str, line: float) -> str:
    """Grade an over/under bet given actual stat value."""
    if direction == "over":
        return "W" if actual > line else ("P" if actual == line else "L")
    else:
        return "W" if actual < line else ("P" if actual == line else "L")


def _find_player(name: str, players: dict) -> dict | None:
    """Find a player in the box score, with fuzzy matching fallback."""
    if name in players:
        return players[name]
    matches = difflib.get_close_matches(name, players.keys(), n=1, cutoff=0.85)
    if matches:
        return players[matches[0]]
    return None


def _get_batter_stat(batting: dict, bet_type: str) -> int | None:
    """Extract the relevant batting stat for a bet type."""
    stat_map = {
        "batter_hits": "hits",
        "batter_runs_scored": "runs",
        "batter_rbis": "rbi",
        "batter_total_bases": "totalBases",
        "batter_strikeouts": "strikeOuts",
    }
    if bet_type == "batter_hits_runs_rbis":
        return batting.get("hits", 0) + batting.get("runs", 0) + batting.get("rbi", 0)
    key = stat_map.get(bet_type)
    return batting.get(key, 0) if key else None


def _get_pitcher_stat(pitching: dict, bet_type: str) -> int | None:
    """Extract the relevant pitching stat for a bet type."""
    stat_map = {
        "pitcher_strikeouts": "strikeOuts",
        "pitcher_hits_allowed": "hits",
        "pitcher_earned_runs": "earnedRuns",
        "pitcher_outs": "outs",
    }
    key = stat_map.get(bet_type)
    return pitching.get(key, 0) if key else None


def grade_bet(bet_row, score: dict, box_score: dict = None) -> str | None:
    """Grade a single bet as W/L/P based on final score and box score.

    Returns None if the bet cannot be graded (missing data).
    """
    bet_type = bet_row["bet_type"]
    side = str(bet_row["side"])

    home_score = score["home_score"]
    away_score = score["away_score"]
    total = score["total_runs"]

    # --- Game-level bets ---

    if bet_type == "moneyline":
        home_won = home_score > away_score
        if side == "home":
            return "W" if home_won else "L"
        else:
            return "W" if not home_won else "L"

    elif bet_type == "run_line":
        tokens = side.split()
        rl_side = tokens[0] if tokens else ""
        spread = float(tokens[1]) if len(tokens) > 1 else 0
        if rl_side == "home":
            adjusted = home_score + spread
            return "W" if adjusted > away_score else ("P" if adjusted == away_score else "L")
        else:
            adjusted = away_score + spread
            return "W" if adjusted > home_score else ("P" if adjusted == home_score else "L")

    elif bet_type == "total":
        tokens = side.split()
        direction = tokens[0] if tokens else ""
        line = float(tokens[1]) if len(tokens) > 1 else 0
        return _grade_over_under(total, direction, line)

    elif bet_type in ("team_total_home", "team_total_away"):
        _, direction, line = _parse_over_under(side)
        team_score = home_score if "home" in side else away_score
        return _grade_over_under(team_score, direction, line)

    elif bet_type == "nrfi":
        total_1 = score.get("total_runs_1", 0)
        if side == "NRFI":
            return "W" if total_1 == 0 else "L"
        else:  # YRFI
            return "W" if total_1 > 0 else "L"

    elif bet_type == "first_1_rl":
        home_1 = score.get("home_score_1", 0)
        away_1 = score.get("away_score_1", 0)
        tokens = side.split()
        rl_side = tokens[0] if tokens else ""
        spread = float(tokens[1]) if len(tokens) > 1 else 0
        if rl_side == "home":
            adjusted = home_1 + spread
            return "W" if adjusted > away_1 else ("P" if adjusted == away_1 else "L")
        else:
            adjusted = away_1 + spread
            return "W" if adjusted > home_1 else ("P" if adjusted == home_1 else "L")

    elif bet_type == "first_3_total":
        total_3 = score.get("total_runs_3", 0)
        tokens = side.split()
        direction = tokens[0] if tokens else ""
        line = float(tokens[1]) if len(tokens) > 1 else 0
        return _grade_over_under(total_3, direction, line)

    elif bet_type == "first_3_ml":
        home_3 = score.get("home_score_3", 0)
        away_3 = score.get("away_score_3", 0)
        if "home" in side:
            return "W" if home_3 > away_3 else ("P" if home_3 == away_3 else "L")
        else:
            return "W" if away_3 > home_3 else ("P" if away_3 == home_3 else "L")

    elif bet_type == "first_3_rl":
        home_3 = score.get("home_score_3", 0)
        away_3 = score.get("away_score_3", 0)
        tokens = side.split()
        rl_side = tokens[0] if tokens else ""
        spread = float(tokens[1]) if len(tokens) > 1 else 0
        if rl_side == "home":
            adjusted = home_3 + spread
            return "W" if adjusted > away_3 else ("P" if adjusted == away_3 else "L")
        else:
            adjusted = away_3 + spread
            return "W" if adjusted > home_3 else ("P" if adjusted == home_3 else "L")

    elif bet_type == "first_5_ml":
        home_5 = score.get("home_score_5", 0)
        away_5 = score.get("away_score_5", 0)
        if "home" in side:
            return "W" if home_5 > away_5 else ("P" if home_5 == away_5 else "L")
        else:
            return "W" if away_5 > home_5 else ("P" if away_5 == home_5 else "L")

    elif bet_type == "first_5_total":
        total_5 = score.get("total_runs_5", 0)
        tokens = side.split()
        direction = tokens[0] if tokens else ""
        line = float(tokens[1]) if len(tokens) > 1 else 0
        return _grade_over_under(total_5, direction, line)

    elif bet_type == "first_5_rl":
        home_5 = score.get("home_score_5", 0)
        away_5 = score.get("away_score_5", 0)
        tokens = side.split()
        rl_side = tokens[0] if tokens else ""
        spread = float(tokens[1]) if len(tokens) > 1 else 0
        if rl_side == "home":
            adjusted = home_5 + spread
            return "W" if adjusted > away_5 else ("P" if adjusted == away_5 else "L")
        else:
            adjusted = away_5 + spread
            return "W" if adjusted > home_5 else ("P" if adjusted == home_5 else "L")

    elif bet_type == "first_5":
        # Legacy bet type format
        home_5 = score.get("home_score_5", 0)
        away_5 = score.get("away_score_5", 0)
        total_5 = score.get("total_runs_5", 0)
        if "F5 ML" in side:
            if "home" in side:
                return "W" if home_5 > away_5 else ("P" if home_5 == away_5 else "L")
            else:
                return "W" if away_5 > home_5 else ("P" if away_5 == home_5 else "L")
        elif "total" in side.lower():
            tokens = side.split()
            direction = tokens[0]
            line = float(tokens[-1])
            return _grade_over_under(total_5, direction, line)

    # --- Player props (require box score) ---

    if bet_type in PLAYER_PROP_TYPES:
        if box_score is None:
            return None

        player_name, direction, line = _parse_over_under(side)
        if not player_name or not direction:
            return None

        player = _find_player(player_name, box_score)
        if player is None:
            log.warning("Player '%s' not found in box score (DNP) — grading as push", player_name)
            return "P"

        if bet_type.startswith("batter_"):
            if player["batting"].get("plateAppearances", 0) == 0:
                log.warning("Player '%s' had 0 PA (DNP) — grading as push", player_name)
                return "P"
            stat_value = _get_batter_stat(player["batting"], bet_type)
        else:  # pitcher_*
            if player["pitching"].get("battersFaced", 0) == 0:
                log.warning("Player '%s' faced 0 batters (DNP) — grading as push", player_name)
                return "P"
            stat_value = _get_pitcher_stat(player["pitching"], bet_type)

        if stat_value is None:
            return None

        return _grade_over_under(stat_value, direction, line)

    return None  # Unknown bet type


def run_results_grader(game_date: str = None, regrade: bool = False,
                       notify: bool = True):
    """Grade all pending bets for a given date."""
    if game_date is None:
        yesterday = date.today() - timedelta(days=1)
        game_date = yesterday.isoformat()

    click.echo(f"\n=== Results Grader — {game_date} ===\n")

    # Pull final scores
    scores = get_final_scores(game_date)
    click.echo(f"Found {len(scores)} final scores")

    if not scores:
        click.echo("No final scores available yet.")
        return

    # Load bets
    df = load_bets()

    if regrade:
        from config import BETS_CSV
        from tracker import atomic_write_csv, file_lock
        with file_lock(BETS_CSV):
            # Re-read under the lock so we don't clobber concurrent writes
            df = load_bets()
            date_mask = df["date"] == game_date
            graded_mask = df["result"].isin(["W", "L", "P"])
            to_reset = df[date_mask & graded_mask]
            if not to_reset.empty:
                click.echo(f"Resetting {len(to_reset)} previously graded bets for re-grading...")
                df.loc[date_mask, "result"] = ""
                df.loc[date_mask, "profit"] = ""
                atomic_write_csv(df, BETS_CSV)
        df = load_bets()

    pending = df[(df["date"] == game_date) & (~df["result"].isin(["W", "L", "P"]))]

    if pending.empty:
        click.echo("No pending bets for this date.")
        return

    click.echo(f"Grading {len(pending)} pending bets...\n")

    # Auto-push bets on postponed/canceled games (sportsbook convention: void → Push).
    # Done before the main loop so postponed-game bets don't waste a score-match try.
    try:
        postponed = get_postponed_games(game_date)
    except Exception as e:
        log.warning("get_postponed_games failed for %s: %s", game_date, e)
        postponed = []
    postponed_keys = {f"{p['away']}@{p['home']}" for p in postponed}
    if postponed_keys:
        click.echo(f"Postponed/canceled games: {', '.join(sorted(postponed_keys))} — auto-pushing")

    # Fetch box scores for games that have player prop bets
    box_scores = {}
    prop_games = set()
    for _, row in pending.iterrows():
        if row["bet_type"] in PLAYER_PROP_TYPES:
            score = _match_score(row["game"], scores)
            if score and score.get("game_pk"):
                prop_games.add((row["game"], score["game_pk"]))

    for game_key, game_pk in prop_games:
        bs = get_box_score(game_pk)
        if bs:
            box_scores[game_key] = bs
            click.echo(f"  Fetched box score for {game_key} ({len(bs)} players)")
        else:
            click.echo(f"  WARNING: Could not fetch box score for {game_key}")

    graded = 0
    for idx, row in pending.iterrows():
        if row["game"] in postponed_keys:
            update_result(idx, "P")
            graded += 1
            click.echo(
                f"  [=] {row['game']} | {row['bet_type']} {row['side']} → P (postponed)"
            )
            continue

        score = _match_score(row["game"], scores)
        if not score:
            click.echo(f"  {row['game']}: No score found, skipping")
            continue

        box_score = box_scores.get(row["game"])
        result = grade_bet(row, score, box_score)

        if result is None:
            click.echo(f"  [?] {row['game']} | {row['bet_type']} {row['side']} — SKIP (cannot grade)")
            continue

        update_result(idx, result)
        graded += 1

        emoji = {"W": "+", "L": "-", "P": "="}[result]
        click.echo(
            f"  [{emoji}] {row['game']} | {row['bet_type']} {row['side']} "
            f"→ {result} (Score: {score['away_score']}-{score['home_score']})"
        )

    click.echo(f"\nGraded {graded} bets.")
    summary = get_summary()
    click.echo(f"Season record: {summary['record']} | Profit: {summary['profit']} units | ROI: {summary['roi']}%")

    # Ensure CLV is populated before notifying. Idempotent and free when
    # close-capture already covered the date; falls back to historical
    # backfill only if some bets are missing CLV.
    try:
        attached = _ensure_clv_for_date(game_date)
        if attached:
            click.echo(f"CLV: backfilled and attached to {attached} previously-missing bets")
    except Exception as e:
        log.exception("CLV ensure-step failed (continuing): %s", e)

    if notify and not regrade:
        try:
            n = send_grade_notifications(game_date=game_date)
            if n["grades_sent"] or n["summary_sent"]:
                click.echo(
                    f"Posted: grades={n['grades_sent']} msg(s), summary={n['summary_sent']} msg "
                    f"({n['bets_filtered']} of {n['bets_graded']} graded picks)."
                )
            elif n["skipped_reason"]:
                click.echo(f"Grade notify: skipped ({n['skipped_reason']}).")
        except Exception as e:
            log.exception("Grade notification dispatch failed")
            click.echo(f"Grade notify: dispatch error: {e}")

        try:
            s = send_season_notification(through_date=game_date)
            if s["sent"]:
                click.echo(f"Season channel: posted season totals ({s['bets_filtered']} bets).")
            elif s["skipped_reason"]:
                click.echo(f"Season notify: skipped ({s['skipped_reason']}).")
        except Exception as e:
            log.exception("Season notification dispatch failed")
            click.echo(f"Season notify: dispatch error: {e}")


@click.command()
@click.option("--date", "game_date", default=None, help="Date to grade (YYYY-MM-DD), defaults to yesterday")
@click.option("--regrade", is_flag=True, help="Reset and re-grade all bets for the date")
@click.option("--no-notify", is_flag=True, help="Skip posting the graded card to the Discord grades channel")
def main(game_date, regrade, no_notify):
    """Grade yesterday's bets against final scores."""
    run_results_grader(game_date, regrade=regrade, notify=not no_notify)


if __name__ == "__main__":
    main()
