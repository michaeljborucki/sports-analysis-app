"""CLI entrypoint for MiroFish T20 Cricket Prediction Pipeline."""
import logging
import time
import click
import signal
from datetime import date, datetime


from config import SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT

logger = logging.getLogger("mirofish")
from scrapers.schedule import get_upcoming_matches
from scrapers.team_stats import get_team_profile
from scrapers.players import get_key_players
from scrapers.venue import get_venue_conditions
from scrapers.toss import get_toss_analysis
from scrapers.odds import get_cricket_odds
from scrapers.scores import get_final_scores
from briefing import build_briefing
from simulate import run_plan_b, run_mirofish
from edge import analyze_all_edges
from tracker import log_bet, get_summary
from agents.results_grader import run_results_grader
from agents.bet_card import format_bet_card
from agents.health_check import run_health_check
from agents.self_optimizer import run_optimizer


class GameTimeout(Exception):
    """Raised when a single game exceeds its time budget."""
    pass


def _timeout_handler(signum, frame):
    raise GameTimeout("Game processing timed out")


@click.group()
def cli():
    """MiroFish T20 Cricket Prediction Pipeline"""
    pass


@cli.command()
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
@click.option("--league", default=None, help="League key (e.g. ipl, bbl). Default: all leagues.")
def daily(game_date, league):
    """Run full daily pipeline: scrape → screen → simulate → detect edges."""
    if game_date is None:
        game_date = date.today().isoformat()

    pipeline_start = time.time()
    click.echo(f"\n=== MiroFish T20 Cricket Pipeline — {game_date} ===\n")
    logger.info("Pipeline started for %s", game_date)

    # Step 1: Get upcoming matches
    click.echo("[1/5] Fetching upcoming matches...")
    t0 = time.time()
    matches = get_upcoming_matches(league)
    if not matches:
        click.echo("No matches found.")
        logger.warning("No matches found for league=%s — exiting", league)
        return
    click.echo(f"  Found {len(matches)} matches")
    logger.info("Step 1 complete: %d matches found (%.1fs)", len(matches), time.time() - t0)
    for m in matches:
        logger.debug("  %s vs %s — %s @ %s", m.team_a, m.team_b, m.league, m.venue)

    # Step 2: Get odds (per league)
    click.echo("[2/5] Fetching odds...")
    t0 = time.time()
    leagues_needed = {m.league for m in matches if m.league}
    odds_by_teams: dict[str, object] = {}
    for lg in leagues_needed:
        try:
            odds_list = get_cricket_odds(lg)
            for o in odds_list:
                key = f"{o.team_a}v{o.team_b}"
                odds_by_teams[key] = o
        except Exception as e:
            logger.warning("Odds fetch failed for league %s: %s", lg, e)
    logger.info("Step 2 complete: %d odds lines fetched (%.1fs)", len(odds_by_teams), time.time() - t0)

    # Step 3: Build briefings + screen
    click.echo("[3/5] Building briefings and running screen pass...")
    logger.info("Step 3: screening %d matches (timeout=%ds per match)", len(matches), GAME_TIMEOUT)
    screened_games = []

    for match_idx, match in enumerate(matches, 1):
        game_key = f"{match.team_a}v{match.team_b}"

        odds = odds_by_teams.get(game_key)
        if not odds:
            click.echo(f"  {game_key}: No odds found, skipping")
            logger.debug("  %s: no odds match found", game_key)
            continue

        try:
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(GAME_TIMEOUT)
            game_start = time.time()
            logger.info("  [%d/%d] Processing %s...", match_idx, len(matches), game_key)

            team_a_profile = get_team_profile(match.team_a, match.league or "")
            team_b_profile = get_team_profile(match.team_b, match.league or "")
            venue_conditions = get_venue_conditions(match.venue, match.league or "")
            toss = get_toss_analysis(match.venue)
            team_a_players = get_key_players(match.team_a, match.league or "")
            team_b_players = get_key_players(match.team_b, match.league or "")
            logger.debug("    Profiles and venue loaded")

            game_data = {
                "team_a": match.team_a,
                "team_b": match.team_b,
                "team_a_full": match.team_a_full,
                "team_b_full": match.team_b_full,
                "league": match.league,
                "venue": match.venue,
                "day_night": getattr(match, "day_night", "N"),
                "date": match.date,
                "odds": {
                    "moneyline": odds.moneyline,
                    "total_runs": odds.total_runs,
                    "implied_probs": odds.implied_probs,
                },
                "venue_conditions": venue_conditions,
                "toss": toss,
                "team_a_profile": team_a_profile,
                "team_b_profile": team_b_profile,
                "team_a_players": team_a_players,
                "team_b_players": team_b_players,
            }

            brief = build_briefing(game_data)
            logger.debug("    Briefing built (%d chars)", len(brief))

            click.echo(f"  Screening {game_key}...")
            screen_start = time.time()
            screen = run_plan_b(brief)
            logger.debug("    Screen pass completed in %.1fs", time.time() - screen_start)
            if not screen:
                click.echo(f"    Screen failed, skipping")
                logger.warning("    %s: screen pass returned None", game_key)
                continue

            edges = analyze_all_edges(screen, game_data["odds"])
            max_edge = max((e["edge"] for e in edges), default=0)
            logger.debug("    Edge analysis: %d edges found, max=%.3f (threshold=%.3f)",
                         len(edges), max_edge, SCREEN_EDGE_THRESHOLD)

            if max_edge >= SCREEN_EDGE_THRESHOLD:
                click.echo(f"    FLAGGED — max edge {max_edge:.1%}, queuing for full sim")
                logger.info("    %s FLAGGED (max edge %.1f%%) — queued for full sim in %.1fs",
                            game_key, max_edge * 100, time.time() - game_start)
                screened_games.append((game_key, brief, game_data))
            else:
                click.echo(f"    No edge found (max {max_edge:.1%})")
                logger.info("    %s passed — no edge (max %.1f%%) in %.1fs",
                            game_key, max_edge * 100, time.time() - game_start)

        except GameTimeout:
            click.echo(f"  {game_key}: TIMEOUT — exceeded {GAME_TIMEOUT}s, skipping")
            logger.error("  %s: TIMEOUT after %ds", game_key, GAME_TIMEOUT)
            continue
        except Exception as e:
            click.echo(f"  {game_key}: ERROR — {e}, skipping")
            logger.exception("  %s: unexpected error", game_key)
            continue
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    logger.info("Step 3 complete: %d/%d matches flagged for full simulation",
                len(screened_games), len(matches))

    # Step 4: Full MiroFish simulation on flagged games
    click.echo(f"\n[4/5] Running full simulation on {len(screened_games)} flagged matches...")
    logger.info("Step 4: running full ensemble on %d flagged matches", len(screened_games))
    total_bets = 0
    total_sim_cost = 0.0

    for sim_idx, (game_key, brief, game_data) in enumerate(screened_games, 1):
        click.echo(f"\n  === {game_key} ===")
        try:
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(GAME_TIMEOUT)
            sim_start = time.time()
            logger.info("  [%d/%d] Full simulation: %s", sim_idx, len(screened_games), game_key)

            result = run_mirofish(brief, runs=3, odds=game_data["odds"])
            sim_elapsed = time.time() - sim_start
            if not result:
                click.echo("    Simulation failed")
                logger.warning("  %s: simulation returned None after %.1fs", game_key, sim_elapsed)
                continue

            meta = result.get("ensemble_meta", {})
            logger.info("  %s: simulation complete in %.1fs — phase=%d, calls=%d, cost=$%.4f",
                        game_key, sim_elapsed, meta.get("phase_reached", 0),
                        meta.get("total_calls", 0), meta.get("cost_usd", 0))
            total_sim_cost += meta.get("cost_usd", 0)

            bets = analyze_all_edges(result, game_data["odds"])
            if not bets:
                click.echo("    No bets after full sim")
                logger.info("  %s: no edges survived full simulation", game_key)
                continue

            logger.info("  %s: %d bet(s) found", game_key, len(bets))
            for bet in bets:
                bet["date"] = game_date
                bet["game"] = game_key
                click.echo(
                    f"    BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                    f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
                )
                logger.info("    BET: %s %s @ %s | edge=%.3f sim=%.3f mkt=%.3f kelly=%.4f",
                            bet["bet_type"], bet["side"], bet["odds"],
                            bet["edge"], bet.get("sim_prob", 0),
                            bet.get("market_prob", 0), bet["kelly_pct"])
                log_bet(bet)
                total_bets += 1

        except GameTimeout:
            click.echo(f"    TIMEOUT — exceeded {GAME_TIMEOUT}s, skipping")
            logger.error("  %s: TIMEOUT after %ds", game_key, GAME_TIMEOUT)
            continue
        except Exception as e:
            click.echo(f"    ERROR — {e}, skipping")
            logger.exception("  %s: unexpected error during simulation", game_key)
            continue
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    # Step 5: Done
    pipeline_elapsed = time.time() - pipeline_start
    click.echo(f"\n[5/5] Done.")
    click.echo(f"\n=== Done. {total_bets} bets logged. ===")
    logger.info("Pipeline complete: %d bets logged, total sim cost=$%.4f, elapsed=%.0fs",
                total_bets, total_sim_cost, pipeline_elapsed)


