from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from .player_names import normalize_player_name
from .venues import MAKER_OF, OPT_IN_BOOKS
from functools import lru_cache


logger = logging.getLogger(__name__)


# M7: Outcome-name collision dedup. Records (event_id, market_key,
# outcome_point) addresses we've already warned about. Process-lifetime;
# bounded by distinct addresses × server uptime (realistic worst case
# ~few thousand entries).
_COLLISION_WARNED: set[tuple[str, str, float]] = set()


def _reset_collision_log_for_tests() -> None:
    """Clear the dedup set. Tests only."""
    _COLLISION_WARNED.clear()


def _check_outcome_name_collisions(rows: Iterable[dict]) -> None:
    """Walk the raw rows once, building (address → set[outcome_name]).
    For any address where the set has >1 distinct name, emit a
    WARNING (deduplicated via _COLLISION_WARNED). Pure observability —
    never mutates rows or raises.
    """
    seen: dict[tuple[str, str, float], set[str]] = {}
    for r in rows:
        try:
            point = float(r.get("outcome_point") or 0.0)
        except (TypeError, ValueError):
            point = 0.0
        addr = (
            str(r.get("event_id") or ""),
            str(r.get("market_key") or ""),
            point,
        )
        name = str(r.get("outcome_name") or "")
        if not addr[0] or not addr[1] or not name:
            continue
        seen.setdefault(addr, set()).add(name)
    for addr, names in seen.items():
        if len(names) <= 1:
            continue
        if addr in _COLLISION_WARNED:
            continue
        _COLLISION_WARNED.add(addr)
        logger.warning(
            "outcome-name collision in %s/%s/%s: %s",
            addr[0], addr[1], addr[2], ", ".join(sorted(names)),
        )


# Bookmaker keys whose rows we DO NOT want to ingest from the Odds API —
# we own these books via a direct fetcher and the Odds API copy is staler.
# Currently:
#   - "kalshi": Odds API quotes are 2-5 minutes stale; the direct
#     kalshi_fetcher polls every 15s.
_EXCLUDE_BOOKMAKERS: frozenset[str] = frozenset({"kalshi"})


@lru_cache(maxsize=65536)
def _canonical_cached_prop(name: str, sport: str, market_key: str = "") -> str:
    player, _, side = name.rpartition(" ")
    if player and side in ("Over", "Under"):
        return f"{normalize_player_name(player, sport, market_key)} {side}"
    return name


def _encode_outcome_name(
    market_key: str, name: str, description: str | None, sport_key: str = "",
) -> str:
    """Player props come back as (name='Over', description='Drew Rasmussen').
    Encode both into a single outcome_name so the cache PK stays stable
    across different players/teams with the same line.

    Applied to:
      - All player-level prop markets: MLB (pitcher_*, batter_*), NBA/NHL/etc.
        (player_*). Player names are canonicalized via
        `normalize_player_name` so the same player from Odds API,
        Polymarket, Coral33, and Kalshi lands in the SAME PK slot.
      - Team-totals markets: outcomes come back as (name='Over', description
        '<team>'). Without this encoding, home and away team Over/Unders at
        the same point would collide in the PK. Team names are passed
        through unchanged — team-level canonicalization is handled by the
        event matcher upstream.
    """
    if not description:
        return name
    if market_key.startswith(("pitcher_", "batter_", "player_")):
        # Cross-book canonicalization: fold + sport-scoped alias lookup.
        # Falls back to the folded description if no alias hit.
        canon = normalize_player_name(description, sport_key, market_key)
        return f"{canon} {name}" if canon else f"{description} {name}"
    # team_totals + alternate_team_totals + any period variant of those.
    if "team_totals" in market_key:
        return f"{description} {name}"
    return name


def _link_maker_counterparts(prices: list[dict]) -> None:
    """Cross-reference a venue's take and maker quotes on one outcome so
    either leg can show the other (e.g. Novig take −135 · make −128)."""
    by_book = {p["bookmaker_key"]: p for p in prices}
    for taker, maker in MAKER_OF.items():
        t, m = by_book.get(taker), by_book.get(maker)
        if t is not None and m is not None:
            t["counterpart_price_american"] = m["price_american"]
            m["counterpart_price_american"] = t["price_american"]


