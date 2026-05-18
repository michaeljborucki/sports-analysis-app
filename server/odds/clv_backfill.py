"""One-shot historical CLV backfill.

Walks Coral33 wager-log entries that don't yet have a closing line and
fetches archived Odds API data to populate them. Cost-aware: the caller
can plan first to see the credit estimate, then execute.

Architecture (per (sport, date) bucket):
  1. Resolve Odds API sport_keys via SPORTS[sport_key].odds_api_sport_keys.
     Static keys ("baseball_mlb") pass through; prefix patterns
     ("tennis_atp_*") are skipped — historical event discovery for
     dynamic tournaments isn't reliable.
  2. Call /v4/historical/sports/{sport_key}/events?date=… to list events
     near the wager's accepted_at. Match wager teams against the listed
     events via the same normalization the live matcher uses.
  3. For each matched event, call /v4/historical/sports/{sport_key}/
     events/{event_id}/odds?date=commence-7min&markets=…&regions=us to
     fetch the closing snapshot.
  4. Normalize the response → odds_snapshot-shaped rows.
  5. Run rows through devig_rows_to_closing_lines() → closing_lines rows.
  6. cache.upsert_closing_lines().

After this completes, lookup_clv() against the wager log finds the
populated rows immediately — no other state changes needed.

Skipped (returns reason in result):
  - parlays/teasers (CLV is per-leg; we only have head-leg detail)
  - wagers with unknown sport_sub_type
  - wagers whose Coral33 sport maps only to prefix-pattern Odds API keys
  - wagers where no historical event matches the team pair
  - 422 / empty per-event responses (event predates Odds API archive)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from ..sports import SPORTS, Sport
from .books.coral33.event_matcher import _normalize_team
from .books.coral33.mapping import Coral33Config
from .books.coral33.wager_log import WagerLogEntry
from .cache import OddsCache
from .client import OddsAPIClient, OddsAPIError
from .clv import (
    _classify_bet,
    _normalize_with_aliases,
    build_subtype_to_sport_key,
    lookup_clv,
)
from .clv_capture import devig_rows_to_closing_lines
from .market_config import MarketConfig
from .normalize import normalize_odds_response


logger = logging.getLogger(__name__)


# Markets to fetch per event during backfill. Excludes player_props by
# default — props ~2× the cost per event and only cover ~25% of typical
# wager volume. Set `include_props=True` on the entry call to widen.
DEFAULT_MARKET_TIERS = ("main", "alternates", "periods")


# Per-sport time-window for matching wager teams to historical events.
# UFC/Boxing share the card-start timestamp across every fight, so use
# the wider matcher window we already use elsewhere.
SPORT_MATCH_WINDOW_DAYS: dict[str, int] = {
    "ufc":    7,
    "boxing": 7,
}
DEFAULT_MATCH_WINDOW_DAYS = 3


@dataclass
class BackfillStats:
    considered: int = 0
    already_has_clv: int = 0
    parlay_skipped: int = 0           # teasers only (parlays head-leg backfill is supported)
    prop_or_nrfi_skipped: int = 0     # need player/yes-no-specific event discovery
    no_sport_match: int = 0
    no_event_match: int = 0
    sport_prefix_pattern_skipped: int = 0
    fetched_events: int = 0
    closing_lines_written: int = 0
    api_calls: int = 0
    credits_used_delta: int = 0  # using_at_end - using_at_start
    credits_remaining: int | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "considered": self.considered,
            "already_has_clv": self.already_has_clv,
            "parlay_skipped": self.parlay_skipped,
            "prop_or_nrfi_skipped": self.prop_or_nrfi_skipped,
            "no_sport_match": self.no_sport_match,
            "no_event_match": self.no_event_match,
            "sport_prefix_pattern_skipped": self.sport_prefix_pattern_skipped,
            "fetched_events": self.fetched_events,
            "closing_lines_written": self.closing_lines_written,
            "api_calls": self.api_calls,
            "credits_used_delta": self.credits_used_delta,
            "credits_remaining": self.credits_remaining,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class _EventTarget:
    """A unique Odds API event that needs a closing-line snapshot."""
    sport_key: str            # our internal key, e.g. "mlb"
    odds_api_sport_key: str   # Odds API canonical, e.g. "baseball_mlb"
    event_id: str
    commence_time: datetime
    home_team: str
    away_team: str


# ───────────────────── Sport / market resolution ──────────────────────


def _markets_for_sport(sport: Sport, include_props: bool) -> list[str]:
    """All distinct market_keys our config requests for this sport,
    flattened across all enabled tiers. Drops the props tier when
    `include_props=False` to halve typical per-event cost."""
    try:
        cfg = MarketConfig.load(sport.markets_config)
    except Exception:
        logger.exception("Failed to load markets config for %s", sport.key)
        return []
    out: set[str] = set()
    for tier in cfg.enabled_tiers():
        if tier.name == "player_props" and not include_props:
            continue
        if tier.name not in DEFAULT_MARKET_TIERS and tier.name != "player_props":
            continue
        if include_props or tier.name in DEFAULT_MARKET_TIERS:
            out.update(tier.markets)
    return sorted(out)


def _resolve_odds_api_keys(sport: Sport) -> tuple[list[str], list[str]]:
    """Split sport's odds_api_sport_keys into (static_keys, patterns).
    Patterns ending in `*` need dynamic resolution (tennis); for the
    backfill we skip them — historical event discovery for tournament-
    paginated sports isn't reliably supported by the archive."""
    static: list[str] = []
    patterns: list[str] = []
    for k in sport.odds_api_sport_keys:
        if k.endswith("*"):
            patterns.append(k)
        else:
            static.append(k)
    return static, patterns


