"""CLI entrypoint for MiroFish UFC/MMA Prediction Pipeline."""
import logging
import time
import click
import signal
from datetime import date, datetime

from config import SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT

logger = logging.getLogger("mirofish")
from scrapers.schedule import get_upcoming_events, get_fight_card
from scrapers.fighters import get_fighter_profile
from scrapers.odds import get_ufc_odds
from scrapers.news import build_fight_context
from scrapers.rankings import get_rankings
from briefing import build_briefing
from simulate import run_plan_b, run_mirofish
from edge import analyze_all_edges
from tracker import log_bet, get_summary
from agents.results_grader import run_results_grader
from agents.bet_card import format_bet_card
from agents.health_check import run_health_check
from agents.self_optimizer import run_optimizer


class FightTimeout(Exception):
    """Raised when a single fight exceeds its time budget."""
    pass


def _timeout_handler(signum, frame):
    raise FightTimeout("Fight processing timed out")


@click.group()
def cli():
    """MiroFish UFC/MMA Prediction Pipeline"""
    pass


@cli.command()
@click.option("--date", "fight_date", default=None, help="Event date (YYYY-MM-DD)")
def daily(fight_date):
    """Run full daily pipeline: scrape -> screen -> simulate -> detect edges."""
    if fight_date is None:
        fight_date = date.today().isoformat()

    pipeline_start = time.time()
    click.echo(f"\n=== MiroFish UFC Pipeline — {fight_date} ===\n")
    logger.info("Pipeline started for %s", fight_date)

    # Step 1: Get upcoming events and fight card
    click.echo("[1/6] Fetching UFC events and fight cards...")
    t0 = time.time()
    events = get_upcoming_events()
    if not events:
        click.echo("No upcoming events found.")
        logger.warning("No events found — exiting")
        return

    # Find event closest to the target date
    fights = []
    event_name = events[0].get("event_name", "UFC Event")
    for event in events:
        detail_url = event.get("detail_url", "")
        if detail_url:
            card = get_fight_card(detail_url)
            if card:
                event_name = event.get("event_name", "UFC Event")
                fights = card
                break

    if not fights:
        click.echo("No fights found on the card.")
        logger.warning("No fights found — exiting")
        return

    click.echo(f"  Found {len(fights)} fights on {event_name}")
    logger.info("Step 1 complete: %d fights found (%.1fs)", len(fights), time.time() - t0)

    # Step 2: Get odds
    click.echo("[2/6] Fetching UFC odds...")
    t0 = time.time()
    odds_list = get_ufc_odds()
    odds_by_fighters = {}
    for o in odds_list:
        key = f"{o.fighter_a} vs {o.fighter_b}"
        odds_by_fighters[key] = o
        # Also index by reverse order
        rev_key = f"{o.fighter_b} vs {o.fighter_a}"
        odds_by_fighters[rev_key] = o
    logger.info("Step 2 complete: %d odds lines fetched (%.1fs)", len(odds_list), time.time() - t0)

    # Step 3: Get rankings
    click.echo("[3/6] Fetching UFC rankings...")
    t0 = time.time()
    rankings = get_rankings()
    logger.info("Step 3 complete: rankings fetched for %d divisions (%.1fs)",
                len(rankings), time.time() - t0)

    # Step 4: Placeholder — reserved for future data enrichment
    click.echo("[4/6] Fetching fight context...")
    t0 = time.time()
    logger.info("Step 4 complete: fight context fetched (%.1fs)", time.time() - t0)

    # Step 5: Build briefings + screen
    click.echo("[5/6] Building briefings and running screen pass...")
    logger.info("Step 5: screening %d fights (timeout=%ds per fight)", len(fights), GAME_TIMEOUT)
    screened_fights = []

    for fight_idx, fight in enumerate(fights, 1):
        fight_key = f"{fight.fighter_a} vs {fight.fighter_b}"

        # Get odds for this fight
        odds = odds_by_fighters.get(fight_key)
        if not odds:
            click.echo(f"  {fight_key}: No odds found, skipping")
            logger.debug("  %s: no odds match found", fight_key)
            continue

        try:
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(GAME_TIMEOUT)
            fight_start = time.time()
            logger.info("  [%d/%d] Processing %s...", fight_idx, len(fights), fight_key)

            # Build fighter profiles in parallel
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
            profile_a = None
            profile_b = None
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    future_a = pool.submit(get_fighter_profile, fight.fighter_a)
                    future_b = pool.submit(get_fighter_profile, fight.fighter_b)
                    try:
                        profile_a = future_a.result(timeout=20)
                    except Exception as e:
                        logger.warning("    Fighter A profile failed for %s: %s", fight.fighter_a, e)
                    try:
                        profile_b = future_b.result(timeout=20)
                    except Exception as e:
                        logger.warning("    Fighter B profile failed for %s: %s", fight.fighter_b, e)
            except Exception as e:
                logger.error("    Parallel profile fetch failed: %s", e)

            # Build fight context
            context_a = build_fight_context(fight.fighter_a)
            context_b = build_fight_context(fight.fighter_b)

            def _profile_to_dict(p):
                if p is None:
                    return {"name": "Unknown"}
                return {
                    "name": p.name, "record": p.record,
                    "wins_ko": p.wins_ko, "wins_sub": p.wins_sub, "wins_dec": p.wins_dec,
                    "stance": p.stance, "height": p.height, "reach": p.reach,
                    "slpm": p.slpm, "str_acc": p.str_acc, "str_def": p.str_def,
                    "td_avg": p.td_avg, "td_def": p.td_def, "sub_avg": p.sub_avg,
                    "avg_fight_time": p.avg_fight_time, "age": p.age,
                    "win_streak": p.win_streak, "last_5_fights": p.last_5_fights,
                }

            def _context_to_dict(ctx):
                return {
                    "injuries": ctx.injuries,
                    "camp_info": ctx.camp_info,
                    "weight_cut_notes": ctx.weight_cut_notes,
                    "short_notice": ctx.short_notice,
                }

            # Lookup fighter ranks
            from scrapers.rankings import get_fighter_rank
            rank_a = get_fighter_rank(fight.fighter_a, rankings)
            rank_b = get_fighter_rank(fight.fighter_b, rankings)

            fight_data = {
                "event_name": event_name,
                "date": fight_date,
                "fighter_a": _profile_to_dict(profile_a),
                "fighter_b": _profile_to_dict(profile_b),
                "weight_class": fight.weight_class,
                "rounds": fight.rounds,
                "card_position": fight.card_position,
                "odds": {
                    "moneyline": odds.moneyline,
                    "total_rounds": odds.total_rounds,
                    "implied_probs": odds.implied_probs,
                },
                "context_a": _context_to_dict(context_a),
                "context_b": _context_to_dict(context_b),
                "rankings": rankings,
                "rank_a": f"#{rank_a[1]} {rank_a[0]}" if rank_a else "Unranked",
                "rank_b": f"#{rank_b[1]} {rank_b[0]}" if rank_b else "Unranked",
            }

            brief = build_briefing(fight_data)
            logger.debug("    Briefing built (%d chars)", len(brief))

            click.echo(f"  Screening {fight_key}...")
            screen_start = time.time()
            # Adaptive screening: more runs for main events
            if fight.rounds == 5:
                screen = run_plan_b(brief, runs=3)  # Championship bout — thorough screen
            else:
                screen = run_plan_b(brief, runs=2)  # Standard bout
            logger.debug("    Screen pass completed in %.1fs", time.time() - screen_start)
            if not screen:
                click.echo(f"    Screen failed, skipping")
                logger.warning("    %s: screen pass returned None", fight_key)
                continue

            screen_odds = fight_data["odds"]
            edges = analyze_all_edges(screen, screen_odds)
            max_edge = max((e["edge"] for e in edges), default=0)
            logger.debug("    Edge analysis: %d edges found, max=%.3f (threshold=%.3f)",
                         len(edges), max_edge, SCREEN_EDGE_THRESHOLD)

            if max_edge >= SCREEN_EDGE_THRESHOLD:
                click.echo(f"    FLAGGED — max edge {max_edge:.1%}, queuing for full sim")
                logger.info("    %s FLAGGED (max edge %.1f%%) — queued for full sim in %.1fs",
                            fight_key, max_edge * 100, time.time() - fight_start)
                screened_fights.append((fight_key, brief, fight_data))
            else:
                click.echo(f"    No edge found (max {max_edge:.1%})")
                logger.info("    %s passed — no edge (max %.1f%%) in %.1fs",
                            fight_key, max_edge * 100, time.time() - fight_start)

        except FightTimeout:
            click.echo(f"  {fight_key}: TIMEOUT — exceeded {GAME_TIMEOUT}s, skipping")
            logger.error("  %s: TIMEOUT after %ds", fight_key, GAME_TIMEOUT)
            continue
        except Exception as e:
            click.echo(f"  {fight_key}: ERROR — {e}, skipping")
            logger.exception("  %s: unexpected error", fight_key)
            continue
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    logger.info("Step 5 complete: %d/%d fights flagged for full simulation",
                len(screened_fights), len(fights))

    # Step 6: Full MiroFish simulation on flagged fights
    click.echo(f"\n[6/6] Running full simulation on {len(screened_fights)} flagged fights...")
    logger.info("Step 6: running full ensemble on %d flagged fights", len(screened_fights))
    total_bets = 0
    total_sim_cost = 0.0

    for sim_idx, (fight_key, brief, fight_data) in enumerate(screened_fights, 1):
        click.echo(f"\n  === {fight_key} ===")
        try:
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(GAME_TIMEOUT)
            sim_start = time.time()
            logger.info("  [%d/%d] Full simulation: %s", sim_idx, len(screened_fights), fight_key)

            result = run_mirofish(brief, odds=fight_data["odds"])
            sim_elapsed = time.time() - sim_start
            if not result:
                click.echo("    Simulation failed")
                logger.warning("  %s: simulation returned None after %.1fs", fight_key, sim_elapsed)
                continue

            meta = result.get("ensemble_meta", {})
            logger.info("  %s: simulation complete in %.1fs — phase=%d, calls=%d, cost=$%.4f",
                        fight_key, sim_elapsed, meta.get("phase_reached", 0),
                        meta.get("total_calls", 0), meta.get("cost_usd", 0))
            total_sim_cost += meta.get("cost_usd", 0)

            bets = analyze_all_edges(result, fight_data["odds"])
            if not bets:
                click.echo("    No bets after full sim")
                logger.info("  %s: no edges survived full simulation", fight_key)
                continue

            logger.info("  %s: %d bet(s) found", fight_key, len(bets))
            for bet in bets:
                bet["date"] = fight_data.get("date", date.today().isoformat())
                bet["game"] = fight_key
                click.echo(
                    f"    BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                    f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
                )
                log_bet(bet)
                total_bets += 1

        except FightTimeout:
            click.echo(f"    TIMEOUT — exceeded {GAME_TIMEOUT}s, skipping")
            logger.error("  %s: TIMEOUT after %ds", fight_key, GAME_TIMEOUT)
            continue
        except Exception as e:
            click.echo(f"    ERROR — {e}, skipping")
            logger.exception("  %s: unexpected error during simulation", fight_key)
            continue
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    pipeline_elapsed = time.time() - pipeline_start
    click.echo(f"\n=== Done. {total_bets} bets logged. ===")
    logger.info("Pipeline complete: %d bets logged, total sim cost=$%.4f, elapsed=%.0fs",
                total_bets, total_sim_cost, pipeline_elapsed)


