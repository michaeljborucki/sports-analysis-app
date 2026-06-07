from dataclasses import dataclass, field
from datetime import datetime, timezone
import requests

from config import ODDS_API_KEY, ODDS_API_BASE, TEAM_NAME_TO_ABBREV
from scrapers.odds_feed import (
    FeedUnavailable,
    feed_enabled,
    get_feed_event,
    get_feed_events,
    warn_missing_markets,
)


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def prob_to_american(prob: float) -> int:
    """Convert probability to the American odds at which implied prob equals it.

    This is the breakeven price for a bet with this win probability —
    any price better than this yields positive edge.
    """
    if prob <= 0 or prob >= 1:
        raise ValueError(f"probability must be in (0, 1), got {prob}")
    if prob >= 0.5:
        return -round(prob / (1 - prob) * 100)
    return round((1 - prob) / prob * 100)


def american_be_with_wiggle(odds: int) -> int:
    """Shrink |odds| by at least 5 toward 0, floored to a multiple of 5.

    Used to display a conservative breakeven with built-in wiggle room.
    Examples: 137->130, -137->-130, 132->125, 130->125, 105->100.
    """
    sign = -1 if odds < 0 else 1
    return sign * ((abs(odds) - 5) // 5 * 5)


def _american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds for comparison."""
    if odds < 0:
        return 100 / abs(odds) + 1
    return odds / 100 + 1


def _outcome_key(outcome: dict) -> str:
    """Unique key for an outcome within a market.

    Includes point value so alternate lines (e.g. team total 3.5 vs 8.5)
    are not merged together during best-line selection.
    """
    point = outcome.get("point", "")
    return f"{outcome.get('name', '')}_{outcome.get('description', '')}_{point}"


def power_devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove vig using the power method. Solves for n where p_a^n + p_b^n = 1.

    Falls back to naive normalization if inputs are degenerate.
    """
    total = prob_a + prob_b
    if total <= 0:
        return (0.5, 0.5)
    # No vig to remove
    if abs(total - 1.0) < 1e-6:
        return (prob_a, prob_b)
    # Guard against degenerate inputs
    if prob_a <= 0.001 or prob_b <= 0.001:
        return (prob_a / total, prob_b / total)

    # Bisection: find n where prob_a^n + prob_b^n = 1
    lo, hi = 0.01, 20.0
    for _ in range(100):
        mid = (lo + hi) / 2
        val = prob_a ** mid + prob_b ** mid
        if val > 1.0:
            lo = mid
        else:
            hi = mid
        if abs(val - 1.0) < 1e-10:
            break

    n = (lo + hi) / 2
    return (round(prob_a ** n, 6), round(prob_b ** n, 6))


@dataclass
class OddsData:
    home: str
    away: str
    commence_time: str
    moneyline: dict = field(default_factory=dict)
    run_line: dict = field(default_factory=dict)
    total: dict = field(default_factory=dict)
    f5_moneyline: dict = field(default_factory=dict)
    f5_total: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)
    # Phase 1 new fields
    event_id: str = ""
    team_total_home: dict = field(default_factory=dict)
    team_total_away: dict = field(default_factory=dict)
    f5_spread: dict = field(default_factory=dict)
    f1_total: dict = field(default_factory=dict)
    f1_spread: dict = field(default_factory=dict)
    f3_moneyline: dict = field(default_factory=dict)
    f3_total: dict = field(default_factory=dict)
    f3_spread: dict = field(default_factory=dict)
    book_sources: dict = field(default_factory=dict)


def _team_abbrev(full_name: str) -> str:
    return TEAM_NAME_TO_ABBREV.get(full_name, full_name)


ADDITIONAL_MARKETS = (
    "team_totals,spreads_1st_5_innings,totals_1st_1_innings,"
    "spreads_1st_1_innings,h2h_1st_3_innings,totals_1st_3_innings,"
    "spreads_1st_3_innings"
)