# ───────────────────── Wager filtering ────────────────────────────────


def _select_wagers(
    wagers: Iterable[WagerLogEntry],
    cache: OddsCache,
    config: Coral33Config,
    subtype_to_sport_key: dict[str, str],
    stats: BackfillStats,
) -> list[tuple[WagerLogEntry, str]]:
    """Filter the wager set to those that need (and can be) backfilled.
    Returns [(wager, sport_key)] pairs. Updates `stats` counters
    in-place."""
    out: list[tuple[WagerLogEntry, str]] = []
    for w in wagers:
        stats.considered += 1
        # Teasers shift the line at wager time — comparing the
        # teased-odds to a vanilla close is incoherent. Parlays /
        # round-robins / if-bets store the head leg's true odds in
        # final_money, so they're fair game for head-leg CLV.
        if (w.wager_type or "").upper() == "T":
            stats.parlay_skipped += 1
            continue
        # Already covered → nothing to do.
        existing = lookup_clv(w, cache, config, subtype_to_sport_key)
        if existing is not None:
            stats.already_has_clv += 1
            continue
        # Player props + NRFI need player-rostered / yes-no event
        # discovery, which our team-pair match doesn't provide. Defer
        # to a later pass when we wire up player-name resolution.
        cls = _classify_bet(w)
        if cls in ("player_prop", "nrfi"):
            stats.prop_or_nrfi_skipped += 1
            continue
        # Sport resolution (uppercase to match the canonical-case keys
        # the reverse map uses).
        sport_key = subtype_to_sport_key.get((w.sport_sub_type or "").upper())
        if sport_key is None:
            stats.no_sport_match += 1
            continue
        out.append((w, sport_key))
    return out


def _wager_pair_normalized(
    wager: WagerLogEntry, sport_key: str, config: Coral33Config,
) -> tuple[str, str] | None:
    """Return the wager's two-team pair after normalization + alt-suffix
    strip + alias application. None when team fields are missing.

    Critical for alt-line wagers: Coral33 emits team names like
    "76ers Alt Line" on the *ALT LINE* subtypes. _normalize_with_aliases()
    strips the suffix first so the alias map sees "76ers" → "philadelphia
    76ers", not "76ers alt line" → no match.
    """
    if not (wager.team1_id and wager.team2_id):
        return None
    a = _normalize_with_aliases(wager.team1_id, sport_key, config)
    b = _normalize_with_aliases(wager.team2_id, sport_key, config)
    if not a or not b:
        return None
    return (a, b)