def normalize_odds_response(
    games: list[dict],
    fetched_at: datetime,
    sport_key: str = "mlb",
) -> list[dict]:
    """Flatten Odds API response (game-level OR per-event) into cache rows."""
    rows: list[dict] = []
    # Per-event responses are a single event dict, not a list; wrap if needed.
    iterable = games if isinstance(games, list) else [games]
    for game in iterable:
        if not game:
            continue
        event_id = game["id"]
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        league_key = game.get("sport_key") if sport_key == "soccer" else None
        league_title = game.get("sport_title") if sport_key == "soccer" else None
        commence = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
        for bm in game.get("bookmakers", []):
            bk = bm["key"]
            # Direct-fetcher books: drop Odds API rows so the direct
            # fetcher's fresher quotes own the (event, market, outcome)
            # cache slot exclusively.
            if bk in _EXCLUDE_BOOKMAKERS:
                continue
            for mk in bm.get("markets", []):
                market_key = mk["key"]
                for oc in mk.get("outcomes", []):
                    encoded_name = _encode_outcome_name(
                        market_key, oc["name"], oc.get("description"),
                        sport_key=sport_key,
                    )
                    base_row = {
                        "event_id": event_id,
                        "sport_key": sport_key,
                        "league_key": league_key,
                        "league_title": league_title,
                        "home_team": home,
                        "away_team": away,
                        "commence_time": commence,
                        "bookmaker_key": bk,
                        "market_key": market_key,
                        "outcome_name": encoded_name,
                        "outcome_point": oc.get("point"),
                        "price_american": int(oc["price"]),
                        "fetched_at": fetched_at,
                    }
                    rows.append(base_row)
                    # NRFI bridge: the Odds API doesn't expose `nrfi` as its
                    # own market — it surfaces the same semantic via
                    # totals_1st_1_innings at point 0.5 (Over=YRFI, Under=
                    # NRFI). Coral33 emits the same semantic under
                    # market_key="nrfi". Synthesize a `nrfi` row here so
                    # the EV/arb scanner pairs Odds-API book prices with
                    # Coral33's NRFI line.
                    if (
                        market_key in (
                            "totals_1st_1_innings",
                            "alternate_totals_1st_1_innings",
                        )
                        and oc.get("point") == 0.5
                    ):
                        if oc["name"] == "Over":
                            nrfi_outcome = "Yes"
                        elif oc["name"] == "Under":
                            nrfi_outcome = "No"
                        else:
                            nrfi_outcome = None
                        if nrfi_outcome is not None:
                            rows.append({
                                **base_row,
                                "market_key": "nrfi",
                                "outcome_name": nrfi_outcome,
                                "outcome_point": 0.0,
                            })
    return rows


def rows_to_games(rows: Iterable[dict], now: datetime) -> list[dict]:
    """Group cache rows into Game → Market → MarketOutcome → BookPrice.

    Applies commission-on-winnings per book at this layer, so `price_american`
    on every emitted BookPrice is the *effective* (post-commission) price.
    The cache still stores the listed price; commission is applied on read.
    """
    return _rows_to_games(rows, now, with_non_prop=False)[0]


def rows_to_games_with_non_prop(
    rows: Iterable[dict], now: datetime,
) -> tuple[list[dict], list[dict]]:
    """`(rows_to_games(rows), rows_to_games(non-prop rows))` in one pass.

    Identical output to the two separate calls. A non-prop market is built
    from exactly the same rows either way, so the non-prop games reuse the
    full pass's market objects; only the game header (taken from the game's
    first non-prop row), `stale_seconds` (max over non-prop rows) and the
    game set/order (first non-prop appearance, then the stable commence
    sort) are tracked separately. Games share market objects — treat both
    lists as read-only, as every snapshot consumer already does.
    """
    return _rows_to_games(rows, now, with_non_prop=True)


