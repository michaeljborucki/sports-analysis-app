from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Config
from .odds.cache import OddsCache
from .odds.client import OddsAPIClient
from .odds.fetcher import OddsFetcher
from .picks.reader import PicksReader


logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    config = Config.from_env()
    cache = OddsCache(config.cache_db)
    cache.init()
    client = OddsAPIClient(api_key=config.odds_api_key)
    fetcher = OddsFetcher(config, cache, client)
    picks_reader = PicksReader(
        bet_card_dir=config.bet_card_dir,
        bets_csv=config.bets_csv,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not config.fetcher_enabled:
            logging.warning(
                "FETCHER_ENABLED=false — serving frozen cache, no API polling"
            )
        elif not config.odds_api_key:
            logging.warning("ODDS_API_KEY not set — fetcher not started")
        else:
            fetcher.start()
        yield
        fetcher.stop()

    app = FastAPI(title="Betting Site API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    from .api.health import build_router as health_router
    from .api.odds import build_router as odds_router
    from .api.picks import build_router as picks_router

    app.include_router(health_router(cache))
    app.include_router(odds_router(cache))
    app.include_router(picks_router(picks_reader, date_override=config.picks_date_override))

    return app


app = create_app()
