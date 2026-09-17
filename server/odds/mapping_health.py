"""Persistent diagnostics; suggestions never change odds matching."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from difflib import get_close_matches
from pathlib import Path

from .player_names import normalize_player_name


class MappingHealth:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS mapping_issues (
                identity TEXT PRIMARY KEY, kind TEXT, sport TEXT, source TEXT,
                event TEXT, raw_name TEXT, market TEXT, candidates TEXT,
                first_seen TEXT, last_seen TEXT, hits INTEGER, resolved INTEGER DEFAULT 0)''')
            db.execute('CREATE TABLE IF NOT EXISTS mapping_names (sport TEXT, event TEXT, market TEXT, name TEXT, raw TEXT, PRIMARY KEY(sport,event,market,name))')
            db.execute('CREATE TABLE IF NOT EXISTS mapping_audit (id INTEGER PRIMARY KEY, checked_at TEXT)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, *, kind, sport, raw_name, event='', market='', candidates=(), source='coral33', resolved=False):
        if kind == "player_observation":
            with self.connect() as db:
                db.execute("INSERT OR REPLACE INTO mapping_names VALUES (?,?,?,?,?)",
                           (sport, event, market, normalize_player_name(raw_name, sport, market), raw_name))
            return
        identity = _identity(kind, sport, source, event, raw_name, market)
        if resolved:
            with self.connect() as db:
                db.execute("UPDATE mapping_issues SET resolved=1 WHERE identity=?", (identity,))
            return
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('''INSERT INTO mapping_issues VALUES (?,?,?,?,?,?,?,?,?,?,1,0)
                ON CONFLICT(identity) DO UPDATE SET last_seen=excluded.last_seen,
                candidates=excluded.candidates,hits=hits+1,resolved=0''',
                (identity, kind, sport, source, event, raw_name, market,
                 json.dumps(list(candidates)), now, now))

    def listing(self):
        with self.connect() as db:
            rows = [dict(r) for r in db.execute(
                'SELECT * FROM mapping_issues ORDER BY resolved,last_seen DESC LIMIT 1000')]
            total = db.execute('SELECT count(*) FROM mapping_issues').fetchone()[0]
            checked = db.execute('SELECT checked_at FROM mapping_audit WHERE id=1').fetchone()
        for row in rows:
            row['candidates'] = json.loads(row['candidates'])
        return {'issues': rows, 'total': total, 'last_player_check': checked[0] if checked else None}

    def audit_players(self, rows):
        groups = defaultdict(lambda: defaultdict(set))
        for row in rows:
            market = row['market_key']
            if not market.startswith(('player_', 'batter_', 'pitcher_')):
                continue
            # Coverage is checked at player/stat level, not threshold: a missing
            # alternate threshold must not masquerade as a name mismatch.
            raw = row.get('outcome_description') or re.sub(r' (Over|Under)$', '', row['outcome_name'])
            if raw in ('Over', 'Under'):
                continue
            sport = row['sport_key']
            name = normalize_player_name(raw, sport, market)
            groups[(sport, row['event_id'], market.removesuffix('_alternate'))][row['bookmaker_key']].add((name, raw))
        with self.connect() as db:
            previous = [dict(r) for r in db.execute("SELECT * FROM mapping_issues WHERE resolved=0 AND kind IN ('player_name','player_coverage')")]
            original_names = {(r["sport"], r["event"], r["market"], r["name"]): r["raw"]
                              for r in db.execute("SELECT * FROM mapping_names")}
        # Disappearing or stale odds are not proof a mapping was fixed.
        # Resolve only when both sources now contain the same canonical name.
        with self.connect() as db:
            for issue in previous:
                books = groups.get((issue['sport'], issue['event'], issue['market']), {})
                canonical = normalize_player_name(issue['raw_name'], issue['sport'], issue['market'])
                coral = {n for n, _ in books.get('coral33', ())}
                other = {n for b, ps in books.items() if b != 'coral33' for n, _ in ps}
                if canonical in coral & other:
                    db.execute('UPDATE mapping_issues SET resolved=1 WHERE identity=?', (issue['identity'],))
        for (sport, event, market), books in groups.items():
            others = {name for book, players in books.items() if book != 'coral33' for name, _ in players}
            for name, raw in books.get('coral33', ()):
                if name in others:
                    continue
                candidates = get_close_matches(name, sorted(others), n=5, cutoff=0.65)
                self.record(kind='player_name' if candidates else 'player_coverage', sport=sport,
                            event=event, market=market, raw_name=original_names.get((sport,event,market,name), raw), candidates=candidates)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO mapping_audit VALUES (1,?)',
                       (datetime.now(timezone.utc).isoformat(),))

    def purge(self, now=None, older_than_days: int = 3) -> int:
        """Drop issues whose fixture is long past.

        Rows never expired, so 77% of the table was dead fixtures that can
        never resolve (resolution needs BOTH books to post the name again)
        while the 1000-row listing cap pushed live issues off the page.
        """
        now = now or datetime.now(timezone.utc)
        cutoff = now - timedelta(days=older_than_days)
        removed = 0
        with self.connect() as db:
            rows = [dict(r) for r in db.execute(
                'SELECT identity, event, last_seen FROM mapping_issues')]
            for row in rows:
                # Team rows carry a kickoff time — judge those on the fixture,
                # because a coral33 board that still lists a game from last
                # week can never resolve no matter how fresh the hit is.
                # Player rows carry an event_id, so they age out on last_seen.
                stamp = None
                for value in (row['event'], row['last_seen']):
                    try:
                        stamp = datetime.fromisoformat(
                            (value or '').replace('Z', '+00:00'))
                        break
                    except (ValueError, TypeError, AttributeError):
                        continue
                if stamp is None or stamp >= cutoff:
                    continue
                db.execute('DELETE FROM mapping_issues WHERE identity=?',
                           (row['identity'],))
                removed += 1
        if removed:
            logging.info('Mapping health: purged %d issues older than %dd',
                         removed, older_than_days)
        return removed

    async def run(self, cache):
        while True:
            try:
                await asyncio.to_thread(self.audit_players, await asyncio.to_thread(cache.all_current_cached))
                await asyncio.to_thread(self.purge)
            except Exception:
                logging.exception('Mapping health player audit failed')
            await asyncio.sleep(60)


def _identity_event(kind: str, event: str) -> str:
    """Bucket a team issue's event key to its UTC date.

    `event` is an Odds API event_id for player issues (stable) but a coral33
    kickoff timestamp for team issues — and coral33 nudges that timestamp
    repeatedly while an order of play firms up. Keying on the raw timestamp
    minted a fresh row per nudge (`F Tiafoe / B Shelton` had six) and meant a
    later resolve could never close the earlier rows. The calendar day is
    stable, and the matcher already refuses to cross days for these sports.
    """
    if not kind.startswith("team"):
        return event
    try:
        return datetime.fromisoformat(
            (event or "").replace("Z", "+00:00")
        ).astimezone(timezone.utc).date().isoformat()
    except (ValueError, TypeError, AttributeError):
        return event


def _identity(kind, sport, source, event, raw_name, market) -> str:
    return json.dumps(
        [kind, sport, source, _identity_event(kind, event), raw_name, market]
    )


def classify_team_issue(raw_name: str, events: list[dict]) -> str:
    """`team` (a mapping bug worth fixing) vs `team_coverage` (a competition
    the Odds API side simply doesn't carry).

    coral33 pulls leagues we never buy odds for — Argentine Primera, the Gulf
    leagues, K-League — and every one of their fixtures is a permanent orphan.
    When NEITHER club resembles anything on the sport's slate, that's the
    cause, and it does not belong in the same queue as a missing alias.
    """
    names = sorted({
        str(e.get(side) or "").strip().lower()
        for e in events for side in ("home_team", "away_team")
        if e.get(side)
    })
    for side in (raw_name or "").split(" / "):
        side = side.strip().lower()
        if side and get_close_matches(side, names, n=1, cutoff=0.85):
            return "team"
    return "team_coverage"


def team_candidates(raw_name, commence, events, sport=None):
    """Suggest only fixtures in the same time window; never auto-join them.

    The window follows the matcher's own per-sport window. A hard-coded 30
    minutes made the suggestion blind for exactly the sports whose matcher is
    most permissive: a UFC card 13h off matched nothing, so the issue showed
    "No candidate" and read like an unfixable name, not a clock problem.
    """
    from .books.coral33.event_matcher import (
        MATCH_WINDOW_MIN, SPORT_WINDOW_MINUTES,
    )
    window_s = SPORT_WINDOW_MINUTES.get(sport, MATCH_WINDOW_MIN) * 60
    when = datetime.fromisoformat(commence.replace('Z', '+00:00'))
    names = []
    for event in events:
        value = event.get('commence_time')
        try:
            start = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
            if abs((start - when).total_seconds()) > window_s:
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        names.append(f"{event['away_team']} / {event['home_team']}")
    return get_close_matches(raw_name, sorted(set(names)), n=5, cutoff=0.55)