def _parse_additional_markets(od: OddsData, markets: dict) -> None:
    """Parse additional market data into OddsData fields."""
    home = od.home
    away = od.away

    # Team totals
    if "team_totals" in markets:
        for outcome in markets["team_totals"].get("outcomes", []):
            team_abbrev = _team_abbrev(outcome.get("description", ""))
            if outcome["name"] == "Over":
                if team_abbrev == home:
                    od.team_total_home["line"] = outcome.get("point", 0)
                    od.team_total_home["over_odds"] = outcome["price"]
                elif team_abbrev == away:
                    od.team_total_away["line"] = outcome.get("point", 0)
                    od.team_total_away["over_odds"] = outcome["price"]
            elif outcome["name"] == "Under":
                if team_abbrev == home:
                    od.team_total_home["under_odds"] = outcome["price"]
                elif team_abbrev == away:
                    od.team_total_away["under_odds"] = outcome["price"]

    # Spread markets (F5, F1, F3)
    spread_map = {
        "spreads_1st_5_innings": "f5_spread",
        "spreads_1st_1_innings": "f1_spread",
        "spreads_1st_3_innings": "f3_spread",
    }
    for market_key, field_name in spread_map.items():
        if market_key in markets:
            target = getattr(od, field_name)
            for outcome in markets[market_key].get("outcomes", []):
                if _team_abbrev(outcome["name"]) == home:
                    target["home"] = outcome.get("point", -0.5)
                    target["home_odds"] = outcome["price"]
                else:
                    target["away"] = outcome.get("point", 0.5)
                    target["away_odds"] = outcome["price"]

    # Totals markets (F1, F3)
    total_map = {
        "totals_1st_1_innings": "f1_total",
        "totals_1st_3_innings": "f3_total",
    }
    for market_key, field_name in total_map.items():
        if market_key in markets:
            target = getattr(od, field_name)
            for outcome in markets[market_key].get("outcomes", []):
                if outcome["name"] == "Over":
                    target["line"] = outcome.get("point", 0)
                    target["over_odds"] = outcome["price"]
                else:
                    target["under_odds"] = outcome["price"]

    # F3 moneyline
    if "h2h_1st_3_innings" in markets:
        for outcome in markets["h2h_1st_3_innings"].get("outcomes", []):
            if _team_abbrev(outcome["name"]) == home:
                od.f3_moneyline["home"] = outcome["price"]
            else:
                od.f3_moneyline["away"] = outcome["price"]


def _merge_event_markets(event: dict, wanted: set[str] | None = None) -> dict:
    """Merge one event's bookmakers into best-odds-per-outcome markets.

    Alternate lines are dropped — for each (market, side, player/team) the most
    common point across books is treated as the primary line and others are
    skipped. `wanted`, when given, restricts the result to those market keys
    (used by the shared-feed path, where the event carries every market the
    backend cached, not just the ones this caller asked for).
    """
    # Count how often each (market, side_desc, point) appears across books to
    # identify the primary line vs alternate lines.
    line_counts = {}  # (market_key, name, description): {point: count}
    for bk in event.get("bookmakers", []):
        for m in bk.get("markets", []):
            mk = m["key"]
            if wanted is not None and mk not in wanted:
                continue
            for outcome in m.get("outcomes", []):
                side_key = (mk, outcome.get("name", ""), outcome.get("description", ""))
                point = outcome.get("point")
                if point is not None:
                    line_counts.setdefault(side_key, {})
                    line_counts[side_key][point] = line_counts[side_key].get(point, 0) + 1

    # For each side, find the most common point (primary line).
    primary_lines = {sk: max(counts, key=counts.get) for sk, counts in line_counts.items()}

    # Merge best odds per outcome, filtering to primary lines only.
    merged = {}
    for bk in event.get("bookmakers", []):
        for m in bk.get("markets", []):
            mk = m["key"]
            if wanted is not None and mk not in wanted:
                continue
            if mk not in merged:
                merged[mk] = {"key": mk, "outcomes": []}
            existing = {_outcome_key(o): o for o in merged[mk].get("outcomes", [])}
            for outcome in m.get("outcomes", []):
                point = outcome.get("point")
                if point is not None:
                    side_key = (mk, outcome.get("name", ""), outcome.get("description", ""))
                    if side_key in primary_lines and point != primary_lines[side_key]:
                        continue  # Skip alternate lines
                okey = _outcome_key(outcome)
                if okey not in existing or _american_to_decimal(outcome["price"]) > _american_to_decimal(existing[okey]["price"]):
                    existing[okey] = outcome
            merged[mk]["outcomes"] = list(existing.values())
    return merged


