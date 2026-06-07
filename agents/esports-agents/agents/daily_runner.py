"""Daily esports prediction pipeline orchestrator."""
import logging
import click
from datetime import datetime, timedelta

from config import SUPPORTED_GAMES, MAX_TIER, SCREEN_EDGE_THRESHOLD
from games import get_game
from scrapers.odds import get_esports_odds
from scrapers.meta import fetch_patch_context
from scrapers.news import fetch_match_context
from scrapers.schedule import get_todays_matches
from simulate import run_plan_b, run_mirofish
from edge import analyze_all_edges
from tracker import log_bet

log = logging.getLogger(__name__)


def run_pipeline(date: str = None, game_keys: list[str] = None):
    """Run the full prediction pipeline for all games."""
    game_keys = game_keys or SUPPORTED_GAMES
    date = date or datetime.now().strftime("%Y-%m-%d")

    log.info(f"[pipeline] Running for {date}, games: {game_keys}")
    total_bets = 0

    for game_key in game_keys:
        game = get_game(game_key)
        log.info(f"[pipeline] Processing {game_key}")

        # Fetch schedule
        matches = game.scrapers.fetch_upcoming_matches()
        matches = [m for m in matches if m.get("tier", 3) <= MAX_TIER]
        if not matches:
            log.info(f"[pipeline] No tier 1-2 matches for {game_key}")
            continue

        # Fetch odds
        odds_list = get_esports_odds(game_key)
        if not odds_list:
            log.warning(f"[pipeline] No odds available for {game_key}")
            continue

        # Fetch patch context (once per game)
        patch_ctx = fetch_patch_context(game_key)

        for match in matches:
            try:
                _process_match(game, game_key, match, odds_list, patch_ctx, date)
                total_bets += 1
            except Exception as e:
                log.error(f"[pipeline] Error processing {match.get('team_a')} vs {match.get('team_b')}: {e}")

    log.info(f"[pipeline] Complete. Processed matches across {len(game_keys)} games.")


def _process_match(game, game_key, match, odds_list, patch_ctx, date):
    """Process a single match through the pipeline."""
    team_a = match.get("team_a", "")
    team_b = match.get("team_b", "")

    # Find matching odds
    odds = _find_odds(odds_list, team_a, team_b)
    if not odds:
        log.debug(f"[pipeline] No odds for {team_a} vs {team_b}, skipping")
        return

    # Assemble match data
    match_data = {
        "tournament": match.get("tournament", ""),
        "date": date,
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
    screen = run_plan_b(briefing, game_config=game)
    if screen is None:
        log.debug(f"[pipeline] Screen pass returned None for {team_a} vs {team_b}")
        return

    # Full ensemble
    result = run_mirofish(briefing, odds=odds.to_dict(), game_config=game)
    if result is None:
        return

    # Edge detection
    fmt = match.get("format", "bo3")
    bets = analyze_all_edges(result.get("predictions", {}), odds, format=fmt, game_config=game.config)

    for bet in bets:
        bet["game_title"] = game_key
        bet["tournament"] = match.get("tournament", "")
        bet["game"] = f"{team_a} vs {team_b}"
        bet["date"] = date
        log_bet(bet)
        log.info(f"[pipeline] BET: {game_key} {team_a} vs {team_b} — {bet['bet_type']} {bet['side']} (edge: {bet['edge']:.1%})")


def _find_odds(odds_list, team_a, team_b):
    """Find odds matching two teams."""
    for odds in odds_list:
        if (team_a.lower() in odds.team_a.lower() or team_a.lower() in odds.team_b.lower()) and \
           (team_b.lower() in odds.team_a.lower() or team_b.lower() in odds.team_b.lower()):
            return odds
    return None


def run_results(date: str = None):
    """Grade yesterday's results."""
    from agents.results_grader import run_results_grader
    date = date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    run_results_grader(date)


def main(date: str = None, skip_health: bool = False, grade_yesterday: bool = True,
         game_keys: list[str] = None):
    """Daily workflow: health -> grade -> pipeline -> card."""
    if not skip_health:
        from agents.health_check import run_health_check
        run_health_check()

    if grade_yesterday:
        try:
            run_results()
        except Exception as e:
            log.warning(f"[daily] Results grading failed: {e}")

    run_pipeline(date=date, game_keys=game_keys)

    from agents.bet_card import format_bet_card
    print(format_bet_card(date))


@click.command()
@click.option("--date", "game_date", default=None, help="Game date (YYYY-MM-DD)")
@click.option("--skip-health", is_flag=True, help="Skip health check")
@click.option("--grade-yesterday", is_flag=True, help="Also grade yesterday's results")
def cli(game_date, skip_health, grade_yesterday):
    """Full daily workflow: health check -> grade yesterday -> run pipeline -> bet card."""
    main(date=game_date, skip_health=skip_health, grade_yesterday=grade_yesterday)


if __name__ == "__main__":
    cli()
