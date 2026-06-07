from dataclasses import dataclass, field
import requests
from config import ODDS_API_KEY, ODDS_API_BASE, ODDS_SPORT_KEY, TEAM_NAME_TO_ABBREV


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def power_devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove vig using the power method. Solves for n where p_a^n + p_b^n = 1."""
    total = prob_a + prob_b
    if total <= 0:
        return (0.5, 0.5)
    if abs(total - 1.0) < 1e-6:
        return (prob_a, prob_b)
    if prob_a <= 0.001 or prob_b <= 0.001:
        return (prob_a / total, prob_b / total)
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
    event_id: str = ""
    moneyline: dict = field(default_factory=dict)
    spread: dict = field(default_factory=dict)
    total: dict = field(default_factory=dict)
    h1_moneyline: dict = field(default_factory=dict)
    h1_total: dict = field(default_factory=dict)
    h1_spread: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)
    # Second half markets
    h2_moneyline: dict = field(default_factory=dict)
    h2_spread: dict = field(default_factory=dict)
    h2_total: dict = field(default_factory=dict)
    # Quarter moneylines and spreads
    q1_moneyline: dict = field(default_factory=dict)
    q1_spread: dict = field(default_factory=dict)
    q1_total: dict = field(default_factory=dict)
    q2_moneyline: dict = field(default_factory=dict)
    q2_spread: dict = field(default_factory=dict)
    q2_total: dict = field(default_factory=dict)
    q3_moneyline: dict = field(default_factory=dict)
    q3_spread: dict = field(default_factory=dict)
    q3_total: dict = field(default_factory=dict)
    q4_moneyline: dict = field(default_factory=dict)
    q4_spread: dict = field(default_factory=dict)
    q4_total: dict = field(default_factory=dict)
    # Team totals: {home: {line, over_odds, under_odds}, away: {...}}
    team_totals: dict = field(default_factory=dict)
    # Alternate lines
    alt_spreads: list = field(default_factory=list)
    alt_totals: list = field(default_factory=list)
    # Player props: {player_name: {points: {line, over_odds, under_odds}, ...}}
    player_props: dict = field(default_factory=dict)


BOOKMAKER_PREFERENCE = ["draftkings", "fanduel", "betmgm"]


def _pick_bookmaker(bookmakers: list) -> dict | None:
    by_key = {bk["key"]: bk for bk in bookmakers}
    for pref in BOOKMAKER_PREFERENCE:
        if pref in by_key:
            return by_key[pref]
    return bookmakers[0] if bookmakers else None


def _devig_two_way(odds_a: int, odds_b: int) -> tuple[float, float]:
    """Convert two American odds to devigged probabilities using power method."""
    prob_a = american_to_implied_prob(odds_a)
    prob_b = american_to_implied_prob(odds_b)
    return power_devig(prob_a, prob_b)


def _consensus_from_bookmakers(bookmakers: list, market_key: str,
                                home_abbrev: str, market_type: str = "two_side") -> dict:
    """Compute consensus devigged implied probs across ALL bookmakers for a market.

    market_type:
      'two_side' - h2h markets (home/away by team name)
      'over_under' - totals markets (Over/Under)
      'spread' - spread markets (home/away by team name, has points)

    Returns dict with devigged prob keys depending on market_type.
    """
    probs_a = []  # home or over or home-spread
    probs_b = []  # away or under or away-spread

    for bk in bookmakers:
        markets_map = {m["key"]: m for m in bk.get("markets", [])}
        if market_key not in markets_map:
            continue
        outcomes = markets_map[market_key].get("outcomes", [])
        if len(outcomes) < 2:
            continue

        if market_type == "over_under":
            over_odds = under_odds = None
            for o in outcomes:
                if o["name"] == "Over":
                    over_odds = o["price"]
                elif o["name"] == "Under":
                    under_odds = o["price"]
            if over_odds is not None and under_odds is not None:
                dv_over, dv_under = _devig_two_way(over_odds, under_odds)
                probs_a.append(dv_over)
                probs_b.append(dv_under)
        else:  # two_side or spread
            home_odds = away_odds = None
            for o in outcomes:
                if _team_abbrev(o["name"]) == home_abbrev:
                    home_odds = o["price"]
                else:
                    away_odds = o["price"]
            if home_odds is not None and away_odds is not None:
                dv_home, dv_away = _devig_two_way(home_odds, away_odds)
                probs_a.append(dv_home)
                probs_b.append(dv_away)

    if not probs_a:
        return {}

    avg_a = sum(probs_a) / len(probs_a)
    avg_b = sum(probs_b) / len(probs_b)
    worst_a = max(probs_a)  # highest prob = least favorable for the bettor
    worst_b = max(probs_b)
    n_books = len(probs_a)

    if market_type == "over_under":
        return {"over": round(avg_a, 6), "under": round(avg_b, 6),
                "worst_over": round(worst_a, 6), "worst_under": round(worst_b, 6),
                "n_books": n_books}
    return {"home": round(avg_a, 6), "away": round(avg_b, 6),
            "worst_home": round(worst_a, 6), "worst_away": round(worst_b, 6),
            "n_books": n_books}


def _build_consensus_implied_probs(bookmakers: list, home: str) -> dict:
    """Build consensus implied probs across all bookmakers for all bulk markets."""
    implied = {}

    # Moneyline
    c = _consensus_from_bookmakers(bookmakers, "h2h", home, "two_side")
    if c:
        implied["ml_home"] = c["home"]
        implied["ml_away"] = c["away"]
        implied["ml_home_worst"] = c["worst_home"]
        implied["ml_away_worst"] = c["worst_away"]
        implied["ml_n_books"] = c["n_books"]

    # Spread
    c = _consensus_from_bookmakers(bookmakers, "spreads", home, "spread")
    if c:
        implied["spread_home"] = c["home"]
        implied["spread_away"] = c["away"]
        implied["spread_home_worst"] = c["worst_home"]
        implied["spread_away_worst"] = c["worst_away"]

    # Total
    c = _consensus_from_bookmakers(bookmakers, "totals", home, "over_under")
    if c:
        implied["total_over"] = c["over"]
        implied["total_under"] = c["under"]
        implied["total_over_worst"] = c["worst_over"]
        implied["total_under_worst"] = c["worst_under"]

    # H1 markets
    c = _consensus_from_bookmakers(bookmakers, "h2h_h1", home, "two_side")
    if c:
        implied["h1_ml_home"] = c["home"]
        implied["h1_ml_away"] = c["away"]
        implied["h1_ml_home_worst"] = c["worst_home"]
        implied["h1_ml_away_worst"] = c["worst_away"]

    c = _consensus_from_bookmakers(bookmakers, "spreads_h1", home, "spread")
    if c:
        implied["h1_spread_home"] = c["home"]
        implied["h1_spread_away"] = c["away"]
        implied["h1_spread_home_worst"] = c["worst_home"]
        implied["h1_spread_away_worst"] = c["worst_away"]

    c = _consensus_from_bookmakers(bookmakers, "totals_h1", home, "over_under")
    if c:
        implied["h1_total_over"] = c["over"]
        implied["h1_total_under"] = c["under"]
        implied["h1_total_over_worst"] = c["worst_over"]
        implied["h1_total_under_worst"] = c["worst_under"]

    return implied


def _team_abbrev(full_name: str) -> str:
    return TEAM_NAME_TO_ABBREV.get(full_name, full_name)


def get_nba_odds() -> list[OddsData]:
    """Fetch NBA odds from The Odds API."""
    markets_options = [
        "h2h,spreads,totals,h2h_h1,totals_h1,spreads_h1",
        "h2h,spreads,totals",
    ]

    resp = None
    for markets in markets_options:
        url = f"{ODDS_API_BASE}/sports/{ODDS_SPORT_KEY}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": markets,
            "oddsFormat": "american",
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 422 and "h1" in markets:
            print("[odds] H1 markets not available, falling back to core markets")
            continue
        resp.raise_for_status()
        break

    data = resp.json()
    remaining = resp.headers.get("x-requests-remaining", "?")
    print(f"[odds] {len(data)} games, {remaining} API requests remaining")

    results = []
    for event in data:
        home = _team_abbrev(event["home_team"])
        away = _team_abbrev(event["away_team"])
        odds_data = OddsData(home=home, away=away, commence_time=event["commence_time"])
        odds_data.event_id = event.get("id", "")

        all_bookmakers = event.get("bookmakers", [])
        bk = _pick_bookmaker(all_bookmakers)
        if bk is not None:
            markets_map = {m["key"]: m for m in bk.get("markets", [])}

            if "h2h" in markets_map:
                for outcome in markets_map["h2h"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        odds_data.moneyline["home"] = outcome["price"]
                    else:
                        odds_data.moneyline["away"] = outcome["price"]

            if "spreads" in markets_map:
                for outcome in markets_map["spreads"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        odds_data.spread["home"] = outcome.get("point", 0)
                        odds_data.spread["home_odds"] = outcome["price"]
                    else:
                        odds_data.spread["away"] = outcome.get("point", 0)
                        odds_data.spread["away_odds"] = outcome["price"]

            if "totals" in markets_map:
                for outcome in markets_map["totals"]["outcomes"]:
                    if outcome["name"] == "Over":
                        odds_data.total["line"] = outcome.get("point", 0)
                        odds_data.total["over_odds"] = outcome["price"]
                    else:
                        odds_data.total["under_odds"] = outcome["price"]

            if "h2h_h1" in markets_map:
                for outcome in markets_map["h2h_h1"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        odds_data.h1_moneyline["home"] = outcome["price"]
                    else:
                        odds_data.h1_moneyline["away"] = outcome["price"]

            if "totals_h1" in markets_map:
                for outcome in markets_map["totals_h1"]["outcomes"]:
                    if outcome["name"] == "Over":
                        odds_data.h1_total["line"] = outcome.get("point", 0)
                        odds_data.h1_total["over_odds"] = outcome["price"]
                    else:
                        odds_data.h1_total["under_odds"] = outcome["price"]

            if "spreads_h1" in markets_map:
                for outcome in markets_map["spreads_h1"]["outcomes"]:
                    if _team_abbrev(outcome["name"]) == home:
                        odds_data.h1_spread["home"] = outcome.get("point", 0)
                        odds_data.h1_spread["home_odds"] = outcome["price"]
                    else:
                        odds_data.h1_spread["away"] = outcome.get("point", 0)
                        odds_data.h1_spread["away_odds"] = outcome["price"]

        # Compute consensus implied probs across ALL bookmakers (not just the selected one)
        odds_data.implied_probs = _build_consensus_implied_probs(all_bookmakers, home)

        results.append(odds_data)

    return results


def get_event_odds(event_id: str) -> dict:
    """Fetch extended markets for a single event via per-event endpoint."""
    from config import ODDS_EVENT_ENDPOINT, ODDS_EVENT_MARKETS
    url = f"{ODDS_EVENT_ENDPOINT}/{event_id}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": ODDS_EVENT_MARKETS,
        "oddsFormat": "american",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _extend_consensus_implied_probs(implied: dict, bookmakers: list, home: str) -> None:
    """Add consensus implied probs for extended markets (Q1-Q4, team totals, props)."""
    # Q1 markets
    c = _consensus_from_bookmakers(bookmakers, "h2h_q1", home, "two_side")
    if c:
        implied["q1_ml_home"] = c["home"]
        implied["q1_ml_away"] = c["away"]
        implied["q1_ml_home_worst"] = c["worst_home"]
        implied["q1_ml_away_worst"] = c["worst_away"]

    c = _consensus_from_bookmakers(bookmakers, "spreads_q1", home, "spread")
    if c:
        implied["q1_spread_home"] = c["home"]
        implied["q1_spread_away"] = c["away"]
        implied["q1_spread_home_worst"] = c["worst_home"]
        implied["q1_spread_away_worst"] = c["worst_away"]

    for q in ["q1", "q2", "q3", "q4"]:
        c = _consensus_from_bookmakers(bookmakers, f"totals_{q}", home, "over_under")
        if c:
            implied[f"{q}_total_over"] = c["over"]
            implied[f"{q}_total_under"] = c["under"]
            implied[f"{q}_total_over_worst"] = c["worst_over"]
            implied[f"{q}_total_under_worst"] = c["worst_under"]

    # Team totals — need custom handling since outcomes have description field for team
    tt_probs_home_over = []
    tt_probs_home_under = []
    tt_probs_away_over = []
    tt_probs_away_under = []
    for bk in bookmakers:
        markets_map = {m["key"]: m for m in bk.get("markets", [])}
        if "team_totals" not in markets_map:
            continue
        # Group by team side
        home_over = home_under = away_over = away_under = None
        for o in markets_map["team_totals"]["outcomes"]:
            side = "home" if _team_abbrev(o.get("description", "")) == home else "away"
            if side == "home":
                if o["name"] == "Over":
                    home_over = o["price"]
                elif o["name"] == "Under":
                    home_under = o["price"]
            else:
                if o["name"] == "Over":
                    away_over = o["price"]
                elif o["name"] == "Under":
                    away_under = o["price"]
        if home_over is not None and home_under is not None:
            dv_o, dv_u = _devig_two_way(home_over, home_under)
            tt_probs_home_over.append(dv_o)
            tt_probs_home_under.append(dv_u)
        if away_over is not None and away_under is not None:
            dv_o, dv_u = _devig_two_way(away_over, away_under)
            tt_probs_away_over.append(dv_o)
            tt_probs_away_under.append(dv_u)

    if tt_probs_home_over:
        implied["tt_home_over"] = round(sum(tt_probs_home_over) / len(tt_probs_home_over), 6)
        implied["tt_home_under"] = round(sum(tt_probs_home_under) / len(tt_probs_home_under), 6)
        implied["tt_home_over_worst"] = round(max(tt_probs_home_over), 6)
        implied["tt_home_under_worst"] = round(max(tt_probs_home_under), 6)
    if tt_probs_away_over:
        implied["tt_away_over"] = round(sum(tt_probs_away_over) / len(tt_probs_away_over), 6)
        implied["tt_away_under"] = round(sum(tt_probs_away_under) / len(tt_probs_away_under), 6)
        implied["tt_away_over_worst"] = round(max(tt_probs_away_over), 6)
        implied["tt_away_under_worst"] = round(max(tt_probs_away_under), 6)

    # Player prop consensus
    prop_market_map = {
        "player_points": "points", "player_rebounds": "rebounds",
        "player_assists": "assists", "player_threes": "threes",
        "player_points_rebounds_assists": "pra",
    }
    for market_key, prop_name in prop_market_map.items():
        # Collect per-player devigged probs across all books
        player_probs: dict[str, list[tuple[float, float]]] = {}
        for bk_item in bookmakers:
            mkts = {m["key"]: m for m in bk_item.get("markets", [])}
            if market_key not in mkts:
                continue
            # Group outcomes by player
            player_odds: dict[str, dict] = {}
            for o in mkts[market_key]["outcomes"]:
                player = o.get("description", o.get("name", "unknown"))
                if player not in player_odds:
                    player_odds[player] = {}
                if o["name"] == "Over":
                    player_odds[player]["over"] = o["price"]
                elif o["name"] == "Under":
                    player_odds[player]["under"] = o["price"]
            for player, po in player_odds.items():
                if "over" in po and "under" in po:
                    dv_o, dv_u = _devig_two_way(po["over"], po["under"])
                    player_probs.setdefault(player, []).append((dv_o, dv_u))
        # Average per player
        for player, prob_list in player_probs.items():
            avg_over = sum(p[0] for p in prob_list) / len(prob_list)
            avg_under = sum(p[1] for p in prob_list) / len(prob_list)
            worst_over = max(p[0] for p in prob_list)
            worst_under = max(p[1] for p in prob_list)
            key_prefix = f"prop_{prop_name}_{player}"
            implied[key_prefix + "_over"] = round(avg_over, 6)
            implied[key_prefix + "_under"] = round(avg_under, 6)
            implied[key_prefix + "_over_worst"] = round(worst_over, 6)
            implied[key_prefix + "_under_worst"] = round(worst_under, 6)


def merge_event_odds(odds_data: OddsData, event_resp: dict) -> None:
    """Merge per-event extended markets into an OddsData instance (mutates in place)."""
    home = odds_data.home
    bookmakers = event_resp.get("bookmakers", [])

    # Extend consensus implied probs with data from ALL bookmakers
    _extend_consensus_implied_probs(odds_data.implied_probs, bookmakers, home)

    bk = _pick_bookmaker(bookmakers)
    if bk is None:
        return

    markets_map = {m["key"]: m for m in bk.get("markets", [])}

    # --- Second half ---
    if "h2h_h2" in markets_map:
        for outcome in markets_map["h2h_h2"]["outcomes"]:
            if _team_abbrev(outcome["name"]) == home:
                odds_data.h2_moneyline["home"] = outcome["price"]
            else:
                odds_data.h2_moneyline["away"] = outcome["price"]

    if "spreads_h2" in markets_map:
        for outcome in markets_map["spreads_h2"]["outcomes"]:
            if _team_abbrev(outcome["name"]) == home:
                odds_data.h2_spread["home"] = outcome.get("point", 0)
                odds_data.h2_spread["home_odds"] = outcome["price"]
            else:
                odds_data.h2_spread["away"] = outcome.get("point", 0)
                odds_data.h2_spread["away_odds"] = outcome["price"]

    if "totals_h2" in markets_map:
        for outcome in markets_map["totals_h2"]["outcomes"]:
            if outcome["name"] == "Over":
                odds_data.h2_total["line"] = outcome.get("point", 0)
                odds_data.h2_total["over_odds"] = outcome["price"]
            else:
                odds_data.h2_total["under_odds"] = outcome["price"]

    # --- Q1 ---
    if "h2h_q1" in markets_map:
        for outcome in markets_map["h2h_q1"]["outcomes"]:
            if _team_abbrev(outcome["name"]) == home:
                odds_data.q1_moneyline["home"] = outcome["price"]
            else:
                odds_data.q1_moneyline["away"] = outcome["price"]

    if "spreads_q1" in markets_map:
        for outcome in markets_map["spreads_q1"]["outcomes"]:
            if _team_abbrev(outcome["name"]) == home:
                odds_data.q1_spread["home"] = outcome.get("point", 0)
                odds_data.q1_spread["home_odds"] = outcome["price"]
            else:
                odds_data.q1_spread["away"] = outcome.get("point", 0)
                odds_data.q1_spread["away_odds"] = outcome["price"]

    if "totals_q1" in markets_map:
        for outcome in markets_map["totals_q1"]["outcomes"]:
            if outcome["name"] == "Over":
                odds_data.q1_total["line"] = outcome.get("point", 0)
                odds_data.q1_total["over_odds"] = outcome["price"]
            else:
                odds_data.q1_total["under_odds"] = outcome["price"]

    # --- Q2 ---
    if "totals_q2" in markets_map:
        for outcome in markets_map["totals_q2"]["outcomes"]:
            if outcome["name"] == "Over":
                odds_data.q2_total["line"] = outcome.get("point", 0)
                odds_data.q2_total["over_odds"] = outcome["price"]
            else:
                odds_data.q2_total["under_odds"] = outcome["price"]

    # --- Q3 ---
    if "totals_q3" in markets_map:
        for outcome in markets_map["totals_q3"]["outcomes"]:
            if outcome["name"] == "Over":
                odds_data.q3_total["line"] = outcome.get("point", 0)
                odds_data.q3_total["over_odds"] = outcome["price"]
            else:
                odds_data.q3_total["under_odds"] = outcome["price"]

    # --- Q4 ---
    if "totals_q4" in markets_map:
        for outcome in markets_map["totals_q4"]["outcomes"]:
            if outcome["name"] == "Over":
                odds_data.q4_total["line"] = outcome.get("point", 0)
                odds_data.q4_total["over_odds"] = outcome["price"]
            else:
                odds_data.q4_total["under_odds"] = outcome["price"]

    # --- Team totals ---
    if "team_totals" in markets_map:
        for outcome in markets_map["team_totals"]["outcomes"]:
            desc = outcome.get("description", "").lower()
            side = "home" if _team_abbrev(outcome.get("description", "")) == home else "away"
            # Determine side by matching description against home team name
            # The description field typically holds the team name
            desc_full = outcome.get("description", "")
            if _team_abbrev(desc_full) == home:
                side = "home"
            else:
                side = "away"
            if side not in odds_data.team_totals:
                odds_data.team_totals[side] = {}
            name = outcome["name"]
            if name == "Over":
                odds_data.team_totals[side]["line"] = outcome.get("point", 0)
                odds_data.team_totals[side]["over_odds"] = outcome["price"]
            elif name == "Under":
                odds_data.team_totals[side]["under_odds"] = outcome["price"]

    # --- Alternate spreads ---
    if "alternate_spreads" in markets_map:
        for outcome in markets_map["alternate_spreads"]["outcomes"]:
            odds_data.alt_spreads.append({
                "team": _team_abbrev(outcome["name"]),
                "point": outcome.get("point", 0),
                "price": outcome["price"],
            })

    # --- Alternate totals ---
    if "alternate_totals" in markets_map:
        for outcome in markets_map["alternate_totals"]["outcomes"]:
            odds_data.alt_totals.append({
                "name": outcome["name"],
                "point": outcome.get("point", 0),
                "price": outcome["price"],
            })

    # --- Player props ---
    prop_market_map = {
        "player_points": "points",
        "player_rebounds": "rebounds",
        "player_assists": "assists",
        "player_threes": "threes",
        "player_points_rebounds_assists": "pra",
    }
    for market_key, prop_name in prop_market_map.items():
        if market_key not in markets_map:
            continue
        for outcome in markets_map[market_key]["outcomes"]:
            player = outcome.get("description", outcome.get("name", "unknown"))
            if player not in odds_data.player_props:
                odds_data.player_props[player] = {}
            if prop_name not in odds_data.player_props[player]:
                odds_data.player_props[player][prop_name] = {}
            otype = outcome["name"]  # "Over" or "Under"
            if otype == "Over":
                odds_data.player_props[player][prop_name]["line"] = outcome.get("point", 0)
                odds_data.player_props[player][prop_name]["over_odds"] = outcome["price"]
            elif otype == "Under":
                odds_data.player_props[player][prop_name]["under_odds"] = outcome["price"]