def get_additional_odds(event_id: str, api_requests_remaining: int = 999,
                        markets: str = ADDITIONAL_MARKETS) -> dict:
    """Fetch additional markets via per-event endpoint.

    Returns raw markets dict or empty dict on failure. Pulls from the shared
    backend feed when configured (free, no API spend), otherwise hits the Odds
    API per-event endpoint directly.
    """
    if feed_enabled():
        try:
            event = get_feed_event(event_id)
            if event is None:
                return {}
            merged = _merge_event_markets(event, set(markets.split(",")))
            return merged if merged else {}
        except FeedUnavailable as e:
            print(f"[odds] Shared feed unavailable ({e}); falling back to Odds API")

    if api_requests_remaining < 100:
        print("[odds] Skipping per-event fetch — API budget low")
        return {}

    url = f"{ODDS_API_BASE}/sports/baseball_mlb/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us,us2,eu,uk",
        "markets": markets,
        "oddsFormat": "american",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        merged = _merge_event_markets(data)
        return merged if merged else {}
    except Exception as e:
        print(f"[odds] Per-event fetch failed for {event_id}: {e}")
    return {}


def _parse_event_to_odds_data(event: dict) -> "OddsData | None":
    """Build OddsData from one raw event JSON (live or historical response).

    Returns None if home/away can't be resolved.
    """
    home_full = event.get("home_team")
    away_full = event.get("away_team")
    if not home_full or not away_full:
        return None
    home = _team_abbrev(home_full)
    away = _team_abbrev(away_full)

    odds_data = OddsData(
        home=home,
        away=away,
        commence_time=event.get("commence_time", ""),
        event_id=event.get("id", ""),
    )

    best = {}
    best_points = {}
    all_book_odds: dict[str, list[dict]] = {}

    # Pre-pass: consensus total line
    _totals_line_counts: dict[float, int] = {}
    for bk in event.get("bookmakers", []):
        for m in bk.get("markets", []):
            if m["key"] == "totals":
                for oc in m.get("outcomes", []):
                    if "point" in oc:
                        pt = oc["point"]
                        _totals_line_counts[pt] = _totals_line_counts.get(pt, 0) + 1
    _consensus_total = max(_totals_line_counts, key=_totals_line_counts.get) if _totals_line_counts else None

    for bk in event.get("bookmakers", []):
        book_name = bk.get("key", "unknown")
        markets = {m["key"]: m for m in bk.get("markets", [])}

        for market_key, market_data in markets.items():
            book_snapshot = {}
            for outcome in market_data.get("outcomes", []):
                price = outcome["price"]
                dec = _american_to_decimal(price)
                side_id = _team_abbrev(outcome["name"]) if market_key in ("h2h", "spreads", "h2h_1st_5_innings") else outcome["name"]
                key = (market_key, side_id)

                if market_key == "spreads" and "point" in outcome:
                    if abs(outcome["point"]) != 1.5:
                        continue

                if market_key == "totals" and "point" in outcome and _consensus_total is not None:
                    if outcome["point"] != _consensus_total:
                        continue

                book_snapshot[side_id] = price

                if key not in best or dec > best[key][0]:
                    best[key] = (dec, price, book_name)
                    if "point" in outcome:
                        best_points[key] = outcome["point"]

            if book_snapshot:
                all_book_odds.setdefault(market_key, []).append(book_snapshot)

    # Populate odds_data from best lines
    if ("h2h", home) in best:
        odds_data.moneyline["home"] = best[("h2h", home)][1]
        odds_data.book_sources["h2h_home"] = best[("h2h", home)][2]
    if ("h2h", away) in best:
        odds_data.moneyline["away"] = best[("h2h", away)][1]
        odds_data.book_sources["h2h_away"] = best[("h2h", away)][2]

    if ("spreads", home) in best:
        odds_data.run_line["home"] = best_points.get(("spreads", home), -1.5)
        odds_data.run_line["home_odds"] = best[("spreads", home)][1]
        odds_data.book_sources["spreads_home"] = best[("spreads", home)][2]
    if ("spreads", away) in best:
        odds_data.run_line["away"] = best_points.get(("spreads", away), 1.5)
        odds_data.run_line["away_odds"] = best[("spreads", away)][1]
        odds_data.book_sources["spreads_away"] = best[("spreads", away)][2]

    if ("totals", "Over") in best:
        odds_data.total["line"] = best_points.get(("totals", "Over"), 0)
        odds_data.total["over_odds"] = best[("totals", "Over")][1]
        odds_data.book_sources["totals_over"] = best[("totals", "Over")][2]
    if ("totals", "Under") in best:
        odds_data.total["under_odds"] = best[("totals", "Under")][1]
        odds_data.book_sources["totals_under"] = best[("totals", "Under")][2]

    if ("h2h_1st_5_innings", home) in best:
        odds_data.f5_moneyline["home"] = best[("h2h_1st_5_innings", home)][1]
        odds_data.book_sources["f5_ml_home"] = best[("h2h_1st_5_innings", home)][2]
    if ("h2h_1st_5_innings", away) in best:
        odds_data.f5_moneyline["away"] = best[("h2h_1st_5_innings", away)][1]
        odds_data.book_sources["f5_ml_away"] = best[("h2h_1st_5_innings", away)][2]

    if ("totals_1st_5_innings", "Over") in best:
        odds_data.f5_total["line"] = best_points.get(("totals_1st_5_innings", "Over"), 0)
        odds_data.f5_total["over_odds"] = best[("totals_1st_5_innings", "Over")][1]
        odds_data.book_sources["f5_total_over"] = best[("totals_1st_5_innings", "Over")][2]
    if ("totals_1st_5_innings", "Under") in best:
        odds_data.f5_total["under_odds"] = best[("totals_1st_5_innings", "Under")][1]
        odds_data.book_sources["f5_total_under"] = best[("totals_1st_5_innings", "Under")][2]

    # Consensus implied probs (averaged power-devig across books)
    if odds_data.moneyline:
        h2h_books = all_book_odds.get("h2h", [])
        if h2h_books:
            dv_homes, dv_aways = [], []
            for book in h2h_books:
                if home in book and away in book:
                    h = american_to_implied_prob(book[home])
                    a = american_to_implied_prob(book[away])
                    dh, da = power_devig(h, a)
                    dv_homes.append(dh)
                    dv_aways.append(da)
            if dv_homes:
                odds_data.implied_probs["ml_home"] = round(sum(dv_homes) / len(dv_homes), 6)
                odds_data.implied_probs["ml_away"] = round(sum(dv_aways) / len(dv_aways), 6)
                odds_data.implied_probs["ml_book_count"] = len(dv_homes)

    if odds_data.run_line:
        rl_books = all_book_odds.get("spreads", [])
        if rl_books:
            dv_homes, dv_aways = [], []
            for book in rl_books:
                if home in book and away in book:
                    h = american_to_implied_prob(book[home])
                    a = american_to_implied_prob(book[away])
                    dh, da = power_devig(h, a)
                    dv_homes.append(dh)
                    dv_aways.append(da)
            if dv_homes:
                odds_data.implied_probs["rl_home"] = round(sum(dv_homes) / len(dv_homes), 6)
                odds_data.implied_probs["rl_away"] = round(sum(dv_aways) / len(dv_aways), 6)
                odds_data.implied_probs["rl_book_count"] = len(dv_homes)
        else:
            rl_home = american_to_implied_prob(odds_data.run_line.get("home_odds", -110))
            rl_away = american_to_implied_prob(odds_data.run_line.get("away_odds", -110))
            dv_home, dv_away = power_devig(rl_home, rl_away)
            odds_data.implied_probs["rl_home"] = dv_home
            odds_data.implied_probs["rl_away"] = dv_away
            odds_data.implied_probs["rl_book_count"] = 1

    return odds_data