# ───────────────────── Event discovery ────────────────────────────────


async def _discover_events_for_bucket(
    client: OddsAPIClient,
    odds_api_sport_key: str,
    wagers: list[tuple[WagerLogEntry, str]],
    sport_key: str,
    config: Coral33Config,
    stats: BackfillStats,
) -> dict[tuple[str, str], _EventTarget]:
    """For one Odds API sport, look up historical events at each unique
    `accepted_at` date in the bucket. Match wager team pairs against
    listed events to discover event_id + commence_time.

    Returns dict {(team1_norm, team2_norm) → EventTarget} keyed by the
    normalized team pair as a set — orientation-agnostic.
    """
    # Unique discovery snapshots — one per wager.accepted_at date, plus
    # one per date + match-window-days (so a wager placed Mon for Fri
    # game still resolves when we list events from Tue).
    window_days = SPORT_MATCH_WINDOW_DAYS.get(
        sport_key, DEFAULT_MATCH_WINDOW_DAYS,
    )
    snapshot_dates: set[str] = set()
    for w, _sk in wagers:
        d = w.accepted_at.date()
        snapshot_dates.add(d.isoformat())
        for delta in range(1, window_days + 1):
            snapshot_dates.add((d + timedelta(days=delta)).isoformat())

    # All listed events (sport-scoped) keyed by their event_id, so
    # repeated discovery calls don't double-count.
    all_listed: dict[str, dict] = {}
    for date_iso in sorted(snapshot_dates):
        # Hit at noon UTC — gets a stable mid-day view that covers both
        # late-morning starts (Asian baseball) and prime-time US events
        # listed as upcoming.
        snap = f"{date_iso}T12:00:00Z"
        try:
            events, info = await client.fetch_historical_events(
                odds_api_sport_key, snap,
            )
        except OddsAPIError as e:
            stats.errors.append(
                f"fetch_historical_events {odds_api_sport_key}@{snap}: {e}"
            )
            continue
        stats.api_calls += 1
        if info.get("requests_remaining") is not None:
            stats.credits_remaining = info["requests_remaining"]
        for ev in events:
            all_listed[ev["id"]] = ev

    # Match wager team pairs to listed events.
    aliases = config.team_aliases.get(sport_key, {})
    wager_pairs: set[frozenset[str]] = set()
    pair_map: dict[frozenset[str], list[WagerLogEntry]] = {}
    for w, _sk in wagers:
        p = _wager_pair_normalized(w, sport_key, config)
        if p is None:
            continue
        fs = frozenset(p)
        wager_pairs.add(fs)
        pair_map.setdefault(fs, []).append(w)

    targets: dict[tuple[str, str], _EventTarget] = {}
    for ev in all_listed.values():
        ev_home = _normalize_team(ev.get("home_team", ""), aliases, sport_key)
        ev_away = _normalize_team(ev.get("away_team", ""), aliases, sport_key)
        if not ev_home or not ev_away:
            continue
        pair_fs = frozenset((ev_home, ev_away))
        if pair_fs not in wager_pairs:
            continue
        commence_raw = ev.get("commence_time")
        if not commence_raw:
            continue
        try:
            commence = datetime.fromisoformat(
                str(commence_raw).replace("Z", "+00:00"),
            )
        except ValueError:
            continue
        if commence.tzinfo is None:
            commence = commence.replace(tzinfo=timezone.utc)
        # If we already picked an event for this pair, keep the one
        # whose commence_time is closest to any matched wager's
        # accepted_at — handles the (rare) case where the same team
        # pair plays multiple times in the discovery window.
        key = (ev_home, ev_away)
        existing = targets.get(key) or targets.get((ev_away, ev_home))
        if existing is not None:
            wagers_for_pair = pair_map.get(pair_fs, [])
            existing_dist = min(
                abs((existing.commence_time - w.accepted_at).total_seconds())
                for w in wagers_for_pair
            )
            new_dist = min(
                abs((commence - w.accepted_at).total_seconds())
                for w in wagers_for_pair
            )
            if new_dist >= existing_dist:
                continue
        targets[key] = _EventTarget(
            sport_key=sport_key,
            odds_api_sport_key=odds_api_sport_key,
            event_id=ev["id"],
            commence_time=commence,
            home_team=ev.get("home_team", ""),
            away_team=ev.get("away_team", ""),
        )

    return targets


