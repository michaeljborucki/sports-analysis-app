from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Config
from .odds.books.coral33 import Coral33Fetcher
from .odds.books.coral33.accounts import AccountsScraper
from .odds.books.kalshi import KalshiFetcher
from .odds.cache import OddsCache
from .odds.cache_mode import CacheMode, CacheModeStore
from .odds.client import OddsAPIClient
from .odds.clv_capture import capture_closing_lines
from .odds.fetcher import FetcherRegistry
from .picks.reader import PicksReader
from .sports import all_sports
from .user_settings import UserSettingsStore


logging.basicConfig(level=logging.INFO)


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
    cache.init()
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
    # (which are 2-5min stale) with a ~15s direct poll. No auth, no key.
    # Lifecycle parallels coral33_fetcher: start in LIVE, stop in
    # LATEST/SNAPSHOT, shut down on app exit.
    kalshi_fetcher = KalshiFetcher(
        cache=cache,
        config_path=_Path(__file__).parent / "config" / "kalshi.toml",
    )
    # Multi-account roll-up scraper (Accounts page). Reads CORAL33_ACCOUNTS
    # env (JSON list) or falls back to the single-account env pair. The
    # cache reference lets the scraper persist balance_snapshots on every
    # refresh, populating the daily-chart's pending overlay automatically.
    accounts_scraper = AccountsScraper(cache=cache)

    from .odds.market_config import MarketConfig
    picks_readers: dict[str, PicksReader] = {}
    for sp in sports:
        try:
            mc = MarketConfig.load(sp.markets_config)
            include = mc.picks.include_bet_types
        except Exception:
            logging.warning("Failed to load picks config for %s", sp.key)
            include = ()
        picks_readers[sp.key] = PicksReader(
            bet_card_dir=sp.agent_dir,
            bets_csv=sp.agent_dir / "bets.csv",
            agent_key=sp.agent_dir.parent.name,
            include_bet_types=include,
        )

    # Closing-line capture scheduler. Runs every 60s in LIVE mode and
    # walks events whose commence_time is in T-15..T-5; each pass devigs
    # the sharp-book consensus from odds_snapshot and writes one
    # closing_lines row per outcome. The job is idempotent on the PK, so
    # re-captures within the window overwrite with the latest fair line.
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from datetime import datetime as _dt, timezone as _tz
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

    async def _wager_log_refresh_tick():
        """Re-pull the wager log so newly-placed bets appear without the
        user having to hit ?force_wager_log=true. Coral33's wager-log
        endpoint costs ~14 calls per account per refresh; 8 accounts ×
        30-min cadence = 224 calls/hour, well under their rate limit.
        Settled wagers are immutable so re-pulling is cheap on the
        persistence side (JSON overwrite)."""
        try:
            await accounts_scraper.get_wager_log(force=True)
        except Exception:
            logging.exception("wager-log refresh tick failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # cache_mode is the single source of truth for whether fetchers run.
        # LIVE → both fetchers up. LATEST / SNAPSHOT → both off, serving the
        # frozen snapshot file. The user toggling cache mode in the UI IS the
        # approval to spend Odds API budget; no separate FETCHER_ENABLED gate.
        # ODDS_API_KEY and coral33 credentials are still required as
        # capability checks — without them the fetcher physically can't run.
        if initial_mode == CacheMode.LIVE:
            if not config.odds_api_key:
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

            # CLV capture only runs in LIVE — there's no point devigging
            # the frozen SNAPSHOT cache (would just freeze a single
            # closing-line snapshot to whatever the snapshot file says).
            clv_scheduler.add_job(
                _capture_tick,
                trigger="interval",
                seconds=60,
                id="clv_capture",
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
            clv_scheduler.start()
            logging.info(
                "CLV capture (60s) + wager-log refresh (30min) "
                "schedulers started"
            )
        else:
            logging.info(
                "cache_mode=%s — fetchers stopped, serving %s",
                initial_mode.value, cache.path.name,
            )

        yield
        try:
            if clv_scheduler.running:
                clv_scheduler.shutdown(wait=False)
        except Exception:
            logging.exception("CLV scheduler shutdown failed")
        coral33_fetcher.shutdown()
        kalshi_fetcher.shutdown()
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
    from .api.picks import build_router as picks_router
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
    from .api.cache_mode import build_router as cache_mode_router
    from .api.settings import build_router as settings_router

    app.include_router(health_router(cache, fetcher))
    app.include_router(odds_router(cache))
    app.include_router(props_router(cache))
    app.include_router(
        picks_router(picks_readers, date_override=config.picks_date_override)
    )
    app.include_router(fetcher_ctl_router(fetcher, mode_store))
    app.include_router(refresh_router(fetcher))
    app.include_router(sports_router(settings_store))
    app.include_router(arbitrage_router(cache))
    app.include_router(low_hold_router(cache))
    app.include_router(free_bets_router(cache))
    app.include_router(ev_router(cache))
    app.include_router(profit_boost_router(cache))
    app.include_router(coral33_ctl_router(coral33_fetcher))
    app.include_router(
        coral33_accounts_router(accounts_scraper, cache=cache, odds_client=client)
    )
    app.include_router(kalshi_ctl_router(kalshi_fetcher))
    app.include_router(
        cache_mode_router(
            mode_store, cache, live_cache_path, snapshot_cache_path,
            fetcher, coral33_fetcher,
            clv_scheduler=clv_scheduler,
            clv_capture_tick=_capture_tick,
            wager_log_refresh_tick=_wager_log_refresh_tick,
            kalshi_fetcher=kalshi_fetcher,
        )
    )
    app.include_router(settings_router(settings_store, fetcher, sports))
    app.include_router(
        dashboard_router(
            cache, fetcher, picks_readers, sports,
            picks_date_override=config.picks_date_override,
        )
    )

    return app


app = create_app()
