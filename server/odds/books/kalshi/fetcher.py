from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ...cache import OddsCache
from .client import KalshiAPIError, KalshiClient
from .event_matcher import KalshiEventMatcher
from .mapping import KalshiConfig, KalshiSportConfig, load_kalshi_config
from .normalizer import normalize_markets
from .ws_client import KalshiWSClient, KalshiWSError
from .ws_ingest import KalshiTickerIngestor


logger = logging.getLogger(__name__)


# REST safety-net cadence. Now that WS handles real-time ticker updates
# (~sub-second), REST exists only to:
#   1. Discover NEW markets that come online (new games posted)
#   2. Refresh NO-side prices for spread/total/team_total markets (ticker
#      channel only carries yes_ask, not no_ask)
#   3. Recover from a WS disconnect window
# 60s is plenty — increase if hitting rate limits, decrease if NO-side
# alt-line prices drift too far.
CYCLE_INTERVAL = int(os.environ.get("KALSHI_CYCLE_SECONDS", "60"))
CYCLE_JITTER   = int(os.environ.get("KALSHI_CYCLE_JITTER", "10"))

# Per-sport startup stagger so we don't fire all 4 sport jobs in the same
# wallclock second on boot.
_STARTUP_STAGGER = (0, max(2, min(15, CYCLE_INTERVAL)))

# Gap between consecutive series fetches WITHIN a sport's cycle. Prevents
# bursting all N series of a sport simultaneously, which 429s Kalshi even
# with auth. 0.5s × ~10 series (NBA worst case) = 5s of paced calls, well
# under the 15s cycle ceiling.
_INTER_SERIES_GAP_S = float(os.environ.get("KALSHI_INTER_SERIES_GAP_S", "0.5"))


def _all_series_for_sport(sc: KalshiSportConfig) -> list[str]:
    """Concatenate every series-list slot for a sport into a single ordered
    list (de-duplicated; order = main, spread, total, team_total, period,
    rfi, f5_winner). The fetcher loops this list per cycle, calling the
    normalizer per-series — dispatching to the right per-market handler
    via SERIES_TO_SPORT_MARKET.
    """
    out: list[str] = []
    seen: set[str] = set()
    for chunk in (
        sc.series_main, sc.series_spread, sc.series_total,
        sc.series_team_total, sc.series_period, sc.series_rfi,
        sc.series_f5_winner,
    ):
        for s in chunk:
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    return out


