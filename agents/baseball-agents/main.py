"""CLI entrypoint for MiroFish MLB Prediction Pipeline."""
import logging
import os
import sys
import time
import click
from concurrent.futures import TimeoutError as FuturesTimeoutError
from datetime import date, datetime

# Universal agent rules live in the shared `agents/` directory, one level up from
# this sport package. Put it on the path so the pipeline can opt into cross-sport
# behaviors (e.g. priority alerts). See agents/universal/README.md.
_AGENTS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENTS_ROOT not in sys.path:
    sys.path.append(_AGENTS_ROOT)

from config import SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT, PARALLEL_GAMES
from universal.priority import run_priority_pipeline

logger = logging.getLogger("mirofish")
from scrapers.pitchers import get_probable_starters, get_starter_profile
from scrapers.lineups import get_confirmed_lineups
from scrapers.bullpen import get_bullpen_state
from scrapers.team_stats import get_team_profile
from scrapers.ballpark import get_game_environment
from scrapers.odds import get_mlb_odds
from scrapers.news import get_injuries
from briefing import build_briefing
from simulate import run_plan_b, run_mirofish
from edge import analyze_all_edges
from tracker import log_bet, get_summary
from agents.results_grader import run_results_grader
from agents.bet_card import format_bet_card
from agents.health_check import run_health_check
from agents.self_optimizer import run_optimizer
from cache import (
    compute_starters_hash, get_cache_entry, set_cache_entry, rotate_old_cache,
)


@click.group()
def cli():
    """MiroFish MLB Prediction Pipeline"""
    pass


_NO_ODDS = "NO_ODDS"
_SCREEN_FAILED = "SCREEN_FAILED"


def _screen_game(game, odds_by_teams, injuries_by_team, game_date):
    """Screen a single game for edges. Thread-safe, no signal handling.

    Returns (game_key, brief, game_data, max_edge), or a string sentinel:
      _NO_ODDS if no odds matched, _SCREEN_FAILED if LLM screen failed.
    """
    away = game["away_team"]
    home = game["home_team"]
    game_key = f"{away}@{home}"

    odds = odds_by_teams.get(game_key)
    if not odds:
        return _NO_ODDS

    game_pk = game.get("game_pk")
    lineup_data = game.get("_lineup")
    starters_hash = compute_starters_hash(lineup_data) if lineup_data else ""
    cache_hit = None
    if starters_hash and game_pk:
        cache_hit = get_cache_entry(game_pk, starters_hash, game_date)

    try:
        try:
            away_pitcher = get_starter_profile(
                game["away_pitcher"], season=int(game_date[:4])
            ) if game["away_pitcher"] != "TBD" else {"name": "TBD"}
        except Exception:
            away_pitcher = {"name": game["away_pitcher"]}

        try:
            home_pitcher = get_starter_profile(
                game["home_pitcher"], season=int(game_date[:4])
            ) if game["home_pitcher"] != "TBD" else {"name": "TBD"}
        except Exception:
            home_pitcher = {"name": game["home_pitcher"]}

        away_profile = get_team_profile(away, season=int(game_date[:4]))
        home_profile = get_team_profile(home, season=int(game_date[:4]))
        env = get_game_environment(home, game_date)

        # Fetch batter stats for each confirmed lineup slot so the briefing
        # can surface real offense context to the LLM. Cheap when the lineup
        # has already been cached by the screen; skipped entirely when no
        # lineup is confirmed (brief renders "(lineup not yet confirmed)").
        home_batters: list = []
        away_batters: list = []
        if lineup_data:
            from scrapers.player_stats import get_batter_stats
            names = lineup_data.get("names", {})
            season = int(game_date[:4])
            for pid in lineup_data.get("home", [])[:9]:
                b = get_batter_stats(pid, season)
                b["full_name"] = names.get(pid, f"Player {pid}")
                home_batters.append(b)
            for pid in lineup_data.get("away", [])[:9]:
                b = get_batter_stats(pid, season)
                b["full_name"] = names.get(pid, f"Player {pid}")
                away_batters.append(b)

        game_data = {
            "away_team": away,
            "home_team": home,
            "away_record": away_profile.get("record", ""),
            "home_record": home_profile.get("record", ""),
            "away_pitcher": away_pitcher,
            "home_pitcher": home_pitcher,
            "away_batters": away_batters,
            "home_batters": home_batters,
            "odds": {
                "moneyline": odds.moneyline,
                "run_line": odds.run_line,
                "total": odds.total,
                "f5_moneyline": odds.f5_moneyline,
                "f5_total": odds.f5_total,
                "implied_probs": odds.implied_probs,
                "f3_moneyline": odds.f3_moneyline,
                "f3_total": odds.f3_total,
                "f1_total": odds.f1_total,
                "team_total_home": odds.team_total_home,
                "team_total_away": odds.team_total_away,
            },
            "odds_obj": odds,
            "environment": env,
            "away_bullpen": get_bullpen_state(
                game["away_team_id"], game_date
            ) if game.get("away_team_id") else {},
            "home_bullpen": get_bullpen_state(
                game["home_team_id"], game_date
            ) if game.get("home_team_id") else {},
            "away_injuries": injuries_by_team.get(away, []),
            "home_injuries": injuries_by_team.get(home, []),
            "game_pk": game.get("game_pk"),
            "game_time_utc": game.get("game_date", ""),
        }

        brief = build_briefing(game_data)

        if cache_hit and cache_hit.get("screening"):
            screen = cache_hit["screening"]
            logger.info("  %s: screening cache HIT (hash=%s)", game_key, starters_hash)
        else:
            screen = run_plan_b(brief)
            if not screen:
                logger.warning("  %s: LLM screen pass returned None, retrying...", game_key)
                screen = run_plan_b(brief)
            if not screen:
                logger.error("  %s: LLM screen pass returned None after retry", game_key)
                return _SCREEN_FAILED
            if starters_hash and game_pk:
                set_cache_entry(game_pk, starters_hash, game_date, "screening", screen)

        game_data["_starters_hash"] = starters_hash
        edges = analyze_all_edges(screen, game_data["odds_obj"])
        max_edge = max((e["edge"] for e in edges), default=0)

        return (game_key, brief, game_data, max_edge)

    except Exception as e:
        logger.exception("  %s: unexpected error during screening", game_key)
        return _SCREEN_FAILED


