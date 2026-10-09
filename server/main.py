from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Config
from .odds.books.coral33 import Coral33Fetcher
from .odds.books.coral33.accounts import AccountsScraper
from .odds.books.kalshi import KalshiFetcher
from .odds.books.polymarket import PolymarketFetcher
from .odds.books.novig import NovigFetcher
from .odds.cache import OddsCache
from .odds.cache_mode import CacheMode, CacheModeStore
from .odds.client import OddsAPIClient
from .odds.clv_capture import capture_closing_lines
from .odds.fetcher import FetcherRegistry
from .odds.latest_snapshot import LatestOddsSnapshotService
from .sports import all_sports
from .user_settings import UserSettingsStore


logging.basicConfig(level=logging.INFO)

# GIL handoff interval 5ms -> 1ms. While the minutely snapshot rebuild burns
# ~5s of pure-Python CPU, every thread doing many short I/O calls (sqlite,
# sockets) waits up to the interval to win the GIL back after each one — a
# handful of SQLite calls added up to 1-1.8s on /api/health. Throughput cost
# to the CPU-bound rebuild is ~1-2%.
sys.setswitchinterval(0.001)


def create_app() -> FastAPI:
    config = Config.from_env()

    # Cache-mode state machine: persists mode across restarts. Cache path is
    # resolved at init from the persisted mode so SNAPSHOT mode survives reboot.
    live_cache_path = config.cache_db
    snapshot_cache_path = live_cache_path.with_name("cache.snapshot.db")
    mode_store = CacheModeStore(live_cache_path.with_name("cache_mode.json"))
    initial_mode = mode_store.get()
    if initial_mode == CacheMode.SNAPSHOT and not snapshot_cache_path.exists():
        logging.warning(
            "cache_mode=snapshot but %s missing — falling back to latest",
            snapshot_cache_path,
        )
        initial_mode = CacheMode.LATEST
        mode_store.set(initial_mode)
    initial_path = (
        snapshot_cache_path if initial_mode == CacheMode.SNAPSHOT else live_cache_path
    )

    cache = OddsCache(initial_path)
    from .odds.mapping_health import MappingHealth
    mapping_health = MappingHealth(initial_path.with_suffix(".mapping.sqlite"))
    cache.init()
    snapshot_service = LatestOddsSnapshotService(cache)
    # Run schema migrations against the *other* path too, so a later mode
    # flip (live ↔ snapshot in cache_mode.py:_apply_mode) doesn't land us
    # on a DB that's missing a recent column. cheap — init is idempotent.
    other_path = (
        live_cache_path if initial_path == snapshot_cache_path else snapshot_cache_path
    )
    if other_path.exists():
        OddsCache(other_path).init()
    client = OddsAPIClient(api_key=config.odds_api_key)
    sports = all_sports()
    settings_store = UserSettingsStore()
    fetcher = FetcherRegistry(config, sports, cache, client, settings_store)

    from pathlib import Path as _Path
    coral33_fetcher = Coral33Fetcher(
        customer_id=config.coral33_customer_id,
        password=config.coral33_password,
        cache=cache,
        config_path=_Path(__file__).parent / "config" / "coral33.toml",
    )
    # Kalshi direct-API fetcher — replaces Odds API's `kalshi` rows
    # (which are 2-5min stale) with a ~15s direct poll. Reads are public
    # so the fetcher works without credentials; when KALSHI_API_KEY and
    # KALSHI_PRIVATE_KEY_PATH are set, every request is signed (unlocks
    # higher rate limits + portfolio/position endpoints).
    kalshi_fetcher = KalshiFetcher(
        cache=cache,
        config_path=_Path(__file__).parent / "config" / "kalshi.toml",
        api_key=config.kalshi_api_key or None,
        private_key_path=config.kalshi_private_key_path,
    )
    # Polymarket direct-API fetcher — Gamma REST (60s) + CLOB WebSocket
    # (sub-second). Public API, no auth or creds needed; reads are free.
    # Phase 1 covers per-game h2h moneylines for NBA/MLB/NHL. Phase 2 will
    # extend to alt markets and player props.
    polymarket_fetcher = PolymarketFetcher(
        cache=cache,
        config_path=_Path(__file__).parent / "config" / "polymarket.toml",
    )
    # Novig direct order-book reader — public REST, no key, read-only.
    # Overrides the Odds API's Novig rows (same PK) with fresher take
    # prices + size. NOVIG_FETCHER_ENABLED=false turns it off.
    novig_fetcher = NovigFetcher(
        cache=cache, settings_store=settings_store,
        snapshot_rows=lambda: (
            snapshot_service.current.rows
            if snapshot_service.current is not None else None
        ),
    )
    novig_enabled = os.environ.get("NOVIG_FETCHER_ENABLED", "true").strip().lower() not in ("0", "false", "no")
    # Multi-account roll-up scraper (Accounts page). Reads CORAL33_ACCOUNTS
    # env (JSON list) or falls back to the single-account env pair. The
    # cache reference lets the scraper persist balance_snapshots on every
    # refresh, populating the daily-chart's pending overlay automatically.
    accounts_scraper = AccountsScraper(cache=cache)

    # Closing-line capture scheduler. Runs every 60s in LIVE mode and
    # walks events whose commence_time is in T-15..T-5; each pass devigs
    # the sharp-book consensus from odds_snapshot and writes one
    # closing_lines row per outcome. The job is idempotent on the PK, so
    # re-captures within the window overwrite with the latest fair line.
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    clv_scheduler = AsyncIOScheduler()

    def _capture_tick():
        try:
            n = capture_closing_lines(cache)
            if n:
                # Also purge old closing lines once per cycle. Cheap on a
                # small table and keeps the file from growing unboundedly.
                cache.purge_old_closing_lines(_dt.now(_tz.utc))
        except Exception:
            logging.exception("CLV capture tick failed")

    def _purge_stale_rows_tick():
        """Shared row-level TTL sweep. Used to run from BOTH the Odds API
        fetcher (~13 sports) AND the coral33 fetcher (~7 sports) every 60s,
        producing 20+ identical scans/min over the same odds_snapshot table.
        Consolidated to a single 60s job so the table is scanned once per
        minute instead of per-sport-per-fetcher.
        """
        try:
            stale = cache.purge_stale_rows(now=_dt.now(_tz.utc))
            if stale:
                logging.info("purged %d stale rows (shared TTL)", stale)
        except Exception:
            logging.exception("purge_stale_rows tick failed")

    async def _wager_log_refresh_tick():
        """Re-pull the wager log so newly-placed bets appear without the
        user having to hit ?force_wager_log=true. Coral33's wager-log
        endpoint costs ~14 calls per account per refresh; 8 accounts ×
        30-min cadence = 224 calls/hour, well under their rate limit.
        Settled wagers are immutable so re-pulling is cheap on the
        persistence side (JSON overwrite). After refreshing, mirror the
        log into the unified `bets` table so /api/bets is in sync.
        """
        try:
            wager_log = await accounts_scraper.get_wager_log(force=True)
        except Exception:
            logging.exception("wager-log refresh tick failed")
            return
        try:
            from .odds.books.coral33.bets_mirror import mirror_coral33_wager_log_to_bets
            mirror_coral33_wager_log_to_bets(cache, wager_log)
        except Exception:
            logging.exception("coral33 bets mirror tick failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await snapshot_service.start()
        # SSE broadcaster — flush + heartbeat tasks run regardless of
        # cache mode (heartbeats keep idle connections alive even when
        # no upserts are happening; the flush loop is a no-op when the
        # dirty flag stays clear). Started here, cancelled below.
        import asyncio as _asyncio
        from .odds import events as _events
        sse_flush_task = _asyncio.create_task(_events.flush_loop())
        sse_heartbeat_task = _asyncio.create_task(_events.heartbeat_loop())

        # OddsCache version-bump debounce loop. WS upserts (Kalshi +
        # Polymarket) call _bump_version() per row, which used to blow
        # up the scanner memos hundreds of times/min during live games.
        # This loop coalesces bumps into one version change per 200ms
        # window so the scanner memo's cache-version fingerprint holds.
        # Runs regardless of cache mode — harmless when no upserts
        # happen, no-op when the dirty flag stays clear.
        cache_version_flush_task = _asyncio.create_task(cache.version_flush_loop())
        mapping_health_task = _asyncio.create_task(mapping_health.run(
            cache,
            snapshot_rows=lambda: (
                snapshot_service.current.rows
                if snapshot_service.current is not None else None
            ),
        ))
        from . import loop_watchdog
        loop_watchdog_task = _asyncio.create_task(loop_watchdog.run())

        # cache_mode is the single source of truth for whether fetchers run.
        # LIVE → both fetchers up. LATEST / SNAPSHOT → both off, serving the
        # frozen snapshot file. The user toggling cache mode in the UI IS the
        # approval to spend Odds API budget; no separate FETCHER_ENABLED gate.
        # ODDS_API_KEY and coral33 credentials are still required as
        # capability checks — without them the fetcher physically can't run.
        if initial_mode == CacheMode.LIVE:
            # ODDS_API_FETCHER_ENABLED ANDs with the cache_mode condition
            # above: it can only ever SUPPRESS the Odds API fetcher, never
            # start one cache_mode wouldn't have. Scoped to this fetcher
            # alone — coral33 / kalshi / polymarket below are unaffected,
            # as are the CLV scheduler and the accounts scraper.
            if not config.odds_api_fetcher_enabled:
                logging.info(
                    "odds api fetcher disabled via ODDS_API_FETCHER_ENABLED "
                    "— reads come from ODDS_SOURCE=%s. coral33/kalshi/"
                    "polymarket fetchers are unaffected.",
                    config.odds_source,
                )
            elif not config.odds_api_key:
                logging.warning("cache_mode=live but ODDS_API_KEY not set — Odds API fetcher off")
            else:
                fetcher.start_all()

            if config.coral33_enabled:
                if config.coral33_customer_id and config.coral33_password:
                    coral33_fetcher.start_all()
                else:
                    logging.warning("CORAL33_ENABLED=true but credentials missing — skipping")
            else:
                logging.info("coral33 fetcher disabled (CORAL33_ENABLED=false)")

            # Kalshi has no credentials / no env-gate — its read endpoints
            # are public and free. Always start in LIVE mode so the
            # direct-fetched kalshi rows are fresh while Odds API's
            # 5-min-stale kalshi rows are suppressed in normalize.py.
            kalshi_fetcher.start_all()

            # Polymarket is also public/no-auth. Always start in LIVE.
            polymarket_fetcher.start_all()

            # Novig is public/no-auth and free (no Odds API spend).
            if novig_enabled:
                novig_fetcher.start_all()
            else:
                logging.info("novig fetcher disabled (NOVIG_FETCHER_ENABLED=false)")

            # Stagger the 60s jobs so they do not fire on the same wall-clock
            # second and spike the event loop's I/O queue. APScheduler keeps
            # each offset via the next_run_time anchor + fixed interval.
            now_utc = _dt.now(_tz.utc)

            # CLV capture only runs in LIVE — there's no point devigging
            # the frozen SNAPSHOT cache (would just freeze a single
            # closing-line snapshot to whatever the snapshot file says).
            clv_scheduler.add_job(
                _capture_tick,
                trigger="interval",
                seconds=60,
                next_run_time=now_utc,  # T+0s — stagger anchor
                id="clv_capture",
                replace_existing=True,
                max_instances=1,
            )

            # Shared row-level TTL sweep — replaces the per-fetcher
            # `purge_stale_rows` calls that previously ran from both the
            # Odds API fetcher (~13 sports) and the coral33 fetcher (~7
            # sports). One scan/min instead of 20+. Offset by 10s so it
            # doesn't compete with the 0/20/40 stagger trio for the same
            # loop slot.
            clv_scheduler.add_job(
                _purge_stale_rows_tick,
                trigger="interval",
                seconds=60,
                next_run_time=now_utc + _td(seconds=10),
                id="purge_stale_rows",
                replace_existing=True,
                max_instances=1,
            )
            # Wager-log auto-refresh — also LIVE-only since it hits
            # Coral33's API. Without this, the /bets endpoint serves
            # whatever was on disk from the last manual force-refresh,
            # which goes stale within hours of new bet placement.
            clv_scheduler.add_job(
                _wager_log_refresh_tick,
                trigger="interval",
                minutes=30,
                id="wager_log_refresh",
                replace_existing=True,
                max_instances=1,
            )

            # Kalshi portfolio sync — pulls auth'd fills into the bets
            # table. 5-min cadence. No-op when Kalshi auth isn't set.
            async def _kalshi_portfolio_tick():
                try:
                    if not kalshi_fetcher.client.is_authenticated:
                        return
                    from .odds.books.kalshi.portfolio_sync import sync_kalshi_fills
                    await sync_kalshi_fills(client=kalshi_fetcher.client, cache=cache)
                except Exception:
                    logging.exception("kalshi portfolio sync tick failed")

            clv_scheduler.add_job(
                _kalshi_portfolio_tick,
                trigger="interval", minutes=5,
                id="kalshi_portfolio_sync",
                replace_existing=True, max_instances=1,
            )

            # Kalshi orderbook depth poll — pulls top-of-book size for
            # registered sports markets so the arb scanner can clamp
            # stake recommendations to fillable depth. 60s cadence.
            async def _kalshi_orderbook_tick():
                try:
                    if not kalshi_fetcher.client.is_authenticated:
                        return
                    from .odds.books.kalshi.orderbook_poller import poll_kalshi_orderbooks
                    if kalshi_fetcher._ingestor is None:
                        return
                    await poll_kalshi_orderbooks(
                        client=kalshi_fetcher.client,
                        ingestor=kalshi_fetcher._ingestor,
                        cache=cache,
                    )
                except Exception:
                    logging.exception("kalshi orderbook poll tick failed")

            clv_scheduler.add_job(
                _kalshi_orderbook_tick,
                trigger="interval", seconds=60,
                next_run_time=now_utc + _td(seconds=20),  # T+20s stagger
                id="kalshi_orderbook_poll",
                replace_existing=True, max_instances=1,
            )

            # Polymarket trade sync — wallet-keyed, no auth needed.
            # Wallet address is read directly from user_settings.json under
            # `polymarket_wallet_address`. Not yet in the UserSettings
            # dataclass — bypass and read the JSON file to avoid a schema
            # migration just for one optional field.
            async def _polymarket_portfolio_tick():
                try:
                    import json
                    from .user_settings import SETTINGS_PATH
                    try:
                        with open(SETTINGS_PATH, "r") as fh:
                            wallet = json.load(fh).get("polymarket_wallet_address", "") or ""
                    except (FileNotFoundError, json.JSONDecodeError):
                        wallet = ""
                    if not wallet:
                        return
                    from .odds.books.polymarket.portfolio_sync import sync_polymarket_trades
                    await sync_polymarket_trades(
                        client=polymarket_fetcher.client,
                        cache=cache,
                        wallet_address=wallet,
                    )
                except Exception:
                    logging.exception("polymarket portfolio sync tick failed")

            clv_scheduler.add_job(
                _polymarket_portfolio_tick,
                trigger="interval", minutes=5,
                id="polymarket_portfolio_sync",
                replace_existing=True, max_instances=1,
            )

            # closing_lines TTL purge — the closing_lines table was 62%
            # of cache.db with no expiry mechanism. Daily, 90-day cutoff
            # keeps recent CLV analysis intact; older bets in the `bets`
            # table will report "CLV unavailable" once their closing
            # lines drop out, which is acceptable. `coalesce=True` +
            # `jitter` smooth out post-resume catch-up; `max_instances=1`
            # prevents overlap if a purge somehow runs long.
            clv_scheduler.add_job(
                lambda: cache.purge_closing_lines_older_than(days=90),
                trigger="interval", hours=24,
                id="closing_lines_purge",
                replace_existing=True, coalesce=True,
                max_instances=1, jitter=600,
            )

            clv_scheduler.start()
            logging.info(
                "CLV capture (60s, T+0) + purge_stale_rows (60s, T+10) "
                "+ wager-log refresh (30min) "
                "+ kalshi/polymarket portfolio sync (5min) "
                "+ kalshi orderbook depth poll (60s, T+20) schedulers started"
            )
        else:
            logging.info(
                "cache_mode=%s — fetchers stopped, serving %s",
                initial_mode.value, cache.path.name,
            )

        yield
        await snapshot_service.stop()
        # Cancel SSE background loops first — they don't depend on any
        # other resource and stopping them lets connected browsers see
        # a clean close. The cache version flush loop sits in the same
        # bucket — no external dependencies, cancel-clean.
        sse_flush_task.cancel()
        sse_heartbeat_task.cancel()
        cache_version_flush_task.cancel()
        mapping_health_task.cancel()
        loop_watchdog_task.cancel()
        for t in (sse_flush_task, sse_heartbeat_task, cache_version_flush_task, mapping_health_task, loop_watchdog_task):
            try:
                await t
            except (asyncio.CancelledError, BaseException):
                pass

        try:
            if clv_scheduler.running:
                clv_scheduler.shutdown(wait=False)
        except Exception:
            logging.exception("CLV scheduler shutdown failed")
        coral33_fetcher.shutdown()
        kalshi_fetcher.shutdown()
        polymarket_fetcher.shutdown()
        novig_fetcher.shutdown()
        fetcher.shutdown()
        # Release the persistent Odds API HTTP/2 connection pool so the
        # shutdown banner doesn't pollute logs with "unclosed AsyncClient".
        try:
            await client.aclose()
        except Exception:
            logging.exception("OddsAPIClient.aclose failed during shutdown")

    app = FastAPI(title="Betting Site API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    from .api.health import build_router as health_router
    from .api.odds import build_router as odds_router
    from .api.props import build_router as props_router
    from .api.fetcher_ctl import build_router as fetcher_ctl_router
    from .api.refresh import build_router as refresh_router
    from .api.sports import build_router as sports_router
    from .api.arbitrage import build_router as arbitrage_router
    from .api.dashboard import build_router as dashboard_router
    from .api.low_hold import build_router as low_hold_router
    from .api.free_bets import build_router as free_bets_router
    from .api.ev import build_router as ev_router
    from .api.profit_boost import build_router as profit_boost_router
    from .api.coral33_ctl import build_router as coral33_ctl_router
    from .api.coral33_accounts import build_router as coral33_accounts_router
    from .api.kalshi_ctl import build_router as kalshi_ctl_router
    from .api.polymarket_ctl import build_router as polymarket_ctl_router
    from .api.novig_ctl import build_router as novig_ctl_router
    from .api.cache_mode import build_router as cache_mode_router
    from .api.settings import build_router as settings_router
    from .api.stream import build_router as stream_router
    from .api.bets import build_router as bets_router
    from .api.systems import build_router as systems_router

    app.include_router(stream_router())
    app.include_router(bets_router(cache))
    app.include_router(systems_router(cache, snapshot_service=snapshot_service))
    app.include_router(health_router(cache, fetcher))

    @app.get("/api/mapping-health")
    def get_mapping_health():
        return mapping_health.listing()
    app.include_router(odds_router(cache, snapshot_service))
    app.include_router(props_router(cache))
    app.include_router(fetcher_ctl_router(fetcher, mode_store))
    app.include_router(refresh_router(fetcher))
    app.include_router(sports_router(settings_store))
    app.include_router(arbitrage_router(cache, snapshot_service))
    app.include_router(low_hold_router(cache, snapshot_service))
    app.include_router(free_bets_router(cache, snapshot_service))
    app.include_router(ev_router(cache, snapshot_service))
    app.include_router(profit_boost_router(cache, snapshot_service))
    app.include_router(coral33_ctl_router(coral33_fetcher))
    app.include_router(
        coral33_accounts_router(accounts_scraper, cache=cache, odds_client=client)
    )
    app.include_router(kalshi_ctl_router(kalshi_fetcher))
    app.include_router(polymarket_ctl_router(polymarket_fetcher))
    app.include_router(novig_ctl_router(novig_fetcher, snapshot_service))
    app.include_router(
        cache_mode_router(
            mode_store, cache, live_cache_path, snapshot_cache_path,
            fetcher, coral33_fetcher,
            clv_scheduler=clv_scheduler,
            clv_capture_tick=_capture_tick,
            wager_log_refresh_tick=_wager_log_refresh_tick,
            kalshi_fetcher=kalshi_fetcher,
            polymarket_fetcher=polymarket_fetcher,
            novig_fetcher=novig_fetcher if novig_enabled else None,
        )
    )
    app.include_router(settings_router(settings_store, fetcher, sports))
    app.include_router(
        dashboard_router(cache, fetcher, sports, snapshot_service=snapshot_service)
    )

    return app


app = create_app()
