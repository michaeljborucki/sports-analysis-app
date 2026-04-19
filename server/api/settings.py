from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..odds.fetcher import FetcherRegistry
from ..odds.market_config import MarketConfig
from ..sports import Sport
from ..user_settings import UserSettings, UserSettingsStore


logger = logging.getLogger(__name__)


class MarketOption(BaseModel):
    key: str                # Odds API market key (e.g., "h2h", "pitcher_strikeouts")
    enabled: bool


class TierOption(BaseModel):
    name: str                         # main / alternates / first_innings / player_props
    enabled_in_config: bool           # from markets.<sport>.toml
    interval_seconds: int
    markets: list[MarketOption]


class SportOption(BaseModel):
    key: str
    label: str
    enabled: bool                     # user-level enable
    tiers: list[TierOption]


class SettingsPayload(BaseModel):
    disabled_sports: list[str]
    disabled_markets: dict[str, list[str]]


class SettingsResponse(BaseModel):
    disabled_sports: list[str]
    disabled_markets: dict[str, list[str]]
    sports: list[SportOption]


class SettingsUpdateResponse(BaseModel):
    settings: SettingsResponse
    reload_status: str                # "not_running" | "started" | ...


def _build_response(
    settings: UserSettings, sports: list[Sport]
) -> SettingsResponse:
    sport_options: list[SportOption] = []
    for sport in sports:
        try:
            cfg = MarketConfig.load(sport.markets_config)
        except Exception:
            continue
        disabled_for_sport = settings.disabled_markets.get(sport.key, set())
        tier_options: list[TierOption] = []
        for tier_name, tier in cfg.tiers.items():
            tier_options.append(
                TierOption(
                    name=tier.name,
                    enabled_in_config=tier.enabled,
                    interval_seconds=tier.interval_seconds,
                    markets=[
                        MarketOption(key=m, enabled=m not in disabled_for_sport)
                        for m in tier.markets
                    ],
                )
            )
        sport_options.append(
            SportOption(
                key=sport.key,
                label=sport.label,
                enabled=settings.is_sport_enabled(sport.key),
                tiers=tier_options,
            )
        )
    return SettingsResponse(
        disabled_sports=sorted(settings.disabled_sports),
        disabled_markets={
            k: sorted(v) for k, v in settings.disabled_markets.items() if v
        },
        sports=sport_options,
    )


def build_router(
    store: UserSettingsStore,
    fetcher: FetcherRegistry,
    sports: list[Sport],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/settings", response_model=SettingsResponse)
    async def get_settings() -> SettingsResponse:
        return _build_response(store.get(), sports)

    @router.post("/api/settings", response_model=SettingsUpdateResponse)
    async def post_settings(
        payload: SettingsPayload,
    ) -> SettingsUpdateResponse:
        valid_sport_keys = {s.key for s in sports}
        unknown = [s for s in payload.disabled_sports if s not in valid_sport_keys]
        if unknown:
            raise HTTPException(400, f"Unknown sport(s): {unknown}")
        for sport_key in payload.disabled_markets:
            if sport_key not in valid_sport_keys:
                raise HTTPException(400, f"Unknown sport key: {sport_key}")

        new = UserSettings(
            disabled_sports=set(payload.disabled_sports),
            disabled_markets={
                k: set(v) for k, v in payload.disabled_markets.items()
            },
        )
        store.set(new)

        # Run hot_reload off the event loop so the scheduler's sync state
        # mutations don't serialize against the async response send. This
        # fires-and-completes; any exception is logged but doesn't fail
        # the request.
        was_running = fetcher.is_running
        status = "not_running"
        if was_running:
            try:
                await asyncio.to_thread(fetcher.hot_reload)
                status = "reloaded"
            except Exception:
                logger.exception("hot_reload failed")
                status = "reload_failed"

        return SettingsUpdateResponse(
            settings=_build_response(store.get(), sports),
            reload_status=status,
        )

    return router
