"""CLI entrypoint for MiroFish Tennis Prediction Pipeline."""
import logging
import threading
import time
import click
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from datetime import date, datetime, timedelta, timezone

from config import SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT, TOUR_CONFIG, PIPELINE_LOOKAHEAD_HOURS

logger = logging.getLogger("mirofish")


def _match_has_started(match: dict, now_utc: datetime | None = None) -> bool:
    """True if the match's ``start_time`` is at or before the current UTC
    moment. Used to skip matches we can no longer bet pre-market on — once
    play begins, books roll to live odds and our pre-match edges become
    meaningless.

    Unparseable or missing ``start_time`` returns False (don't filter) —
    the schedule scraper is authoritative, and if it handed us a match
    without a parseable time we proceed rather than drop coverage.
    """
    raw = match.get("start_time", "")
    if not raw:
        return False
    try:
        clean = str(raw).strip().replace("Z", "+00:00")
        commence = datetime.fromisoformat(clean)
    except (ValueError, TypeError):
        return False
    if commence.tzinfo is None:
        commence = commence.replace(tzinfo=timezone.utc)
    now = now_utc or datetime.now(timezone.utc)
    return commence <= now


# Match-level parallelism. Screening = 1 Kimi call per match so can scale.
# Full-sim's ensemble already parallelizes 6 models internally, so the outer
# match pool stays small to avoid flooding OpenRouter with 30+ concurrent
# calls (which triggers 429s on models with tighter rate limits — DeepSeek
# has shown this on busy days).
MATCH_SCREEN_WORKERS = 4
MATCH_SIM_WORKERS = 2

# Lock for tracker.log_bet CSV writes — multiple match threads can finish
# simultaneously and race the read-modify-write on bets.csv.
_log_bet_lock = threading.Lock()


def _safe_log_bet(bet: dict) -> None:
    from tracker import log_bet
    with _log_bet_lock:
        log_bet(bet)


# Lock for the per-tour player cache — _ensure_player may append to the
# players CSV on first sight of a player_key, and multiple screening threads
# can race the read-modify-write without this.
_player_cache_lock = threading.Lock()


def _resolve_full_name(abbrev_name: str, player_key, tour: str, cache: dict) -> str:
    """Resolve an api-tennis abbreviated name ("A. Rublev") to the full
    Sackmann-format name ("Andrey Rublev") via the sackmann_sync player
    cache. Falls back to the abbreviation if the lookup fails.

    Fixes a silent data-pipeline bug: ``scrapers/players.get_player_profile``
    matches on full-name substrings, so abbreviated inputs return placeholder
    data (Elo 1500, 0-0 record, 999 days since last match) — which the
    ensemble challenger then correctly kills as "missing player data".
    """
    from scrapers.sackmann_sync import _ensure_player, _full_name
    if not player_key:
        return abbrev_name
    with _player_cache_lock:
        meta = _ensure_player(player_key, tour, cache)
    return _full_name(meta, abbrev_name)


@click.group()
def cli():
    """MiroFish Tennis Prediction Pipeline"""
    pass


# ---------------------------------------------------------------------------
# Per-match helpers (pure — no shared state except _safe_log_bet's CSV lock)
# ---------------------------------------------------------------------------