def _simulate_game(game_key, brief, game_data, game_date):
    """Run full ensemble simulation on one flagged game. Thread-safe.

    Returns (game_key, bets_list, result_dict).
    """
    sim_start = time.time()
    bets = []
    game_pk = game_data.get("game_pk")
    starters_hash = game_data.get("_starters_hash", "")

    cached = None
    if starters_hash and game_pk:
        cache_hit = get_cache_entry(game_pk, starters_hash, game_date)
        if cache_hit and cache_hit.get("ensemble"):
            cached = cache_hit["ensemble"]

    if cached:
        result = cached
        sim_elapsed = time.time() - sim_start
        logger.info("  %s: ensemble cache HIT (hash=%s) in %.1fs",
                    game_key, starters_hash, sim_elapsed)
    else:
        result = run_mirofish(brief, runs=3, odds=game_data["odds"], game_label=game_key)
        sim_elapsed = time.time() - sim_start
        if not result:
            logger.warning("  %s: simulation returned None after %.1fs", game_key, sim_elapsed)
            return (game_key, [], None)
        meta = result.get("ensemble_meta", {})
        logger.info("  %s: simulation complete in %.1fs — phase=%d, calls=%d, cost=$%.4f",
                    game_key, sim_elapsed, meta.get("phase_reached", 0),
                    meta.get("total_calls", 0), meta.get("cost_usd", 0))
        if starters_hash and game_pk:
            set_cache_entry(game_pk, starters_hash, game_date, "ensemble", result)

    game_time_utc = game_data.get("game_time_utc", "")
    game_bets = analyze_all_edges(result, game_data["odds_obj"])
    for bet in game_bets:
        bet["date"] = game_date
        bet["game"] = game_key
        bet["game_time"] = game_time_utc
        log_bet(bet)
        bets.append(bet)

    # Monte Carlo prop simulation if lineups confirmed
    try:
        from simulation.monte_carlo import run_monte_carlo
        from simulation.props_edge import get_prop_odds, analyze_all_props
        from scrapers.player_stats import get_lineup, get_batter_stats, get_pitcher_stats
        from config import PARK_FACTORS

        odds_obj = game_data.get("odds_obj")
        if game_pk and odds_obj and odds_obj.event_id:
            lineup_data = game_data.get("_lineup") or get_lineup(game_pk)
            if lineup_data and lineup_data.get("home") and lineup_data.get("away"):
                season = int(game_date[:4])
                home_lineup = [get_batter_stats(pid, season) for pid in lineup_data["home"]]
                away_lineup = [get_batter_stats(pid, season) for pid in lineup_data["away"]]
                hp_stats = get_pitcher_stats(lineup_data["home_pitcher"], season)
                ap_stats = get_pitcher_stats(lineup_data["away_pitcher"], season)

                home_abbrev = game_data["home_team"]
                park = PARK_FACTORS.get(home_abbrev, {})
                from simulation.weather import weather_hr_multiplier
                env_for_mc = game_data.get("environment", {}) or {}
                w_mult = weather_hr_multiplier(
                    env_for_mc.get("weather"), env_for_mc.get("roof", "open")
                )
                mc_results = run_monte_carlo(
                    home_lineup=home_lineup, away_lineup=away_lineup,
                    home_pitcher=hp_stats, away_pitcher=ap_stats,
                    park_factor_runs=park.get("runs", 1.0),
                    park_factor_hr=park.get("hr", 1.0),
                    weather_hr_multiplier=w_mult,
                    n_sims=5000,
                )
                logger.info("  %s: MC simulation complete (%d sims, weather_hr=%.3f)",
                            game_key, 5000, w_mult)

                prop_odds = get_prop_odds(odds_obj.event_id)
                prop_bets = analyze_all_props(mc_results, prop_odds)
                for bet in prop_bets:
                    bet["date"] = game_date
                    bet["game"] = game_key
                    bet["game_time"] = game_time_utc
                    log_bet(bet)
                    bets.append(bet)
    except Exception as e:
        logger.error("  %s: MC prop simulation failed: %s", game_key, e)

    return (game_key, bets, result)