def _rows_to_games(
    rows: Iterable[dict], now: datetime, *, with_non_prop: bool,
) -> tuple[list[dict], list[dict]]:
    from .best_odds import best_price_dict, median_american_odds
    from .commissions import effective_american
    from .market_config import is_prop_market

    # M7: outcome-name collision detection — log once per address per
    # process when two books emit different outcome_name strings for the
    # same (event_id, market_key, outcome_point). Pure observability.
    rows = list(rows)
    _check_outcome_name_collisions(rows)

    by_event: dict[str, dict] = {}
    # with_non_prop: per-event header + staleness as a non-prop-only pass
    # would compute them (setdefault on the first non-prop row).
    np_by_event: dict[str, dict] = {}
    for r in rows:
        row_is_prop = is_prop_market(r["market_key"])
        if row_is_prop:
            canonical = _canonical_cached_prop(r["outcome_name"], r.get("sport_key", "mlb"), r["market_key"])
            if canonical != r["outcome_name"]:
                r = {**r, "outcome_name": canonical}
        ev = by_event.get(r["event_id"])
        if ev is None:
            ev = by_event[r["event_id"]] = _event_header(r)
        if not ev["league_key"] and r.get("league_key"):
            ev["league_key"] = r["league_key"]
        if not ev["league_title"] and r.get("league_title"):
            ev["league_title"] = r["league_title"]
        np_ev = None
        if with_non_prop and not row_is_prop:
            np_ev = np_by_event.get(r["event_id"])
            if np_ev is None:
                np_ev = np_by_event[r["event_id"]] = _event_header(r)
            if not np_ev["league_key"] and r.get("league_key"):
                np_ev["league_key"] = r["league_key"]
            if not np_ev["league_title"] and r.get("league_title"):
                np_ev["league_title"] = r["league_title"]
        market_key = r["market_key"]
        numeric_prop = (
            is_prop_market(market_key)
            and r.get("outcome_point") is not None
            and r["outcome_name"].endswith((" Over", " Under"))
        )
        is_alternate_prop = numeric_prop and market_key.endswith("_alternate")
        if is_alternate_prop:
            # The API expresses milestones as O/U thresholds (25+ => Over
            # 24.5). Preserve that exact point; only merge the stat identity.
            market_key = market_key.removesuffix("_alternate")
        mk = ev["markets_by_key"].setdefault(market_key, {})
        out_key = (r["outcome_name"], r.get("outcome_point"))
        out = mk.setdefault(out_key, {
            "outcome_name": r["outcome_name"],
            "outcome_point": r.get("outcome_point"),
            "prices": [],
        })
        fetched_at = _coerce_dt(r["fetched_at"])
        # Apply commission — every price emitted by the API is already the
        # effective payout number; the frontend treats it as-is.
        effective_price = effective_american(
            int(r["price_american"]), r["bookmaker_key"]
        )
        price = {
            "bookmaker_key": r["bookmaker_key"],
            "price_american": effective_price,
            "point": r.get("outcome_point"),
            "fetched_at": fetched_at,
            # Coral33-only: 'straight' / 'parlay' / 'both'. NULL for every
            # other book — propagated all the way to the EVOpportunity so
            # the frontend can filter on parlay-eligibility.
            "wager_type": r.get("wager_type"),
            # Kalshi/Polymarket only: top-of-book fillable dollar size at
            # the displayed price. NULL for sportsbook rows (no depth data).
            # Consumed by the arb scanner to clamp stake recommendations
            # on cross-venue opportunities.
            "max_stake_dollars": r.get("max_stake_dollars"),
        }
        if numeric_prop:
            # Main and alternate feeds can repeat a book's same line. Use
            # its newest quote once; at equal timestamps prefer the main.
            by_book = out.setdefault("prop_prices", {})
            priority = (fetched_at, not is_alternate_prop)
            previous = by_book.get(r["bookmaker_key"])
            if previous is None or priority > previous[0]:
                by_book[r["bookmaker_key"]] = (priority, price)
        else:
            out["prices"].append(price)
        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        age = max(0, int((now_utc - fetched_at).total_seconds()))
        if age > ev["stale_seconds"]:
            ev["stale_seconds"] = age
        if np_ev is not None and age > np_ev["stale_seconds"]:
            np_ev["stale_seconds"] = age

    games = []
    markets_by_event: dict[str, list[dict]] = {}
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    for ev in by_event.values():
        markets = []
        markets_by_event[ev["event_id"]] = markets
        for mk_key, outcomes in ev["markets_by_key"].items():
            out_list = []
            for out in outcomes.values():
                out["prices"].extend(p for _, p in out.get("prop_prices", {}).values())
                _link_maker_counterparts(out["prices"])
                # Opt-in books (novig_maker) are prices you'd post, not
                # market prices — never the "best" or part of consensus.
                market_prices = [p for p in out["prices"] if p["bookmaker_key"] not in OPT_IN_BOOKS]
                best_price = best_price_dict(market_prices)
                consensus = median_american_odds([p["price_american"] for p in market_prices])
                out_list.append({
                    "outcome_name": out["outcome_name"],
                    "prices": out["prices"],
                    "best_price": best_price,
                    "consensus_price_american": consensus,
                })
            markets.append({"market_key": mk_key, "outcomes": out_list})
        games.append({
            "event_id": ev["event_id"],
            "sport_key": ev["sport_key"],
            "league_key": ev["league_key"],
            "league_title": ev["league_title"],
            "home_team": ev["home_team"],
            "away_team": ev["away_team"],
            "commence_time": ev["commence_time"],
            "is_live": ev["commence_time"] <= now_utc,
            "markets": markets,
            "stale_seconds": ev["stale_seconds"],
        })
    games.sort(key=lambda g: g["commence_time"])

    non_prop_games = []
    for ev in np_by_event.values():
        non_prop_games.append({
            "event_id": ev["event_id"],
            "sport_key": ev["sport_key"],
            "league_key": ev["league_key"],
            "league_title": ev["league_title"],
            "home_team": ev["home_team"],
            "away_team": ev["away_team"],
            "commence_time": ev["commence_time"],
            "is_live": ev["commence_time"] <= now_utc,
            "markets": [
                m for m in markets_by_event[ev["event_id"]]
                if not is_prop_market(m["market_key"])
            ],
            "stale_seconds": ev["stale_seconds"],
        })
    non_prop_games.sort(key=lambda g: g["commence_time"])
    return games, non_prop_games


def _event_header(r: dict) -> dict:
    return {
        "event_id": r["event_id"],
        "sport_key": r.get("sport_key", "mlb"),
        "league_key": r.get("league_key"),
        "league_title": r.get("league_title"),
        "home_team": r["home_team"],
        "away_team": r["away_team"],
        "commence_time": _coerce_dt(r["commence_time"]),
        "markets_by_key": {},
        "stale_seconds": 0,
    }


def _coerce_dt(v) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return datetime.fromisoformat(str(v))
