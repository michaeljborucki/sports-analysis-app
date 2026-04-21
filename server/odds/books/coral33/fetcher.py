from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ...cache import OddsCache
from .client import Coral33APIError, Coral33Client
from .event_matcher import Coral33EventMatcher
from .mapping import Coral33Config, load_coral33_config
from .normalizer import (
    _clean_team,
    _parse_coral_datetime,
    normalize_league_lines,
    normalize_player_props,
)


logger = logging.getLogger(__name__)


# One job per sport runs all three tiers (main → alt → prop) sequentially
# each cycle. This avoids hitting coral33 with overlapping requests, and
# guarantees the CorrelationID index is populated by main before props look
# it up.
CYCLE_INTERVAL = 240          # ~4 min average between full cycles per sport
CYCLE_JITTER   = 60           # actual fires land in 180–300s
CAPTCHA_BACKOFF = 300

# Different sports stagger their startup fire so all ~5 jobs don't hit
# coral33 simultaneously on boot.
_STARTUP_STAGGER = (0, 60)


class Coral33Fetcher:
    """Per-sport poller for coral33.com odds. Scoped to the same `OddsCache`
    used by the Odds API fetcher, so rows land alongside existing events under
    a shared event_id.

    Owned by main.create_app(); its start/stop lifecycle is independent of
    the Odds API `FetcherRegistry` so users can toggle it off via .env
    (`CORAL33_ENABLED=false`) without affecting the main fetcher.
    """

    def __init__(
        self,
        customer_id: str,
        password: str,
        cache: OddsCache,
        config_path: Path,
    ):
        self.customer_id = customer_id
        self.password = password
        self.cache = cache
        self.config_path = config_path
        self.client = Coral33Client(customer_id=customer_id, password=password)
        self.scheduler = AsyncIOScheduler()
        self._running = False
        self._config: Coral33Config | None = None
        self._captcha_until: float = 0.0  # epoch seconds
        # CorrelationID → {event_id, home_team, away_team, commence_time} —
        # populated on every main-tier "Game" tick; consumed by the prop tier
        # to map prop rows (which lack team info) back to the correct Odds
        # API event. CorrelationID is coral33's shared game identifier across
        # main + prop endpoints (format "{rot_num}-g").
        self._correlation_index: dict[str, dict] = {}
        # Observability for the Settings / manual-refresh UI.
        self._last_cycle_at: datetime | None = None
        self._last_cycle_rows: dict[str, int] = {}   # sport → row count

    @property
    def is_running(self) -> bool:
        return self._running

    def _load_config(self) -> Coral33Config:
        if self._config is None:
            self._config = load_coral33_config(self.config_path)
        return self._config

    def _matcher(self) -> Coral33EventMatcher:
        cfg = self._load_config()

        def events_for(sport_key: str) -> list[dict]:
            return self.cache.distinct_events(sport_key=sport_key)

        return Coral33EventMatcher(events_for, team_aliases=cfg.team_aliases)

    def start_all(self) -> dict:
        if self._running:
            return {"status": "already_running"}
        if not self.customer_id or not self.password:
            return {"status": "no_credentials"}
        self._config = None  # pick up TOML edits
        cfg = self._load_config()
        if not cfg.sports:
            return {"status": "no_sports_configured"}

        now = datetime.now(timezone.utc)

        for sport_key, sc in cfg.sports.items():
            if not (sc.subtypes_main or sc.subtypes_alt or sc.subtypes_prop):
                continue
            # One job per sport; the cycle runs main → alt → prop sequentially.
            first_fire = now + timedelta(seconds=random.uniform(*_STARTUP_STAGGER))
            self.scheduler.add_job(
                self._sport_cycle_runner(sport_key),
                trigger="interval",
                seconds=CYCLE_INTERVAL,
                jitter=CYCLE_JITTER,
                next_run_time=first_fire,
                id=f"coral33:{sport_key}",
                replace_existing=True,
                max_instances=1,
            )

        if not self.scheduler.running:
            self.scheduler.start()
        self._running = True
        logger.info(
            "coral33 fetcher started: %d sports (cycle %ds ±%ds)",
            len(cfg.sports), CYCLE_INTERVAL, CYCLE_JITTER,
        )
        return {"status": "started", "sports": list(cfg.sports.keys())}

    @property
    def status(self) -> dict:
        """Snapshot of fetcher health for the UI (last cycle time, captcha
        back-off, token state)."""
        import time as _time
        captcha_remaining = max(0, int(self._captcha_until - _time.time()))
        return {
            "running": self._running,
            "last_cycle_at": self._last_cycle_at.isoformat() if self._last_cycle_at else None,
            "last_cycle_rows": dict(self._last_cycle_rows),
            "captcha_backoff_remaining_s": captcha_remaining,
            "jwt_authenticated": self.client.is_authenticated,
        }

    def stop_all(self) -> dict:
        if not self._running:
            return {"status": "already_stopped"}
        try:
            self.scheduler.remove_all_jobs()
        except Exception:
            logger.exception("coral33: error removing jobs")
        self._running = False
        logger.info("coral33 fetcher stopped")
        return {"status": "stopped"}

    def shutdown(self) -> None:
        try:
            self.stop_all()
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass

    # ---------- Sport-cycle runner (main → alt → prop, serial) ----------

    def _sport_cycle_runner(self, sport_key: str):
        async def run():
            await self._run_sport_cycle(sport_key)
        return run

    async def _run_sport_cycle(self, sport_key: str) -> None:
        """Run a full coral33 cycle for one sport: main, then alt, then prop.

        Dependency map:
          - main  → depends only on Odds API events in cache (for team-name
                    matching). No coral33 state needed.
          - alt   → same — Odds API events only. Could technically run before
                    main without losing data, but we serialize for rate-limit
                    politeness and a more human-like request pattern.
          - prop  → DEPENDS ON main having populated `_correlation_index` this
                    cycle (or a prior one). Running prop before main on a
                    cold start orphans every row.
        """
        import time as _time
        if _time.time() < self._captcha_until:
            logger.info("coral33 %s: backing off (captcha)", sport_key)
            return

        cfg = self._load_config()
        sport_cfg = cfg.sports.get(sport_key)
        if sport_cfg is None:
            return

        now = datetime.now(timezone.utc)
        # Once-per-cycle cleanup of rows for games that have gone live since
        # we last pulled them. Done at the top of the cycle so all three tiers
        # write into a freshly-scrubbed slate.
        purged = self.cache.purge_live_rows_for_book("coral33", now)
        if purged:
            logger.info("coral33 %s: purged %d live rows", sport_key, purged)

        matcher = self._matcher()
        captcha_hit = False
        total_rows = 0

        async def pull_and_normalize(
            calls: list[tuple[str, str, str]],
            *, is_alt: bool,
            ingest_correlation: bool = False,
        ) -> int:
            nonlocal captcha_hit
            tier_rows = 0
            for sport_type, subtype, period in calls:
                try:
                    data = await self.client.get_league_lines(sport_type, subtype, period)
                except Coral33APIError as e:
                    logger.warning(
                        "coral33 %s %s/%s/%s: %s",
                        sport_key, sport_type, subtype, period, e,
                    )
                    continue
                if data.get("CaptchaRequired"):
                    captcha_hit = True
                    logger.warning(
                        "coral33 captcha on %s/%s/%s — backing off",
                        sport_type, subtype, period,
                    )
                    continue
                if ingest_correlation and period == "Game":
                    self._ingest_correlation_index(data, sport_key, matcher)
                rows = normalize_league_lines(
                    data, period=period, sport_key=sport_key,
                    fetched_at=now, match_event=matcher.match,
                    is_alternate=is_alt,
                )
                if rows:
                    self.cache.upsert(rows)
                    tier_rows += len(rows)
            return tier_rows

        # 1. Main always goes first — it populates _correlation_index on the
        # "Game" pull, which props need. Alt technically doesn't depend on
        # main but we run it after main anyway so main's cache writes land
        # before the second tier starts.
        main_rows = await pull_and_normalize(
            sport_cfg.main_period_calls,
            is_alt=False,
            ingest_correlation=True,
        )
        logger.info("coral33 %s main: %d rows", sport_key, main_rows)
        total_rows += main_rows

        # 2 & 3. Alt and prop run in random order — both fine to run second,
        # and shuffling on each cycle makes the outbound traffic pattern less
        # predictable (a little extra anti-fingerprint).
        secondary: list[tuple[str, callable]] = []
        if sport_cfg.alt_calls:
            async def run_alt() -> int:
                return await pull_and_normalize(sport_cfg.alt_calls, is_alt=True)
            secondary.append(("alt", run_alt))
        if sport_cfg.prop_calls:
            async def run_prop() -> int:
                return await self._pull_props(sport_cfg, sport_key, now)
            secondary.append(("prop", run_prop))
        random.shuffle(secondary)

        for label, runner in secondary:
            if captcha_hit:
                break
            tier_rows = await runner()
            logger.info("coral33 %s %s: %d rows", sport_key, label, tier_rows)
            total_rows += tier_rows

        if captcha_hit:
            self._captcha_until = _time.time() + CAPTCHA_BACKOFF

        self._last_cycle_at = now
        self._last_cycle_rows[sport_key] = total_rows

    def _ingest_correlation_index(
        self, data: dict, sport_key: str, matcher: Coral33EventMatcher,
    ) -> None:
        """Populate `_correlation_index[CorrelationID] = {event_id, home,
        away, commence}` from a main-tier Get_LeagueLines2 response. Props
        later look up by CorrelationID (shared parent-game identifier)."""
        for line in data.get("Lines") or []:
            cid = (line.get("CorrelationID") or "").strip()
            if not cid:
                continue
            team1 = _clean_team(line.get("Team1ID", ""))
            team2 = _clean_team(line.get("Team2ID", ""))
            if not team1 or not team2:
                continue
            try:
                commence = _parse_coral_datetime(line.get("GameDateTime", ""))
            except ValueError:
                continue
            # Same convention as the main normalizer: Team1=away, Team2=home
            event_id = matcher.match(sport_key, home=team2, away=team1, commence=commence)
            if event_id is None:
                continue
            self._correlation_index[cid] = {
                "event_id": event_id,
                "home_team": team2,
                "away_team": team1,
                "commence_time": commence,
            }

    async def _pull_props(self, sport_cfg, sport_key: str, now: datetime) -> int:
        def lookup(correlation_id):
            if not isinstance(correlation_id, str):
                return None
            return self._correlation_index.get(correlation_id)

        tier_rows = 0
        for sport_type, subtype, period in sport_cfg.prop_calls:
            try:
                data = await self.client.get_league_lines(sport_type, subtype, period)
            except Coral33APIError as e:
                logger.warning(
                    "coral33 %s prop %s/%s/%s: %s",
                    sport_key, sport_type, subtype, period, e,
                )
                continue
            if data.get("CaptchaRequired"):
                import time as _time
                self._captcha_until = _time.time() + CAPTCHA_BACKOFF
                logger.warning(
                    "coral33 captcha on %s/%s/%s (prop) — backing off",
                    sport_type, subtype, period,
                )
                continue
            rows = normalize_player_props(
                data, sport_key=sport_key, fetched_at=now,
                game_num_lookup=lookup,
            )
            if rows:
                self.cache.upsert(rows)
                tier_rows += len(rows)
        return tier_rows

    async def refresh_now(self, sport_keys: list[str] | None = None) -> dict:
        """Trigger an immediate cycle for the given sports (or all configured
        sports if None). Sports run in parallel; tiers within a sport run
        sequentially (main → alt → prop). Used by the UI refresh button.
        """
        cfg = self._load_config()
        if not self.customer_id or not self.password:
            return {"status": "no_credentials"}
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
