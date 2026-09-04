from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable


@dataclass(frozen=True)
class CachedContext:
    payload: dict
    fetched_at: datetime
    expires_at: datetime
    is_stale: bool = False
    warning: str | None = None


class SystemContextCache:
    def __init__(
        self,
        path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS system_context_cache (
                    provider TEXT NOT NULL,
                    cache_key TEXT NOT NULL,
                    effective_date TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    source_timestamp TEXT,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_error TEXT,
                    PRIMARY KEY (provider, cache_key, effective_date)
                );
                CREATE TABLE IF NOT EXISTS system_context_meta (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO system_context_meta (key, value)
                VALUES ('generation', 0);
            """)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @property
    def generation(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM system_context_meta WHERE key='generation'"
            ).fetchone()
        return int(row["value"] if row else 0)

    @staticmethod
    def _dt(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed

    def _read(self, provider: str, cache_key: str, effective_date: date) -> CachedContext | None:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT payload_json, fetched_at, expires_at
                   FROM system_context_cache
                   WHERE provider=? AND cache_key=? AND effective_date=?""",
                (provider, cache_key, effective_date.isoformat()),
            ).fetchone()
        if not row:
            return None
        return CachedContext(
            payload=json.loads(row["payload_json"]),
            fetched_at=self._dt(row["fetched_at"]),
            expires_at=self._dt(row["expires_at"]),
        )

    def _write(
        self,
        provider: str,
        cache_key: str,
        effective_date: date,
        payload: dict,
        fetched_at: datetime,
        expires_at: datetime,
    ) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._conn() as conn:
            previous = conn.execute(
                """SELECT payload_json FROM system_context_cache
                   WHERE provider=? AND cache_key=? AND effective_date=?""",
                (provider, cache_key, effective_date.isoformat()),
            ).fetchone()
            conn.execute(
                """INSERT INTO system_context_cache (
                       provider, cache_key, effective_date, payload_json,
                       fetched_at, expires_at, last_error
                   ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                   ON CONFLICT(provider, cache_key, effective_date) DO UPDATE SET
                       payload_json=excluded.payload_json,
                       fetched_at=excluded.fetched_at,
                       expires_at=excluded.expires_at,
                       last_error=NULL""",
                (
                    provider, cache_key, effective_date.isoformat(), encoded,
                    fetched_at.isoformat(), expires_at.isoformat(),
                ),
            )
            if previous is None or previous["payload_json"] != encoded:
                conn.execute(
                    "UPDATE system_context_meta SET value=value+1 WHERE key='generation'"
                )

    def _record_error(self, provider: str, cache_key: str, effective_date: date, detail: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE system_context_cache SET last_error=?
                   WHERE provider=? AND cache_key=? AND effective_date=?""",
                (detail, provider, cache_key, effective_date.isoformat()),
            )

    async def get_or_refresh(
        self,
        provider: str,
        cache_key: str,
        effective_date: date,
        ttl: timedelta,
        loader: Callable[[], Awaitable[dict]],
        *,
        allow_stale: bool = True,
    ) -> CachedContext:
        key = (provider, cache_key, effective_date.isoformat())
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = self._clock()
            current = self._read(provider, cache_key, effective_date)
            if current and current.expires_at > now:
                return current
            try:
                payload = await loader()
            except Exception as exc:
                detail = str(exc).strip() or type(exc).__name__
                self._record_error(provider, cache_key, effective_date, detail)
                if current and allow_stale:
                    age_minutes = max(0, int((now - current.fetched_at).total_seconds() // 60))
                    return CachedContext(
                        payload=current.payload,
                        fetched_at=current.fetched_at,
                        expires_at=current.expires_at,
                        is_stale=True,
                        warning=f"{provider} refresh failed ({detail}); using {age_minutes}m old context",
                    )
                return CachedContext(
                    payload={}, fetched_at=now, expires_at=now,
                    is_stale=True, warning=f"{provider} context unavailable: {detail}",
                )
            expires_at = now + ttl
            self._write(provider, cache_key, effective_date, payload, now, expires_at)
            return CachedContext(payload=payload, fetched_at=now, expires_at=expires_at)
