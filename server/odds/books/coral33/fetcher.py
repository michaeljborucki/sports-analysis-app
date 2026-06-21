from __future__ import annotations

import asyncio
import logging
import os
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
    normalize_extras,
    normalize_league_lines,
    normalize_player_props,
)


logger = logging.getLogger(__name__)


# One job per sport runs all three tiers (main → alt → prop) sequentially
# each cycle. This avoids hitting coral33 with overlapping requests, and
# guarantees the CorrelationID index is populated by main before props look
# it up.
#
# Cadence is env-tunable so we can dial up freshness vs captcha-trigger risk
# without a redeploy:
#   CORAL33_CYCLE_SECONDS — base interval (default 60s, was 240s)
#   CORAL33_CYCLE_JITTER  — ± random jitter window (default 15s)
# Conservative fallback: lift these back to 240/60 if Coral33 starts captcha-
# gating Lines requests. Watch /api/coral33/status.captcha_backoff_remaining_s.
CYCLE_INTERVAL = int(os.environ.get("CORAL33_CYCLE_SECONDS", "60"))
CYCLE_JITTER   = int(os.environ.get("CORAL33_CYCLE_JITTER", "15"))
CAPTCHA_BACKOFF = 300

# Per-sport startup stagger so we don't fire all jobs in the same wallclock
# second on boot. Capped at the cycle interval so we don't push the first
# fire of any sport past its second scheduled fire.
_STARTUP_STAGGER = (0, max(15, min(60, CYCLE_INTERVAL)))


def _row_key(row: dict) -> tuple:
    """Cache primary-key tuple — same shape OddsCache.upsert keys on so two
    normalized rows representing the same line collapse into one upsert."""
    return (
        row["event_id"],
        row["bookmaker_key"],
        row["market_key"],
        row["outcome_name"],
        float(row.get("outcome_point") or 0.0),
    )


# Market keys that Coral33 surfaces as parlay-eligible at the API layer but
# are NOT actually placeable on a parlay slip — team-total markets in
# particular only resolve in straight mode. We force-tag any such row as
# `wager_type="straight"` regardless of what the parlay-mode fetch returned,
# so the EV/arb scanner's parlay filter never proposes them as parlay legs.
_STRAIGHT_ONLY_MARKET_PREFIXES: tuple[str, ...] = (
    "team_totals",
    "alternate_team_totals",
)


def _is_straight_only_market(market_key: str) -> bool:
    return market_key.startswith(_STRAIGHT_ONLY_MARKET_PREFIXES)


