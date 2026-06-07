"""CLI entrypoint for MiroFish Esports Prediction Pipeline."""
import logging
import time
import click
import signal
from datetime import date, datetime

from config import SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT, SUPPORTED_GAMES
from games import get_game
from scrapers.odds import get_esports_odds
from scrapers.meta import fetch_patch_context
from scrapers.news import fetch_match_context
from simulate import run_plan_b, run_mirofish
from edge import analyze_all_edges
from tracker import log_bet, get_summary
from agents.results_grader import run_results_grader
from agents.bet_card import format_bet_card
from agents.health_check import run_health_check
from agents.self_optimizer import run_optimizer

logger = logging.getLogger("mirofish")


class GameTimeout(Exception):
    """Raised when a single game exceeds its time budget."""
    pass


def _timeout_handler(signum, frame):
    raise GameTimeout("Game processing timed out")


def _parse_game_keys(game_option: str) -> list[str]:
    """Parse --game option into a list of game keys."""
    if game_option is None or game_option == "all":
        return SUPPORTED_GAMES
    keys = [k.strip() for k in game_option.split(",")]
    for k in keys:
        if k not in SUPPORTED_GAMES:
            raise click.BadParameter(f"Unknown game '{k}'. Supported: {', '.join(SUPPORTED_GAMES)}")
    return keys


@click.group()
def cli():
    """MiroFish Esports Prediction Pipeline"""
    pass


@cli.command()
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
@click.option("--game", "game_option", default="all",
              help=f"Game to process: {', '.join(SUPPORTED_GAMES)}, or 'all' (default: all)")
def daily(game_date, game_option):
    """Run full daily pipeline: scrape -> screen -> simulate -> detect edges."""
    if game_date is None:
        game_date = date.today().isoformat()

    game_keys = _parse_game_keys(game_option)

    pipeline_start = time.time()
    click.echo(f"\n=== MiroFish Esports Pipeline — {game_date} ===")
    click.echo(f"    Games: {', '.join(game_keys)}\n")
    logger.info("Pipeline started for %s, games=%s", game_date, game_keys)

    total_bets = 0
    total_sim_cost = 0.0

    for game_key in game_keys:
        game = get_game(game_key)
        click.echo(f"\n--- [{game_key.upper()}] ---")

        # Step 1: Fetch schedule
        click.echo(f"  [1] Fetching {game_key} schedule...")
        t0 = time.time()
        matches = game.scrapers.fetch_upcoming_matches()
        from config import MAX_TIER
        matches = [m for m in matches if m.get("tier", 3) <= MAX_TIER]
        if not matches:
            click.echo(f"  No tier 1-{MAX_TIER} matches for {game_key}")
            continue
        click.echo(f"  Found {len(matches)} matches ({time.time()-t0:.1f}s)")

        # Step 2: Fetch odds
        click.echo(f"  [2] Fetching odds...")
        t0 = time.time()
        odds_list = get_esports_odds(game_key)
        if not odds_list:
            click.echo(f"  No odds available for {game_key}, skipping")
            continue
        click.echo(f"  {len(odds_list)} odds lines ({time.time()-t0:.1f}s)")

        # Step 3: Fetch patch context (once per game)
        click.echo(f"  [3] Fetching patch/meta context...")
        patch_ctx = fetch_patch_context(game_key)

        # Step 4: Screen and simulate each match
        click.echo(f"  [4] Processing {len(matches)} matches...")
        for match_idx, match in enumerate(matches, 1):
            team_a = match.get("team_a", "")
            team_b = match.get("team_b", "")
            match_label = f"{team_a} vs {team_b}"

            # Find odds
            odds = None
            for o in odds_list:
                if (team_a.lower() in o.team_a.lower() or team_a.lower() in o.team_b.lower()) and \
                   (team_b.lower() in o.team_a.lower() or team_b.lower() in o.team_b.lower()):
                    odds = o
                    break
            if not odds:
                click.echo(f"    {match_label}: no odds, skipping")
                continue

            try:
                old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(GAME_TIMEOUT)
                match_start = time.time()

                # Assemble match data
                match_data = {
                    "tournament": match.get("tournament", ""),
                    "date": game_date,
                    "format": match.get("format", "bo3"),
                    "bo_count": int(match.get("format", "bo3").replace("bo", "")),
                    "tier": match.get("tier", 2),
                    "team_a": game.scrapers.fetch_team_profile(team_a),
                    "team_b": game.scrapers.fetch_team_profile(team_b),
                    "odds": odds.to_dict(),
                    "head_to_head": game.scrapers.fetch_head_to_head(team_a, team_b),
                    "patch": patch_ctx,
                    "context": fetch_match_context(game_key, team_a, team_b),
                }

                # Build briefing
                briefing = game.briefing.build_briefing(match_data)

                # Screen pass
                click.echo(f"    [{match_idx}/{len(matches)}] Screening {match_label}...")
                screen = run_plan_b(briefing, game_config=game)
                if screen is None:
                    click.echo(f"      Screen pass failed, skipping")
                    continue

                # Check for edge in screen
                fmt = match.get("format", "bo3")
                screen_edges = analyze_all_edges(screen, odds, format=fmt, game_config=game.config)
                max_edge = max((e["edge"] for e in screen_edges), default=0)

                if max_edge < SCREEN_EDGE_THRESHOLD:
                    click.echo(f"      No edge (max {max_edge:.1%})")
                    continue

                click.echo(f"      FLAGGED — max edge {max_edge:.1%}, running full sim...")

                # Full ensemble
                result = run_mirofish(briefing, odds=odds.to_dict(), game_config=game)
                sim_elapsed = time.time() - match_start
                if not result:
                    click.echo(f"      Simulation failed")
                    continue

                meta = result.get("ensemble_meta", {})
                total_sim_cost += meta.get("cost_usd", 0)

                # Edge detection on full sim
                bets = analyze_all_edges(result.get("predictions", {}), odds, format=fmt, game_config=game.config)
                if not bets:
                    click.echo(f"      No bets after full sim")
                    continue

                for bet in bets:
                    bet["date"] = game_date
                    bet["game"] = match_label
                    bet["game_title"] = game_key
                    bet["tournament"] = match.get("tournament", "")
                    click.echo(
                        f"      BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                        f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
                    )
                    log_bet(bet)
                    total_bets += 1

            except GameTimeout:
                click.echo(f"    {match_label}: TIMEOUT ({GAME_TIMEOUT}s), skipping")
                logger.error("%s: TIMEOUT after %ds", match_label, GAME_TIMEOUT)
            except Exception as e:
                click.echo(f"    {match_label}: ERROR — {e}")
                logger.exception("%s: error", match_label)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

    pipeline_elapsed = time.time() - pipeline_start
    click.echo(f"\n=== Done. {total_bets} bets logged across {len(game_keys)} games. ===")
    logger.info("Pipeline complete: %d bets, cost=$%.4f, elapsed=%.0fs",
                total_bets, total_sim_cost, pipeline_elapsed)