def get_historical_mlb_odds(snapshot_iso: str,
                            sport: str = "baseball_mlb",
                            markets: str = "h2h,spreads,totals",
                            regions: str = "us") -> list[OddsData]:
    """Fetch a historical odds snapshot from The Odds API.

    snapshot_iso: ISO-8601 UTC timestamp like '2026-04-19T23:00:00Z'.
    The API rounds to the nearest 5-minute bucket and returns all events active at that time.
    Cost: ~10 credits per (region × market) per call.

    The /odds snapshot endpoint only supports h2h/spreads/totals historically.
    Use get_historical_event_odds() for team_totals, NRFI (totals_1st_1_innings),
    F5 markets, and other additional/alternate markets.
    """
    url = f"{ODDS_API_BASE}/historical/sports/{sport}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "date": snapshot_iso,
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    events = payload.get("data", []) if isinstance(payload, dict) else []
    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"[odds.hist] {snapshot_iso} → {len(events)} events (remaining: {remaining})")

    results = []
    for event in events:
        odds_data = _parse_event_to_odds_data(event)
        if odds_data is not None:
            results.append(odds_data)
    return results


_HIST_EVENT_DEFAULT_MARKETS = (
    # Mainlines: team totals + NRFI + F1/F3/F5 mainline markets
    "team_totals,totals_1st_1_innings,spreads_1st_1_innings,"
    "h2h_1st_3_innings,totals_1st_3_innings,spreads_1st_3_innings,"
    "spreads_1st_5_innings,"
    # Player props
    "pitcher_strikeouts,pitcher_earned_runs,pitcher_outs,pitcher_hits_allowed,"
    "batter_total_bases,batter_rbis,batter_hits,batter_runs_scored,"
    "batter_hits_runs_rbis,batter_strikeouts"
)


