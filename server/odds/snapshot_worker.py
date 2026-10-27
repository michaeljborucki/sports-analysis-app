"""Full odds-snapshot build in a separate process (betting_db mode).

The in-process build (betting-db read + map + rows_to_games over ~440k rows)
took 33-48s of CPU every 60s in a worker thread, so the API's event loop
spent much of its time waiting on the GIL (2026-10-24: ~17-25% of uptime
stalled). Here a fresh spawned process does the whole build and exits,
returning its memory to the OS.

Transfer: one pickle of the whole result would make the parent hold the GIL
for its entire unpickle (~1s+). Instead the child returns many small pickles
— contiguous 2,000-row slices and one per game — and the parent unpickles
them one by one in a worker thread, so the loop runs between chunks. Order
lists travel alongside, so the reassembled rows / games / base rows come out
in exactly the order the in-process build produces.

Nothing here writes: betting-db is opened read-only and cache.db is only
SELECTed (same `_direct_book_rows` query as the in-process build).
"""
from __future__ import annotations

import gc
import logging
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROWS_PER_CHUNK = 2000
SIGS_PER_CHUNK = 200
_PROTOCOL = pickle.HIGHEST_PROTOCOL


def _chunks(items: list, size: int) -> list[bytes]:
    return [
        pickle.dumps(items[i:i + size], protocol=_PROTOCOL)
        for i in range(0, len(items), size)
    ]


def build_payload(cache_path: str) -> dict[str, Any]:
    """Child-process entry point. Returns only bytes / small lists."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)   # same format as the API's log
    # A one-shot process: nothing it allocates needs cycle collection, and
    # gen-2 passes over ~1M fresh objects would roughly double the build.
    # (Restored on the way out, so calling this in-process — tests — is safe.)
    gc_was_enabled = gc.isenabled()
    gc.disable()
    from . import normalize
    original_check = normalize._check_outcome_name_collisions
    try:
        return _build_payload(cache_path, normalize)
    finally:
        normalize._check_outcome_name_collisions = original_check
        if gc_was_enabled:
            gc.enable()


def _build_payload(cache_path: str, normalize) -> dict[str, Any]:
    started = time.perf_counter()
    from .cache import OddsCache
    from .latest_snapshot import direct_signatures, merge_betting_db

    # Collision WARNINGs dedup per process; this process lives for one build,
    # so it would re-log every collision every minute. Hand them to the
    # parent's dedup instead (see unpack_payload) — same log output.
    collisions: list[tuple] = []
    normalize._check_outcome_name_collisions = (
        lambda rows: collisions.extend(normalize._collect_outcome_name_collisions(rows))
    )

    built_at = datetime.now(timezone.utc)
    merged, base, direct = merge_betting_db(OddsCache(Path(cache_path)))
    read_done = time.perf_counter()
    all_games, non_prop_list = normalize.rows_to_games_with_non_prop(
        merged, now=built_at,
    )
    games_done = time.perf_counter()

    # `merged` = kept base rows (base order) + direct. Ship merged, plus the
    # base rows a direct book displaced and their base positions, so the
    # parent rebuilds `base` exactly.
    n_kept = len(merged) - len(direct)
    kept_ids = {id(r) for r in merged[:n_kept]}
    excluded_positions: list[int] = []
    excluded_rows: list[dict] = []
    for i, r in enumerate(base):
        if id(r) not in kept_ids:
            excluded_positions.append(i)
            excluded_rows.append(r)

    np_by_event = {g["event_id"]: g for g in non_prop_list}
    sig_items = list(direct_signatures(direct).items())
    payload = {
        "built_at": built_at,
        "row_chunks": _chunks(merged, ROWS_PER_CHUNK),
        "n_kept": n_kept,
        "excluded_positions": excluded_positions,
        "excluded_chunks": _chunks(excluded_rows, ROWS_PER_CHUNK),
        # A game and its non-prop view share market objects: same pickle.
        "game_chunks": [
            pickle.dumps((g, np_by_event.get(g["event_id"])), protocol=_PROTOCOL)
            for g in all_games
        ],
        "non_prop_order": [g["event_id"] for g in non_prop_list],
        "sig_chunks": _chunks(sig_items, SIGS_PER_CHUNK),
        "collisions": collisions,
        "child_timings_ms": {
            "read": (read_done - started) * 1000,
            "games": (games_done - read_done) * 1000,
            "pack": (time.perf_counter() - games_done) * 1000,
        },
    }
    return payload


def unpack_payload(payload: dict[str, Any]) -> tuple[
    tuple[dict, ...], list[dict], list[dict], list[dict], dict[str, tuple], datetime,
]:
    """Parent side, run in a worker thread: `(rows, all_games, non_prop_list,
    base, direct_sig, built_at)` exactly as the in-process build has them.
    Each `pickle.loads` is one short C call, so the GIL is released between
    chunks."""
    from .normalize import _warn_outcome_name_collisions

    merged: list[dict] = []
    for blob in payload["row_chunks"]:
        merged.extend(pickle.loads(blob))
    excluded: list[dict] = []
    for blob in payload["excluded_chunks"]:
        excluded.extend(pickle.loads(blob))

    n_kept = payload["n_kept"]
    positions = payload["excluded_positions"]
    base: list[dict] = []
    k = x = 0
    for pos in range(n_kept + len(excluded)):
        if x < len(positions) and positions[x] == pos:
            base.append(excluded[x])
            x += 1
        else:
            base.append(merged[k])
            k += 1

    all_games: list[dict] = []
    np_by_event: dict[str, dict] = {}
    for blob in payload["game_chunks"]:
        game, np_game = pickle.loads(blob)
        all_games.append(game)
        if np_game is not None:
            np_by_event[game["event_id"]] = np_game
    non_prop_list = [np_by_event[e] for e in payload["non_prop_order"]]

    direct_sig: dict[str, tuple] = {}
    for blob in payload["sig_chunks"]:
        direct_sig.update(pickle.loads(blob))

    _warn_outcome_name_collisions(payload["collisions"])
    return tuple(merged), all_games, non_prop_list, base, direct_sig, payload["built_at"]
