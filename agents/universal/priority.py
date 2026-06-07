"""Universal rule: priority-ordered analysis with immediate per-game alerts.

The naive daily pipeline analyzes the entire slate and only alerts once every
game is done. That's wrong for time-sensitive markets: a game starting in 20
minutes shouldn't have its alert held hostage by a game that starts at midnight.

This rule fixes both halves of that problem and is intentionally sport-agnostic
— it knows nothing about baseball, odds, or LLMs. A sport supplies its own
per-game work and its own alert sender; this module supplies the ordering and
the "alert the instant a game finishes" behavior:

  1. **Priority order** — games are sorted by first pitch (soonest first) so the
     games closest to starting get a worker as soon as one is free.
  2. **Immediate alerts** — the moment a game's analysis finishes, if it
     produced any bets, its alert fires right away. The pipeline never waits for
     the rest of the slate.

Concurrency model: games are submitted to a bounded thread pool in soonest-first
order, so workers pick up the most-urgent games first. Results are consumed as
they complete and alerts are dispatched from the consuming thread (one at a
time), so the sport's alert sender never needs to be thread-safe.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

logger = logging.getLogger("mirofish.universal.priority")

# Games whose first-pitch time is missing or unparseable sort last — they're the
# least urgent thing to spend a worker on, and a bad timestamp shouldn't jump the
# queue ahead of a game we know is about to start.
_FAR_FUTURE = datetime.max.replace(tzinfo=timezone.utc)


def _first_pitch(game: dict, time_field: str) -> datetime:
    """Parse a game's first-pitch UTC timestamp; unknown/bad values sort last."""
    raw = game.get(time_field)
    if not raw:
        return _FAR_FUTURE
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return _FAR_FUTURE


def sort_by_first_pitch(games: Iterable[dict], time_field: str = "game_date") -> list[dict]:
    """Return ``games`` sorted soonest-first by their first-pitch timestamp.

    ``time_field`` is the game-dict key holding an ISO-8601 UTC timestamp (the
    convention every sport's schedule adapter already follows). Games with a
    missing or unparseable timestamp are placed last, preserving their relative
    order (the sort is stable).
    """
    return sorted(games, key=lambda g: _first_pitch(g, time_field))


def run_priority_pipeline(
    games: Iterable[dict],
    process_game: Callable[[dict], Any],
    *,
    send_alert: Callable[[str, Any], None] | None = None,
    get_game_key: Callable[[dict], str],
    get_bets: Callable[[Any], list] = lambda r: (r or {}).get("bets", []),
    max_workers: int = 4,
    game_timeout: float | None = None,
    time_field: str = "game_date",
    on_complete: Callable[[dict, Any], None] | None = None,
    on_error: Callable[[dict, BaseException], None] | None = None,
) -> dict:
    """Analyze ``games`` soonest-first and alert immediately as each one finishes.

    Args:
        games: the games to analyze. Sorted soonest-first internally.
        process_game: ``(game) -> result``. The sport's full per-game analysis
            (e.g. screen → simulate → log). Runs in a worker thread, so it must
            be thread-safe. Its return value is opaque here and passed straight
            back to ``get_bets`` / ``send_alert`` / ``on_complete``.
        send_alert: ``(game_key, result) -> None``. Fired immediately after a
            game finishes, but only when ``get_bets(result)`` is non-empty. Runs
            on the consuming thread (never concurrently), so it need not be
            thread-safe. ``None`` disables alerting.
        get_game_key: ``(game) -> str``. Stable identifier used for alerts and
            logging (e.g. ``"NYY@BOS"``).
        get_bets: ``(result) -> list``. Extracts the bets a game produced.
            Default reads ``result["bets"]``; an empty list means "no alert".
        max_workers: max games analyzed concurrently.
        game_timeout: per-game seconds to wait for a result before treating it as
            failed (``on_error`` with ``TimeoutError``). ``None`` waits forever.
            Note: this bounds the *wait*, not the worker — the underlying thread
            keeps running, matching ``concurrent.futures`` semantics.
        time_field: game-dict key holding the first-pitch UTC ISO timestamp.
        on_complete: ``(game, result) -> None``. Called for every game that
            returns a result (bets or not) — use it for progress output.
        on_error: ``(game, exc) -> None``. Called when a game raises or times
            out. The exception is swallowed afterward so one bad game can't sink
            the slate.

    Returns a summary dict: ``{processed, alerted, errors, total_bets}``.
    """
    ordered = sort_by_first_pitch(games, time_field=time_field)
    summary = {"processed": 0, "alerted": 0, "errors": 0, "total_bets": 0}
    if not ordered:
        return summary

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # Submit in soonest-first order; the pool's work queue is FIFO, so the
        # most-urgent games are the first to claim a worker.
        futures = {pool.submit(process_game, game): game for game in ordered}

        for future in as_completed(futures):
            game = futures[future]
            game_key = get_game_key(game)
            try:
                result = future.result(timeout=game_timeout)
            except BaseException as exc:  # noqa: BLE001 — one game must not sink the slate
                summary["errors"] += 1
                logger.warning("priority: %s failed: %s", game_key, exc)
                if on_error is not None:
                    on_error(game, exc)
                continue

            summary["processed"] += 1
            if on_complete is not None:
                on_complete(game, result)

            bets = get_bets(result)
            if bets:
                summary["total_bets"] += len(bets)
                if send_alert is not None:
                    # Alert the instant this game is done — don't wait for the
                    # rest of the slate. Sent from the consuming thread, so this
                    # is serialized across games.
                    try:
                        send_alert(game_key, result)
                        summary["alerted"] += 1
                    except Exception:  # noqa: BLE001 — alert failure must not abort analysis
                        logger.exception("priority: alert dispatch failed for %s", game_key)

    return summary
