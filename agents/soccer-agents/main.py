"""CLI entrypoint for MiroFish Soccer Prediction Pipeline."""
import logging
import time
import click
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from config import SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT, ACTIVE_LEAGUES, PARALLEL_GAMES

logger = logging.getLogger("mirofish")
from scrapers.schedule import get_fixtures
from scrapers.team_stats import get_team_profile, get_recent_form
from scrapers.xg import get_xg_profile
from scrapers.injuries import get_squad_injuries
from scrapers.context import get_match_context
from scrapers.odds import get_soccer_odds
from scrapers.name_map import normalize_team_name
from scrapers.club_elo import get_match_elo
from briefing import build_briefing
from simulate import run_plan_b, run_mirofish
from edge import analyze_all_edges
from tracker import log_bet, get_summary
from agents.results_grader import run_results_grader
from agents.bet_card import format_bet_card
from agents.health_check import run_health_check
from agents.self_optimizer import run_optimizer
from agents.clv_snapshotter import snap_close_for_date
from agents.bankroll_guardian import gate_bets, compute_bankroll_state
from agents.integrity import audit_orphans, audit_name_mappings


_NO_ODDS = "NO_ODDS"
_SCREEN_FAILED = "SCREEN_FAILED"


def _screen_match(odds, lg, game_date):
    """Thread-safe screen of one match. Returns tuple or sentinel string."""
    home = odds.home
    away = odds.away
    match_key = f"{away}@{home}"
    try:
        home_norm = normalize_team_name(home, lg)
        away_norm = normalize_team_name(away, lg)

        home_stats = get_team_profile(home_norm, league=lg)
        away_stats = get_team_profile(away_norm, league=lg)
        home_xg = get_xg_profile(home_norm, league=lg)
        away_xg = get_xg_profile(away_norm, league=lg)
        home_injuries = get_squad_injuries(home_norm, league=lg)
        away_injuries = get_squad_injuries(away_norm, league=lg)
        context = get_match_context(home_norm, away_norm, league=lg)
        home_form = get_recent_form(home_norm, league=lg)
        away_form = get_recent_form(away_norm, league=lg)
        elo = get_match_elo(home_norm, away_norm, league=lg, game_date=game_date)

        match_data = {
            "home_team": home,
            "away_team": away,
            "league": lg,
            "elo": elo,
            "matchday": "",
            "venue": "",
            "kickoff_time": odds.commence_time,
            "odds": {
                "asian_handicap": odds.asian_handicap,
                "total": odds.total,
                "btts": odds.btts,
                "moneyline_1x2": odds.moneyline_1x2,
                "implied_probs": odds.implied_probs,
            },
            "home_stats": home_stats,
            "away_stats": away_stats,
            "home_xg": home_xg,
            "away_xg": away_xg,
            "home_injuries": home_injuries,
            "away_injuries": away_injuries,
            "context": context,
            "home_form": home_form,
            "away_form": away_form,
        }
        brief = build_briefing(match_data)
        screen = run_plan_b(brief)
        if not screen:
            return _SCREEN_FAILED

        edges = analyze_all_edges(screen, match_data["odds"])
        max_edge = max((e["edge"] for e in edges), default=0)
        return (match_key, brief, match_data, max_edge)
    except Exception as e:
        logger.exception("  %s: screen error", match_key)
        return _SCREEN_FAILED


def _simulate_match(match_key, brief, match_data, game_date, lg):
    """Thread-safe full-sim + log. Returns (match_key, bets_logged, cost)."""
    logged = 0
    cost = 0.0
    try:
        result = run_mirofish(brief, runs=3, odds=match_data["odds"], match_data=match_data)
        if not result:
            return (match_key, 0, 0.0)
        cost = result.get("ensemble_meta", {}).get("cost_usd", 0)

        bets = analyze_all_edges(result, match_data["odds"])
        if not bets:
            return (match_key, 0, cost)

        bets = gate_bets(bets)
        if not bets:
            logger.warning("  %s: bankroll guardian blocked slate", match_key)
            return (match_key, 0, cost)

        for bet in bets:
            bet["date"] = game_date
            bet["game"] = match_key
            bet["league"] = lg
            if log_bet(bet):
                logged += 1
                click.echo(
                    f"    BET {match_key}: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                    f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
                )
    except Exception as e:
        logger.exception("  %s: simulation error", match_key)
    return (match_key, logged, cost)


@click.group()
def cli():
    """MiroFish Soccer Prediction Pipeline"""
    pass