def _process_game(game, odds_by_teams, injuries_by_team, game_date):
    """Full per-game analysis: screen → (if flagged) simulate → log. Thread-safe.

    This is the per-game unit the universal priority rule runs. Each game is
    screened and, only if it clears the edge threshold, fully simulated — so the
    expensive ensemble still runs solely on flagged games, just inline per game
    rather than as a separate batch phase. Records the screen outcome in
    analyzed_games state and returns a result dict the runner uses to decide
    whether to alert:

        {"game_key", "status", "bets", "max_edge", "result"?}

    status ∈ {flagged, no_edge, no_odds, screen_error}. Only "flagged" games
    carry bets (possibly empty if the full sim ultimately found no edge).
    """
    from agents.analyzed_games import mark_analyzed
    game_key = f"{game['away_team']}@{game['home_team']}"

    screen = _screen_game(game, odds_by_teams, injuries_by_team, game_date)

    if screen == _NO_ODDS:
        mark_analyzed(game_date, game_key, "no_odds")
        return {"game_key": game_key, "status": "no_odds", "bets": [], "max_edge": 0.0}
    if screen == _SCREEN_FAILED:
        mark_analyzed(game_date, game_key, "screen_error")
        return {"game_key": game_key, "status": "screen_error", "bets": [], "max_edge": 0.0}

    _, brief, game_data, max_edge = screen
    if max_edge < SCREEN_EDGE_THRESHOLD:
        mark_analyzed(game_date, game_key, "no_edge")
        return {"game_key": game_key, "status": "no_edge", "bets": [], "max_edge": max_edge}

    mark_analyzed(game_date, game_key, "flagged")
    _, bets, result = _simulate_game(game_key, brief, game_data, game_date)
    return {"game_key": game_key, "status": "flagged", "bets": bets,
            "max_edge": max_edge, "result": result}