# ───────────────────── Per-event close fetch ──────────────────────────


async def _fetch_and_devig_event(
    client: OddsAPIClient,
    cache: OddsCache,
    target: _EventTarget,
    markets: list[str],
    regions: list[str],
    snapshot_lead_minutes: int,
    stats: BackfillStats,
) -> int:
    """Fetch one event's archived odds at commence - lead, normalize,
    devig, and upsert. Returns count of closing-line rows written."""
    snap_dt = target.commence_time - timedelta(minutes=snapshot_lead_minutes)
    snap_iso = snap_dt.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z",
    )
    try:
        data, info = await client.fetch_historical_event_odds(
            sport_key=target.odds_api_sport_key,
            event_id=target.event_id,
            date=snap_iso,
            markets=markets,
            regions=regions,
        )
    except OddsAPIError as e:
        stats.errors.append(
            f"fetch_historical_event_odds {target.event_id}@{snap_iso}: {e}"
        )
        return 0
    stats.api_calls += 1
    if info.get("requests_remaining") is not None:
        stats.credits_remaining = info["requests_remaining"]
    if not data:
        return 0

    # Normalize into odds_snapshot-shaped rows; sport_key here is OUR
    # internal key, not the Odds API key, since downstream lookup
    # (closing_lines and clv.py) speaks in our keys.
    rows = normalize_odds_response(
        data, fetched_at=snap_dt, sport_key=target.sport_key,
    )
    if not rows:
        return 0

    event_meta = {
        "event_id": target.event_id,
        "sport_key": target.sport_key,
        "home_team": target.home_team,
        "away_team": target.away_team,
        "commence_time": target.commence_time,
    }
    close_rows = devig_rows_to_closing_lines(event_meta, rows, snap_dt)
    if not close_rows:
        return 0
    return cache.upsert_closing_lines(close_rows)


# ───────────────────── Top-level driver ───────────────────────────────


