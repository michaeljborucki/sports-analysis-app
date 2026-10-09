"""Record which Novig markets stay tradable once a game goes in-play.

Novig has no per-market "available live" flag: markets carry only a status,
and events flip OPEN_PREGAME -> OPEN_INGAME at start. So we watch:

  every PREGAME_S : events?status=OPEN_PREGAME + markets?eventStatus=OPEN_PREGAME
                    (the inventory each event had before start)
  every INGAME_S  : events?status=OPEN_INGAME + markets?eventStatus=OPEN_INGAME
                    (what is listed in-game, and with which status)

and keep it in logs/novig_live_markets.sqlite. `--report` turns that into a
league x market-type table: of the markets that existed pregame, what share
were seen OPEN in-game, how often they sat SUSPENDED, and which types only
appear in-game.

READ-ONLY, public unauthenticated catalog routes, no keys. Never trades.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "logs" / "novig_live_markets.sqlite"
BASE = "https://api.novig.com"
PREGAME_S = 600
INGAME_S = 60
PAGE_GAP_S = 1.0

logger = logging.getLogger("novig_live_recorder")

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY, league TEXT, sport TEXT, description TEXT,
  starts_ts INTEGER, first_ingame_ms INTEGER, last_status TEXT, last_seen_ms INTEGER);
CREATE TABLE IF NOT EXISTS pregame (
  market_id TEXT PRIMARY KEY, event_id TEXT, market_type TEXT, strike TEXT,
  description TEXT, last_seen_ms INTEGER);
CREATE TABLE IF NOT EXISTS ingame (
  market_id TEXT PRIMARY KEY, event_id TEXT, market_type TEXT, strike TEXT,
  description TEXT, first_seen_ms INTEGER, last_seen_ms INTEGER,
  n_obs INTEGER DEFAULT 0, n_open INTEGER DEFAULT 0, last_status TEXT);
CREATE INDEX IF NOT EXISTS pregame_event ON pregame(event_id);
CREATE INDEX IF NOT EXISTS ingame_event ON ingame(event_id);
"""


def _db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.executescript(SCHEMA)
    return c


async def _paged(http: httpx.AsyncClient, path: str, params: dict) -> list[dict]:
    items, after = [], None
    while True:
        p = dict(params, limit=5000)
        if after:
            p["after"] = after
        for attempt in range(6):
            r = await http.get(path, params=p)
            if r.status_code != 429:
                break
            await asyncio.sleep(min(60, 5 * 2 ** attempt))
        r.raise_for_status()
        body = r.json()
        items.extend(body.get("items") or [])
        after = body.get("next")
        if not after:
            return items
        await asyncio.sleep(PAGE_GAP_S)


def _upsert_events(db: sqlite3.Connection, events: list[dict], now_ms: int) -> None:
    for e in events:
        ingame = now_ms if e.get("status") == "OPEN_INGAME" else None
        db.execute(
            """INSERT INTO events VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(event_id) DO UPDATE SET
                 last_status=excluded.last_status, last_seen_ms=excluded.last_seen_ms,
                 starts_ts=excluded.starts_ts,
                 first_ingame_ms=COALESCE(events.first_ingame_ms, excluded.first_ingame_ms)""",
            (e["eventId"], e.get("league"), e.get("sport"), e.get("description"),
             e.get("startsTs"), ingame, e.get("status"), now_ms))


async def pregame_pass(http: httpx.AsyncClient, db: sqlite3.Connection) -> None:
    now = int(time.time() * 1000)
    events = await _paged(http, "/v3/public/catalog/events", {"status": "OPEN_PREGAME"})
    await asyncio.sleep(PAGE_GAP_S)
    markets = await _paged(http, "/v3/public/catalog/markets", {"eventStatus": "OPEN_PREGAME"})
    _upsert_events(db, events, now)
    db.executemany(
        """INSERT INTO pregame VALUES (?,?,?,?,?,?)
           ON CONFLICT(market_id) DO UPDATE SET last_seen_ms=excluded.last_seen_ms""",
        [(m["marketId"], m["eventId"], m.get("marketType"), m.get("strike"),
          m.get("description"), now) for m in markets])
    db.commit()
    logger.info("pregame: %d events, %d markets", len(events), len(markets))