def _screen_one_match(match: dict, odds_list: list, current_tour: str,
                      game_date_arg: str | None,
                      player_cache: dict | None = None) -> dict:
    """Screen one match. Returns a status dict. ``status`` is one of:
    ``flagged``, ``no_odds``, ``no_edge``, ``screen_failed``, ``error``.

    On ``flagged``, the dict also carries ``brief``, ``match_data``,
    ``bet_date``, ``start_time`` needed by ``_simulate_one_match``.
    """
    from scrapers.schedule import parse_match_datetime
    from scrapers.players import get_player_profile, get_head_to_head
    from scrapers.odds import find_odds_for_match
    from scrapers.conditions import get_match_conditions
    from briefing import build_briefing
    from simulate import run_plan_b
    from edge import analyze_all_edges

    abbrev_a = match["player_a"]
    abbrev_b = match["player_b"]
    # Resolve abbreviated api-tennis names ("A. Rublev") to full Sackmann
    # names ("Andrey Rublev") so get_player_profile below returns real stats
    # instead of placeholder data. Falls back to the abbreviation when the
    # player_key is missing or api-tennis lookup fails.
    cache = player_cache if player_cache is not None else {}
    pa_name = _resolve_full_name(abbrev_a, match.get("player_a_key"), current_tour, cache)
    pb_name = _resolve_full_name(abbrev_b, match.get("player_b_key"), current_tour, cache)
    # Match key stays in abbreviated form — it flows to Discord / bet card /
    # bets.csv and we want the user-facing label to match api-tennis/odds
    # sources they'll see elsewhere.
    match_key = f"{abbrev_a} vs {abbrev_b}"
    start_time = match.get("start_time", "")
    match_dt = parse_match_datetime(start_time)
    bet_date = (
        match_dt.date().isoformat() if match_dt
        else (game_date_arg or date.today().isoformat())
    )

    # Pre-market only — once play starts, odds roll to live and our edges
    # (based on pre-match probabilities) are no longer valid.
    if _match_has_started(match):
        return {"match_key": match_key, "status": "already_started", "start_time": start_time}

    odds = find_odds_for_match(odds_list, abbrev_a, abbrev_b)
    if not odds:
        return {"match_key": match_key, "status": "no_odds"}

    try:
        surface = match.get("surface", "hard")
        pa_profile = get_player_profile(pa_name, current_tour, surface)
        pb_profile = get_player_profile(pb_name, current_tour, surface)
        h2h = get_head_to_head(pa_name, pb_name, current_tour)
        conditions = get_match_conditions(
            match.get("tournament", ""), surface,
            match.get("indoor_outdoor", "outdoor"),
        )
        match_data = {
            "tournament": match.get("tournament", ""),
            "round": match.get("round", ""),
            "surface": surface,
            "indoor_outdoor": match.get("indoor_outdoor", "outdoor"),
            "best_of": 5 if "grand slam" in match.get("tournament", "").lower() else 3,
            "player_a": pa_profile,
            "player_b": pb_profile,
            "head_to_head": h2h,
            "odds": {
                "moneyline": odds.moneyline,
                "game_handicap": odds.game_handicap,
                "total_games": odds.total_games,
                "implied_probs": odds.implied_probs,
            },
            "conditions": conditions,
            "injuries": {"player_a": "N/A", "player_b": "N/A"},
        }
        brief = build_briefing(match_data)
        screen = run_plan_b(brief)
        if not screen:
            return {"match_key": match_key, "status": "screen_failed"}

        edges = analyze_all_edges(screen, match_data["odds"], tour=current_tour)
        max_edge = max((e["edge"] for e in edges), default=0)
        if max_edge >= SCREEN_EDGE_THRESHOLD:
            return {
                "match_key": match_key, "status": "flagged",
                "max_edge": max_edge,
                "brief": brief, "match_data": match_data,
                "bet_date": bet_date, "start_time": start_time,
            }
        return {"match_key": match_key, "status": "no_edge", "max_edge": max_edge}
    except Exception as e:
        logger.exception("Error screening %s", match_key)
        return {"match_key": match_key, "status": "error", "error": str(e)}


