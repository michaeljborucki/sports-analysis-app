from __future__ import annotations

from typing import Iterable


# The feed includes EVERY book in the cache — the Odds API books plus the
# directly-fetched ones (coral33, kalshi, polymarket). coral33 carries genuine
# sportsbook lines and polymarket is a real open-market price, so both belong
# in the agents' consensus devig. Their normalizers emit canonical team names
# (matching what the Odds API emits), so h2h/spread outcomes key correctly
# through the agents' team-name lookup and contribute to the devig.


# Mirror of normalize._encode_outcome_name: player props and team totals are
# stored with the player/team folded into `outcome_name` (e.g. "Aaron Judge
# Over", "New York Yankees Under") to keep the cache primary key unique. The
# decoder splits that back into (description, name) so the reconstructed feed
# matches the Odds API's native (name="Over", description="Aaron Judge") shape.
_PROP_PREFIXES = ("pitcher_", "batter_", "player_")
_ENCODED_SUFFIXES = (" Over", " Under", " Yes", " No")


def decode_outcome_name(market_key: str, outcome_name: str) -> tuple[str | None, str]:
    """Reverse normalize._encode_outcome_name.

    Returns (description, name). `description` is None for any market that
    isn't a player prop or team total (moneylines, spreads, totals, etc.,
    whose outcome_name is already the raw name).
    """
    if market_key.startswith(_PROP_PREFIXES) or "team_totals" in market_key:
        for suffix in _ENCODED_SUFFIXES:
            if outcome_name.endswith(suffix):
                return outcome_name[: -len(suffix)], suffix.strip()
    return None, outcome_name


def rows_to_odds_api_events(rows: Iterable[dict]) -> list[dict]:
    """Reconstruct cache rows into The Odds API's native event JSON shape.

    Inverse of normalize.normalize_odds_response. The output is a list of
    events, each `{id, sport_key, home_team, away_team, commence_time,
    bookmakers: [{key, markets: [{key, outcomes: [{name, price, point?,
    description?}]}]}]}` — the exact shape an agent's parsers expect from a
    direct `/sports/<key>/odds` or `/events/<id>/odds` call.

    Rows are expected to come from `OddsCache.all_current(sport_key=...)`,
    which already nulls `outcome_point` for h2h. Every book is included; only
    the synthetic `nrfi` bridge market is dropped (agents read NRFI straight
    off totals_1st_1_innings).
    """
    by_event: dict[str, dict] = {}
    for r in rows:
        bookmaker_key = r["bookmaker_key"]
        market_key = r["market_key"]
        # `nrfi` is a backend-only bridge market synthesized in normalize.py
        # to pair Odds API totals_1st_1_innings with coral33's NRFI line. It
        # isn't part of the Odds API schema and agents read NRFI straight off
        # totals_1st_1_innings, so leave it out of the reconstructed feed.
        if market_key == "nrfi":
            continue

        event = by_event.setdefault(r["event_id"], {
            "id": r["event_id"],
            "sport_key": r.get("sport_key"),
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "commence_time": r["commence_time"],
            "_books": {},  # bookmaker_key -> {market_key: [outcome, ...]}
        })
        markets = event["_books"].setdefault(bookmaker_key, {})
        outcomes = markets.setdefault(market_key, [])

        description, name = decode_outcome_name(market_key, r["outcome_name"])
        outcome: dict = {"name": name, "price": int(r["price_american"])}
        point = r.get("outcome_point")
        if point is not None:
            outcome["point"] = float(point)
        if description is not None:
            outcome["description"] = description
        outcomes.append(outcome)

    events = []
    for event in by_event.values():
        books = event.pop("_books")
        event["bookmakers"] = [
            {
                "key": bookmaker_key,
                "markets": [
                    {"key": market_key, "outcomes": outcomes}
                    for market_key, outcomes in markets.items()
                ],
            }
            for bookmaker_key, markets in books.items()
        ]
        events.append(event)
    return events
