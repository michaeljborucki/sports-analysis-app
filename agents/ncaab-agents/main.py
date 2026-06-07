"""CLI entrypoint for MiroFish NCAAB Prediction Pipeline."""
import logging
import time
import click
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone


from config import SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT

logger = logging.getLogger("mirofish")
from scrapers.schedule import get_ncaab_schedule
from scrapers.team_stats import get_team_efficiency
from scrapers.roster import get_roster_context
from scrapers.injuries import get_ncaab_injuries
from scrapers.matchup import get_matchup_context
from scrapers.odds import get_ncaab_odds
from briefing import build_briefing
from simulate import run_plan_b, run_mirofish
from edge import analyze_all_edges, analyze_all_bets
from tracker import log_bet, log_prediction, get_summary
from agents.results_grader import run_results_grader
from agents.bet_card import format_bet_card
from agents.health_check import run_health_check
from agents.self_optimizer import run_optimizer

# Lock for thread-safe click.echo output
_print_lock = threading.Lock()


def _echo(msg):
    """Thread-safe click.echo."""
    with _print_lock:
        click.echo(msg)


@click.group()
def cli():
    """MiroFish NCAAB Prediction Pipeline"""
    pass


def _parse_game_time(game_time_str: str) -> datetime | None:
    """Parse ESPN game_time ISO string to a timezone-aware datetime."""
    if not game_time_str:
        return None
    try:
        # ESPN returns ISO format like "2026-03-20T23:00Z"
        dt = datetime.fromisoformat(game_time_str.replace("Z", "+00:00"))
        return dt
    except (ValueError, TypeError):
        return None


def _is_game_started(game: dict) -> bool:
    """Return True if the game has already tipped off or is live/final."""
    # Check ESPN status first — most reliable
    status = game.get("status", "")
    if status in ("STATUS_IN_PROGRESS", "STATUS_FINAL", "STATUS_END_PERIOD",
                   "STATUS_HALFTIME"):
        return True

    # Fall back to game_time check
    gt = _parse_game_time(game.get("game_time", ""))
    if gt is None:
        return False  # can't determine — assume not started
    return datetime.now(timezone.utc) >= gt


def _screen_game(game_key, game, odds, team_stats_cache, injuries_by_team):
    """Screen a single game for edges. Returns (game_key, brief, game_data) or None."""
    away = game["away_team"]
    home = game["home_team"]

    away_stats = team_stats_cache.get(away, {})
    home_stats = team_stats_cache.get(home, {})

    game_data = {
        "away_team": away,
        "home_team": home,
        "away_stats": away_stats,
        "home_stats": home_stats,
        "away_roster": get_roster_context(away, game.get("away_team_id")),
        "home_roster": get_roster_context(home, game.get("home_team_id")),
        "matchup": get_matchup_context(away_stats, home_stats, game),
        "odds": {
            "moneyline": odds.moneyline,
            "spread": odds.spread,
            "total": odds.total,
            "h1_moneyline": odds.h1_moneyline,
            "h1_total": odds.h1_total,
            "h1_spread": odds.h1_spread,
            "implied_probs": odds.implied_probs,
        },
        "away_injuries": injuries_by_team.get(away, []),
        "home_injuries": injuries_by_team.get(home, []),
        "venue": game.get("venue", ""),
        "game_time": game.get("game_time", ""),
    }

    brief = build_briefing(game_data)

    _echo(f"  Screening {game_key}...")
    screen = run_plan_b(brief)
    if not screen:
        _echo(f"    {game_key}: Screen failed, skipping")
        return None

    edges = analyze_all_edges(screen, game_data["odds"])
    max_edge = max((e["edge"] for e in edges), default=0)

    if max_edge >= SCREEN_EDGE_THRESHOLD:
        _echo(f"    {game_key}: FLAGGED — max edge {max_edge:.1%}")
        logger.info("  %s FLAGGED (max edge %.1f%%)", game_key, max_edge * 100)
        return (game_key, brief, game_data)
    else:
        _echo(f"    {game_key}: No edge (max {max_edge:.1%})")
        return None