def _merge_with_wager_type(
    straight_rows: list[dict],
    parlay_rows: list[dict],
) -> list[dict]:
    """Dedupe two normalized row lists by cache key and tag each with its
    parlay-eligibility:

      - present in BOTH calls → wager_type='both'
      - Straight only         → wager_type='straight'
      - Parlay only           → wager_type='parlay'

    For rows that appear in both sets the Straight version wins as the
    "canonical" copy — coral33's Straight tab is the page the user lands on
    by default, and price field semantics are identical between modes.

    Override: any row whose market_key is in `_STRAIGHT_ONLY_MARKET_PREFIXES`
    (team totals + their alt variants) is force-tagged `straight` regardless
    of parlay-fetch presence — those markets resolve straight-only on
    Coral33 and surfacing them as parlay legs would propose unplaceable
    bets.
    """
    by_key: dict[tuple, dict] = {}
    parlay_keys: set[tuple] = set()
    for r in parlay_rows:
        k = _row_key(r)
        if _is_straight_only_market(r["market_key"]):
            # Skip parlay-tier emission entirely for straight-only markets.
            continue
        parlay_keys.add(k)
        # Tentatively land parlay rows; Straight pass below overwrites for
        # the "both" / Straight-only cases.
        by_key[k] = {**r, "wager_type": "parlay"}
    for r in straight_rows:
        k = _row_key(r)
        # Straight-only markets are forced to "straight" even if coral33's
        # parlay fetch echoed them; otherwise apply the standard dedupe.
        if _is_straight_only_market(r["market_key"]):
            wager_type = "straight"
        else:
            wager_type = "both" if k in parlay_keys else "straight"
        by_key[k] = {**r, "wager_type": wager_type}
    return list(by_key.values())


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
        # 30-minute grace window: don't purge a row whose commence_time
        # is within the last 30 minutes. Catches the common rain-delay /
        # soft-start case without polling Coral33 for live game status.
        purged = self.cache.purge_live_rows_for_book(
            "coral33", now, grace_seconds=1800,
        )
        if purged:
            logger.info("coral33 %s: purged %d live rows", sport_key, purged)
        # Row-level TTL for dropped lines — applies to ALL books, not just
        # coral33. Piggy-backing on coral33's cycle so it runs even if the
        # Odds API fetcher is paused (manual Latest/Snapshot mode).
        stale = self.cache.purge_stale_rows(now=now)
        if stale:
            logger.info("coral33 %s: purged %d stale rows (TTL)", sport_key, stale)

        matcher = self._matcher()
        captcha_hit = False
        total_rows = 0

        async def pull_and_normalize(
            calls: list[tuple[str, str, str]],
            *, is_alt: bool,
            ingest_correlation: bool = False,
        ) -> int:
            """For each (sportType, subtype, period) tuple, hit coral33 with
            wagerType=Straight AND wagerType=Parlay in parallel. Dedupe the
            two normalized row sets by (event_id, market_key, outcome_name,
            outcome_point) — rows present in both → wager_type='both', only
            Straight → 'straight', only Parlay → 'parlay'. Then upsert once.
            """
            nonlocal captcha_hit
            tier_rows = 0
            for sport_type, subtype, period in calls:
                straight_data, parlay_data = await asyncio.gather(
                    self._safe_get_league_lines(
                        sport_type, subtype, period, "Straight", sport_key,
                    ),
                    self._safe_get_league_lines(
                        sport_type, subtype, period, "Parlay", sport_key,
                    ),
                )
                if straight_data is None and parlay_data is None:
                    continue
                # Captcha on either pull aborts the whole tier — coral will
                # keep returning captcha until the back-off completes.
                if (
                    (straight_data and straight_data.get("CaptchaRequired"))
                    or (parlay_data and parlay_data.get("CaptchaRequired"))
                ):
                    captcha_hit = True
                    logger.warning(
                        "coral33 captcha on %s/%s/%s — backing off",
                        sport_type, subtype, period,
                    )
                    continue
                # Correlation index is fed from the Straight pull only —
                # both wager types return the same Lines metadata, but we
                # only need to ingest once.
                if (
                    ingest_correlation
                    and period == "Game"
                    and straight_data is not None
                ):
                    self._ingest_correlation_index(straight_data, sport_key, matcher)

                straight_rows = (
                    normalize_league_lines(
                        straight_data, period=period, sport_key=sport_key,
                        fetched_at=now, match_event=matcher.match,
                        is_alternate=is_alt,
                    )
                    if straight_data is not None
                    else []
                )
                parlay_rows = (
                    normalize_league_lines(
                        parlay_data, period=period, sport_key=sport_key,
                        fetched_at=now, match_event=matcher.match,
                        is_alternate=is_alt,
                    )
                    if parlay_data is not None
                    else []
                )
                merged = _merge_with_wager_type(straight_rows, parlay_rows)
                if merged:
                    self.cache.upsert(merged)
                    tier_rows += len(merged)
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

        # 2, 3 & 4. Alt / prop / extras run in random order — all fine to
        # run after main, and shuffling each cycle makes outbound traffic
        # patterns less predictable (a little extra anti-fingerprint).
        secondary: list[tuple[str, callable]] = []
        if sport_cfg.alt_calls:
            async def run_alt() -> int:
                return await pull_and_normalize(sport_cfg.alt_calls, is_alt=True)
            secondary.append(("alt", run_alt))
        if sport_cfg.prop_calls:
            async def run_prop() -> int:
                return await self._pull_props(sport_cfg, sport_key, now)
            secondary.append(("prop", run_prop))
        if sport_cfg.extra_calls:
            async def run_extras() -> int:
                return await self._pull_extras(sport_cfg, sport_key, now, matcher)
            secondary.append(("extras", run_extras))
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
            matched = matcher.match(sport_key, home=team2, away=team1, commence=commence)
            if matched is None:
                continue
            # Store CANONICAL Odds API team names so downstream props join
            # cleanly with main-tier outcomes (same event_id + same team text
            # ⇒ same outcome bucket).
            self._correlation_index[cid] = {
                "event_id": matched["event_id"],
                "home_team": matched.get("home_team") or team2,
                "away_team": matched.get("away_team") or team1,
                "commence_time": commence,
            }

    async def _pull_props(self, sport_cfg, sport_key: str, now: datetime) -> int:
        def lookup(correlation_id):
            if not isinstance(correlation_id, str):
                return None
            return self._correlation_index.get(correlation_id)

        tier_rows = 0
        for sport_type, subtype, period in sport_cfg.prop_calls:
            straight_data, parlay_data = await asyncio.gather(
                self._safe_get_league_lines(
                    sport_type, subtype, period, "Straight", sport_key,
                ),
                self._safe_get_league_lines(
                    sport_type, subtype, period, "Parlay", sport_key,
                ),
            )
            if straight_data is None and parlay_data is None:
                continue
            if (
                (straight_data and straight_data.get("CaptchaRequired"))
                or (parlay_data and parlay_data.get("CaptchaRequired"))
            ):
                import time as _time
                self._captcha_until = _time.time() + CAPTCHA_BACKOFF
                logger.warning(
                    "coral33 captcha on %s/%s/%s (prop) — backing off",
                    sport_type, subtype, period,
                )
                continue
            straight_rows = (
                normalize_player_props(
                    straight_data, sport_key=sport_key, fetched_at=now,
                    game_num_lookup=lookup,
                )
                if straight_data is not None
                else []
            )
            parlay_rows = (
                normalize_player_props(
                    parlay_data, sport_key=sport_key, fetched_at=now,
                    game_num_lookup=lookup,
                )
                if parlay_data is not None
                else []
            )
            merged = _merge_with_wager_type(straight_rows, parlay_rows)
            if merged:
                self.cache.upsert(merged)
                tier_rows += len(merged)
        return tier_rows

    async def _pull_extras(
        self, sport_cfg, sport_key: str, now: datetime,
        matcher: "Coral33EventMatcher",
    ) -> int:
        """Iterate `[[sports.<x>.extras]]` entries: fetch each, normalize
        according to the per-entry `kind`, upsert. All rows landed here end
        up under bespoke market_keys (totals_hits_runs_errors,
        team_to_score_first, yes_no_score_first_inning, spreads_reg_time,
        etc.) — the existing scanners ignore these keys until/unless we
        wire them in explicitly."""
        tier_rows = 0
        for sport_type, subtype, period, kind in sport_cfg.extra_calls:
            straight_data, parlay_data = await asyncio.gather(
                self._safe_get_league_lines(
                    sport_type, subtype, period, "Straight", sport_key,
                ),
                self._safe_get_league_lines(
                    sport_type, subtype, period, "Parlay", sport_key,
                ),
            )
            if straight_data is None and parlay_data is None:
                continue
            if (
                (straight_data and straight_data.get("CaptchaRequired"))
                or (parlay_data and parlay_data.get("CaptchaRequired"))
            ):
                import time as _time
                self._captcha_until = _time.time() + CAPTCHA_BACKOFF
                logger.warning(
                    "coral33 captcha on %s/%s/%s (extras) — backing off",
                    sport_type, subtype, period,
                )
                continue
            straight_rows = (
                normalize_extras(
                    straight_data, kind=kind, sport_key=sport_key,
                    fetched_at=now, match_event=matcher.match,
                )
                if straight_data is not None
                else []
            )
            parlay_rows = (
                normalize_extras(
                    parlay_data, kind=kind, sport_key=sport_key,
                    fetched_at=now, match_event=matcher.match,
                )
                if parlay_data is not None
                else []
            )
            merged = _merge_with_wager_type(straight_rows, parlay_rows)
            if merged:
                self.cache.upsert(merged)
                tier_rows += len(merged)
        return tier_rows

    async def _safe_get_league_lines(
        self,
        sport_type: str,
        subtype: str,
        period: str,
        wager_type: str,
        sport_key: str,
    ) -> dict | None:
        """Wrap get_league_lines in a try/except so a single-mode failure
        (Parlay returning 500 while Straight is fine, etc.) doesn't kill the
        whole tier — caller treats `None` as 'no data this side'."""
        try:
            return await self.client.get_league_lines(
                sport_type, subtype, period, wager_type=wager_type,
            )
        except Coral33APIError as e:
            logger.warning(
                "coral33 %s %s/%s/%s [%s]: %s",
                sport_key, sport_type, subtype, period, wager_type, e,
            )
            return None

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