async def backfill_clv(
    wagers: Iterable[WagerLogEntry],
    cache: OddsCache,
    client: OddsAPIClient,
    config: Coral33Config,
    *,
    include_props: bool = False,
    snapshot_lead_minutes: int = 7,
    max_credits: int | None = None,
    dry_run: bool = False,
) -> BackfillStats:
    """Backfill historical closing lines for a set of wagers.

    Args:
      wagers: WagerLogEntry list — typically the union across all
        Coral33 accounts. Filtered down to "needs backfill" inside.
      cache: shared OddsCache (for closing-lines upserts).
      client: OddsAPIClient (must have api_key configured).
      config: Coral33Config (for alias / sport map).
      include_props: fetch player-prop markets too. Doubles cost.
      snapshot_lead_minutes: snapshot offset before commence. Default 7
        matches baseball-agents.
      max_credits: hard ceiling on credits consumed (per credits_remaining
        header). When set, backfill aborts cleanly once usage crosses it.
      dry_run: when True, performs event discovery but skips per-event
        fetches and writes. Reports estimated event count + credit
        budget without spending it.

    Returns BackfillStats. Idempotent — re-running after a partial run
    skips wagers that now have CLV.
    """
    stats = BackfillStats()
    subtype_map = build_subtype_to_sport_key(config)
    selected = _select_wagers(wagers, cache, config, subtype_map, stats)
    if not selected:
        return stats

    # Bucket by our sport_key so we resolve markets + odds_api_keys once
    # per sport.
    by_sport: dict[str, list[tuple[WagerLogEntry, str]]] = {}
    for w, sk in selected:
        by_sport.setdefault(sk, []).append((w, sk))

    starting_used: int | None = None

    for sport_key, sport_wagers in by_sport.items():
        sport = SPORTS.get(sport_key)
        if sport is None:
            stats.no_sport_match += len(sport_wagers)
            continue
        static_keys, patterns = _resolve_odds_api_keys(sport)
        if patterns and not static_keys:
            # All keys are dynamic patterns (tennis_atp_*). Historical
            # discovery for these is unreliable — skip.
            stats.sport_prefix_pattern_skipped += len(sport_wagers)
            continue
        markets = _markets_for_sport(sport, include_props=include_props)
        if not markets:
            logger.warning(
                "backfill: no enabled markets for %s; skipping %d wagers",
                sport_key, len(sport_wagers),
            )
            continue

        # Per-Odds-API-key event discovery. For multi-key sports
        # (asian_baseball: npb + kbo, soccer: 12 leagues) we just iterate
        # — wagers will only match events from their actual league.
        all_targets: dict[str, _EventTarget] = {}
        for odds_api_sport_key in static_keys:
            targets = await _discover_events_for_bucket(
                client, odds_api_sport_key, sport_wagers, sport_key,
                config, stats,
            )
            for t in targets.values():
                all_targets[t.event_id] = t

        # Count un-matched wagers in this sport.
        matched_pairs: set[frozenset[str]] = set()
        aliases = config.team_aliases.get(sport_key, {})
        for t in all_targets.values():
            h = _normalize_team(t.home_team, aliases, sport_key)
            a = _normalize_team(t.away_team, aliases, sport_key)
            matched_pairs.add(frozenset({h, a}))
        for w, _ in sport_wagers:
            pair = _wager_pair_normalized(w, sport_key, config)
            if pair is None or frozenset(pair) not in matched_pairs:
                stats.no_event_match += 1

        if dry_run:
            stats.fetched_events += len(all_targets)
            continue

        # Per-event fetches.
        for target in all_targets.values():
            if max_credits is not None and stats.credits_remaining is not None:
                # Stop if we've crossed the user-set budget. The Odds API
                # `requests_remaining` decreases as we spend; abort when
                # it would drop below the safe floor.
                if stats.credits_used_delta >= max_credits:
                    logger.info(
                        "backfill: credit ceiling %d reached, stopping",
                        max_credits,
                    )
                    return stats
            written = await _fetch_and_devig_event(
                client, cache, target, markets, regions=["us"],
                snapshot_lead_minutes=snapshot_lead_minutes, stats=stats,
            )
            if written > 0:
                stats.fetched_events += 1
                stats.closing_lines_written += written
            if starting_used is None and stats.credits_remaining is not None:
                # First time we see a remaining count — establish baseline.
                # Cost delta is approximated by `requests_remaining`
                # diff; the absolute usage counter (`requests_used`)
                # isn't propagated through info dicts in this client.
                starting_used = stats.credits_remaining
            elif (
                starting_used is not None
                and stats.credits_remaining is not None
            ):
                stats.credits_used_delta = (
                    starting_used - stats.credits_remaining
                )

    return stats


# ───────────────────── Sync convenience ───────────────────────────────


def run_backfill_sync(
    wagers: Iterable[WagerLogEntry],
    cache: OddsCache,
    client: OddsAPIClient,
    config: Coral33Config,
    **kwargs,
) -> BackfillStats:
    """Synchronous wrapper around backfill_clv() for CLI / shell use."""
    return asyncio.run(backfill_clv(wagers, cache, client, config, **kwargs))