@cli.command()
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
@click.option("--league", default=None, help="Single league to run (default: all active)")
@click.option("--no-notify", is_flag=True, help="Skip Discord notifications after pipeline")
def daily(game_date, league, no_notify):
    """Run full daily pipeline: scrape -> screen -> simulate -> detect edges."""
    if game_date is None:
        game_date = date.today().isoformat()

    leagues = [league] if league else ACTIVE_LEAGUES
    pipeline_start = time.time()
    click.echo(f"\n=== MiroFish Soccer Pipeline - {game_date} ===\n")

    total_bets = 0
    total_sim_cost = 0.0

    for lg in leagues:
        click.echo(f"\n--- {lg} ---\n")

        click.echo(f"[1/3] Fetching {lg} odds & fixtures...")
        odds_list = get_soccer_odds(league=lg)
        if not odds_list:
            click.echo(f"  No odds/fixtures found for {lg}")
            continue
        click.echo(f"  Found {len(odds_list)} matches with odds")

        click.echo(f"[2/3] Screening {len(odds_list)} matches ({PARALLEL_GAMES} parallel)...")
        screened = []
        screen_errors = 0
        with ThreadPoolExecutor(max_workers=PARALLEL_GAMES) as pool:
            futures = {
                pool.submit(_screen_match, odds, lg, game_date): odds
                for odds in odds_list
            }
            for future in as_completed(futures):
                odds = futures[future]
                match_key = f"{odds.away}@{odds.home}"
                try:
                    result = future.result(timeout=GAME_TIMEOUT)
                except TimeoutError:
                    click.echo(f"  {match_key}: TIMEOUT ({GAME_TIMEOUT}s)")
                    screen_errors += 1
                    continue
                except Exception as e:
                    click.echo(f"  {match_key}: ERROR - {e}")
                    screen_errors += 1
                    continue

                if result == _SCREEN_FAILED:
                    click.echo(f"  {match_key}: screen failed")
                    screen_errors += 1
                elif result[3] >= SCREEN_EDGE_THRESHOLD:
                    click.echo(f"  {match_key}: FLAGGED (max edge {result[3]:.1%})")
                    screened.append(result)
                else:
                    click.echo(f"  {match_key}: no edge ({result[3]:.1%})")

        click.echo(f"\n[3/3] Full simulation on {len(screened)} flagged matches "
                   f"({PARALLEL_GAMES} parallel)...")
        with ThreadPoolExecutor(max_workers=PARALLEL_GAMES) as pool:
            futures = {
                pool.submit(_simulate_match, mk, br, md, game_date, lg): mk
                for mk, br, md, _ in screened
            }
            for future in as_completed(futures):
                mk = futures[future]
                try:
                    _, logged, cost = future.result(timeout=GAME_TIMEOUT)
                except TimeoutError:
                    click.echo(f"  {mk}: TIMEOUT ({GAME_TIMEOUT}s)")
                    continue
                except Exception as e:
                    click.echo(f"  {mk}: sim ERROR - {e}")
                    continue
                total_bets += logged
                total_sim_cost += cost

    elapsed = time.time() - pipeline_start
    click.echo(f"\n=== Done. {total_bets} bets logged. Cost: ${total_sim_cost:.4f}. Time: {elapsed:.0f}s ===")

    if not no_notify and total_bets > 0:
        try:
            from notify import send_notifications
            summary = send_notifications(game_date=game_date)
            if summary["bets_new"]:
                click.echo(f"  Notifications: {summary['bets_new']} new → "
                           f"{'sent ' + str(summary['sent']) if summary['discord_enabled'] else 'Discord off'}")
        except Exception as e:
            logger.error("Notification dispatch failed: %s", e)


@cli.command()
@click.argument("away_team")
@click.argument("home_team")
@click.option("--date", "game_date", default=None)
@click.option("--league", default="MLS", help="League name")
def match(away_team, home_team, game_date, league):
    """Analyze a single match."""
    if game_date is None:
        game_date = date.today().isoformat()

    click.echo(f"\nAnalyzing {away_team}@{home_team} ({league}) on {game_date}...")

    odds_list = get_soccer_odds(league=league)
    game_odds = None
    for o in odds_list:
        if o.away == away_team and o.home == home_team:
            game_odds = o
            break

    if not game_odds:
        click.echo("Could not find odds for this match.")
        return

    home_stats = get_team_profile(home_team, league=league)
    away_stats = get_team_profile(away_team, league=league)
    home_xg = get_xg_profile(home_team, league=league)
    away_xg = get_xg_profile(away_team, league=league)
    context = get_match_context(home_team, away_team, league=league)
    home_form = get_recent_form(home_team, league=league)
    away_form = get_recent_form(away_team, league=league)
    elo = get_match_elo(home_team, away_team, league=league, game_date=game_date)

    match_data = {
        "home_team": home_team,
        "away_team": away_team,
        "league": league,
        "elo": elo,
        "odds": {
            "asian_handicap": game_odds.asian_handicap,
            "total": game_odds.total,
            "btts": game_odds.btts,
            "moneyline_1x2": game_odds.moneyline_1x2,
            "implied_probs": game_odds.implied_probs,
        },
        "home_stats": home_stats,
        "away_stats": away_stats,
        "home_xg": home_xg,
        "away_xg": away_xg,
        "home_injuries": get_squad_injuries(home_team, league=league),
        "away_injuries": get_squad_injuries(away_team, league=league),
        "context": context,
        "home_form": home_form,
        "away_form": away_form,
    }

    brief = build_briefing(match_data)
    click.echo("\n--- Briefing ---")
    click.echo(brief[:500] + "...\n")

    click.echo("Running simulation...")
    result = run_mirofish(brief, runs=3, odds=match_data["odds"], match_data=match_data)
    if not result:
        click.echo("Simulation failed.")
        return

    bets = analyze_all_edges(result, match_data["odds"])
    if not bets:
        click.echo("No value found.")
        return

    bets = gate_bets(bets)
    if not bets:
        click.echo("Bankroll guardian blocked this slate.")
        return

    for bet in bets:
        bet["date"] = game_date
        bet["game"] = f"{away_team}@{home_team}"
        bet["league"] = league
        click.echo(
            f"  BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
            f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
        )
        log_bet(bet)


