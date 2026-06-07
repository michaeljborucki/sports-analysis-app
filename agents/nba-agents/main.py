"""CLI entrypoint for MiroFish NBA Prediction Pipeline."""
import asyncio
import click
import logging
from datetime import date, datetime

from config import SCREEN_EDGE_THRESHOLD
from scrapers.schedule import get_todays_games
from scrapers.team_stats import get_team_profile
from scrapers.injuries import get_injuries
from scrapers.matchup import get_matchup_data
from scrapers.rest import get_rest_data
from scrapers.odds import get_nba_odds
from briefing import build_briefing
from simulate import run_plan_b, run_mirofish
from edge import analyze_all_edges
from tracker import log_bet, get_summary, get_breakdown, format_breakdown
from agents.results_grader import run_results_grader
from agents.bet_card import format_bet_card
from agents.health_check import run_health_check
from agents.self_optimizer import run_optimizer

logger = logging.getLogger("mirofish.pipeline")


async def run_daily_pipeline(game_date: str) -> int:
    """Run the full async pipeline. Returns number of bets logged."""
    from config import MAX_CONCURRENT_API_CALLS, MAX_CONCURRENT_GAMES
    from scrapers.odds import get_event_odds, merge_event_odds
    from simulate import run_prop_ensemble
    from edge import analyze_prop_edges
    from derive import derive_quarter_projections
    from pipeline_utils import format_prop_lines, build_game_odds_dict

    nba_sem = asyncio.Semaphore(MAX_CONCURRENT_API_CALLS)
    odds_sem = asyncio.Semaphore(MAX_CONCURRENT_API_CALLS)

    # Phase 1: Parallel data gathering
    logger.info("Phase 1: Fetching schedule, odds, injuries...")
    games, odds_list, all_injuries = await asyncio.gather(
        asyncio.to_thread(get_todays_games, game_date),
        asyncio.to_thread(get_nba_odds),
        asyncio.to_thread(get_injuries),
    )

    if not games:
        logger.info("No games found for %s", game_date)
        return 0

    logger.info("Found %d games", len(games))

    odds_by_teams = {}
    for o in odds_list:
        key = f"{o.away}@{o.home}"
        odds_by_teams[key] = o

    injuries_by_team = {}
    for inj in all_injuries:
        team = inj["team"]
        injuries_by_team.setdefault(team, []).append(inj)

    # Phase 2: Extended odds (parallel per game)
    logger.info("Phase 2: Fetching extended odds...")

    async def fetch_extended(odds_data):
        if not odds_data.event_id:
            return
        try:
            async with odds_sem:
                event_resp = await asyncio.to_thread(get_event_odds, odds_data.event_id)
            merge_event_odds(odds_data, event_resp)
        except Exception as e:
            logger.warning("Extended odds failed for %s: %s", odds_data.event_id, e)

    await asyncio.gather(*[fetch_extended(o) for o in odds_list])

    # Phase 3: Per-game enrichment (parallel)
    logger.info("Phase 3: Enriching game data...")

    async def nba_call(fn, *args):
        async with nba_sem:
            return await asyncio.to_thread(fn, *args)

    async def enrich_game(game):
        away = game["away_team"]
        home = game["home_team"]
        game_key = f"{away}@{home}"
        odds = odds_by_teams.get(game_key)
        if not odds:
            logger.info("[%s] No odds found, skipping", game_key)
            return None

        try:
            away_profile, home_profile, away_rest, home_rest, matchup = await asyncio.gather(
                nba_call(get_team_profile, away),
                nba_call(get_team_profile, home),
                nba_call(get_rest_data, away, game_date),
                nba_call(get_rest_data, home, game_date),
                nba_call(get_matchup_data, home, away),
            )
        except Exception as e:
            logger.error("[%s] Enrichment failed: %s", game_key, e)
            return None

        game_data = {
            "away_team": away,
            "home_team": home,
            "away_record": away_profile.get("record", ""),
            "home_record": home_profile.get("record", ""),
            "away_stats": away_profile,
            "home_stats": home_profile,
            "away_rest": away_rest,
            "home_rest": home_rest,
            "matchup": matchup,
            "arena": game.get("arena", ""),
            "game_time": game.get("game_time", ""),
            "odds": build_game_odds_dict(odds),
            "away_injuries": injuries_by_team.get(away, []),
            "home_injuries": injuries_by_team.get(home, []),
        }
        return (game_key, game_data, odds)

    enriched_results = await asyncio.gather(*[enrich_game(g) for g in games])
    enriched = [r for r in enriched_results if r is not None]

    # Phase 4: Screening (parallel)
    logger.info("Phase 4: Screening %d games...", len(enriched))

    async def screen_game(game_key, game_data, odds):
        try:
            brief = build_briefing(game_data)
            screen = await asyncio.to_thread(run_plan_b, brief)
            if not screen:
                logger.info("[%s] Screen failed", game_key)
                return None
            edges = analyze_all_edges(screen, game_data["odds"])
            max_edge = max((e["edge"] for e in edges), default=0)
            if max_edge >= SCREEN_EDGE_THRESHOLD:
                logger.info("[%s] FLAGGED -- max edge %.1f%%", game_key, max_edge * 100)
                return (game_key, brief, game_data, odds)
            else:
                logger.info("[%s] No edge (max %.1f%%)", game_key, max_edge * 100)
                return None
        except Exception as e:
            logger.error("[%s] Screen error: %s", game_key, e)
            return None

    screen_results = await asyncio.gather(*[screen_game(gk, gd, o) for gk, gd, o in enriched])
    flagged = [r for r in screen_results if r is not None]

    # Phase 5+6: Full ensemble + props (parallel per flagged game)
    logger.info("Phase 5+6: Simulating %d flagged games...", len(flagged))
    total_bets = 0

    async def simulate_game(game_key, brief, game_data, odds):
        all_bets = []

        # Phase 5: Full ensemble
        try:
            result = await asyncio.to_thread(run_mirofish, brief, 3, game_data["odds"])
        except Exception as e:
            logger.error("[%s] Ensemble failed: %s", game_key, e)
            result = None

        if result:
            # Derive Q2-Q4 projections
            derived = derive_quarter_projections(result.get("predictions", {}))

            # Game-level edge detection
            bets = analyze_all_edges(result, game_data["odds"], derived=derived)
            for bet in bets:
                bet["market"] = "game"
                bet["player"] = ""
            all_bets.extend(bets)

        # Phase 6: Player props
        if odds.player_props:
            try:
                prop_lines_str = format_prop_lines(odds)
                prop_result = await asyncio.to_thread(run_prop_ensemble, brief, prop_lines_str)
                if prop_result:
                    prop_bets = analyze_prop_edges(prop_result, game_data["odds"])
                    for bet in prop_bets:
                        bet["market"] = "prop"
                    all_bets.extend(prop_bets)
            except Exception as e:
                logger.warning("[%s] Prop ensemble failed: %s", game_key, e)

        return game_key, all_bets

    sim_results = await asyncio.gather(*[simulate_game(gk, b, gd, o) for gk, b, gd, o in flagged])

    for game_key, bets in sim_results:
        for bet in bets:
            bet["date"] = game_date
            bet["game"] = game_key
            logger.info("[%s] BET: %s %s @ %s | Edge: %.1f%% | Kelly: %.2f%%",
                        game_key, bet["bet_type"], bet["side"], bet["odds"],
                        bet["edge"] * 100, bet["kelly_pct"] * 100)
            log_bet(bet)
            total_bets += 1

    logger.info("Pipeline complete. %d bets logged.", total_bets)
    return total_bets