def get_historical_event_odds(event_id: str,
                              snapshot_iso: str,
                              sport: str = "baseball_mlb",
                              markets: str = _HIST_EVENT_DEFAULT_MARKETS,
                              regions: str = "us") -> tuple[dict, dict]:
    """Fetch a single event's historical odds for additional + prop markets.

    Returns (merged_markets, raw_event):
      - merged_markets: dict suitable for _parse_additional_markets (alternate lines filtered out)
      - raw_event: the unfiltered event JSON, useful for prop extraction
    Returns ({}, {}) on failure.
    """
    url = f"{ODDS_API_BASE}/historical/sports/{sport}/events/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "date": snapshot_iso,
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            print(f"[odds.hist] event {event_id} @ {snapshot_iso}: status {resp.status_code}")
            return {}, {}
        payload = resp.json()
        event = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not event:
            return {}, {}

        # Per-event responses include alternate lines for team_totals/totals.
        # Identify the primary (most-common across books) line per side, drop alternates.
        line_counts: dict = {}
        for bk in event.get("bookmakers", []):
            for m in bk.get("markets", []):
                mk = m["key"]
                for outcome in m.get("outcomes", []):
                    side_key = (mk, outcome.get("name", ""), outcome.get("description", ""))
                    point = outcome.get("point")
                    if point is not None:
                        line_counts.setdefault(side_key, {})
                        line_counts[side_key][point] = line_counts[side_key].get(point, 0) + 1
        primary_lines = {sk: max(counts, key=counts.get) for sk, counts in line_counts.items()}

        merged = {}
        for bk in event.get("bookmakers", []):
            for m in bk.get("markets", []):
                mk = m["key"]
                if mk not in merged:
                    merged[mk] = {"key": mk, "outcomes": []}
                existing = {_outcome_key(o): o for o in merged[mk].get("outcomes", [])}
                for outcome in m.get("outcomes", []):
                    point = outcome.get("point")
                    if point is not None:
                        side_key = (mk, outcome.get("name", ""), outcome.get("description", ""))
                        if side_key in primary_lines and point != primary_lines[side_key]:
                            continue  # skip alternate lines
                    okey = _outcome_key(outcome)
                    if okey not in existing or _american_to_decimal(outcome["price"]) > _american_to_decimal(existing[okey]["price"]):
                        existing[okey] = outcome
                merged[mk]["outcomes"] = list(existing.values())
        return merged, event
    except Exception as e:
        print(f"[odds.hist] event {event_id} fetch failed: {e}")
        return {}, {}


