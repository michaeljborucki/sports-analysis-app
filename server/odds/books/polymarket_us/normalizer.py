"""Polymarket US event -> odds_snapshot rows. Pure functions, no I/O.

Input: one event from the public gateway (`GET /v1/events/slug/{slug}` ->
`.event`; the bare event dict is accepted too).

Price semantics (verified live against the order book): every market is ONE
instrument with a long and a short side; the book is the LONG side's.
`marketSides[i].quote.value` is the price to BUY that side (long = best
offer, short = 1 - best long bid). We only ever surface that buy price
("always surface the ASK"), never `price` (a bid/mark). No quote -> that side
can't be bought -> no row.

Fees: taker fee per contract = Θ·p·(1-p), Θ = the market's feeCoefficient.
Effective cost c = p + Θ·p·(1-p), converted to American odds rounded AGAINST
the bettor (math.floor — same convention as the kalshi / polymarket intl
normalizers).

What is filtered (and counted in NormalizedEvent.skipped, never silently):
  - market closed / inactive / status != MARKET_STATUS_OPEN
  - side not tradable, quote missing/unparseable, p <= 0 or p >= 1, c >= 1
  - crossed book: both sides quoted and long + short < 1.00 (buying both
    would be a riskless profit -> stale/corrupt data; both sides dropped)
  - live / started events (matched commence <= fetched_at) unless
    include_live=True — mirrors kalshi / polymarket intl (pre-game only)
  - No sides of 3-way "winner" markets (they are double-chance/lay bets; the
    app has no key with that meaning)
  - duplicate PKs (first market by slug order wins)
Lopsided-but-real lines are NOT dropped (no overround gate): an ask is a
buyable price, so it can't create a phantom edge; it just looks expensive.
"""
from __future__ import annotations

import collections
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from ...player_names import normalize_player_name
from ..coral33.event_matcher import _normalize_team
from . import mapping
from .mapping import BOOK_KEY  # re-exported


logger = logging.getLogger(__name__)

DEFAULT_FEE_COEFFICIENT = 0.0695
OPEN_STATUS = "MARKET_STATUS_OPEN"

__all__ = [
    "BOOK_KEY", "DEFAULT_FEE_COEFFICIENT", "NormalizedEvent",
    "buy_price_to_american", "american_from_book", "normalize_event",
]


# ── price math ──────────────────────────────────────────────────────────

def buy_price_to_american(p: float, fee_coefficient: float = DEFAULT_FEE_COEFFICIENT) -> int | None:
    """Buy price (0..1) -> fee-adjusted American odds, rounded against the
    bettor. None when p is outside (0, 1) or the fee eats the whole payout."""
    try:
        p = float(p)
        theta = DEFAULT_FEE_COEFFICIENT if fee_coefficient is None else float(fee_coefficient)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or not math.isfinite(theta) or p <= 0 or p >= 1:
        return None
    cost = p + theta * p * (1 - p)
    profit = 1.0 - cost
    if cost <= 0 or profit <= 0:
        return None
    if cost > profit:
        return math.floor(-cost / profit * 100)
    return math.floor(profit / cost * 100)


def _num(v) -> float | None:
    if isinstance(v, dict):
        v = v.get("value")
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def american_from_book(
    bids: list[dict], offers: list[dict], is_long: bool, fee_coefficient: float,
) -> tuple[int | None, float | None]:
    """Order book for ONE market (levels like {"px": {"value": "0.20"},
    "qty": "140045.32"}; bids highest-first, offers lowest-first — the best
    level is still picked by price, so unsorted input is safe).

    Long buy = best offer; short buy = 1 - best bid. Returns
    (american_after_fee, max_stake_dollars = buy_price * qty at that top
    level) or (None, None) when that side can't be bought."""
    levels = offers if is_long else bids
    best: tuple[float, float] | None = None
    for lvl in levels or ():
        if not isinstance(lvl, dict):
            continue
        px = _num(lvl.get("px"))
        qty = _num(lvl.get("qty"))
        if px is None or qty is None or qty <= 0 or not (0 < px < 1):
            continue
        better = best is None or (px < best[0] if is_long else px > best[0])
        if better:
            best = (px, qty)
    if best is None:
        return None, None
    px, qty = best
    buy = px if is_long else 1.0 - px
    american = buy_price_to_american(buy, fee_coefficient)
    if american is None:
        return None, None
    return american, round(buy * qty, 2)