@cli.command()
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
@click.option("--no-lineup-filter", is_flag=True, help="Run all games even without confirmed lineups")
@click.option("--no-notify", is_flag=True, help="Skip Discord/Telegram notifications after pipeline")
def daily(game_date, no_lineup_filter, no_notify):
    """Run full daily pipeline: scrape → screen → simulate → detect edges."""
    if game_date is None:
        game_date = date.today().isoformat()

    pipeline_start = time.time()
    click.echo(f"\n=== MLB Pipeline — {game_date} ===\n")
    logger.info("Pipeline started for %s", game_date)

    rotated = rotate_old_cache(keep_days=30)
    if rotated:
        click.echo(f"  Cache: rotated {rotated} stale file(s)")

    # Step 1: Get schedule + probable pitchers
    click.echo("[1/6] Fetching schedule and probable pitchers...")
    t0 = time.time()
    games = get_probable_starters(game_date)
    if not games:
        click.echo("No games found for this date.")
        logger.warning("No games found for %s — exiting", game_date)
        return
    click.echo(f"  Found {len(games)} games")
    logger.info("Step 1 complete: %d games found (%.1fs)", len(games), time.time() - t0)
    for g in games:
        logger.debug("  %s@%s — %s vs %s", g["away_team"], g["home_team"],
                      g["away_pitcher"], g["home_pitcher"])

    # Step 2: Get odds
    click.echo("[2/6] Fetching odds...")
    t0 = time.time()
    odds_list = get_mlb_odds()
    odds_by_teams = {}
    for o in odds_list:
        key = f"{o.away}@{o.home}"
        odds_by_teams[key] = o

    # Enrich with additional markets (per-event endpoint)
    from scrapers.odds import get_additional_odds, _parse_additional_markets
    for o in odds_list:
        if o.event_id:
            additional = get_additional_odds(o.event_id)
            if additional:
                _parse_additional_markets(o, additional)
    click.echo(f"  Enriched with additional markets")
    logger.info("Step 2 complete: %d odds lines fetched (%.1fs)", len(odds_list), time.time() - t0)

    # Step 3: Get lineups
    click.echo("[3/6] Fetching lineups...")
    t0 = time.time()
    lineups = get_confirmed_lineups(game_date)
    logger.info("Step 3 complete: lineups fetched (%.1fs)", time.time() - t0)

    # Step 4: Get injuries
    click.echo("[4/6] Fetching injuries...")
    t0 = time.time()
    all_injuries = get_injuries()
    injuries_by_team = {}
    for inj in all_injuries:
        team = inj["team"]
        injuries_by_team.setdefault(team, []).append(inj)
    logger.info("Step 4 complete: %d injuries across %d teams (%.1fs)",
                len(all_injuries), len(injuries_by_team), time.time() - t0)

    # Filter to games with confirmed lineups (skip games without batting orders)
    if not no_lineup_filter:
        from scrapers.player_stats import get_lineup
        lineup_ready = []
        lineup_skipped = []
        for game in games:
            game_pk = game.get("game_pk")
            gk = f"{game['away_team']}@{game['home_team']}"
            if game_pk:
                lineup_data = get_lineup(game_pk)
                if lineup_data and lineup_data.get("home") and lineup_data.get("away"):
                    game["_lineup"] = lineup_data
                    lineup_ready.append(game)
                else:
                    lineup_skipped.append(gk)
            else:
                lineup_skipped.append(gk)
        if lineup_skipped:
            click.echo(f"  Skipping {len(lineup_skipped)} games (no confirmed lineup): "
                        f"{', '.join(lineup_skipped)}")
        games = lineup_ready
        click.echo(f"  {len(games)} games with confirmed lineups")
        logger.info("Lineup filter: %d ready, %d skipped", len(games), len(lineup_skipped))
        if not games:
            click.echo("\nNo games with confirmed lineups. Re-run closer to game time or use --no-lineup-filter.")
            return

    # Skip games already analyzed on this date (prevents re-processing on auto-retry triggers)
    from agents.analyzed_games import load_analyzed
    already_analyzed = load_analyzed(game_date)
    if already_analyzed:
        pre_count = len(games)
        games = [g for g in games
                 if f"{g['away_team']}@{g['home_team']}" not in already_analyzed]
        skipped_analyzed = pre_count - len(games)
        if skipped_analyzed:
            click.echo(f"  Skipping {skipped_analyzed} already-analyzed games: "
                        f"{', '.join(sorted(already_analyzed))}")
        if not games:
            click.echo("\nNo unanalyzed games remaining. Exiting.")
            return

    # Odds matching diagnostic
    matched = 0
    unmatched = []
    for game in games:
        gk = f"{game['away_team']}@{game['home_team']}"
        if gk in odds_by_teams:
            matched += 1
        else:
            unmatched.append(gk)
    click.echo(f"  Odds matched: {matched}/{len(games)} games")
    if unmatched:
        click.echo(f"  No odds for: {', '.join(unmatched)}")
        # Show available odds keys for debugging
        logger.info("  Available odds keys: %s", list(odds_by_teams.keys()))
        logger.info("  Unmatched game keys: %s", unmatched)

    # Step 5: Analyze games soonest-first; alert immediately as each finishes.
    #
    # Universal "priority alerts" rule (agents/universal/priority.py). Instead of
    # screening the whole slate, then simulating the whole slate, then sending one
    # batched alert at the very end, we analyze each game end-to-end and fire its
    # alert the moment it's done. Games closest to first pitch are processed first,
    # so the most time-sensitive alerts never wait behind games starting hours
    # later. The expensive ensemble still runs only on flagged games (see
    # `_process_game`), so cost is unchanged.
    click.echo(f"\n[5/5] Analyzing {len(games)} games soonest-first "
               f"({PARALLEL_GAMES} at a time), alerting per game...")
    logger.info("Step 5: priority analysis of %d games (%d parallel, timeout=%ds)",
                len(games), PARALLEL_GAMES, GAME_TIMEOUT)

    notify_enabled = not no_notify
    counts = {"flagged": 0, "no_edge": 0, "no_odds": 0, "screen_error": 0}
    totals = {"bets": 0, "sim_cost": 0.0}

    def _report(game, result):
        """Per-game progress echo + running tallies. Runs on the main thread."""
        gk, status = result["game_key"], result["status"]
        counts[status] = counts.get(status, 0) + 1
        if status == "no_odds":
            click.echo(f"  {gk}: No odds, skipped")
        elif status == "screen_error":
            click.echo(f"  {gk}: SCREEN FAILED (LLM error)")
        elif status == "no_edge":
            click.echo(f"  {gk}: No edge ({result['max_edge']:.1%})")
        else:  # flagged
            totals["sim_cost"] += (result.get("result") or {}).get(
                "ensemble_meta", {}).get("cost_usd", 0)
            bets = result["bets"]
            if bets:
                click.echo(f"  {gk}: FLAGGED — edge {result['max_edge']:.1%} → {len(bets)} bet(s)")
                for bet in bets:
                    click.echo(
                        f"      {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                        f"Edge: {bet['edge']:.1%}"
                    )
                totals["bets"] += len(bets)
            else:
                click.echo(f"  {gk}: FLAGGED — edge {result['max_edge']:.1%}, no bets after full sim")

    def _alert(game_key, result):
        """Fire this one game's alert the instant it finishes. Main thread."""
        if not notify_enabled:
            return
        try:
            from notify import send_notifications
            n = send_notifications(game_date=game_date, game_key=game_key)
            if n["bets_new"]:
                status = (f"sent {n['sent']} Discord message(s)"
                          if n["discord_enabled"] else "Discord not enabled")
                click.echo(f"    Alert: {n['bets_new']} new bet(s) for {game_key} → {status}")
        except Exception as e:
            logger.error("Per-game notification dispatch failed for %s: %s", game_key, e)

    def _on_error(game, exc):
        gk = f"{game['away_team']}@{game['home_team']}"
        from agents.analyzed_games import mark_analyzed
        counts["screen_error"] = counts.get("screen_error", 0) + 1
        if isinstance(exc, FuturesTimeoutError):
            click.echo(f"  {gk}: TIMEOUT ({GAME_TIMEOUT}s)")
            mark_analyzed(game_date, gk, "screen_timeout")
        else:
            click.echo(f"  {gk}: ERROR — {exc}")
            mark_analyzed(game_date, gk, "screen_error")
            logger.error("  %s: unexpected error during analysis: %s", gk, exc)

    summary = run_priority_pipeline(
        games,
        lambda game: _process_game(game, odds_by_teams, injuries_by_team, game_date),
        send_alert=_alert,
        get_game_key=lambda g: f"{g['away_team']}@{g['home_team']}",
        max_workers=PARALLEL_GAMES,
        # Per-game budget covers screen + full sim, each bounded by GAME_TIMEOUT.
        game_timeout=GAME_TIMEOUT * 2,
        on_complete=_report,
        on_error=_on_error,
    )

    total_bets = totals["bets"]
    total_sim_cost = totals["sim_cost"]
    pipeline_elapsed = time.time() - pipeline_start
    click.echo(f"\n  Flagged: {counts['flagged']} | No edge: {counts['no_edge']} | "
               f"No odds: {counts['no_odds']} | Errors: {counts['screen_error']}")
    click.echo(f"\n=== Done. {total_bets} bets logged. (${total_sim_cost:.4f} sim cost, {pipeline_elapsed:.0f}s) ===")
    logger.info("Pipeline complete: %d bets, %d game(s) alerted, cost=$%.4f, elapsed=%.0fs",
                total_bets, summary["alerted"], total_sim_cost, pipeline_elapsed)

    # Safety-net sweep: per-game alerts above are the primary path. This catches
    # any straggler a per-game alert missed (e.g. a transient Discord error).
    # send_notifications dedup guarantees it never re-sends what already went out.
    if notify_enabled and total_bets > 0:
        try:
            from notify import send_notifications
            n_summary = send_notifications(game_date=game_date)
            if n_summary["bets_new"]:
                status = (f"sent {n_summary['sent']} Discord message(s)"
                          if n_summary["discord_enabled"]
                          else "Discord not enabled")
                click.echo(f"  Sweep: {n_summary['bets_new']} unsent bet(s) → {status}")
        except Exception as e:
            logger.error("Final notification sweep failed: %s", e)


