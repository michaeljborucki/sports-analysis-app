"""Fetch tennis odds from The Odds API."""
from dataclasses import dataclass, field
import requests
from config import ODDS_API_KEY, ODDS_API_BASE, TOUR_CONFIG


def american_to_implied_prob(odds: int) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def prob_to_american(prob: float) -> int:
    """American odds whose implied probability equals `prob`.

    This is the breakeven price — any price better than this yields positive edge.
    """
    if prob <= 0 or prob >= 1:
        raise ValueError(f"probability must be in (0, 1), got {prob}")
    if prob >= 0.5:
        return -round(prob / (1 - prob) * 100)
    return round((1 - prob) / prob * 100)


def american_be_with_wiggle(odds: int) -> int:
    """Shrink |odds| by at least 5 toward 0, floored to a multiple of 5.

    American odds have no valid representation in (-100, +100) — decimal 2.00 maps
    to both ±100. When the shrink lands below |100|, cross zero to produce a valid
    price on the other side (e.g. -103 → would-be -95 → +105).
    """
    sign = -1 if odds < 0 else 1
    shrunk = (abs(odds) - 5) // 5 * 5
    if shrunk >= 100:
        return sign * shrunk
    # Crossed zero: land on the opposite side, same distance from 100.
    return -sign * (100 + (100 - shrunk))


def _american_to_decimal(odds: int) -> float:
    if odds < 0:
        return round(100 / abs(odds) + 1, 6)
    return round(odds / 100 + 1, 6)


def compute_clv(bet_odds: int, close_odds: int) -> dict:
    """Closing-line value.

    clv_cents: signed American-cent movement in our favor. Positive means we beat the close.
      - Same sign on both: |close| shortened/lengthened directly comparable.
      - Signs differ: cross-zero — reduce the gap to the hinge at ±100.
    clv_pct: (bet_decimal / close_decimal) - 1. Interpretable across prices.
    """
    bet_dec = _american_to_decimal(int(bet_odds))
    close_dec = _american_to_decimal(int(close_odds))
    clv_pct = round((bet_dec / close_dec) - 1.0, 4)

    bet_odds = int(bet_odds)
    close_odds = int(close_odds)
    if bet_odds < 0 and close_odds < 0:
        cents = abs(close_odds) - abs(bet_odds)
    elif bet_odds > 0 and close_odds > 0:
        cents = bet_odds - close_odds
    elif bet_odds > 0 and close_odds < 0:
        # We took a dog price, market closed as favorite on our side.
        cents = (bet_odds - 100) + (abs(close_odds) - 100)
    else:
        # We took a favorite price, market closed as dog on our side.
        cents = -((abs(bet_odds) - 100) + (close_odds - 100))

    return {"clv_cents": int(cents), "clv_pct": clv_pct}


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
    player_a: str
    player_b: str
    commence_time: str
    moneyline: dict = field(default_factory=dict)
    game_handicap: dict = field(default_factory=dict)
    total_games: dict = field(default_factory=dict)
    implied_probs: dict = field(default_factory=dict)


def _last_name(name: str) -> str:
    parts = name.replace(".", " ").replace(",", " ").split()
    return parts[-1].lower() if parts else ""


def _flip_player_keys(d: dict) -> dict:
    sentinel = "__TMP_PLAYER__"
    out = {}
    for k, v in d.items():
        nk = k.replace("player_a", sentinel).replace("player_b", "player_a").replace(sentinel, "player_b")
        out[nk] = v
    return out


def _flip_odds(o: "OddsData") -> "OddsData":
    return OddsData(
        player_a=o.player_b,
        player_b=o.player_a,
        commence_time=o.commence_time,
        moneyline=_flip_player_keys(o.moneyline),
        game_handicap=_flip_player_keys(o.game_handicap),
        total_games=dict(o.total_games),
        implied_probs=_flip_player_keys(o.implied_probs),
    )


