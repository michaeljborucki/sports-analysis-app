from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from .player_names import normalize_player_name


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
        canon = normalize_player_name(description, sport_key)
        return f"{canon} {name}" if canon else f"{description} {name}"
    # team_totals + alternate_team_totals + any period variant of those.
    if "team_totals" in market_key:
        return f"{description} {name}"
    return name


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
    from .best_odds import pick_best_price, median_american_odds
    from .commissions import effective_american

    # M7: outcome-name collision detection — log once per address per
    # process when two books emit different outcome_name strings for the
    # same (event_id, market_key, outcome_point). Pure observability.
    rows = list(rows)
    _check_outcome_name_collisions(rows)

    by_event: dict[str, dict] = {}
    for r in rows:
        ev = by_event.setdefault(r["event_id"], {
            "event_id": r["event_id"],
            "sport_key": r.get("sport_key", "mlb"),
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "commence_time": _coerce_dt(r["commence_time"]),
            "markets_by_key": {},
            "stale_seconds": 0,
        })
        mk = ev["markets_by_key"].setdefault(r["market_key"], {})
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
        out["prices"].append({
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
        })
        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        age = max(0, int((now_utc - fetched_at).total_seconds()))
        if age > ev["stale_seconds"]:
            ev["stale_seconds"] = age

    games = []
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    for ev in by_event.values():
        markets = []
        for mk_key, outcomes in ev["markets_by_key"].items():
            out_list = []
            for out in outcomes.values():
                price_tuples = [(p["bookmaker_key"], p["price_american"]) for p in out["prices"]]
                best = pick_best_price(price_tuples)
                best_price = None
                if best is not None:
                    best_price = next(
                        p for p in out["prices"]
                        if p["bookmaker_key"] == best[0] and p["price_american"] == best[1]
                    )
                consensus = median_american_odds([p["price_american"] for p in out["prices"]])
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
            "home_team": ev["home_team"],
            "away_team": ev["away_team"],
            "commence_time": ev["commence_time"],
            "is_live": ev["commence_time"] <= now_utc,
            "markets": markets,
            "stale_seconds": ev["stale_seconds"],
        })
    games.sort(key=lambda g: g["commence_time"])
    return games


def _coerce_dt(v) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    return datetime.fromisoformat(str(v))