class KalshiFetcher:
    """Per-sport poller for Kalshi's public REST API.

    Mirrors `Coral33Fetcher`'s lifecycle (start_all / stop_all / shutdown +
    APScheduler-driven jobs + per-cycle status tracking) so cache_mode.py
    can flip both fetchers identically. Differences from coral33:

      - No auth. No JWT refresh. No captcha back-off.
      - Cadence ~15s (vs coral33's 60s) — public API is free.
      - One HTTP call per sport per cycle (vs coral33's main/alt/prop tiers).
      - Phase 1: h2h only. Phase 2 will fan out into multiple series per
        sport (spreads, totals, team_totals, periods, NRFI, F5) — the
        config schema already carries empty stub lists for those.
    """

    def __init__(
        self,
        cache: OddsCache,
        config_path: Path,
        api_key: str | None = None,
        private_key_path: Path | None = None,
    ):
        self.cache = cache
        self.config_path = config_path
        # When auth creds are provided, every request is signed — unlocks
        # higher rate limits and the portfolio endpoints. Unauthed reads
        # still work without them, so missing creds don't break the
        # public-data fetch.
        self.client = KalshiClient(
            api_key=api_key,
            private_key_path=private_key_path,
        )
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._config: KalshiConfig | None = None
        # Observability for the Settings / manual-refresh UI.
        self._last_cycle_at: datetime | None = None
        self._last_cycle_rows: dict[str, int] = {}   # sport → row count

        # WebSocket stack: enabled when both credentials are present (the
        # WS auth scheme uses the same RSA signing as REST). Unauth WS
        # works for /ticker, but anonymous connections get rate-limited
        # aggressively — keep WS off unless we can sign.
        self._ws_enabled = bool(api_key and private_key_path)
        self._ingestor: KalshiTickerIngestor | None = (
            KalshiTickerIngestor(cache) if self._ws_enabled else None
        )
        self._ws_client: KalshiWSClient | None = (
            KalshiWSClient(api_key=api_key, private_key_path=private_key_path)
            if self._ws_enabled and api_key and private_key_path
            else None
        )
        self._ws_task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def _load_config(self) -> KalshiConfig:
        if self._config is None:
            self._config = load_kalshi_config(self.config_path)
        return self._config

    def _matcher(self) -> KalshiEventMatcher:
        cfg = self._load_config()

        def events_for(sport_key: str) -> list[dict]:
            return self.cache.distinct_events(sport_key=sport_key)

        return KalshiEventMatcher(events_for, team_aliases=cfg.team_aliases)

    def start_all(self) -> dict:
        if self._running:
            return {"status": "already_running"}
        self._config = None  # pick up TOML edits across restarts
        cfg = self._load_config()
        if not cfg.sports:
            return {"status": "no_sports_configured"}

        now = datetime.now(timezone.utc)
        scheduled: list[str] = []
        for sport_key, sc in cfg.sports.items():
            # A sport is "configured" if it has at least one series in any
            # of the per-market-type slots. Phase 1 required series_main;
            # Phase 2 may legitimately have empty series_main (off-season)
            # while still having alt-line series populated.
            if not _all_series_for_sport(sc):
                continue
            first_fire = now + timedelta(seconds=random.uniform(*_STARTUP_STAGGER))
            self.scheduler.add_job(
                self._sport_cycle_runner(sport_key),
                trigger="interval",
                seconds=CYCLE_INTERVAL,
                jitter=CYCLE_JITTER,
                next_run_time=first_fire,
                id=f"kalshi:{sport_key}",
                replace_existing=True,
                max_instances=1,
            )
            scheduled.append(sport_key)

        if not self.scheduler.running:
            self.scheduler.start()
        self._running = True

        # Spin up the WS task — runs alongside the REST scheduler. WS
        # delivers sub-second price updates; REST is the safety net for
        # discovery + NO-side prices. We start WS AFTER the REST
        # scheduler so the first cycle has time to populate the ingestor
        # with templates before the first ticker batch arrives.
        if self._ws_enabled and self._ws_client is not None:
            self._ws_task = asyncio.create_task(self._run_ws_consumer())

        logger.info(
            "kalshi fetcher started: %d sports (REST cycle %ds ±%ds, WS=%s)",
            len(scheduled), CYCLE_INTERVAL, CYCLE_JITTER,
            "on" if self._ws_enabled else "off",
        )
        return {"status": "started", "sports": scheduled}

    @property
    def status(self) -> dict:
        """Snapshot of fetcher health for the UI. Mirrors coral33's status
        shape (so the frontend can poll both endpoints with the same
        component). `jwt_authenticated` is True-by-fiat — Kalshi reads are
        unauthenticated, but we keep the field so any UI that displays an
        "auth" badge for coral33 also shows green for kalshi."""
        out = {
            "running": self._running,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "last_cycle_rows": dict(self._last_cycle_rows),
            "jwt_authenticated": True,
        }
        # WS health is the more interesting freshness signal now — surface
        # it so the UI / debugging can see real-time stream state.
        if self._ws_client is not None:
            out.update(self._ws_client.status())
        if self._ingestor is not None:
            out.update(self._ingestor.status())
        return out

    def registered_tickers(self) -> list[str]:
        """Market_tickers currently in the ingestor's template map.
        Empty list if the ingestor hasn't been initialized yet (e.g.
        before start_all()). Used by the orderbook poller."""
        if self._ingestor is None:
            return []
        return self._ingestor.registered_tickers()

    def _smart_match_event(self, matcher):
        """M3: build a match_event callable that prefers multi-anchor
        scan when the normalizer signals a date-only ticker (via the
        wide _DATE_ONLY_MATCH_WINDOW_MIN). Falls back to the existing
        single-anchor wide-window match() if no anchor hits.
        """
        from datetime import datetime as _dt, timezone as _tz
        from zoneinfo import ZoneInfo
        from .._anchor_table import anchors_for_sport, TIGHT_WINDOW_MIN
        from .normalizer import _DATE_ONLY_MATCH_WINDOW_MIN
        _ET = ZoneInfo("America/New_York")

        def _match(sport_k: str, home: str, away: str, anchor, window_minutes=None):
            if window_minutes == _DATE_ONLY_MATCH_WINDOW_MIN:
                anchor_et = anchor.astimezone(_ET) if anchor.tzinfo else anchor
                candidates = [
                    _dt(anchor_et.year, anchor_et.month, anchor_et.day, h, m,
                        tzinfo=_ET).astimezone(_tz.utc)
                    for h, m in anchors_for_sport(sport_k)
                ]
                tight = matcher.match_multi_anchor(
                    sport_k, home, away, candidates,
                    tight_window_min=TIGHT_WINDOW_MIN,
                )
                if tight is not None:
                    return tight
            return matcher.match(
                sport_k, home, away, anchor, window_minutes=window_minutes,
            )

        return _match

    def stop_all(self) -> dict:
        if not self._running:
            return {"status": "already_stopped"}
        try:
            self.scheduler.remove_all_jobs()
        except Exception:
            logger.exception("kalshi: error removing jobs")
        # Stop the WS consumer too. We cancel the task; the WSClient's
        # `_stop` flag is checked at the next reconnect boundary, but
        # cancel forces immediate teardown.
        if self._ws_client is not None:
            self._ws_client.stop()
        if self._ws_task is not None and not self._ws_task.done():
            self._ws_task.cancel()
            self._ws_task = None
        self._running = False
        logger.info("kalshi fetcher stopped")
        return {"status": "stopped"}

    async def _run_ws_consumer(self) -> None:
        """Background task consuming the WebSocket ticker stream. Wraps
        the auto-reconnecting iterator from KalshiWSClient and routes
        each ticker message through the ingestor.

        Errors:
          - KalshiWSError (e.g. auth failure) → log + exit; REST keeps
            running as fallback.
          - Cancelled (stop_all called) → exit cleanly.
          - Unexpected → log + exit; REST fallback.
        """
        if self._ws_client is None or self._ingestor is None:
            return
        try:
            async for msg in self._ws_client.ticker_messages():
                try:
                    self._ingestor.process_ticker(msg)
                except Exception:
                    logger.exception("kalshi WS: process_ticker failed")
        except asyncio.CancelledError:
            logger.info("kalshi WS consumer cancelled")
            raise
        except KalshiWSError as e:
            logger.error(
                "kalshi WS consumer terminated (REST fallback only): %s", e,
            )
        except Exception:
            logger.exception(
                "kalshi WS consumer crashed (REST fallback only)",
            )

    def shutdown(self) -> None:
        try:
            self.stop_all()
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass
        # Drop the HTTP client too so we don't leak a connection pool on
        # process exit.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.client.aclose())
            else:
                loop.run_until_complete(self.client.aclose())
        except Exception:
            pass

    # ---------- Sport-cycle runner ----------

    def _sport_cycle_runner(self, sport_key: str):
        async def run():
            await self._run_sport_cycle(sport_key)
        return run

    async def _run_sport_cycle(self, sport_key: str) -> None:
        cfg = self._load_config()
        sport_cfg = cfg.sports.get(sport_key)
        if sport_cfg is None:
            return
        all_series = _all_series_for_sport(sport_cfg)
        if not all_series:
            return

        now = datetime.now(timezone.utc)
        # Live-game purge: Kalshi keeps trading after kickoff (their YES/NO
        # lifecycle is post-tip-off-trading-allowed). Mirror coral33's
        # behavior and drop rows for games that have started — our sharp-
        # devig model isn't calibrated against in-play prices.
        purged = self.cache.purge_live_rows_for_book("kalshi", now)
        if purged:
            logger.info("kalshi %s: purged %d live rows", sport_key, purged)

        matcher = self._matcher()
        total_rows = 0

        # Phase 2: iterate ALL series slots (main + spread + total +
        # team_total + period + rfi + f5_winner). The normalizer dispatches
        # on market_key resolved from SERIES_TO_SPORT_MARKET.
        #
        # Inter-series pacing: even with auth, Kalshi 429s when we burst
        # all N series at cycle start (NBA has 10 series, which → 10
        # concurrent requests in a few hundred ms). 0.5s gap spreads the
        # burst across most of the 15s cycle window. With pagination,
        # net per-cycle elapsed ≈ N × (0.5s + ~150ms request) =
        # 6.5s for NBA, well under the 15s ceiling.
        for i, series_ticker in enumerate(all_series):
            if i > 0:
                await asyncio.sleep(_INTER_SERIES_GAP_S)
            markets = await self._safe_list_markets(series_ticker, sport_key)
            if markets is None:
                continue
            rows = normalize_markets(
                markets,
                series_ticker=series_ticker,
                fetched_at=now,
                match_event=self._smart_match_event(matcher),
            )
            if rows:
                self.cache.upsert(rows)
                total_rows += len(rows)
                # Hand the normalized rows to the WS ingestor so it knows
                # which market_tickers map to which cache-row templates.
                # On the next ticker message for these markets, the
                # ingestor will mutate price + fetched_at and upsert
                # without waiting for the next REST cycle.
                if self._ingestor is not None:
                    self._ingestor.register_rows(rows)

        self._last_cycle_at = now
        self._last_cycle_rows[sport_key] = total_rows

    async def _safe_list_markets(
        self, series_ticker: str, sport_key: str,
    ) -> list[dict] | None:
        try:
            return await self.client.list_markets(series_ticker)
        except KalshiAPIError as e:
            logger.warning(
                "kalshi %s %s: %s",
                sport_key, series_ticker, e,
            )
            return None

    async def refresh_now(self, sport_keys: list[str] | None = None) -> dict:
        """Trigger an immediate cycle for the given sports (or all configured
        sports if None). Sports run in parallel. Mirror of
        Coral33Fetcher.refresh_now for UI-button parity."""
        cfg = self._load_config()
        targets = sport_keys or list(cfg.sports.keys())
        t0 = datetime.now(timezone.utc)
        results = await asyncio.gather(
            *(self._run_sport_cycle(s) for s in targets if s in cfg.sports),
            return_exceptions=True,
        )
        errors = [str(r) for r in results if isinstance(r, Exception)]
        duration = (datetime.now(timezone.utc) - t0).total_seconds()
        return {
            "status": "ok" if not errors else "partial",
            "sports_refreshed": targets,
            "duration_s": round(duration, 2),
            "errors": errors,
            "last_cycle_rows": dict(self._last_cycle_rows),
        }