def _simulate_game(game_key, brief, game_data, game_date):
    """Run full ensemble simulation on a flagged game. Returns list of bets."""
    # Re-check: skip if the game has started since we began screening
    gt = _parse_game_time(game_data.get("game_time", ""))
    if gt and datetime.now(timezone.utc) >= gt:
        _echo(f"\n  === {game_key} === SKIPPED (game has started)")
        logger.info("  %s: skipped — game started during pipeline", game_key)
        return []

    _echo(f"\n  === {game_key} ===")
    sim_start = time.time()

    result = run_mirofish(brief, runs=3, odds=game_data["odds"], game_data=game_data)
    sim_elapsed = time.time() - sim_start
    if not result:
        _echo(f"    {game_key}: Simulation failed after {sim_elapsed:.0f}s")
        return []

    meta = result.get("ensemble_meta", {})
    logger.info("  %s: simulation complete in %.1fs — phase=%d, calls=%d, cost=$%.4f",
                game_key, sim_elapsed, meta.get("phase_reached", 0),
                meta.get("total_calls", 0), meta.get("cost_usd", 0))

    # Extract predicted score from ensemble result
    pred_score = result.get("predictions", {}).get("predicted_score", {})
    score_str = ""
    if pred_score and "away" in pred_score and "home" in pred_score:
        score_str = f"{pred_score['away']}-{pred_score['home']}"

    # Challenger verdicts (soft warnings, not hard kills)
    meta = result.get("ensemble_meta", {})
    challenger_verdicts = meta.get("challenger_verdicts", {})

    # Log ALL bet types to predictions CSV (for full bet card display)
    all_bets = analyze_all_bets(result, game_data["odds"])
    for pred in all_bets:
        pred["date"] = game_date
        pred["game"] = game_key
        pred["game_time"] = game_data.get("game_time", "")
        pred["predicted_score"] = score_str
        cv = challenger_verdicts.get(pred["bet_type"], {})
        pred["challenger_flag"] = cv.get("verdict") == "kill"
        pred["challenger_reason"] = cv.get("flaw_found") or cv.get("reasoning", "")
        log_prediction(pred)

    # Log edge-positive bets to bets CSV (for grading/P&L)
    bets = analyze_all_edges(result, game_data["odds"])
    if not bets:
        _echo(f"    {game_key}: No bets after full sim ({sim_elapsed:.0f}s)")
    killed_slots = [s for s, v in challenger_verdicts.items() if v.get("verdict") == "kill"]
    for bet in bets:
        bet["date"] = game_date
        bet["game"] = game_key
        bet["predicted_score"] = score_str
        flag = " [!]" if bet["bet_type"] in killed_slots else ""
        _echo(
            f"    {game_key} BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
            f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}{flag}"
        )
        log_bet(bet)

    return bets


# Max parallel games — keeps API rate limits and memory in check
MAX_PARALLEL_SCREENS = 8
MAX_PARALLEL_SIMS = 4


@cli.command()
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
def daily(game_date):
    """Run full daily pipeline: scrape -> screen -> simulate -> detect edges."""
    if game_date is None:
        game_date = date.today().isoformat()

    pipeline_start = time.time()
    click.echo(f"\n=== MiroFish NCAAB Pipeline — {game_date} ===\n")
    logger.info("Pipeline started for %s", game_date)

    # Step 1: Get schedule
    click.echo("[1/6] Fetching schedule...")
    t0 = time.time()
    all_games = get_ncaab_schedule(game_date)
    if not all_games:
        click.echo("No games found for this date.")
        logger.warning("No games found for %s — exiting", game_date)
        return

    # Filter out games that have already started
    games = [g for g in all_games if not _is_game_started(g)]
    started = len(all_games) - len(games)
    if started:
        click.echo(f"  Found {len(all_games)} games, {started} already started — analyzing {len(games)}")
    else:
        click.echo(f"  Found {len(games)} games")
    if not games:
        click.echo("All games have already started.")
        return
    logger.info("Step 1 complete: %d games (%d started, %d remaining) (%.1fs)",
                len(all_games), started, len(games), time.time() - t0)

    # Step 2: Get odds
    click.echo("[2/6] Fetching odds...")
    t0 = time.time()
    odds_list = get_ncaab_odds()
    odds_by_teams = {}
    for o in odds_list:
        key = f"{o.away}@{o.home}"
        odds_by_teams[key] = o
    logger.info("Step 2 complete: %d odds lines fetched (%.1fs)", len(odds_list), time.time() - t0)

    # Step 3: Get team stats (efficiency)
    click.echo("[3/6] Fetching team efficiency stats...")
    t0 = time.time()
    team_stats_cache = {}
    for game in games:
        for team in (game["away_team"], game["home_team"]):
            if team not in team_stats_cache:
                team_stats_cache[team] = get_team_efficiency(team)
    logger.info("Step 3 complete: %d team efficiency profiles cached (%.1fs)",
                len(team_stats_cache), time.time() - t0)

    # Step 4: Get injuries
    click.echo("[4/6] Fetching injuries...")
    t0 = time.time()
    injuries_by_team = {}
    for game in games:
        for team, team_id in ((game["away_team"], game.get("away_team_id")),
                              (game["home_team"], game.get("home_team_id"))):
            if team not in injuries_by_team and team_id:
                injuries_by_team[team] = get_ncaab_injuries(team_id)
    logger.info("Step 4 complete: injuries fetched for %d teams (%.1fs)",
                len(injuries_by_team), time.time() - t0)

    # Step 5: Build briefings + screen (parallel)
    click.echo(f"[5/6] Screening games (up to {MAX_PARALLEL_SCREENS} in parallel)...")
    logger.info("Step 5: screening %d games in parallel", len(games))
    t0 = time.time()
    screened_games = []

    # Build list of games with odds matches
    games_with_odds = []
    for game in games:
        away = game["away_team"]
        home = game["home_team"]
        away_abbrev = game.get("away_abbrev", away)
        home_abbrev = game.get("home_abbrev", home)
        game_key = f"{away_abbrev}@{home_abbrev}"
        full_key = f"{away}@{home}"
        odds = odds_by_teams.get(game_key) or odds_by_teams.get(full_key)
        if not odds:
            click.echo(f"  {game_key}: No odds found, skipping")
            continue
        games_with_odds.append((game_key, game, odds))

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SCREENS) as pool:
        futures = {
            pool.submit(
                _screen_game, gk, g, o, team_stats_cache, injuries_by_team
            ): gk
            for gk, g, o in games_with_odds
        }
        for future in as_completed(futures):
            gk = futures[future]
            try:
                result = future.result(timeout=GAME_TIMEOUT)
                if result:
                    screened_games.append(result)
            except Exception as e:
                _echo(f"  {gk}: ERROR — {e}")
                logger.exception("  %s: screen error", gk)

    logger.info("Step 5 complete: %d/%d games flagged (%.1fs)",
                len(screened_games), len(games), time.time() - t0)

    # Step 6: Full MiroFish simulation on flagged games (parallel)
    click.echo(f"\n[6/6] Running full simulation on {len(screened_games)} flagged games"
               f" (up to {MAX_PARALLEL_SIMS} in parallel)...")
    logger.info("Step 6: running full ensemble on %d flagged games", len(screened_games))
    t0 = time.time()
    total_bets = 0

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SIMS) as pool:
        futures = {
            pool.submit(
                _simulate_game, gk, brief, gd, game_date
            ): gk
            for gk, brief, gd in screened_games
        }
        for future in as_completed(futures):
            gk = futures[future]
            try:
                bets = future.result(timeout=GAME_TIMEOUT)
                total_bets += len(bets)
            except Exception as e:
                _echo(f"  {gk}: SIM ERROR — {e}")
                logger.exception("  %s: simulation error", gk)

    pipeline_elapsed = time.time() - pipeline_start
    click.echo(f"\n=== Done. {total_bets} bets logged in {pipeline_elapsed:.0f}s ===")
    logger.info("Pipeline complete: %d bets logged, elapsed=%.0fs",
                total_bets, pipeline_elapsed)