@click.group()
def cli():
    """MiroFish NBA Prediction Pipeline"""
    pass


@cli.command()
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
def daily(game_date):
    """Run full daily pipeline: scrape -> screen -> simulate -> detect edges."""
    if game_date is None:
        game_date = date.today().isoformat()

    click.echo(f"\n=== MiroFish NBA Pipeline — {game_date} ===\n")
    total_bets = asyncio.run(run_daily_pipeline(game_date))
    click.echo(f"\n=== Done. {total_bets} bets logged. ===")


@cli.command()
@click.argument("away_team")
@click.argument("home_team")
@click.option("--date", "game_date", default=None)
def game(away_team, home_team, game_date):
    """Analyze a single game."""
    if game_date is None:
        game_date = date.today().isoformat()

    click.echo(f"\nAnalyzing {away_team}@{home_team} on {game_date}...")

    # Get odds
    odds_list = get_nba_odds()
    game_odds = None
    for o in odds_list:
        if o.away == away_team and o.home == home_team:
            game_odds = o
            break

    if not game_odds:
        click.echo("Could not find odds for this game.")
        return

    away_profile = get_team_profile(away_team)
    home_profile = get_team_profile(home_team)
    away_rest = get_rest_data(away_team, game_date)
    home_rest = get_rest_data(home_team, game_date)
    matchup = get_matchup_data(home_team, away_team)

    all_injuries = get_injuries()
    injuries_by_team = {}
    for inj in all_injuries:
        team = inj["team"]
        injuries_by_team.setdefault(team, []).append(inj)

    game_data = {
        "away_team": away_team,
        "home_team": home_team,
        "away_record": away_profile.get("record", ""),
        "home_record": home_profile.get("record", ""),
        "away_stats": away_profile,
        "home_stats": home_profile,
        "away_rest": away_rest,
        "home_rest": home_rest,
        "matchup": matchup,
        "arena": "",
        "game_time": "",
        "odds": {
            "moneyline": game_odds.moneyline,
            "spread": game_odds.spread,
            "total": game_odds.total,
            "h1_moneyline": game_odds.h1_moneyline,
            "h1_total": game_odds.h1_total,
            "h1_spread": game_odds.h1_spread,
            "implied_probs": game_odds.implied_probs,
        },
        "away_injuries": injuries_by_team.get(away_team, []),
        "home_injuries": injuries_by_team.get(home_team, []),
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
        bet["game"] = f"{away_team}@{home_team}"
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
    breakdown = get_breakdown()
    if breakdown:
        click.echo(format_breakdown(breakdown))
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