@cli.command("notify")
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
@click.option("--force", is_flag=True, help="Re-send already-notified bets")
@click.option("--dry-run", is_flag=True, help="Print messages instead of sending")
def notify_cmd(game_date, force, dry_run):
    """Send filtered bet card to Discord per data/alerts_config.json."""
    from notify import send_notifications

    summary = send_notifications(game_date=game_date, force=force, dry_run=dry_run)
    click.echo(
        f"Notify: {summary['bets_new']} new of {summary['bets_filtered']} "
        f"filtered ({summary['bets_total']} total). "
        f"Discord enabled: {summary['discord_enabled']}. Sent: {summary['sent']}"
    )


@cli.command("close-capture")
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
@click.option("--force", is_flag=True, help="Skip the T-15..T-5 window and capture all upcoming games")
def close_capture(game_date, force):
    """Capture consensus closing odds for in-window games (CLV tracking, no LLM calls)."""
    from scrapers.closing_lines import capture_closing_lines

    summary = capture_closing_lines(game_date=game_date, force=force)
    if summary.get("monitoring_complete_for_today"):
        click.echo("CLV monitoring complete for today — all games have started.")
        return
    click.echo(
        f"CLV capture: {summary['captured_games']} game(s), "
        f"{summary['captured_rows']} new rows "
        f"(skipped {summary['skipped_games']} out-of-window)"
    )