@cli.command()
@click.argument("away_team")
@click.argument("home_team")
@click.option("--date", "game_date", default=None)
def game(away_team, home_team, game_date):
    """Analyze a single game."""
    if game_date is None:
        game_date = date.today().isoformat()

    click.echo(f"\nAnalyzing {away_team}@{home_team} on {game_date}...")

    # Get team efficiency stats
    away_stats = get_team_efficiency(away_team)
    home_stats = get_team_efficiency(home_team)

    # Get odds
    odds_list = get_ncaab_odds()
    game_odds = None
    for o in odds_list:
        if o.away == away_team and o.home == home_team:
            game_odds = o
            break

    if not game_odds:
        click.echo("Could not find odds for this game.")
        return

    game_data = {
        "away_team": away_team,
        "home_team": home_team,
        "away_stats": away_stats,
        "home_stats": home_stats,
        "away_roster": get_roster_context(away_team, None),
        "home_roster": get_roster_context(home_team, None),
        "matchup": get_matchup_context(away_stats, home_stats, {}),
        "odds": {
            "moneyline": game_odds.moneyline,
            "spread": game_odds.spread,
            "total": game_odds.total,
            "h1_moneyline": game_odds.h1_moneyline,
            "h1_total": game_odds.h1_total,
            "h1_spread": game_odds.h1_spread,
            "implied_probs": game_odds.implied_probs,
        },
        "away_injuries": [],
        "home_injuries": [],
        "venue": "",
        "game_time": "",
    }

    brief = build_briefing(game_data)
    click.echo("\n--- Briefing ---")
    click.echo(brief[:500] + "...\n")

    click.echo("Running simulation...")
    result = run_mirofish(brief, runs=3, odds=game_data["odds"], game_data=game_data)
    if not result:
        click.echo("Simulation failed.")
        return

    bets = analyze_all_edges(result, game_data["odds"])
    if not bets:
        click.echo("No value found.")
        return

    pred_score = result.get("predictions", {}).get("predicted_score", {})
    score_str = ""
    if pred_score and "away" in pred_score and "home" in pred_score:
        score_str = f"{pred_score['away']}-{pred_score['home']}"

    for bet in bets:
        bet["date"] = game_date
        bet["game"] = f"{away_team}@{home_team}"
        bet["predicted_score"] = score_str
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