# ── result type ─────────────────────────────────────────────────────────

@dataclass
class NormalizedEvent:
    rows: list[dict]                       # odds_snapshot rows
    unmapped: collections.Counter          # sportsMarketType -> markets skipped (no app key / unparseable)
    event_id: str | None                   # matched app event_id, None if unmatched (then rows == [])
    # Everything else that was dropped, by reason (e.g. "closed",
    # "no_quote", "live_event", "duplicate_pk:<type>"). Observability only.
    skipped: collections.Counter = field(default_factory=collections.Counter)


# ── team resolution ─────────────────────────────────────────────────────

def _combine(a: str, b: str) -> str:
    a, b = (a or "").strip(), (b or "").strip()
    if not a:
        return b
    if not b:
        return a
    la, lb = a.lower(), b.lower()
    if lb in la:
        return a
    if la in lb:
        return b
    return f"{a} {b}"


def _team_candidates(team: dict, soccer: bool) -> list[str]:
    """Full-name guesses for one Polymarket team, best first. The gateway is
    inconsistent per league: NBA name="Warriors"/safeName="Golden State",
    NFL name="Pittsburgh Steelers"/safeName="PIT Steelers", NHL
    safeName="Tampa Bay Lightning", MLB name="Tampa Bay Rays", WNBA
    name="Golden State"/alias="Valkyries", soccer name="Arsenal FC"."""
    name = (team.get("name") or "").strip()
    safe = (team.get("safeName") or "").strip()
    alias = (team.get("alias") or "").strip()
    if soccer:
        out = [safe, name, re.sub(r"(^FC\s+|\s+FC$)", "", name).strip(), _combine(safe, name)]
    else:
        out = [
            _combine(safe, name), _combine(name, alias), _combine(safe, alias),
            name, safe,
        ]
    seen: list[str] = []
    for c in out:
        if c and c not in seen:
            seen.append(c)
    return seen


def _tokens(s: str, sport_key: str) -> set[str]:
    return set(_normalize_team(s, {}, sport_key).split())


def _score(team: dict, cands: list[str], canon: str, sport_key: str) -> int:
    nc = _normalize_team(canon, {}, sport_key)
    if any(_normalize_team(c, {}, sport_key) == nc for c in cands):
        return 3
    ctoks = set(nc.split())
    for key in ("alias", "name", "abbreviation"):
        v = (team.get(key) or "").strip()
        if v and _tokens(v, sport_key) and _tokens(v, sport_key) <= ctoks:
            return 2
    best = max((len(_tokens(c, sport_key) & ctoks) for c in cands), default=0)
    return 1 if best else 0


def _resolve_teams(
    event: dict, sport_key: str, commence: datetime,
    match_event: Callable[[str, str, str, datetime], dict | None],
) -> tuple[dict, dict[int, str]] | None:
    teams = [t for t in (event.get("teams") or []) if isinstance(t, dict) and t.get("id") is not None]
    if len(teams) != 2:
        return None
    soccer = sport_key == "soccer"
    ca = _team_candidates(teams[0], soccer)
    cb = _team_candidates(teams[1], soccer)
    pairs = sorted(
        ((i, j) for i in range(len(ca)) for j in range(len(cb))),
        key=lambda ij: (ij[0] + ij[1], ij),
    )
    matched = None
    for i, j in pairs:
        matched = match_event(sport_key, ca[i], cb[j], commence)
        if matched:
            break
    if not matched:
        return None
    home, away = matched.get("home_team"), matched.get("away_team")
    if not home or not away:
        return None
    a_home = _score(teams[0], ca, home, sport_key) + _score(teams[1], cb, away, sport_key)
    a_away = _score(teams[0], ca, away, sport_key) + _score(teams[1], cb, home, sport_key)
    if a_home == a_away:
        hint = (teams[0].get("ordering") or "").lower()
        if hint == "home":
            a_home += 1
        elif hint == "away":
            a_away += 1
        else:
            return None
    if a_home > a_away:
        id_map = {teams[0]["id"]: home, teams[1]["id"]: away}
    else:
        id_map = {teams[0]["id"]: away, teams[1]["id"]: home}
    return matched, id_map


# ── market helpers ──────────────────────────────────────────────────────

def _parse_dt(s) -> datetime | None:
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _market_open(m: dict) -> bool:
    if m.get("closed") or m.get("active") is False:
        return False
    status = m.get("status")
    return status is None or status == OPEN_STATUS