@cli.command("close-backfill")
@click.option("--start", "start_date", required=True, help="Start date YYYY-MM-DD (inclusive)")
@click.option("--end", "end_date", required=True, help="End date YYYY-MM-DD (inclusive)")
@click.option("--no-additional", is_flag=True, help="Skip per-event team_totals + NRFI fetch (cheaper)")
def close_backfill(start_date, end_date, no_additional):
    """Backfill historical mainline closing lines via The Odds API.

    Cost: ~30 credits per snapshot + ~20 credits per event (if --no-additional not set).
    """
    from scrapers.closing_lines import historical_backfill_range

    summary = historical_backfill_range(start_date, end_date,
                                        include_additional=not no_additional)
    click.echo(
        f"CLV backfill {start_date}..{end_date}: "
        f"{summary['captured_games']} game(s), "
        f"{summary['captured_rows']} new rows | "
        f"{summary['snapshot_calls']} snapshot calls + {summary['event_calls']} event calls"
    )


@cli.command("clv-apply")
@click.option("--date", "game_date", default=None, help="Limit to one date (YYYY-MM-DD)")
def clv_apply(game_date):
    """Walk graded bets and back-apply CLV from data/closing_lines.csv."""
    from tracker import load_bets, lookup_clv, BETS_CSV, atomic_write_csv, file_lock
    import pandas as pd

    # Hold the lock across the whole read-modify-write so a concurrent
    # grader/logger write isn't clobbered by our full rewrite.
    with file_lock(BETS_CSV):
        df = pd.read_csv(BETS_CSV)
        for col in ("close_odds", "close_prob", "clv_cents", "clv_pct"):
            if col not in df.columns:
                df[col] = ""

        settled_mask = df["result"].isin(["W", "L", "P"])
        if game_date:
            settled_mask &= (df["date"] == game_date)
        missing_mask = settled_mask & (df["close_odds"].isna() | (df["close_odds"].astype(str).str.strip() == ""))

        candidates = df[missing_mask]
        click.echo(f"Found {len(candidates)} graded bets missing CLV. Applying...")

        applied = 0
        for index, row in candidates.iterrows():
            try:
                clv = lookup_clv(row)
            except Exception as e:
                click.echo(f"  row {index} lookup failed: {e}")
                continue
            if not clv:
                continue
            df.at[index, "close_odds"] = clv["close_odds"]
            df.at[index, "close_prob"] = clv["close_prob"]
            df.at[index, "clv_cents"] = clv["clv_cents"]
            df.at[index, "clv_pct"] = clv["clv_pct"]
            applied += 1

        atomic_write_csv(df, BETS_CSV)
    click.echo(f"Applied CLV to {applied}/{len(candidates)} bets.")