def _simulate_one_match(match_key: str, brief: str, match_data: dict,
                        bet_date: str, start_time: str, current_tour: str,
                        force_resim: bool = False) -> dict:
    """Full-sim one flagged match, filter edges, log bets. Returns status dict
    with ``status`` in (``logged``, ``no_bets``, ``sim_failed``, ``already_started``,
    ``cached``, ``error``) and ``bets`` list of logged bets (empty unless ``logged``).

    The ensemble's prediction dict is cached per ``(bet_date, match_key)`` to
    avoid re-spending ~$0.30 of OpenRouter cost when ``main.py daily`` is
    re-run later in the day. Edge detection still runs against the LIVE
    odds every time, so bet side / size update if the line moved — only
    the ensemble probability estimates are reused.

    Pass ``force_resim=True`` to bypass the cache and call ``run_mirofish``
    fresh (e.g. odds moved enough to suspect the cached probs are stale).
    """
    from simulate import run_mirofish
    from edge import analyze_all_edges, apply_bet_filters
    from sim_cache import get_cached_sim, save_cached_sim

    # Second pre-market check: a match that was still upcoming at screen
    # time may have started while we waited in the outer pool's queue or
    # during screening. Skip to avoid logging a bet on a live match.
    if _match_has_started({"start_time": start_time}):
        return {"match_key": match_key, "status": "already_started", "bets": []}

    try:
        cached = None if force_resim else get_cached_sim(bet_date, match_key)
        if cached is not None:
            result = cached
            from_cache = True
        else:
            result = run_mirofish(brief, runs=3, odds=match_data["odds"])
            from_cache = False
            if result:
                save_cached_sim(bet_date, match_key, result)
        if not result:
            return {"match_key": match_key, "status": "sim_failed", "bets": []}

        bets = analyze_all_edges(result, match_data["odds"], tour=current_tour)
        bets = apply_bet_filters(bets)
        if not bets:
            return {
                "match_key": match_key,
                "status": "no_bets" if not from_cache else "cached_no_bets",
                "bets": [],
            }

        logged = []
        for bet in bets:
            bet["date"] = bet_date
            bet["start_time"] = start_time
            bet["game"] = match_key
            _safe_log_bet(bet)
            logged.append(bet)
        return {
            "match_key": match_key, "status": "logged",
            "bets": logged, "from_cache": from_cache,
        }
    except Exception as e:
        logger.exception("Simulation error for %s", match_key)
        return {"match_key": match_key, "status": "error", "error": str(e), "bets": []}


_UNDATED_SENTINEL = datetime.max.replace(tzinfo=timezone.utc)


def _sort_key_by_start_time(match: dict) -> tuple:
    """Sort key for the merged slate — ascending by UTC start time.

    Matches with unparseable / missing start_time sort to the end so they
    don't block time-sensitive processing. Secondary key is tour then
    match_id for stable ordering when times tie.

    The sentinel is tz-aware (UTC) to match ``parse_match_datetime``'s
    output — mixing naive and aware datetimes raises TypeError on compare.
    """
    from scrapers.schedule import parse_match_datetime
    dt = parse_match_datetime(match.get("start_time", "")) or _UNDATED_SENTINEL
    return (dt, str(match.get("tour", "")), str(match.get("match_id", "")))


@cli.command()
@click.option("--date", "game_date", default=None, help="Calendar date (YYYY-MM-DD). Omit to use next 24h window.")
@click.option("--tour", default="both", type=click.Choice(["atp", "wta", "both"]))
@click.option("--no-notify", is_flag=True, help="Skip Discord picks notification.")
@click.option("--force-resim", is_flag=True,
              help="Bypass the per-day sim cache and run the full ensemble fresh. "
                   "Costs ~$0.30 per match — use only when odds have moved enough "
                   "that cached probabilities may produce stale bet sizing.")