def _sides(m: dict) -> tuple[dict, dict] | None:
    sides = [s for s in (m.get("marketSides") or []) if isinstance(s, dict)]
    if len(sides) != 2:
        return None
    long_ = [s for s in sides if s.get("long") is True]
    short = [s for s in sides if s.get("long") is False]
    if len(long_) != 1 or len(short) != 1:
        return None
    return long_[0], short[0]


def _buy(side: dict) -> float | None:
    if side.get("tradable") is False:
        return None
    p = _num(side.get("quote"))
    if p is None or p <= 0 or p >= 1:
        return None
    return p


def _yes_no(side: dict) -> str | None:
    d = (side.get("description") or "").strip().lower()
    if d in ("yes", "over"):
        return "Over"
    if d in ("no", "under"):
        return "Under"
    return None


_PROP_Q_RX = re.compile(r"^Will (.+?) (?:record|score|throw) (?:at least )?\d")
_PROP_T_RX = re.compile(r"^(.+?) (?:over )?\d+(?:\.\d+)?\+? ")


def _player_name(m: dict) -> str | None:
    hit = _PROP_Q_RX.match((m.get("question") or "").strip())
    if hit:
        return hit.group(1).strip()
    hit = _PROP_T_RX.match((m.get("title") or "").strip())
    return hit.group(1).strip() if hit else None


def _imbalance(m: dict) -> float:
    s = _sides(m)
    if s is None:
        return 9.0
    pl, ps = _buy(s[0]), _buy(s[1])
    if pl is not None and ps is not None:
        return abs(pl - ps)
    if pl is not None:
        return 2 * abs(pl - 0.5) + 1.0     # one-sided: rank behind two-sided
    if ps is not None:
        return 2 * abs(ps - 0.5) + 1.0
    return 9.0


# eventState.marketGroupStats id fragment per period suffix.
_MGS_PERIOD = {
    "": "full-game", "_h1": "1st-half", "_h2": "2nd-half",
    "_q1": "1st-quarter", "_q2": "2nd-quarter", "_q3": "3rd-quarter", "_q4": "4th-quarter",
    "_p1": "1st-period", "_p2": "2nd-period", "_p3": "3rd-period",
    "_1st_5_innings": "first-5-innings",
}


def _published_main_line(event: dict, kind: str, suffix: str) -> float | None:
    es = event.get("eventState") or {}
    fam = {"spread": "spread", "total": "totals"}.get(kind)
    if fam is None:
        return None
    frag = _MGS_PERIOD.get(suffix)
    for g in es.get("marketGroupStats") or []:
        if frag and g.get("marketGroupId") == f"game-lines/{fam}/{frag}":
            return _num(g.get("line"))
    if suffix == "":
        return _num(es.get("mainSpreadLine" if kind == "spread" else "mainTotalLine"))
    return None


def _pick_main_markets(event: dict, classified: list[tuple[dict, str, str, str]]) -> set[str]:
    """Market slugs that carry the MAIN line of their group.

    Group = (kind, suffix) for spreads/totals, + team for team totals. Main =
    the line Polymarket publishes in eventState (mainSpreadLine/mainTotalLine
    or marketGroupStats; spreads compared by |line|) — when several markets
    sit on it, or none is published, the most balanced market (|long ask -
    short ask| smallest) wins, which is how books choose a main line."""
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for m, kind, suffix, _mk in classified:
        if kind not in ("spread", "total", "team_total"):
            continue
        team = None
        if kind == "team_total":
            s = _sides(m)
            team = s[0].get("teamId") if s else None
        groups[(kind, suffix, team)].append(m)
    mains: set[str] = set()
    for (kind, suffix, _team), ms in groups.items():
        pub = _published_main_line(event, kind, suffix)
        pool = ms
        if pub is not None:
            on = [m for m in ms if _num(m.get("line")) is not None
                  and abs(abs(_num(m.get("line"))) - abs(pub)) < 1e-9]
            if on:
                pool = on
        best = min(pool, key=lambda m: (_imbalance(m), abs(_num(m.get("line")) or 0.0), m.get("slug") or ""))
        if _imbalance(best) < 9.0:
            mains.add(best.get("slug") or "")
    return mains


# ── main entry ──────────────────────────────────────────────────────────