@cli.command()
@click.argument("team_a")
@click.argument("team_b")
@click.option("--league", default=None, help="League key (e.g. ipl, bbl)")
@click.option("--date", "game_date", default=None)
def game(team_a, team_b, league, game_date):
    """Analyze a single T20 match. Example: python main.py game CSK MI --league ipl"""
    if game_date is None:
        game_date = date.today().isoformat()

    click.echo(f"\nAnalyzing {team_a} vs {team_b} on {game_date}...")

    # Find match info from schedule
    matches = get_upcoming_matches(league)
    match = None
    for m in matches:
        if m.team_a == team_a and m.team_b == team_b:
            match = m
            break
        if m.team_b == team_a and m.team_a == team_b:
            match = m
            break

    # Determine venue and league from match or defaults
    venue = match.venue if match else "Unknown Venue"
    match_league = (match.league if match else league) or ""
    team_a_full = match.team_a_full if match else team_a
    team_b_full = match.team_b_full if match else team_b

    # Get odds
    odds_list = []
    if match_league:
        try:
            odds_list = get_cricket_odds(match_league)
        except Exception as e:
            logger.warning("Could not fetch odds for league %s: %s", match_league, e)

    game_odds = None
    for o in odds_list:
        if (o.team_a == team_a and o.team_b == team_b) or \
           (o.team_a == team_b and o.team_b == team_a):
            game_odds = o
            break

    if not game_odds:
        click.echo("Could not find odds for this match.")
        return

    team_a_profile = get_team_profile(team_a, match_league)
    team_b_profile = get_team_profile(team_b, match_league)
    venue_conditions = get_venue_conditions(venue, match_league)
    toss = get_toss_analysis(venue)
    team_a_players = get_key_players(team_a, match_league)
    team_b_players = get_key_players(team_b, match_league)

    game_data = {
        "team_a": team_a,
        "team_b": team_b,
        "team_a_full": team_a_full,
        "team_b_full": team_b_full,
        "league": match_league,
        "venue": venue,
        "day_night": "N",
        "date": game_date,
        "odds": {
            "moneyline": game_odds.moneyline,
            "total_runs": game_odds.total_runs,
            "implied_probs": game_odds.implied_probs,
        },
        "venue_conditions": venue_conditions,
        "toss": toss,
        "team_a_profile": team_a_profile,
        "team_b_profile": team_b_profile,
        "team_a_players": team_a_players,
        "team_b_players": team_b_players,
    }

    brief = build_briefing(game_data)
    click.echo("\n--- Briefing ---")
    click.echo(brief[:500] + "...\n")

    click.echo("Running simulation...")
    result = run_mirofish(brief, runs=3, odds=game_data["odds"])
    if not result:
        click.echo("Simulation failed.")
        return

    bets = analyze_all_edges(result, game_data["odds"])
    if not bets:
        click.echo("No value found.")
        return

    for bet in bets:
        bet["date"] = game_date
        bet["game"] = f"{team_a}v{team_b}"
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