def daily(game_date, tour, no_notify, force_resim):
    """Run full daily pipeline: scrape -> screen -> simulate -> detect edges.

    When ``--tour both`` (default) ATP and WTA matches are MERGED into a
    single queue and processed in start-time order, so the earliest
    upcoming matches get simulated first regardless of tour. This keeps us
    pre-market on time-sensitive matches even when the other tour has a
    larger slate that would otherwise push everything back.

    Screening and full simulation run matches in parallel with bounded
    concurrency; per-match budget is ``GAME_TIMEOUT`` seconds, enforced by
    ``future.result(timeout=...)``.
    """
    from scrapers.schedule import get_schedule, get_upcoming_matches
    from scrapers.odds import get_tennis_odds

    use_window = game_date is None
    scope_label = f"next {PIPELINE_LOOKAHEAD_HOURS}h" if use_window else game_date
    tours = ["atp", "wta"] if tour == "both" else [tour]

    pipeline_start = time.time()
    click.echo(f"\n=== MiroFish Tennis Pipeline — {'+'.join(t.upper() for t in tours)} — {scope_label} ===\n")

    # Step 1: Fetch schedules and tag each match with its tour.
    # Lookahead window is intentionally short (PIPELINE_LOOKAHEAD_HOURS): odds
    # drift, lineups can change, and cached predictions decay on far-out
    # matches. Better to re-run the pipeline as matches approach than to
    # spend ensemble cost on something that won't tip for 18 hours.
    click.echo("[1/5] Fetching schedules...")
    matches: list[dict] = []
    for t in tours:
        slate = (get_upcoming_matches(t, hours=PIPELINE_LOOKAHEAD_HOURS)
                 if use_window else get_schedule(t, game_date))
        for m in slate:
            m["tour"] = t
        matches.extend(slate)
        click.echo(f"  {t.upper()}: {len(slate)} matches")
    if not matches:
        click.echo("No matches found for this window.")
        return
    # Merge + time-sort across both tours so earliest-starting matches get
    # screened and simulated first.
    matches.sort(key=_sort_key_by_start_time)
    click.echo(f"  Merged slate: {len(matches)} matches, time-sorted")

    # Step 2: Fetch per-tour odds once; look up by match tour downstream.
    click.echo("[2/5] Fetching odds...")
    odds_by_tour: dict[str, list] = {}
    for t in tours:
        odds_by_tour[t] = get_tennis_odds(t)
        click.echo(f"  {t.upper()}: {len(odds_by_tour[t])} odds lines")

    # Per-tour player caches (first lookup loads players.csv, subsequent hit memory).
    caches_by_tour: dict[str, dict] = {t: {} for t in tours}

    # Step 3: Parallel screening across the merged slate.
    click.echo(f"[3/5] Building briefings and screening ({MATCH_SCREEN_WORKERS} concurrent)...")
    screened: list[dict] = []
    executor = ThreadPoolExecutor(max_workers=MATCH_SCREEN_WORKERS)
    try:
        futures = {
            executor.submit(
                _screen_one_match, m, odds_by_tour[m["tour"]], m["tour"],
                game_date, caches_by_tour[m["tour"]],
            ): m
            for m in matches
        }
        for future in as_completed(futures):
            m = futures[future]
            match_key_hint = f"{m['player_a']} vs {m['player_b']}"
            try:
                r = future.result(timeout=GAME_TIMEOUT)
            except FuturesTimeoutError:
                click.echo(f"  [{match_key_hint}] TIMEOUT during screen")
                continue
            except Exception as e:
                click.echo(f"  [{match_key_hint}] ERROR: {e}")
                continue

            mk = r["match_key"]
            st = r["status"]
            tour_tag = m["tour"].upper()
            if st == "flagged":
                r["tour"] = m["tour"]
                click.echo(f"  [{tour_tag}] [{mk}] FLAGGED — max edge {r['max_edge']:.1%}")
                screened.append(r)
            elif st == "no_edge":
                click.echo(f"  [{tour_tag}] [{mk}] no edge (max {r['max_edge']:.1%})")
            elif st == "no_odds":
                click.echo(f"  [{tour_tag}] [{mk}] no odds, skipping")
            elif st == "already_started":
                from notify.format import format_start_time_local
                t = format_start_time_local(r.get("start_time", ""))
                click.echo(f"  [{tour_tag}] [{mk}] match already started ({t or 'time unknown'}), skipping pre-market")
            elif st == "screen_failed":
                click.echo(f"  [{tour_tag}] [{mk}] screen failed")
            elif st == "error":
                click.echo(f"  [{tour_tag}] [{mk}] error: {r.get('error', '?')}")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # Preserve the time-sorted ordering for full-sim: whichever flagged
    # matches start earliest go first. as_completed above doesn't guarantee
    # order, so re-sort on start_time here.
    screened.sort(key=_sort_key_by_start_time)

    # Step 4: Parallel full simulation.
    click.echo(f"\n[4/5] Running full simulation on {len(screened)} flagged matches ({MATCH_SIM_WORKERS} concurrent)...")
    bets_by_tour: dict[str, int] = {t: 0 for t in tours}
    executor = ThreadPoolExecutor(max_workers=MATCH_SIM_WORKERS)
    try:
        futures = {
            executor.submit(
                _simulate_one_match,
                r["match_key"], r["brief"], r["match_data"],
                r["bet_date"], r["start_time"], r["tour"], force_resim,
            ): (r["match_key"], r["tour"])
            for r in screened
        }
        for future in as_completed(futures):
            mk, match_tour = futures[future]
            tour_tag = match_tour.upper()
            try:
                r = future.result(timeout=GAME_TIMEOUT)
            except FuturesTimeoutError:
                click.echo(f"  [{tour_tag}] [{mk}] TIMEOUT after {GAME_TIMEOUT}s — skipping")
                continue
            except Exception as e:
                click.echo(f"  [{tour_tag}] [{mk}] ERROR: {e}")
                continue

            st = r["status"]
            if st == "logged":
                cache_tag = " (cached)" if r.get("from_cache") else ""
                for bet in r["bets"]:
                    click.echo(
                        f"  [{tour_tag}] [{mk}]{cache_tag} BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                        f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
                    )
                    bets_by_tour[match_tour] += 1
                # Discord dispatch immediately — matches starting mid-pipeline
                # shouldn't wait for the whole slate to sim before alerting.
                # send_notifications dedups via already_sent state so this
                # can't double-post the same bet. Per-bet dispatch dates are
                # collected from the logged bets so we cover both today and
                # tomorrow cleanly.
                if not no_notify:
                    try:
                        from notify import send_notifications
                        for nd in sorted({str(b.get("date", "")) for b in r["bets"] if b.get("date")}):
                            s = send_notifications(game_date=nd)
                            if s["bets_new"]:
                                status = (f"sent {s['sent']} Discord msg(s)" if s["discord_enabled"]
                                          else "Discord not enabled")
                                click.echo(f"  [{tour_tag}] [{mk}] Notify {nd}: {s['bets_new']} new → {status}")
                    except Exception as e:
                        logger.error("Per-match notify dispatch failed for %s: %s", mk, e)
            elif st == "no_bets":
                click.echo(f"  [{tour_tag}] [{mk}] no bets after full sim")
            elif st == "cached_no_bets":
                click.echo(f"  [{tour_tag}] [{mk}] no bets (cached sim, no ensemble call)")
            elif st == "sim_failed":
                click.echo(f"  [{tour_tag}] [{mk}] simulation failed")
            elif st == "already_started":
                click.echo(f"  [{tour_tag}] [{mk}] match started during processing, skipping pre-market")
            elif st == "error":
                click.echo(f"  [{tour_tag}] [{mk}] error: {r.get('error', '?')}")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # Step 5: Summary — per-tour bet count plus total.
    elapsed = time.time() - pipeline_start
    total_bets = sum(bets_by_tour.values())
    breakdown = ", ".join(f"{t.upper()}={bets_by_tour[t]}" for t in tours)
    click.echo(f"\n[5/5] Pipeline complete. {total_bets} bets logged ({breakdown}) in {elapsed:.0f}s.")

    if not no_notify:
        try:
            from notify import send_notifications
            notify_dates = [game_date] if game_date else sorted({
                date.today().isoformat(),
                (date.today() + timedelta(days=1)).isoformat(),
            })
            for nd in notify_dates:
                s = send_notifications(game_date=nd)
                if s["bets_new"]:
                    status = (f"sent {s['sent']} Discord msg(s)" if s["discord_enabled"]
                              else "Discord not enabled")
                    click.echo(f"Notify {nd}: {s['bets_new']} new → {status}")
        except Exception as e:
            logger.error("Notification dispatch failed: %s", e)