def normalize_event(
    event: dict,
    league_slug: str,
    fetched_at: datetime,
    match_event: Callable[[str, str, str, datetime], dict | None],
    *,
    sport_key: str | None = None,
    include_live: bool = False,
) -> NormalizedEvent:
    """One Polymarket US event -> NormalizedEvent (see module docstring).

    `match_event(sport_key, team_a, team_b, commence_utc)` returns
    {"event_id","home_team","away_team","commence_time"} or None
    (PolymarketEventMatcher.match contract). `sport_key` overrides the
    league_slug -> sport lookup (mapping.LEAGUE_TO_SPORT)."""
    if isinstance(event, dict) and isinstance(event.get("event"), dict):
        event = event["event"]
    unmapped: collections.Counter = collections.Counter()
    skipped: collections.Counter = collections.Counter()
    league = (league_slug or "").lower()
    sport = sport_key or mapping.LEAGUE_TO_SPORT.get(league)
    if not sport or not isinstance(event, dict):
        skipped[f"unknown_league:{league}"] += 1
        return NormalizedEvent([], unmapped, None, skipped)

    markets = sorted(
        (m for m in (event.get("markets") or []) if isinstance(m, dict)),
        key=lambda m: str(m.get("slug") or ""),
    )
    # Type-level classification first so the unmapped report is complete
    # even when the event doesn't match.
    classified: list[tuple[dict, str, str, str]] = []
    for m in markets:
        smt = m.get("sportsMarketType") or "(none)"
        kind, info, mk = mapping.classify(sport, smt)
        if kind is None:
            unmapped[smt] += 1
            continue
        if not _market_open(m):
            skipped["closed"] += 1
            continue
        classified.append((m, kind, info, mk))

    commence = _parse_dt(event.get("startTime")) or _parse_dt(event.get("startDate"))
    if commence is None:
        skipped["no_start_time"] += 1
        return NormalizedEvent([], unmapped, None, skipped)
    resolved = _resolve_teams(event, sport, commence, match_event)
    if resolved is None:
        skipped["unmatched_event"] += 1
        return NormalizedEvent([], unmapped, None, skipped)
    matched, id_map = resolved
    event_id = matched["event_id"]
    real_commence = _parse_dt(matched.get("commence_time")) or commence
    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
    if not include_live and real_commence <= now:
        skipped["live_event"] += 1
        return NormalizedEvent([], unmapped, event_id, skipped)

    league_key = league_title = None
    if sport == "soccer":
        league_key, league_title = mapping.SOCCER_LEAGUES.get(league, (None, None))

    base = {
        "event_id": event_id,
        "sport_key": sport,
        "league_key": league_key,
        "league_title": league_title,
        "home_team": matched["home_team"],
        "away_team": matched["away_team"],
        "commence_time": real_commence,
        "bookmaker_key": BOOK_KEY,
        "fetched_at": fetched_at,
        "max_stake_dollars": None,
        "wager_type": None,
    }

    mains = _pick_main_markets(event, classified)
    rows: list[dict] = []
    seen_pk: set[tuple] = set()

    def emit(m: dict, smt: str, side: dict, market_key: str, outcome: str,
             point: float | None, fee: float) -> bool:
        p = _buy(side)
        if p is None:
            skipped["no_quote"] += 1
            return False
        american = buy_price_to_american(p, fee)
        if american is None:
            skipped["bad_price"] += 1
            return False
        pk = (event_id, market_key, outcome, point)
        if pk in seen_pk:
            skipped[f"duplicate_pk:{smt}"] += 1
            return False
        seen_pk.add(pk)
        rows.append({
            **base,
            "market_key": market_key,
            "outcome_name": outcome,
            "outcome_point": point,
            "price_american": american,
            "_market_slug": m.get("slug"),
            "_long": bool(side.get("long")),
            "_fee": fee,
        })
        return True

    for m, kind, info, mk in classified:
        smt = m.get("sportsMarketType")
        sides = _sides(m)
        if sides is None:
            unmapped[smt] += 1
            continue
        long_s, short_s = sides
        fee = _num(m.get("feeCoefficient"))
        if fee is None or fee < 0:
            fee = DEFAULT_FEE_COEFFICIENT
        pl, ps = _buy(long_s), _buy(short_s)
        if pl is not None and ps is not None and pl + ps < 1.0 - 1e-9:
            skipped["crossed_book"] += 1
            continue

        if kind == "ml":
            names = [id_map.get(s.get("teamId")) for s in sides]
            if None in names or names[0] == names[1]:
                unmapped[smt] += 1
                continue
            for s, name in zip(sides, names):
                emit(m, smt, s, mk, name, None, fee)

        elif kind == "ml3":
            # Only the Yes (long) side of each per-outcome market; the No side
            # is a double-chance/lay bet the app has no key for.
            yes = long_s if (long_s.get("description") or "").strip().lower() == "yes" else None
            if yes is None:
                unmapped[smt] += 1
                continue
            tid = yes.get("teamId")
            if tid is None:
                q = f"{m.get('question') or ''} {m.get('title') or ''}".lower()
                if not re.search(r"\b(tie|tied|draw)\b", q):
                    unmapped[smt] += 1
                    continue
                name = "Draw"
            else:
                name = id_map.get(tid)
                if name is None:
                    unmapped[smt] += 1
                    continue
            emit(m, smt, yes, mk, name, None, fee)
            skipped["three_way_no_side"] += 1

        elif kind == "spread":
            out = []
            for s in sides:
                name = id_map.get(s.get("teamId"))
                pt = _num((s.get("description") or "").replace("+", ""))
                out.append((s, name, pt))
            if any(n is None or p is None for _, n, p in out) or out[0][1] == out[1][1] \
                    or abs(out[0][2] + out[1][2]) > 1e-9:
                unmapped[smt] += 1
                continue
            key = mk if (m.get("slug") or "") in mains else (mapping.alt_key(kind, info, sport) or mk)
            for s, name, pt in out:
                emit(m, smt, s, key, name, float(pt), fee)

        elif kind == "total":
            line = _num(m.get("line"))
            labels = [_yes_no(s) for s in sides]
            if line is None or sorted(labels, key=str) != ["Over", "Under"] \
                    or any(s.get("teamId") is not None for s in sides):
                unmapped[smt] += 1
                continue
            key = mk if (m.get("slug") or "") in mains else (mapping.alt_key(kind, info, sport) or mk)
            for s, lab in zip(sides, labels):
                emit(m, smt, s, key, lab, float(line), fee)

        elif kind == "team_total":
            line = _num(m.get("line"))
            labels = [_yes_no(s) for s in sides]
            team = id_map.get(long_s.get("teamId"))
            if line is None or team is None or sorted(labels, key=str) != ["Over", "Under"] \
                    or short_s.get("teamId") not in (None, long_s.get("teamId")):
                unmapped[smt] += 1
                continue
            key = mk if (m.get("slug") or "") in mains else (mapping.alt_key(kind, info, sport) or mk)
            for s, lab in zip(sides, labels):
                emit(m, smt, s, key, f"{team} {lab}", float(line), fee)

        elif kind == "nrfi":
            # "Will any run be scored in the 1st inning?" Yes = a run scores
            # (YRFI). App convention (kalshi KXMLBRFI, coral33, Odds API
            # bridge Over 0.5 -> Yes): nrfi "Yes" = run scored, "No" = NRFI.
            labels = [(s.get("description") or "").strip().lower() for s in sides]
            if sorted(labels) != ["no", "yes"]:
                unmapped[smt] += 1
                continue
            for s, lab in zip(sides, labels):
                emit(m, smt, s, mk, "Yes" if lab == "yes" else "No", None, fee)

        elif kind == "prop":
            line = _num(m.get("line"))
            display = _player_name(m)
            labels = [_yes_no(s) for s in sides]
            if line is None or not display or sorted(labels, key=str) != ["Over", "Under"]:
                unmapped[smt] += 1
                continue
            player = normalize_player_name(display, sport, info)
            if not player:
                unmapped[smt] += 1
                continue
            # "N+" / "at least N" == Over N-0.5. A half-point line is
            # already an O/U threshold.
            point = float(line) - 0.5 if float(line).is_integer() else float(line)
            for s, lab in zip(sides, labels):
                emit(m, smt, s, info, f"{player} {lab}", point, fee)

        else:  # defensive
            unmapped[smt] += 1

    if unmapped or skipped:
        logger.debug(
            "polymarket_us %s: %d rows; unmapped=%s skipped=%s",
            event.get("slug"), len(rows), dict(unmapped), dict(skipped),
        )
    return NormalizedEvent(rows, unmapped, event_id, skipped)