@cli.command()
@click.argument("fighter_a")
@click.argument("fighter_b")
@click.option("--date", "fight_date", default=None)
def fight(fighter_a, fighter_b, fight_date):
    """Analyze a single fight."""
    if fight_date is None:
        fight_date = date.today().isoformat()

    fight_key = f"{fighter_a} vs {fighter_b}"
    click.echo(f"\nAnalyzing {fight_key}...")

    # Get fighter profiles
    profile_a = get_fighter_profile(fighter_a)
    profile_b = get_fighter_profile(fighter_b)

    # Get odds
    odds_list = get_ufc_odds()
    fight_odds = None
    for o in odds_list:
        if (fighter_a.lower() in o.fighter_a.lower() or
                fighter_a.lower() in o.fighter_b.lower()):
            fight_odds = o
            break

    if not fight_odds:
        click.echo("Could not find odds for this fight.")
        return

    def _profile_to_dict(p):
        if p is None:
            return {"name": "Unknown"}
        return {
            "name": p.name, "record": p.record,
            "wins_ko": p.wins_ko, "wins_sub": p.wins_sub, "wins_dec": p.wins_dec,
            "stance": p.stance, "height": p.height, "reach": p.reach,
            "slpm": p.slpm, "str_acc": p.str_acc, "str_def": p.str_def,
            "td_avg": p.td_avg, "td_def": p.td_def, "sub_avg": p.sub_avg,
            "avg_fight_time": p.avg_fight_time, "age": p.age,
            "win_streak": p.win_streak, "last_5_fights": p.last_5_fights,
        }

    fight_data = {
        "event_name": "Single Fight Analysis",
        "date": fight_date,
        "fighter_a": _profile_to_dict(profile_a),
        "fighter_b": _profile_to_dict(profile_b),
        "weight_class": "TBD",
        "rounds": 3,
        "odds": {
            "moneyline": fight_odds.moneyline,
            "total_rounds": fight_odds.total_rounds,
            "implied_probs": fight_odds.implied_probs,
        },
        "context_a": {"injuries": [], "camp_info": "", "weight_cut_notes": ""},
        "context_b": {"injuries": [], "camp_info": "", "weight_cut_notes": ""},
        "rankings": {},
    }

    brief = build_briefing(fight_data)
    click.echo("\n--- Briefing ---")
    click.echo(brief[:500] + "...\n")

    click.echo("Running simulation...")
    result = run_mirofish(brief, odds=fight_data["odds"])
    if not result:
        click.echo("Simulation failed.")
        return

    bets = analyze_all_edges(result, fight_data["odds"])
    if not bets:
        click.echo("No value found.")
        return

    for bet in bets:
        bet["date"] = fight_date
        bet["game"] = fight_key
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
@click.option("--date", "fight_date", default=None, help="Date to grade (YYYY-MM-DD)")
def results(fight_date):
    """Grade pending bets against fight results."""
    run_results_grader(fight_date)


@cli.command()
@click.option("--date", "fight_date", default=None, help="Date (YYYY-MM-DD)")
def card(fight_date):
    """Display formatted bet card."""
    click.echo(format_bet_card(fight_date))


@cli.command()
def health():
    """Run pre-fight health check on all API connections."""
    run_health_check()


@cli.command()
@click.option("--min-bets", default=30, help="Minimum settled bets to analyze")
def optimize(min_bets):
    """Analyze performance and recommend threshold adjustments."""
    run_optimizer(min_bets)


if __name__ == "__main__":
    cli()
