from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Config
from .odds.cache import OddsCache
from .odds.client import OddsAPIClient
from .odds.fetcher import FetcherRegistry
from .odds.market_config import MarketConfig
from .picks.reader import PicksReader


logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    config = Config.from_env()
    cache = OddsCache(config.cache_db)
    cache.init()
    client = OddsAPIClient(api_key=config.odds_api_key)
    market_cfg = MarketConfig.load()
    fetcher = FetcherRegistry(config, market_cfg, cache, client)
    picks_reader = PicksReader(
        bet_card_dir=config.bet_card_dir,
        bets_csv=config.bets_csv,
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
        yield
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

    app.include_router(health_router(cache, fetcher))
    app.include_router(odds_router(cache))
    app.include_router(props_router(cache))
    app.include_router(
        picks_router(picks_reader, date_override=config.picks_date_override)
    )
    app.include_router(fetcher_ctl_router(fetcher))
    app.include_router(refresh_router(fetcher))

    return app


app = create_app()