@cli.command()
@click.argument("team_a")
@click.argument("team_b")
@click.option("--game", "game_key", required=True,
              help=f"Game key: {', '.join(SUPPORTED_GAMES)}")
@click.option("--date", "game_date", default=None)
@click.option("--format", "match_format", default="bo3", help="Match format (bo1, bo3, bo5)")
def match(team_a, team_b, game_key, game_date, match_format):
    """Analyze a single esports match."""
    if game_date is None:
        game_date = date.today().isoformat()

    if game_key not in SUPPORTED_GAMES:
        click.echo(f"Unknown game '{game_key}'. Supported: {', '.join(SUPPORTED_GAMES)}")
        return

    game = get_game(game_key)
    click.echo(f"\nAnalyzing [{game_key.upper()}] {team_a} vs {team_b} on {game_date}...")

    # Get odds
    odds_list = get_esports_odds(game_key)
    game_odds = None
    for o in odds_list:
        if (team_a.lower() in o.team_a.lower() or team_a.lower() in o.team_b.lower()) and \
           (team_b.lower() in o.team_a.lower() or team_b.lower() in o.team_b.lower()):
            game_odds = o
            break

    if not game_odds:
        click.echo("Could not find odds for this match.")
        return

    # Build match data
    patch_ctx = fetch_patch_context(game_key)
    match_data = {
        "tournament": "",
        "date": game_date,
        "format": match_format,
        "bo_count": int(match_format.replace("bo", "")),
        "tier": 1,
        "team_a": game.scrapers.fetch_team_profile(team_a),
        "team_b": game.scrapers.fetch_team_profile(team_b),
        "odds": game_odds.to_dict(),
        "head_to_head": game.scrapers.fetch_head_to_head(team_a, team_b),
        "patch": patch_ctx,
        "context": fetch_match_context(game_key, team_a, team_b),
    }

    briefing = game.briefing.build_briefing(match_data)
    click.echo("\n--- Briefing ---")
    click.echo(briefing[:500] + "...\n")

    click.echo("Running simulation...")
    result = run_mirofish(briefing, odds=game_odds.to_dict(), game_config=game)
    if not result:
        click.echo("Simulation failed.")
        return

    bets = analyze_all_edges(
        result.get("predictions", {}), game_odds,
        format=match_format, game_config=game.config,
    )
    if not bets:
        click.echo("No value found.")
        return

    for bet in bets:
        bet["date"] = game_date
        bet["game"] = f"{team_a} vs {team_b}"
        bet["game_title"] = game_key
        click.echo(
            f"  BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
            f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
        )
        log_bet(bet)


@cli.command()
def report():
    """Show P&L summary."""
    summary = get_summary()
    click.echo("\n=== MiroFish P&L Report ===")
    click.echo(f"  Total bets: {summary['total_bets']}")
    click.echo(f"  Record: {summary['record']}")
    click.echo(f"  Profit (units): {summary.get('profit', 0)}")
    click.echo(f"  ROI: {summary.get('roi', 0)}%")
    click.echo()


@cli.command()
@click.option("--date", "game_date", default=None, help="Date to grade (YYYY-MM-DD), defaults to yesterday")
def results(game_date):
    """Grade pending bets against final scores."""
    run_results_grader(game_date)


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
