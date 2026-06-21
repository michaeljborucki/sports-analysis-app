"""Unit tests for Kalshi Phase 2 normalizers.

Covers:
- `_split_team_pair` (team-pair decomposition from event_ticker tail)
- `_strip_strike_index` (peeling trailing strike-index from market suffix)
- `yes_to_american` (kelly-style YES decimal → American odds)
- Each Phase 2 `_normalize_*` path with realistic sample input.

The matcher is stubbed: it always returns a deterministic event_id keyed
on the (home, away) pair handed in, so we can assert the per-market
row shape without needing live Odds API events in the cache.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from server.odds.books.kalshi.normalizer import (
    _alt_market_passes_quality,
    _market_passes_quality,
    _split_team_pair,
    _strip_strike_index,
    normalize_markets,
    yes_to_american,
)
from server.odds.books.kalshi.mapping import TEAM_CODE_TO_CANONICAL


NOW = datetime(2026, 5, 12, 18, 0, tzinfo=timezone.utc)


def _stub_match(sport_key, home, away, commence, window):
    return {
        "event_id": f"stub-{sport_key}-{home}-{away}",
        "home_team": home,
        "away_team": away,
        "commence_time": commence,
    }


# ─── _split_team_pair ─────────────────────────────────────────────────


def test_split_team_pair_mlb_unambiguous():
    mlb = TEAM_CODE_TO_CANONICAL["mlb"]
    assert _split_team_pair("SDSEA", mlb) == ("SD", "SEA")
    assert _split_team_pair("ATHLAA", mlb) == ("ATH", "LAA")
    assert _split_team_pair("MILCHC", mlb) == ("MIL", "CHC")


def test_split_team_pair_wnba_four_char_code():
    wnba = TEAM_CODE_TO_CANONICAL["wnba"]
    assert _split_team_pair("CONNPDX", wnba) == ("CONN", "PDX")


def test_split_team_pair_returns_none_for_invalid_pair():
    mlb = TEAM_CODE_TO_CANONICAL["mlb"]
    # ZZX isn't in our map
    assert _split_team_pair("ZZXYY", mlb) is None
    # Too short
    assert _split_team_pair("AB", mlb) is None


def test_split_team_pair_empty_input():
    assert _split_team_pair("", TEAM_CODE_TO_CANONICAL["mlb"]) is None
    assert _split_team_pair(None, TEAM_CODE_TO_CANONICAL["mlb"]) is None  # type: ignore[arg-type]


# ─── _strip_strike_index ─────────────────────────────────────────────


def test_strip_strike_index_team_with_digits():
    assert _strip_strike_index("MIL8") == "MIL"
    assert _strip_strike_index("NYK124") == "NYK"
    assert _strip_strike_index("CONN3") == "CONN"


def test_strip_strike_index_no_digits():
    assert _strip_strike_index("TIE") == "TIE"
    assert _strip_strike_index("LAA") == "LAA"


def test_strip_strike_index_pure_numeric():
    # Totals suffix is pure numeric — leave alone
    assert _strip_strike_index("14") == "14"
    assert _strip_strike_index("230") == "230"


def test_strip_strike_index_empty():
    assert _strip_strike_index("") == ""


# ─── yes_to_american ─────────────────────────────────────────────────


def test_yes_to_american_underdog():
    # 0.3 raw → +233. With 7% taker fee:
    #   cost   = 0.3 + 0.07 * 0.3 * 0.7 = 0.3147
    #   profit = 1 - 0.3147 = 0.6853
    #   American = floor(0.6853 / 0.3147 * 100) = floor(217.76) = +217
    assert yes_to_american(0.3) == 217


def test_yes_to_american_favorite():
    # 0.7 raw → -233. With 7% taker fee:
    #   cost   = 0.7 + 0.07 * 0.7 * 0.3 = 0.7147
    #   profit = 0.2853
    #   American = floor(-0.7147 / 0.2853 * 100) = floor(-250.51) = -251
    assert yes_to_american(0.7) == -251


def test_yes_to_american_even_money():
    # 0.5 is NOT even money once the fee is in: the bettor pays 51.75¢
    # to win 48.25¢, which is -108 American.
    assert yes_to_american(0.5) == -108


def test_yes_to_american_edge_cases():
    assert yes_to_american(0.0) is None
    assert yes_to_american(1.0) is None
    assert yes_to_american(-0.5) is None


# ─── Quality gates ───────────────────────────────────────────────────


def test_market_quality_gate_h2h():
    good = {"status": "active", "yes_ask_dollars": "0.45", "no_ask_dollars": "0.60"}
    assert _market_passes_quality(good) is True

    inactive = dict(good, status="closed")
    assert _market_passes_quality(inactive) is False

    overround = dict(good, yes_ask_dollars="0.70", no_ask_dollars="0.60")  # 1.30
    assert _market_passes_quality(overround) is False

    missing_no = {"status": "active", "yes_ask_dollars": "0.45", "no_ask_dollars": None}
    assert _market_passes_quality(missing_no) is False


def test_alt_market_quality_gate_drops_thin_alts():
    # The Phase 1 gate would pass this (sum=1.01, both prices present, active),
    # but alt-line gate drops it (yes_ask < 0.02 = no real YES offer).
    thin = {"status": "active", "yes_ask_dollars": "0.01", "no_ask_dollars": "1.00"}
    assert _market_passes_quality(thin) is True   # phase 1 gate would pass
    assert _alt_market_passes_quality(thin) is False

    # Wide bid-ask: sum below 0.80 — alt gate drops
    wide = {"status": "active", "yes_ask_dollars": "0.30", "no_ask_dollars": "0.40"}
    assert _alt_market_passes_quality(wide) is False

    # Healthy alt
    good = {"status": "active", "yes_ask_dollars": "0.40", "no_ask_dollars": "0.65"}
    assert _alt_market_passes_quality(good) is True


# ─── End-to-end normalize_markets dispatcher ────────────────────────


def _mkt(**kwargs):
    """Build a Kalshi market dict with sensible defaults."""
    base = {
        "status": "active",
        "yes_ask_dollars": "0.45",
        "no_ask_dollars": "0.60",
        "floor_strike": 8.5,
        "strike_type": "greater",
    }
    base.update(kwargs)
    return base


def test_normalize_totals_emits_over_under_pair():
    markets = [
        _mkt(
            ticker="KXMLBTOTAL-26MAY181940MILCHC-9",
            event_ticker="KXMLBTOTAL-26MAY181940MILCHC",
            yes_ask_dollars="0.45",
            no_ask_dollars="0.60",
            floor_strike=8.5,
        ),
    ]
    rows = normalize_markets(markets, "KXMLBTOTAL", NOW, _stub_match)
    assert len(rows) == 2
    over = next(r for r in rows if r["outcome_name"] == "Over")
    under = next(r for r in rows if r["outcome_name"] == "Under")
    assert over["outcome_point"] == 8.5
    assert under["outcome_point"] == 8.5
    assert over["market_key"] == "alternate_totals"
    assert under["market_key"] == "alternate_totals"
    assert over["price_american"] == 113   # yes 0.45 fee-adjusted → +113
    assert under["price_american"] == -161 # no  0.60 fee-adjusted → -161


def test_normalize_spreads_signs_outcome_point_correctly():
    markets = [
        _mkt(
            ticker="KXMLBSPREAD-26MAY181940MILCHC-MIL4",
            event_ticker="KXMLBSPREAD-26MAY181940MILCHC",
            floor_strike=3.5,
        ),
    ]
    rows = normalize_markets(markets, "KXMLBSPREAD", NOW, _stub_match)
    assert len(rows) == 2
    yes_row = next(r for r in rows if r["outcome_name"] == "Milwaukee Brewers")
    no_row = next(r for r in rows if r["outcome_name"] == "Chicago Cubs")
    assert yes_row["outcome_point"] == -3.5  # favored: laying the runs
    assert no_row["outcome_point"] == 3.5    # underdog: receiving the runs
    assert yes_row["market_key"] == "alternate_spreads"


def test_normalize_team_totals_emits_named_over_under():
    markets = [
        _mkt(
            ticker="KXMLBTEAMTOTAL-26MAY181940MILCHC-MIL8",
            event_ticker="KXMLBTEAMTOTAL-26MAY181940MILCHC",
            floor_strike=7.5,
        ),
    ]
    rows = normalize_markets(markets, "KXMLBTEAMTOTAL", NOW, _stub_match)
    assert len(rows) == 2
    names = {r["outcome_name"] for r in rows}
    assert names == {"Milwaukee Brewers Over", "Milwaukee Brewers Under"}
    for r in rows:
        assert r["outcome_point"] == 7.5
        assert r["market_key"] == "alternate_team_totals"


def test_normalize_rfi_emits_yes_no():
    markets = [
        _mkt(
            ticker="KXMLBRFI-26MAY202138ATHLAA",
            event_ticker="KXMLBRFI-26MAY202138ATHLAA",
            yes_ask_dollars="0.54",
            no_ask_dollars="0.55",
            floor_strike=1,
        ),
    ]
    rows = normalize_markets(markets, "KXMLBRFI", NOW, _stub_match)
    assert len(rows) == 2
    names = {r["outcome_name"] for r in rows}
    assert names == {"Yes", "No"}
    for r in rows:
        assert r["outcome_point"] is None
        assert r["market_key"] == "nrfi"


def test_normalize_f5_winner_3way_emits_one_yes_row_per_market():
    # 3 markets per event for F5: TIE, MIL, CHC.
    base_event = "KXMLBF5-26MAY181940MILCHC"
    markets = [
        _mkt(
            ticker=f"{base_event}-TIE", event_ticker=base_event,
            yes_ask_dollars="0.13",
            no_ask_dollars="0.89",
            floor_strike=None,
            yes_sub_title="Tie",
        ),
        _mkt(
            ticker=f"{base_event}-MIL", event_ticker=base_event,
            yes_ask_dollars="0.40",
            no_ask_dollars="0.65",
            floor_strike=None,
            yes_sub_title="Milwaukee",
        ),
        _mkt(
            ticker=f"{base_event}-CHC", event_ticker=base_event,
            yes_ask_dollars="0.45",
            no_ask_dollars="0.60",
            floor_strike=None,
            yes_sub_title="Chicago C",
        ),
    ]
    rows = normalize_markets(markets, "KXMLBF5", NOW, _stub_match)
    assert len(rows) == 3
    names = {r["outcome_name"] for r in rows}
    assert names == {"Draw", "Milwaukee Brewers", "Chicago Cubs"}
    for r in rows:
        assert r["market_key"] == "h2h_3_way_1st_5_innings"
        assert r["outcome_point"] is None


def test_normalize_alt_quality_drops_thin_market():
    # Thin alt: yes=0.01 / no=1.00 — alt gate should drop it
    markets = [
        _mkt(
            ticker="KXMLBSPREAD-26MAY181940MILCHC-MIL9",
            event_ticker="KXMLBSPREAD-26MAY181940MILCHC",
            yes_ask_dollars="0.01",
            no_ask_dollars="1.00",
            floor_strike=8.5,
        ),
    ]
    rows = normalize_markets(markets, "KXMLBSPREAD", NOW, _stub_match)
    assert rows == []


def test_normalize_h2h_period_skips_tie_market():
    # NBA 1H winner emits 3 markets per event (Tie + 2 team-sided).
    # We only keep the 2 team-sided.
    base_event = "KXNBA1HWINNER-26MAY19CLENYK"
    markets = [
        _mkt(
            ticker=f"{base_event}-TIE", event_ticker=base_event,
            yes_ask_dollars="0.05", no_ask_dollars="0.96",
            yes_sub_title="Tie",
        ),
        _mkt(
            ticker=f"{base_event}-CLE", event_ticker=base_event,
            yes_ask_dollars="0.40", no_ask_dollars="0.65",
            yes_sub_title="Cleveland",
        ),
        _mkt(
            ticker=f"{base_event}-NYK", event_ticker=base_event,
            yes_ask_dollars="0.50", no_ask_dollars="0.55",
            yes_sub_title="New York",
        ),
    ]
    rows = normalize_markets(markets, "KXNBA1HWINNER", NOW, _stub_match)
    # 2 team-sided markets × 1 row each (h2h-style, one per market) = 2 rows
    assert len(rows) == 2
    names = {r["outcome_name"] for r in rows}
    assert names == {"Cleveland Cavaliers", "New York Knicks"}
    for r in rows:
        assert r["market_key"] == "h2h_h1"


# ──────────────────────── KalshiClient.get_orderbook ──────────────────


@pytest.mark.asyncio
async def test_get_orderbook_calls_signed_get_with_path():
    from unittest.mock import AsyncMock
    from server.odds.books.kalshi.client import KalshiClient
    client = KalshiClient(api_key="test", private_key_path=None)
    client._signed_get = AsyncMock(return_value={"orderbook": {"yes": [], "no": []}})
    result = await client.get_orderbook("KXMARKET-TICKER")
    client._signed_get.assert_called_once_with("/markets/KXMARKET-TICKER/orderbook")
    assert "orderbook" in result


# ─────────────────── registered_tickers() accessor ────────────────────


def test_ingestor_registered_tickers_returns_known_tickers(tmp_path):
    from datetime import datetime, timezone
    from server.odds.cache import OddsCache
    from server.odds.books.kalshi.ws_ingest import KalshiTickerIngestor
    cache = OddsCache(tmp_path / "test.db")
    cache.init()
    ing = KalshiTickerIngestor(cache=cache)
    now = datetime.now(timezone.utc)
    ing.register_rows([{
        "_market_ticker": "KX-A", "_ws_side": "yes",
        "event_id": "e1", "sport_key": "nba", "home_team": "BOS",
        "away_team": "MIA", "commence_time": now,
        "bookmaker_key": "kalshi",
        "market_key": "h2h", "outcome_name": "BOS",
        "outcome_point": None, "price_american": -145, "fetched_at": now,
    }, {
        "_market_ticker": "KX-B", "_ws_side": "yes",
        "event_id": "e2", "sport_key": "nba", "home_team": "OKC",
        "away_team": "MIN", "commence_time": now,
        "bookmaker_key": "kalshi",
        "market_key": "h2h", "outcome_name": "OKC",
        "outcome_point": None, "price_american": +110, "fetched_at": now,
    }])
    assert set(ing.registered_tickers()) == {"KX-A", "KX-B"}