async def ingame_pass(http: httpx.AsyncClient, db: sqlite3.Connection) -> None:
    now = int(time.time() * 1000)
    events = await _paged(http, "/v3/public/catalog/events", {"status": "OPEN_INGAME"})
    await asyncio.sleep(PAGE_GAP_S)
    markets = await _paged(http, "/v3/public/catalog/markets", {"eventStatus": "OPEN_INGAME"})
    _upsert_events(db, events, now)
    db.executemany(
        """INSERT INTO ingame VALUES (?,?,?,?,?,?,?,1,?,?)
           ON CONFLICT(market_id) DO UPDATE SET
             last_seen_ms=excluded.last_seen_ms, n_obs=ingame.n_obs+1,
             n_open=ingame.n_open+excluded.n_open, last_status=excluded.last_status""",
        [(m["marketId"], m["eventId"], m.get("marketType"), m.get("strike"),
          m.get("description"), now, now, int(m.get("status") == "OPEN"), m.get("status"))
         for m in markets])
    db.commit()
    logger.info("ingame: %d events, %d markets", len(events), len(markets))


async def run() -> None:
    db = _db()
    last_pre = 0.0
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0,
                                 headers={"Accept": "application/json"}) as http:
        while True:
            t0 = time.monotonic()
            try:
                if t0 - last_pre >= PREGAME_S:
                    await pregame_pass(http, db)
                    last_pre = t0
                    await asyncio.sleep(PAGE_GAP_S)
                await ingame_pass(http, db)
            except Exception as e:                       # keep recording through blips
                logger.warning("pass failed: %s", e)
            await asyncio.sleep(max(5.0, INGAME_S - (time.monotonic() - t0)))


# Novig re-lists markets in-game under NEW ids, so pregame and in-game are
# matched on (event, market type, strike). Only games we saw pregame count.
REPORT_SQL = """
WITH started AS (
  SELECT * FROM events WHERE first_ingame_ms IS NOT NULL
    AND event_id IN (SELECT event_id FROM pregame)),
live AS (
  SELECT event_id, market_type, strike, SUM(n_open) AS n_open, SUM(n_obs) AS n_obs
  FROM ingame GROUP BY event_id, market_type, strike),
pre AS (
  SELECT DISTINCT s.league, p.event_id, p.market_type, p.strike FROM pregame p JOIN started s USING (event_id)),
j AS (
  SELECT pre.*, l.event_id IS NOT NULL AS listed_live, COALESCE(l.n_open, 0) > 0 AS seen_open,
         COALESCE(l.n_open * 1.0 / NULLIF(l.n_obs, 0), 0) AS open_share
  FROM pre LEFT JOIN live l USING (event_id, market_type, strike))
SELECT league, market_type, COUNT(DISTINCT event_id) AS events, COUNT(*) AS pre_mkts,
       SUM(listed_live), SUM(seen_open),
       ROUND(100.0 * SUM(seen_open) / COUNT(*), 0),
       ROUND(100.0 * AVG(CASE WHEN seen_open THEN open_share END), 0)
FROM j GROUP BY league, market_type ORDER BY league, 7 DESC, pre_mkts DESC
"""

LIVE_ONLY_SQL = """
SELECT e.league, i.market_type, COUNT(DISTINCT i.event_id), COUNT(*), SUM(i.n_open > 0)
FROM ingame i JOIN events e USING (event_id)
WHERE i.event_id IN (SELECT event_id FROM pregame)
  AND NOT EXISTS (SELECT 1 FROM pregame p WHERE p.event_id = i.event_id
                  AND p.market_type = i.market_type AND p.strike IS i.strike)
GROUP BY e.league, i.market_type ORDER BY e.league, 4 DESC
"""


def report(min_events: int) -> None:
    db = _db()
    n = db.execute("SELECT COUNT(*) FROM events WHERE first_ingame_ms IS NOT NULL").fetchone()[0]
    m = db.execute("SELECT COUNT(*) FROM events WHERE first_ingame_ms IS NOT NULL AND event_id IN (SELECT event_id FROM pregame)").fetchone()[0]
    print(f"Games seen in-play: {n} ({m} also seen pregame — only those are counted)\n")
    print("Pregame markets of games that went live — how many stayed tradable in-game")
    print(f"{'league':<14}{'market type':<28}{'games':>6}{'pre mkts':>9}{'listed':>8}{'open':>6}{'% open':>8}{'% time open':>12}")
    for r in db.execute(REPORT_SQL):
        if r[2] < min_events:
            continue
        print(f"{(r[0] or '?'):<14}{(r[1] or '?'):<28}{r[2]:>6}{r[3]:>9}{r[4]:>8}{r[5]:>6}"
              f"{(r[6] if r[6] is not None else 0):>7.0f}%{(r[7] if r[7] is not None else 0):>11.0f}%")
    print("\nIn-game-only markets (never listed pregame)")
    for r in db.execute(LIVE_ONLY_SQL):
        if r[2] >= min_events:
            print(f"{(r[0] or '?'):<14}{(r[1] or '?'):<28}{r[2]:>6} games{r[3]:>7} mkts{r[4]:>7} seen open")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--min-events", type=int, default=1)
    a = ap.parse_args()
    if a.report:
        report(a.min_events)
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run())


if __name__ == "__main__":
    main()