@cli.command()
@click.argument("player_a")
@click.argument("player_b")
@click.option("--date", "game_date", default=None)
@click.option("--tour", default="atp", type=click.Choice(["atp", "wta"]))
def match(player_a, player_b, game_date, tour):
    """Analyze a single match."""
    from scrapers.players import get_player_profile, get_head_to_head
    from scrapers.odds import get_tennis_odds
    from scrapers.conditions import get_match_conditions
    from briefing import build_briefing
    from simulate import run_mirofish
    from edge import analyze_all_edges, apply_bet_filters
    from tracker import log_bet

    if game_date is None:
        game_date = date.today().isoformat()

    click.echo(f"\nAnalyzing {player_a} vs {player_b} ({tour.upper()})...")

    pa_profile = get_player_profile(player_a, tour)
    pb_profile = get_player_profile(player_b, tour)
    h2h = get_head_to_head(player_a, player_b, tour)

    odds_list = get_tennis_odds(tour)
    game_odds = None
    for o in odds_list:
        if player_a.lower() in o.player_a.lower() or player_a.lower() in o.player_b.lower():
            game_odds = o
            break

    if not game_odds:
        click.echo("Could not find odds for this match.")
        return

    match_data = {
        "tournament": "", "round": "", "surface": "hard",
        "indoor_outdoor": "outdoor", "best_of": 3,
        "player_a": pa_profile, "player_b": pb_profile,
        "head_to_head": h2h,
        "odds": {
            "moneyline": game_odds.moneyline,
            "game_handicap": game_odds.game_handicap,
            "total_games": game_odds.total_games,
            "implied_probs": game_odds.implied_probs,
        },
        "conditions": get_match_conditions(),
        "injuries": {"player_a": "N/A", "player_b": "N/A"},
    }

    brief = build_briefing(match_data)
    click.echo("\n--- Briefing ---")
    click.echo(brief[:500] + "...\n")

    click.echo("Running simulation...")
    result = run_mirofish(brief, runs=3, odds=match_data["odds"])
    if not result:
        click.echo("Simulation failed.")
        return

    bets = analyze_all_edges(result, match_data["odds"], tour=tour)
    bets = apply_bet_filters(bets)
    if not bets:
        click.echo("No value found.")
        return

    for bet in bets:
        bet["date"] = game_date
        bet["game"] = f"{player_a} vs {player_b}"
        click.echo(
            f"  BET: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
            f"Edge: {bet['edge']:.1%} | Kelly: {bet['kelly_pct']:.2%}"
        )
        log_bet(bet)