def find_odds_for_match(odds_list: list["OddsData"], player_a: str, player_b: str) -> "OddsData | None":
    """Match schedule players to odds by last-name pair, flipping orientation if needed."""
    pa_last = _last_name(player_a)
    pb_last = _last_name(player_b)
    if not pa_last or not pb_last or pa_last == pb_last:
        return None
    target = {pa_last, pb_last}
    for o in odds_list:
        oa_last = _last_name(o.player_a)
        ob_last = _last_name(o.player_b)
        if {oa_last, ob_last} != target:
            continue
        return o if oa_last == pa_last else _flip_odds(o)
    return None


def get_tennis_odds(tour: str = "atp") -> list[OddsData]:
    sport_prefix = TOUR_CONFIG[tour]["odds_sport_key"]
    sports_resp = requests.get(f"{ODDS_API_BASE}/sports", params={"apiKey": ODDS_API_KEY}, timeout=15)
    sports_resp.raise_for_status()
    sport_keys = [s["key"] for s in sports_resp.json() if s["key"].startswith(sport_prefix + "_") and s.get("active")]

    events_all = []
    remaining = "?"
    for sport_key in sport_keys:
        url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        events_all.extend(resp.json())
        remaining = resp.headers.get("x-requests-remaining", remaining)
    print(f"[odds] {tour.upper()}: {len(events_all)} matches across {len(sport_keys)} tournaments, API requests remaining: {remaining}")

    results = []
    for event in events_all:
        player_a = event["home_team"]
        player_b = event["away_team"]
        odds_data = OddsData(player_a=player_a, player_b=player_b, commence_time=event["commence_time"])

        h2h_pairs = []  # (player_a_price, player_b_price) per book
        got_display = False
        for bk in event.get("bookmakers", []):
            markets = {m["key"]: m for m in bk.get("markets", [])}
            # Collect paired h2h odds from ALL bookmakers
            if "h2h" in markets:
                pa, pb = None, None
                for outcome in markets["h2h"]["outcomes"]:
                    if outcome["name"] == player_a:
                        pa = outcome["price"]
                    else:
                        pb = outcome["price"]
                if pa is not None and pb is not None:
                    h2h_pairs.append((pa, pb))
            # Use first book with data for display odds
            if not got_display:
                if "h2h" in markets:
                    for outcome in markets["h2h"]["outcomes"]:
                        if outcome["name"] == player_a:
                            odds_data.moneyline["player_a"] = outcome["price"]
                        else:
                            odds_data.moneyline["player_b"] = outcome["price"]
                if "spreads" in markets:
                    for outcome in markets["spreads"]["outcomes"]:
                        if outcome["name"] == player_a:
                            odds_data.game_handicap["player_a_point"] = outcome.get("point", 0)
                            odds_data.game_handicap["player_a_odds"] = outcome["price"]
                        else:
                            odds_data.game_handicap["player_b_point"] = outcome.get("point", 0)
                            odds_data.game_handicap["player_b_odds"] = outcome["price"]
                if "totals" in markets:
                    for outcome in markets["totals"]["outcomes"]:
                        if outcome["name"] == "Over":
                            odds_data.total_games["line"] = outcome.get("point", 0)
                            odds_data.total_games["over_odds"] = outcome["price"]
                        else:
                            odds_data.total_games["under_odds"] = outcome["price"]
                if odds_data.moneyline:
                    got_display = True

        # Compute consensus implied probs across ALL bookmakers
        if odds_data.moneyline and h2h_pairs:
            dv_as, dv_bs = [], []
            for pa_price, pb_price in h2h_pairs:
                pa = american_to_implied_prob(pa_price)
                pb = american_to_implied_prob(pb_price)
                da, db = power_devig(pa, pb)
                dv_as.append(da)
                dv_bs.append(db)
            odds_data.implied_probs["player_a"] = round(sum(dv_as) / len(dv_as), 6)
            odds_data.implied_probs["player_b"] = round(sum(dv_bs) / len(dv_bs), 6)
            odds_data.implied_probs["player_a_worst"] = round(max(dv_as), 6)
            odds_data.implied_probs["player_b_worst"] = round(max(dv_bs), 6)
            odds_data.implied_probs["ml_book_count"] = len(dv_as)
        results.append(odds_data)
    return results