@cli.command()
@click.argument("away_team")
@click.argument("home_team")
@click.option("--date", "game_date", default=None)
@click.option("--away-pitcher", default=None, help="Away starting pitcher name")
@click.option("--home-pitcher", default=None, help="Home starting pitcher name")
def game(away_team, home_team, game_date, away_pitcher, home_pitcher):
    """Analyze a single game."""
    if game_date is None:
        game_date = date.today().isoformat()

    click.echo(f"\nAnalyzing {away_team}@{home_team} on {game_date}...")

    # Look up probable pitchers and game_pk from schedule if not provided
    game_pk = None
    game_time_utc = ""
    if not away_pitcher or not home_pitcher:
        games = get_probable_starters(game_date)
        for g in games:
            if g["away_team"] == away_team and g["home_team"] == home_team:
                away_pitcher = away_pitcher or g["away_pitcher"]
                home_pitcher = home_pitcher or g["home_pitcher"]
                game_pk = g.get("game_pk")
                game_time_utc = g.get("game_date", "")
                break
    else:
        games = get_probable_starters(game_date)
        for g in games:
            if g["away_team"] == away_team and g["home_team"] == home_team:
                game_pk = g.get("game_pk")
                game_time_utc = g.get("game_date", "")
                break

    # Build pitcher profiles
    season = int(game_date[:4])
    ap = get_starter_profile(away_pitcher, season) if away_pitcher and away_pitcher != "TBD" else {"name": "TBD"}
    hp = get_starter_profile(home_pitcher, season) if home_pitcher and home_pitcher != "TBD" else {"name": "TBD"}

    # Get odds
    odds_list = get_mlb_odds()
    game_odds = None
    for o in odds_list:
        if o.away == away_team and o.home == home_team:
            game_odds = o
            break

    if not game_odds:
        click.echo("Could not find odds for this game.")
        return

    # Enrich with additional markets (per-event endpoint)
    from scrapers.odds import get_additional_odds, _parse_additional_markets
    if game_odds.event_id:
        additional = get_additional_odds(game_odds.event_id)
        if additional:
            _parse_additional_markets(game_odds, additional)
            click.echo("  Enriched with additional markets")

    env = get_game_environment(home_team, game_date)
    away_profile = get_team_profile(away_team)
    home_profile = get_team_profile(home_team)

    game_data = {
        "away_team": away_team,
        "home_team": home_team,
        "away_record": away_profile.get("record", ""),
        "home_record": home_profile.get("record", ""),
        "away_pitcher": ap,
        "home_pitcher": hp,
        "odds": {
            "moneyline": game_odds.moneyline,
            "run_line": game_odds.run_line,
            "total": game_odds.total,
            "f5_moneyline": game_odds.f5_moneyline,
            "f5_total": game_odds.f5_total,
            "implied_probs": game_odds.implied_probs,
            "f3_moneyline": game_odds.f3_moneyline,
            "f3_total": game_odds.f3_total,
            "f1_total": game_odds.f1_total,
            "team_total_home": game_odds.team_total_home,
            "team_total_away": game_odds.team_total_away,
        },
        "odds_obj": game_odds,  # OddsData instance for edge detection
        "environment": env,
        "away_bullpen": {},
        "home_bullpen": {},
        "away_injuries": [],
        "home_injuries": [],
        "game_pk": game_pk,
    }

    brief = build_briefing(game_data)
    click.echo("\n--- Briefing ---")
    click.echo(brief[:500] + "...\n")

    click.echo("Running simulation...")
    result = run_mirofish(brief, runs=3, odds=game_data["odds"], game_label=f"{away_team}@{home_team}")
    if not result:
        click.echo("Simulation failed.")
        return

    bets = analyze_all_edges(result, game_data["odds_obj"])
    for bet in bets:
        bet["date"] = game_date
        bet["game"] = f"{away_team}@{home_team}"
        bet["game_time"] = game_time_utc
        click.echo(
            f"  BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
            f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
        )
        log_bet(bet)

    # Monte Carlo prop simulation
    prop_bets = []
    try:
        from simulation.monte_carlo import run_monte_carlo
        from simulation.props_edge import get_prop_odds, analyze_all_props
        from scrapers.player_stats import get_lineup, get_batter_stats, get_pitcher_stats
        from config import PARK_FACTORS

        game_key = f"{away_team}@{home_team}"
        if game_pk and game_odds.event_id:
            lineup_data = get_lineup(game_pk)
            if lineup_data and lineup_data.get("home") and lineup_data.get("away"):
                click.echo("\nRunning Monte Carlo prop simulation (5000 sims)...")
                season = int(game_date[:4])
                home_lineup = [get_batter_stats(pid, season) for pid in lineup_data["home"]]
                away_lineup = [get_batter_stats(pid, season) for pid in lineup_data["away"]]
                hp_stats = get_pitcher_stats(lineup_data["home_pitcher"], season)
                ap_stats = get_pitcher_stats(lineup_data["away_pitcher"], season)

                park = PARK_FACTORS.get(home_team, {})
                from simulation.weather import weather_hr_multiplier
                w_mult = weather_hr_multiplier(
                    env.get("weather"), env.get("roof", "open")
                )
                mc_results = run_monte_carlo(
                    home_lineup=home_lineup, away_lineup=away_lineup,
                    home_pitcher=hp_stats, away_pitcher=ap_stats,
                    park_factor_runs=park.get("runs", 1.0),
                    park_factor_hr=park.get("hr", 1.0),
                    weather_hr_multiplier=w_mult,
                    n_sims=5000,
                )

                prop_odds = get_prop_odds(game_odds.event_id)
                prop_bets = analyze_all_props(mc_results, prop_odds)
                for bet in prop_bets:
                    bet["date"] = game_date
                    bet["game"] = game_key
                    bet["game_time"] = game_time_utc
                    click.echo(
                        f"  PROP: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                        f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
                    )
                    log_bet(bet)
                click.echo(f"\n  {len(prop_bets)} prop edges found.")
            else:
                click.echo("\nNo confirmed lineup — skipping prop simulation.")
        else:
            if not game_pk:
                click.echo("\nNo game_pk — skipping prop simulation.")
            elif not game_odds.event_id:
                click.echo("\nNo event_id — skipping prop simulation.")
    except Exception as e:
        click.echo(f"\nProp simulation failed: {e}")
        logger.exception("MC prop simulation failed for %s@%s", away_team, home_team)

    total = len(bets) + len(prop_bets)
    if total == 0:
        click.echo("\nNo value found.")
    else:
        click.echo(f"\n=== {total} total bets ({len(bets)} game-level, {len(prop_bets)} props) ===")