@cli.command()
def report():
    """Show P&L summary."""
    from tracker import get_summary
    summary = get_summary()
    click.echo("\n=== MiroFish Tennis P&L Report ===")
    click.echo(f"  Total bets: {summary['total_bets']}")
    click.echo(f"  Record: {summary['record']}")
    click.echo(f"  Profit (units): {summary.get('profit', 0)}")
    click.echo(f"  ROI: {summary.get('roi', 0)}%")
    click.echo()


@cli.command()
@click.option("--date", "game_date", default=None)
@click.option("--tour", default="atp", type=click.Choice(["atp", "wta"]))
@click.option("--no-notify", is_flag=True, help="Skip Discord grade + season notifications.")
def results(game_date, tour, no_notify):
    """Grade pending bets against final scores."""
    from agents.results_grader import run_results_grader
    run_results_grader(game_date, tour)

    if no_notify:
        return
    resolved_date = game_date or (date.today() - timedelta(days=1)).isoformat()
    try:
        from notify import send_grade_notifications, send_season_notification
        g = send_grade_notifications(game_date=resolved_date)
        if g["grades_sent"] or g["summary_sent"]:
            click.echo(
                f"Notify grades: {g['grades_sent']} msg + summary={g['summary_sent']} "
                f"({g['bets_filtered']} of {g['bets_graded']} picks)"
            )
        elif g["skipped_reason"]:
            click.echo(f"Notify grades: skipped ({g['skipped_reason']})")
        s = send_season_notification(through_date=resolved_date)
        if s["sent"]:
            click.echo(f"Notify season: 1 msg ({s['bets_filtered']} bets)")
        elif s["skipped_reason"]:
            click.echo(f"Notify season: skipped ({s['skipped_reason']})")
    except Exception as e:
        logger.error("Grade/season notify dispatch failed: %s", e)


