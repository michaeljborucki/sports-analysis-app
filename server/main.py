from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Config
from .odds.books.coral33 import Coral33Fetcher
from .odds.cache import OddsCache
from .odds.client import OddsAPIClient
from .odds.fetcher import FetcherRegistry
from .picks.reader import PicksReader
from .sports import all_sports
from .user_settings import UserSettingsStore


logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    config = Config.from_env()
    cache = OddsCache(config.cache_db)
    cache.init()
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

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not config.fetcher_enabled:
            logging.warning(
                "FETCHER_ENABLED=false — serving frozen cache. "
                "POST /api/fetcher/start to enable at runtime."
            )
        elif not config.odds_api_key:
            logging.warning("ODDS_API_KEY not set — fetcher disabled")
        else:
            fetcher.start_all()

        if config.coral33_enabled:
            if config.coral33_customer_id and config.coral33_password:
                coral33_fetcher.start_all()
            else:
                logging.warning("CORAL33_ENABLED=true but credentials missing — skipping")
        else:
            logging.info("coral33 fetcher disabled (CORAL33_ENABLED=false)")

        yield
        coral33_fetcher.shutdown()
        fetcher.shutdown()

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
    from .api.settings import build_router as settings_router

    app.include_router(health_router(cache, fetcher))
    app.include_router(odds_router(cache))
    app.include_router(props_router(cache))
    app.include_router(
        picks_router(picks_readers, date_override=config.picks_date_override)
    )
    app.include_router(fetcher_ctl_router(fetcher))
    app.include_router(refresh_router(fetcher))
    app.include_router(sports_router(settings_store))
    app.include_router(arbitrage_router(cache))
    app.include_router(low_hold_router(cache))
    app.include_router(free_bets_router(cache))
    app.include_router(ev_router(cache))
    app.include_router(settings_router(settings_store, fetcher, sports))
    app.include_router(
        dashboard_router(
            cache, fetcher, picks_readers, sports,
            picks_date_override=config.picks_date_override,
        )
    )

    return app


app = create_app()