@cli.command()
def report():
    """Show P&L summary."""
    summary = get_summary()
    click.echo("\n=== P&L Report ===")
    click.echo(f"  Total bets: {summary['total_bets']}")
    click.echo(f"  Record: {summary['record']}")
    click.echo(f"  Profit (units): {summary.get('profit', 0)}")
    click.echo(f"  ROI: {summary.get('roi', 0)}%")
    click.echo()


@cli.command()
@click.option("--date", "game_date", default=None, help="Date to grade (YYYY-MM-DD), defaults to yesterday")
@click.option("--regrade", is_flag=True, help="Reset and re-grade all bets for the date")
def results(game_date, regrade):
    """Grade pending bets against final scores."""
    run_results_grader(game_date, regrade=regrade)


@cli.command()
@click.option("--date", "game_date", default=None, help="Date (YYYY-MM-DD)")
def card(game_date):
    """Display formatted bet card."""
    click.echo(format_bet_card(game_date))


@cli.command()
def health():
    """Run pre-game health check on all API connections."""
    run_health_check()


@cli.command()
@click.option("--min-bets", default=30, help="Minimum settled bets to analyze")
def optimize(min_bets):
    """Analyze performance and recommend threshold adjustments."""
    run_optimizer(min_bets)


if __name__ == "__main__":
    cli()
