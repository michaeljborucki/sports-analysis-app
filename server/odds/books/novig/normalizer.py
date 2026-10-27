"""Novig catalog + order book → odds_snapshot rows. Pure functions only.

Book semantics (Novig v3 spec, verified live 2026-10-03): `orders[outcomeId]`
lists resting BUY orders on that outcome, best price first. Prices are
probabilities; one contract pays 1¢. In a two-outcome market, buying outcome
A as a taker fills against the best resting bid on B, so

    take_price(A) = 1 - best_bid(B)        size = qty resting at that bid

which is exactly how Kalshi's book works (see kalshi/quote_depth.py).
A side with no opposing bid has no take price and produces no row.

PK alignment: every row is written into the slot of a Novig row betting-db
already holds for the same event/line/player (the "sibling"), so the direct
quote overrides the Odds API copy on read instead of duplicating it.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Iterable

from ...player_names import normalize_player_name
from ..coral33.event_matcher import _normalize_team
from .mapping import BOOK_KEY, MAKER_BOOK_KEY, family_for, family_id


# Match windows (minutes) between Novig's startsTs and the cache event's
# commence_time — same per-sport latitude the coral33 matcher uses.
_MATCH_WINDOW_MIN = {"tennis": 720, "ufc": 1500, "boxing": 1500}
_DEFAULT_WINDOW_MIN = 180

_ROUND_SUFFIX_RX = re.compile(
    r"\s+(round of \d+|round \d+|quarterfinals?|semifinals?|finals?|"
    r"(?:\d+(?:st|nd|rd|th) )?qualifying round|qualifying|qualification)$",
    re.IGNORECASE,
)
_SIGNED_NUM_RX = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*$")


# ───────────────────────────── prices ─────────────────────────────

def prob_to_american(p: float) -> int | None:
    """Probability price → American odds, rounded to nearest with exact
    halves toward zero — matches the Odds API's own Novig conversion
    (0.575 → -135, 0.68 → -212 not -213, 0.5 → +100)."""
    if not (0.0 < p < 1.0):
        return None
    raw = -100.0 * p / (1.0 - p) if p > 0.5 else 100.0 * (1.0 - p) / p
    return int(math.copysign(math.floor(abs(raw) + 0.5 - 1e-6), raw))


def _taker_fee_applies(market: dict) -> bool:
    """Game markets charge the taker only in-game (`WHEN_LIVE`); we only
    quote pregame, so only `ALWAYS` markets carry a fee here."""
    fee = market.get("fee") or {}
    return fee.get("charged") == "ALWAYS"


def effective_take_prob(p: float, market: dict) -> float:
    """Per-contract cost of taking at `p`, including the taker fee
    `c * P * (1-P)` when the market charges it pregame."""
    if not _taker_fee_applies(market):
        return p
    try:
        c = float((market.get("fee") or {}).get("coefficient") or 0)
    except (TypeError, ValueError):
        c = 0.0
    return p + c * p * (1.0 - p)


def take_quotes(market: dict, book: dict) -> dict[str, tuple[float, float]]:
    """{outcomeId: (take_prob, max_stake_dollars)} for a two-outcome market.

    take_prob is the raw book price (fee handled by the caller); the stake
    is what a taker can put up at that price: qty resting at the opposing
    best bid × take price × 1¢.
    """
    outcomes = market.get("outcomes") or []
    if len(outcomes) != 2:
        return {}
    orders = (book or {}).get("orders") or {}
    out: dict[str, tuple[float, float]] = {}
    for me, other in ((outcomes[0], outcomes[1]), (outcomes[1], outcomes[0])):
        best = _best_bid(orders.get(other["outcomeId"]) or [])
        if best is None:
            continue
        bid, qty = best
        take = round(1.0 - bid, 4)
        if not (0.0 < take < 1.0):
            continue
        out[me["outcomeId"]] = (take, round(qty * take / 100.0, 2))
    return out


def next_tick(p: float) -> float | None:
    """The next price up on Novig's submittable grid: 0.001 steps through
    0.050, 0.005 steps 0.055-0.945, 0.001 steps 0.950-0.999."""
    k = round(p * 1000)              # work in integer thousandths
    if k < 50:
        k += 1
    elif k < 945:
        k = (k // 5 + 1) * 5         # snap up to the next 0.005 step
        if k == 50:
            k = 55
    elif k < 999:
        k = max(k + 1, 950)
    else:
        return None
    return k / 1000.0


def maker_quotes(market: dict, book: dict) -> dict[str, float]:
    """{outcomeId: maker_prob} — the price you'd post to be first in line.

    One tick above the outcome's current best bid; when that would reach
    the take price (a one-tick spread), join the best bid instead, since
    anything higher would cross and fill as a taker. No bid on the outcome
    means nothing to improve on, so no maker quote.
    """
    outcomes = market.get("outcomes") or []
    if len(outcomes) != 2:
        return {}
    orders = (book or {}).get("orders") or {}
    out: dict[str, float] = {}
    for me, other in ((outcomes[0], outcomes[1]), (outcomes[1], outcomes[0])):
        mine = _best_bid(orders.get(me["outcomeId"]) or [])
        if mine is None:
            continue
        bid = mine[0]
        price = next_tick(bid)
        theirs = _best_bid(orders.get(other["outcomeId"]) or [])
        take = None if theirs is None else round(1.0 - theirs[0], 4)
        if price is None or (take is not None and price >= take - 1e-9):
            price = bid
        if 0.0 < price < 1.0:
            out[me["outcomeId"]] = round(price, 4)
    return out


def _best_bid(levels: list[dict]) -> tuple[float, int] | None:
    """(price, total qty at that price) of the best resting bid."""
    best_p: float | None = None
    qty = 0
    for o in levels:
        try:
            p = float(o["price"])
            q = int(o["qty"])
        except (KeyError, TypeError, ValueError):
            continue
        if q <= 0:
            continue
        if best_p is None or p > best_p + 1e-9:
            best_p, qty = p, q
        elif abs(p - best_p) <= 1e-9:
            qty += q
    return None if best_p is None else (best_p, qty)


# ───────────────────────────── events ─────────────────────────────

def _fold(name: str, sport: str, aliases: dict[str, str] | None = None) -> str:
    return _normalize_team(name, aliases or {}, sport)


def _names_match(novig: str, cache: str) -> bool:
    if not novig or not cache:
        return False
    return (
        novig == cache
        or cache.startswith(novig + " ")   # "georgia" ↔ "georgia bulldogs"
        or novig.startswith(cache + " ")
    )


def split_event_description(description: str) -> tuple[str, str] | None:
    """"Away @ Home [round]" → (away, home). None when not a matchup."""
    if " @ " not in (description or ""):
        return None
    away, home = description.split(" @ ", 1)
    home = _ROUND_SUFFIX_RX.sub("", home.strip())
    return away.strip(), home


def match_event(
    novig_event: dict, sport: str, cache_events: Iterable[dict],
    aliases: dict[str, str] | None = None,
) -> tuple[dict, bool] | None:
    """Find the cache event for a Novig event.

    Returns (cache_event, novig_home_is_cache_home) or None. Both teams
    must match (exact or prefix — Novig's NCAAF names drop the mascot) and
    the start times must fall inside the sport's window; the closest start
    wins. `aliases` is the sport's coral33 alias table (folded name →
    canonical folded name), applied to both sides.
    """
    pair = split_event_description(novig_event.get("description", ""))
    if pair is None:
        return None
    n_away, n_home = (_fold(x, sport, aliases) for x in pair)
    starts = datetime.fromtimestamp(novig_event["startsTs"] / 1000, tz=timezone.utc)
    window_s = _MATCH_WINDOW_MIN.get(sport, _DEFAULT_WINDOW_MIN) * 60
    best: tuple[float, dict, bool] | None = None
    for ev in cache_events:
        c_home = _fold(ev.get("home_team", ""), sport, aliases)
        c_away = _fold(ev.get("away_team", ""), sport, aliases)
        if _names_match(n_home, c_home) and _names_match(n_away, c_away):
            straight = True
        elif _names_match(n_home, c_away) and _names_match(n_away, c_home):
            straight = False
        else:
            continue
        diff = abs((_as_utc(ev["commence_time"]) - starts).total_seconds())
        if diff > window_s:
            continue
        if best is None or diff < best[0]:
            best = (diff, ev, straight)
    return None if best is None else (best[1], best[2])


def _as_utc(ts) -> datetime:
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


# ─────────────────────────── sibling index ───────────────────────────

def _kind_of(market_key: str) -> str | None:
    if market_key.startswith(("player_", "batter_", "pitcher_")):
        return "prop"
    if "team_totals" in market_key:
        return "team_total"
    if market_key.startswith("h2h"):
        return "ml"
    if "spreads" in market_key:
        return "spread"
    if "totals" in market_key:
        return "total"
    return None


def _pt(x) -> float:
    return round(float(x or 0.0), 2)


def build_sibling_index(
    rows: Iterable[dict], events_by_id: dict[str, dict],
    *, exclude_books: frozenset[str] | None = None,
) -> dict[tuple, set[str]]:
    """Index existing Novig rows by what identifies their market, ignoring
    the side, so either side of a Novig market can find its slot.

    With `exclude_books`, index every OTHER book's rows instead (all books
    except those listed) — the fallback slot map for Novig markets the
    Odds API never carried a Novig copy of: the other books' market_key on
    the same line is what Novig's price must share to pair with them.

    Key: (event_id, family_id, line, entity) → {market_key, …}
      ml         line=None,            entity=None
      spread     line=home handicap,   entity=None
      total      line=total,           entity=None
      team_total line=total,           entity=exact team name
      prop       line=line,            entity=canonical player (as encoded)
    """
    index: dict[tuple, set[str]] = {}
    for r in rows:
        book = r.get("bookmaker_key")
        if exclude_books is None:
            if book != BOOK_KEY:
                continue
        elif book in exclude_books:
            continue
        mk = r["market_key"]
        kind = _kind_of(mk)
        if kind is None:
            continue
        eid = r["event_id"]
        name = r["outcome_name"]
        point = r.get("outcome_point")
        if kind == "ml":
            key = (eid, family_id(mk), None, None)
        elif kind == "spread":
            ev = events_by_id.get(eid) or r
            home = ev.get("home_team")
            if name == home:
                line = _pt(point)
            elif name == ev.get("away_team"):
                line = _pt(-float(point or 0.0))
            else:
                continue
            key = (eid, family_id(mk), line, None)
        elif kind == "total":
            key = (eid, family_id(mk), _pt(point), None)
        else:  # team_total / prop: "<entity> Over|Under"
            entity, _, side = name.rpartition(" ")
            if side not in ("Over", "Under") or not entity:
                continue
            key = (eid, family_id(mk), _pt(point), entity)
        index.setdefault(key, set()).add(mk)
    return index


# ─────────────────────────── market planning ───────────────────────────

def _parse_signed(name: str) -> float | None:
    m = _SIGNED_NUM_RX.search(name or "")
    return float(m.group(1)) if m else None


def _strip_suffix(description: str, strike, market_type: str) -> str:
    """"Joe Burrow 268.5 PASSING_YARDS" → "Joe Burrow"."""
    d = (description or "").strip()
    d = d.removesuffix(market_type).strip()
    if strike not in (None, "", "0"):
        for form in (str(strike), f"{float(strike):g}"):
            if d.endswith(" " + form):
                d = d[: -len(form)].strip()
                break
    return d


def plan_market(
    market: dict,
    sport: str,
    cache_event: dict,
    novig_home_is_cache_home: bool,
    index: dict[tuple, set[str]],
) -> list[tuple[str, str, str, float | None]]:
    """Decide which odds_snapshot slots a Novig market fills.

    Returns [(outcomeId, market_key, outcome_name, outcome_point), …] —
    empty when the market type is unmapped or betting-db has no sibling
    Novig row for it (in which case we don't spend a book request on it).
    """
    fam = family_for(sport, market.get("marketType", ""))
    outcomes = market.get("outcomes") or []
    if fam is None or len(outcomes) != 2:
        return []
    kind, candidate_keys = fam
    eid = cache_event["event_id"]
    c_home = cache_event["home_team"]
    c_away = cache_event["away_team"]
    n_home_team = c_home if novig_home_is_cache_home else c_away
    n_away_team = c_away if novig_home_is_cache_home else c_home
    strike = market.get("strike")
    plan: list[tuple[str, str, str, float | None]] = []

    def slots(line, entity) -> set[str]:
        hits: set[str] = set()
        for mk in candidate_keys:
            hits |= index.get((eid, family_id(mk), line, entity), set())
        return hits

    if kind == "ml":
        home_label = market.get("description", "").removesuffix(" 1H").strip()
        names = [o["name"] for o in outcomes]
        if home_label not in names:
            return []
        for mk in slots(None, None):
            for o in outcomes:
                team = n_home_team if o["name"] == home_label else n_away_team
                plan.append((o["outcomeId"], mk, team, None))
        return plan

    try:
        strike_f = float(strike)
    except (TypeError, ValueError):
        return []

    if kind == "spread":
        if strike_f == 0:
            return []  # pick'em: point==strike can't tell the sides apart
        sides = []
        for o in outcomes:
            pt = _parse_signed(o["name"])
            if pt is None:
                return []
            is_home = abs(pt - strike_f) < 1e-9
            sides.append((o, pt, is_home))
        if sum(1 for s in sides if s[2]) != 1:
            return []
        # Novig's strike is its home side's handicap; re-express it from
        # the cache's home team's point of view.
        cache_home_line = _pt(strike_f if novig_home_is_cache_home else -strike_f)
        for mk in slots(cache_home_line, None):
            for o, pt, is_home in sides:
                team = n_home_team if is_home else n_away_team
                plan.append((o["outcomeId"], mk, team, _pt(pt)))
        return plan

    def over_under(o) -> str | None:
        n = (o.get("name") or "").split(" ", 1)[0]
        return n if n in ("Over", "Under") else None

    if kind == "total":
        for mk in slots(_pt(strike_f), None):
            for o in outcomes:
                side = over_under(o)
                if side:
                    plan.append((o["outcomeId"], mk, side, _pt(strike_f)))
        return plan

    entity_raw = _strip_suffix(market.get("description", ""), strike, market["marketType"])
    if kind == "team_total":
        folded = _fold(entity_raw, sport)
        team = None
        for cand in (c_home, c_away):
            if _names_match(folded, _fold(cand, sport)):
                team = cand
                break
        if team is None:
            return []
        for mk in slots(_pt(strike_f), team):
            for o in outcomes:
                side = over_under(o)
                if side:
                    plan.append((o["outcomeId"], mk, f"{team} {side}", _pt(strike_f)))
        return plan

    # prop — the canonical player form can depend on the market key
    # (sport-scoped aliases), so resolve it per candidate key.
    seen: set[str] = set()
    for mk_candidate in candidate_keys:
        canon = normalize_player_name(entity_raw, sport, mk_candidate)
        if not canon:
            continue
        for mk in index.get((eid, family_id(mk_candidate), _pt(strike_f), canon), set()):
            if mk in seen:
                continue
            seen.add(mk)
            for o in outcomes:
                side = over_under(o)
                if side:
                    plan.append((o["outcomeId"], mk, f"{canon} {side}", _pt(strike_f)))
    return plan


def rows_for(
    market: dict,
    plan: list[tuple[str, str, str, float | None]],
    quotes: dict[str, tuple[float, float | None]],
    sport: str,
    cache_event: dict,
    fetched_at: datetime,
    book_key: str = BOOK_KEY,
) -> list[dict]:
    """Materialize odds_snapshot rows for the quoted sides.

    `book_key=novig` takes (prob, stake) take quotes; `novig_maker` takes
    (prob, None) maker quotes — makers pay no fee and have no depth cap.
    """
    rows: list[dict] = []
    for outcome_id, mk, name, point in plan:
        q = quotes.get(outcome_id)
        if q is None:
            continue
        take, stake = q
        prob = effective_take_prob(take, market) if book_key == BOOK_KEY else take
        american = prob_to_american(prob)
        if american is None:
            continue
        rows.append({
            "event_id": cache_event["event_id"],
            "sport_key": sport,
            "home_team": cache_event["home_team"],
            "away_team": cache_event["away_team"],
            "commence_time": _as_utc(cache_event["commence_time"]),
            "bookmaker_key": book_key,
            "market_key": mk,
            "outcome_name": name,
            "outcome_point": point,
            "price_american": american,
            "fetched_at": fetched_at,
            "max_stake_dollars": stake,
        })
    return rows