# Mirror of simulation.props_edge.PROP_MARKETS. Duplicated here so the feed
# coverage check doesn't drag the calibration stack (numpy/pandas/sklearn) into
# lightweight callers like close-capture just to log a warning. test_odds_feed
# pins this equal to the source list so the two can't drift.
_PROP_MARKET_KEYS = frozenset({
    "pitcher_strikeouts", "pitcher_earned_runs", "pitcher_outs", "pitcher_hits_allowed",
    "batter_total_bases", "batter_rbis", "batter_hits", "batter_runs_scored",
    "batter_hits_runs_rbis", "batter_strikeouts",
})


def _expected_feed_markets() -> set[str]:
    """Every market the MLB pipeline pulls from the feed: mainlines + the
    per-event additional markets + player props. Used to warn when the backend
    isn't serving something the agent models (e.g. a market toggled off in the
    betting-site settings)."""
    expected = {"h2h", "spreads", "totals", "h2h_1st_5_innings", "totals_1st_5_innings"}
    expected |= set(ADDITIONAL_MARKETS.split(","))
    expected |= _PROP_MARKET_KEYS
    return expected


def get_mlb_odds(date: str = None, sport: str = None) -> list[OddsData]:
    """Fetch MLB odds for h2h, spreads, totals markets.

    Pulls from the shared backend feed when configured (reusing the betting
    site's live-odds cache, no API spend); otherwise hits The Odds API
    directly. Uses regular season odds only.
    """
    if feed_enabled():
        try:
            events = get_feed_events()
            print(f"[odds] Using shared feed ({len(events)} events)")
            warn_missing_markets(events, _expected_feed_markets(), context="mlb")
            return _build_odds_data(events, date)
        except FeedUnavailable as e:
            print(f"[odds] Shared feed unavailable ({e}); falling back to Odds API")

    sport_keys = [sport] if sport else ["baseball_mlb"]
    markets_options = [
        "h2h,spreads,totals,h2h_1st_5_innings,totals_1st_5_innings",
        "h2h,spreads,totals",
    ]

    resp = None
    for sport_key in sport_keys:
        url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
        for markets in markets_options:
            params = {
                "apiKey": ODDS_API_KEY,
                "regions": "us,us2,eu,uk",
                "markets": markets,
                "oddsFormat": "american",
            }
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 422 and "1st_5" in markets:
                print("[odds] F5 markets not available, falling back to core markets")
                continue
            resp.raise_for_status()
            break

        data = resp.json()
        if data:
            print(f"[odds] Using {sport_key} ({len(data)} games)")
            break
        else:
            print(f"[odds] No games on {sport_key}, trying next...")

    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"[odds] API requests remaining: {remaining}")

    return _build_odds_data(data, date)


def _build_odds_data(events: list[dict], date: str = None) -> list[OddsData]:
    """Parse raw Odds API events into OddsData: skip started games and filter
    to the current game day (US/Eastern). Shared by the direct-API and
    shared-feed paths so both apply identical live-skip and day-filtering."""
    results = []
    now = datetime.now(timezone.utc)
    skipped_live = 0
    for event in events:
        # Skip games that have already started
        commence_time = event.get("commence_time", "")
        if commence_time:
            try:
                game_start = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
                if game_start <= now:
                    skipped_live += 1
                    continue
            except (ValueError, TypeError):
                pass  # if we can't parse, include it

        odds_data = _parse_event_to_odds_data(event)
        if odds_data is None:
            continue
        results.append(odds_data)

    if skipped_live:
        print(f"[odds] Skipped {skipped_live} live/started games")

    # Filter to current game day only — the API often returns tomorrow's games too.
    # Use US/Eastern to determine game date since MLB games are scheduled in US time.
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo("America/New_York")
    game_date_str = date or datetime.now(eastern).strftime("%Y-%m-%d")
    day_filtered = []
    skipped_other_day = 0
    for odds_data in results:
        ct = odds_data.commence_time
        if ct:
            try:
                game_dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                local_date = game_dt.astimezone(eastern).strftime("%Y-%m-%d")
                if local_date != game_date_str:
                    skipped_other_day += 1
                    continue
            except (ValueError, TypeError):
                pass
        day_filtered.append(odds_data)

    if skipped_other_day:
        print(f"[odds] Filtered to {game_date_str}: kept {len(day_filtered)}, skipped {skipped_other_day} from other days")

    return day_filtered