@cli.command("notify")
@click.option("--date", "game_date", default=None, help="Target date (YYYY-MM-DD)")
@click.option("--force", is_flag=True, help="Re-send already-notified bets")
@click.option("--dry-run", is_flag=True, help="Print messages instead of sending")
def notify_cmd(game_date, force, dry_run):
    """Send filtered bet card to Discord per data/alerts_config.json."""
    from notify import send_notifications
    s = send_notifications(game_date=game_date, force=force, dry_run=dry_run)
    click.echo(
        f"Notify: {s['bets_new']} new of {s['bets_filtered']} filtered "
        f"({s['bets_total']} total). Discord enabled: {s['discord_enabled']}. Sent: {s['sent']}"
    )


@cli.command("clv-capture")
@click.option("--date", "game_date", default=None, help="Match date (YYYY-MM-DD); defaults to yesterday.")
@click.option("--tour", default=None, type=click.Choice(["atp", "wta"]))
@click.option("--offset-min", default=5, help="Minutes before commence_time to snapshot.")
def clv_capture(game_date, tour, offset_min):
    """Snapshot consensus closing lines from The Odds API historical endpoint and
    write them to data/closing_lines.csv."""
    from scrapers.closing_lines import capture_closing_lines_for_date
    if game_date is None:
        game_date = (date.today() - timedelta(days=1)).isoformat()
    summary = capture_closing_lines_for_date(game_date, tour=tour, snapshot_offset_min=offset_min)
    click.echo(
        f"CLV capture {game_date} ({tour or 'both'}): "
        f"{summary['captured_rows']} rows across {summary['captured_games']} matches "
        f"({summary['snapshot_calls']} snapshot calls, {summary['skipped']} skipped)"
    )


@cli.command("clv-apply")
@click.option("--date", "game_date", default=None, help="Apply to bets on this date.")
def clv_apply(game_date):
    """Walk bets.csv and back-apply CLV from data/closing_lines.csv (for dates where capture ran after grade)."""
    import pandas as pd
    from tracker import lookup_clv, CLV_COLUMNS, BETS_CSV
    df = pd.read_csv(BETS_CSV)
    for col in CLV_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    applied = 0
    missed = 0
    target = df if game_date is None else df[df["date"] == game_date]
    for idx in target.index:
        row = df.loc[idx].to_dict()
        if str(row.get("clv_cents", "")) not in ("", "nan"):
            continue  # already applied
        clv = lookup_clv(row)
        if not clv:
            missed += 1
            continue
        df.at[idx, "close_odds"] = clv["close_odds"]
        df.at[idx, "close_prob"] = clv["close_prob"]
        df.at[idx, "clv_cents"] = clv["clv_cents"]
        df.at[idx, "clv_pct"] = clv["clv_pct"]
        applied += 1
    df.to_csv(BETS_CSV, index=False)
    click.echo(f"CLV apply: filled {applied} rows, {missed} had no close line available.")


@cli.command()
@click.option("--date", "game_date", default=None)
def card(game_date):
    """Display formatted bet card and save it to data/bet_card_<date>.{txt,json}."""
    from agents.bet_card import format_bet_card, save_bet_card
    click.echo(format_bet_card(game_date))
    txt_path, json_path = save_bet_card(game_date)
    click.echo(f"Saved: {txt_path}")
    click.echo(f"Saved: {json_path}")


@cli.command()
def health():
    """Run pre-game health check on all API connections."""
    from agents.health_check import run_health_check
    run_health_check()


@cli.command()
@click.option("--min-bets", default=30)
def optimize(min_bets):
    """Analyze performance and recommend threshold adjustments."""
    from agents.self_optimizer import run_optimizer
    run_optimizer(min_bets)


if __name__ == "__main__":
    cli()
