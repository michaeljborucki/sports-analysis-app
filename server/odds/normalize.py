from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable


def _encode_outcome_name(market_key: str, name: str, description: str | None) -> str:
    """Player props come back as (name='Over', description='Drew Rasmussen').
    Encode both into a single outcome_name so the cache PK stays stable
    across different players/teams with the same line.

    Applied to:
      - All player-level prop markets: MLB (pitcher_*, batter_*), NBA/NHL/etc.
        (player_*).
      - Team-totals markets: outcomes come back as (name='Over', description
        '<team>'). Without this encoding, home and away team Over/Unders at
        the same point would collide in the PK.
    """
    if not description:
        return name
    if market_key.startswith(("pitcher_", "batter_", "player_")):
        return f"{description} {name}"
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
            for mk in bm.get("markets", []):
                market_key = mk["key"]
                for oc in mk.get("outcomes", []):
                    encoded_name = _encode_outcome_name(
                        market_key, oc["name"], oc.get("description")
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