@cli.command()
def bankroll():
    """Show current bankroll guardian state."""
    state = compute_bankroll_state()
    click.echo("\n=== Bankroll Guardian ===")
    click.echo(f"  Status: {state['status']}")
    click.echo(f"  Trailing 7d P&L: {state['trailing_profit_u']:+.2f} units")
    click.echo(f"  Kelly multiplier: {state['kelly_multiplier']:.2f}x")
    click.echo(f"  Today exposure: {state['today_exposure_pct']:.2%} "
               f"of {state['daily_cap_pct']:.0%} cap")


@cli.command()
def report():
    """Show P&L summary."""
    summary = get_summary()
    click.echo("\n=== MiroFish P&L Report ===")
    click.echo(f"  Total bets: {summary['total_bets']}")
    click.echo(f"  Record: {summary['record']}")
    click.echo(f"  Profit (units): {summary.get('profit', 0)}")
    click.echo(f"  ROI: {summary.get('roi', 0)}%")
    if summary.get("clv_samples"):
        click.echo(
            f"  CLV: avg {summary['avg_clv']:+.4f} | beat close "
            f"{summary['beat_close_pct']:.0%} ({summary['clv_samples']} samples)"
        )


@cli.command("snap-close")
@click.option("--date", "game_date", default=None, help="Date (YYYY-MM-DD), default today")
def snap_close(game_date):
    """Legacy: back-fills close_market_prob for pending bets. Prefer close-capture."""
    result = snap_close_for_date(game_date)
    click.echo(
        f"CLV snapshot: {result['updated']} updated, {result['skipped']} skipped "
        f"(of {result['pending_total']} pending)"
    )


@cli.command("close-capture")
@click.option("--date", "game_date", default=None, help="Date (YYYY-MM-DD), default today")
@click.option("--force", is_flag=True, help="Skip the T-15..T-5 window and capture all upcoming games")
def close_capture_cmd(game_date, force):
    """Capture consensus closing odds for in-window matches (CLV, no LLM calls).

    Designed to run on a tight cron ~every 5m. Silently no-ops when no matches
    are in the T-15..T-5 kickoff window. Rows are written to data/closing_lines.csv
    with dedup on (date, game, bet_type, side, line).

    Bets get CLV auto-filled when they are graded (results_grader looks up this
    CSV). To capture now regardless of timing, use --force.
    """
    from scrapers.closing_lines import capture_closing_lines
    summary = capture_closing_lines(game_date=game_date, force=force)
    click.echo(
        f"CLV capture: {summary['captured_games']} game(s), "
        f"{summary['captured_rows']} new rows "
        f"(skipped {summary['skipped_games']} out-of-window)"
    )


@cli.command()
@click.option("--date", "game_date", default=None)
def results(game_date):
    """Grade pending bets against final scores."""
    run_results_grader(game_date)


@cli.command()
@click.option("--date", "game_date", default=None)
@click.option("--upcoming", is_flag=True, help="Only show bets whose kickoff is in the future.")
def card(game_date, upcoming):
    """Display formatted bet card."""
    click.echo(format_bet_card(game_date, upcoming_only=upcoming))


@cli.command()
def health():
    """Run pre-game health check."""
    run_health_check()


@cli.command()
@click.option("--min-bets", default=30)
def optimize(min_bets):
    """Analyze performance and recommend adjustments."""
    run_optimizer(min_bets)


@cli.command("audit-orphans")
@click.option("--stale-days", default=2)
@click.option("--no-regrade", is_flag=True)
def audit_orphans_cmd(stale_days, no_regrade):
    """Find stale/ungraded bets and attempt re-grade."""
    result = audit_orphans(stale_days=stale_days, attempt_regrade=not no_regrade)
    click.echo(
        f"Orphan audit: {result['orphans']} initial, "
        f"{result['regrade_dates']} dates regraded, "
        f"{result['remaining']} still orphaned"
    )


@cli.command("audit-names")
def audit_names_cmd():
    """Flag teams whose Odds API name doesn't resolve to ESPN standings."""
    result = audit_name_mappings()
    total_missed = sum(len(v) for v in result.values())
    click.echo(f"Name mapping audit: {total_missed} unmapped across {len(result)} leagues")
    for lg, items in result.items():
        click.echo(f"  {lg}: {'OK' if not items else f'{len(items)} unmapped'}")
        for item in items:
            click.echo(f"    - {item}")


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


if __name__ == "__main__":
    cli()
