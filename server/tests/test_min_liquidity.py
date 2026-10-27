from datetime import datetime, timedelta, timezone

from server.odds.arbitrage import scan_all_arbs
from server.odds.liquidity import filter_games_min_liquidity, is_liquid, resolve_min_liquidity
from server.user_settings import UserSettings, UserSettingsStore


NOW = datetime.now(timezone.utc)


def _p(book, price, size=None):
    return {"bookmaker_key": book, "price_american": price, "point": None,
            "max_stake_dollars": size, "fetched_at": NOW}


def _game(home_prices, away_prices):
    def outcome(name, prices):
        best = max(prices, key=lambda p: p["price_american"])
        return {"outcome_name": name, "prices": prices, "best_price": best}
    return {
        "event_id": "e1", "sport_key": "nba", "home_team": "H", "away_team": "A",
        "commence_time": NOW + timedelta(hours=3),
        "markets": [{"market_key": "h2h", "outcomes": [
            outcome("H", home_prices), outcome("A", away_prices),
        ]}],
    }


def test_is_liquid_passes_unknown_depth_and_off():
    assert is_liquid({"max_stake_dollars": None}, 100)
    assert is_liquid({"max_stake_dollars": 5}, 0)
    assert not is_liquid({"max_stake_dollars": 5}, 100)
    assert is_liquid({"max_stake_dollars": 100}, 100)


def test_filter_shares_untouched_games_and_recomputes_best():
    clean = _game([_p("draftkings", -110)], [_p("fanduel", -105)])
    thin = _game([_p("kalshi", 120, size=4), _p("draftkings", 105)], [_p("fanduel", -110)])
    out = filter_games_min_liquidity([clean, thin], 50)
    assert out[0] is clean
    home = out[1]["markets"][0]["outcomes"][0]
    assert [p["bookmaker_key"] for p in home["prices"]] == ["draftkings"]
    assert home["best_price"]["bookmaker_key"] == "draftkings"
    assert thin["markets"][0]["outcomes"][0]["prices"][0]["bookmaker_key"] == "kalshi"  # input untouched
    assert filter_games_min_liquidity([thin], 0)[0] is thin


def test_arb_falls_back_to_next_liquid_leg():
    g = _game([_p("kalshi", 130, size=4), _p("draftkings", 115)], [_p("fanduel", -105)])
    arbs = scan_all_arbs([g])
    assert arbs and arbs[0]["sides"][0]["book"] == "kalshi"
    filtered = scan_all_arbs(filter_games_min_liquidity([g], 50))
    assert filtered and filtered[0]["sides"][0]["book"] == "draftkings"
    assert filtered[0]["roi_pct"] < arbs[0]["roi_pct"]


def test_setting_roundtrip_and_resolution(tmp_path):
    store = UserSettingsStore(tmp_path / "s.json")
    assert store.get().min_liquidity_dollars == 0
    assert resolve_min_liquidity(None, store) == 0
    store.set(UserSettings(min_liquidity_dollars=75))
    assert UserSettingsStore(tmp_path / "s.json").get().min_liquidity_dollars == 75
    assert resolve_min_liquidity(None, store) == 75
    assert resolve_min_liquidity(0, store) == 0          # explicit param wins
    assert resolve_min_liquidity(None, None) == 0
    assert UserSettings.from_dict({"min_liquidity_dollars": "junk"}).min_liquidity_dollars == 0
