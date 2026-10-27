"""Kalshi depth + NO-side pricing from top-of-book quotes (REST markets and
WS ticker messages), and the WS client's per-ticker subscription sync."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.odds.books.kalshi import ws_client as wsc
from server.odds.books.kalshi.normalizer import normalize_markets, yes_to_american
from server.odds.books.kalshi.quote_depth import ask_dollars, max_stake_from_quote
from server.odds.books.kalshi.ws_ingest import KalshiTickerIngestor
from server.odds.cache import OddsCache

from .test_kalshi_normalizer import NOW, _mkt, _stub_match


QUOTE = {"yes_ask_dollars": "0.4200", "yes_ask_size_fp": "254.62",
         "yes_bid_dollars": "0.3800", "yes_bid_size_fp": "261.00"}


def test_yes_depth_is_ask_times_ask_size():
    assert ask_dollars(QUOTE, side="yes") == 0.42
    assert max_stake_from_quote(QUOTE, side="yes") == round(0.42 * 254.62, 2)


def test_no_is_bought_against_the_yes_bid():
    assert ask_dollars(QUOTE, side="no") == 0.62
    assert max_stake_from_quote(QUOTE, side="no") == round(0.62 * 261.0, 2)


@pytest.mark.parametrize("quote,side", [
    ({"yes_ask_dollars": "0.42"}, "yes"),                               # no size
    ({"yes_ask_dollars": "0.42", "yes_ask_size_fp": "0"}, "yes"),       # empty
    ({"yes_bid_dollars": "0.0000", "yes_bid_size_fp": "10"}, "no"),     # no bid -> no NO ask
    ({"yes_ask_dollars": "1.0000", "yes_ask_size_fp": "10"}, "yes"),    # no real ask
    ({"yes_ask_dollars": "x", "yes_ask_size_fp": "10"}, "yes"),         # malformed
])
def test_missing_or_degenerate_quote_has_no_depth(quote, side):
    assert max_stake_from_quote(quote, side=side) is None


def test_normalizer_attaches_depth_to_both_sides():
    m = _mkt(ticker="KXMLBTOTAL-26MAY181940MILCHC-9",
             event_ticker="KXMLBTOTAL-26MAY181940MILCHC",
             yes_ask_dollars="0.45", no_ask_dollars="0.60", floor_strike=8.5,
             yes_ask_size_fp="100.00", yes_bid_dollars="0.40", yes_bid_size_fp="50.00")
    rows = normalize_markets([m], "KXMLBTOTAL", NOW, _stub_match)
    by = {r["outcome_name"]: r for r in rows}
    assert by["Over"]["max_stake_dollars"] == 45.0     # 0.45 x 100
    assert by["Under"]["max_stake_dollars"] == 30.0    # 0.60 x 50


def test_normalizer_without_sizes_leaves_depth_unset():
    m = _mkt(ticker="KXMLBTOTAL-26MAY181940MILCHC-9",
             event_ticker="KXMLBTOTAL-26MAY181940MILCHC")
    rows = normalize_markets([m], "KXMLBTOTAL", NOW, _stub_match)
    assert rows and all("max_stake_dollars" not in r for r in rows)


def _template(side, outcome, stake=None):
    return {
        "_market_ticker": "T", "_ws_side": side,
        "event_id": "ev", "sport_key": "baseball_mlb",
        "home_team": "A", "away_team": "B",
        "commence_time": datetime.now(timezone.utc) + timedelta(hours=3),
        "bookmaker_key": "kalshi", "market_key": "alternate_totals",
        "outcome_name": outcome, "outcome_point": 8.5,
        "price_american": 100, "fetched_at": datetime.now(timezone.utc),
        "max_stake_dollars": stake,
    }


class _Cache:
    def __init__(self):
        self.rows = []

    def upsert_nowait(self, rows, label=None):
        self.rows.extend(rows)


def test_ws_tick_prices_both_sides_with_depth():
    ing = KalshiTickerIngestor(_Cache())
    ing.register_rows([_template("yes", "Over"), _template("no", "Under")])
    n = ing.process_ticker({"msg": {"market_ticker": "T", **QUOTE}})
    assert n == 2
    by = {r["outcome_name"]: r for r in ing.cache.rows}
    assert by["Over"]["price_american"] == yes_to_american(0.42)
    assert by["Under"]["price_american"] == yes_to_american(0.62)
    assert by["Over"]["max_stake_dollars"] == round(0.42 * 254.62, 2)
    assert by["Under"]["max_stake_dollars"] == round(0.62 * 261.0, 2)


def test_ws_tick_without_bid_leaves_no_side_alone():
    ing = KalshiTickerIngestor(_Cache())
    ing.register_rows([_template("yes", "Over"), _template("no", "Under", stake=12.0)])
    n = ing.process_ticker({"msg": {"market_ticker": "T", "yes_ask_dollars": "0.55"}})
    assert n == 1
    (row,) = ing.cache.rows
    assert row["outcome_name"] == "Over"
    assert row["max_stake_dollars"] is None         # template had none, tick had no size


def test_ws_tick_without_size_keeps_last_known_depth():
    ing = KalshiTickerIngestor(_Cache())
    ing.register_rows([_template("yes", "Over", stake=33.0)])
    ing.process_ticker({"msg": {"market_ticker": "T", "yes_ask_dollars": "0.55"}})
    assert ing.cache.rows[0]["max_stake_dollars"] == 33.0


# ───────────────────────── subscription sync ─────────────────────────


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def test_sync_adds_and_deletes_in_chunks(monkeypatch):
    monkeypatch.setattr(wsc, "_SUB_CHUNK", 2)
    want = {"A", "B", "C", "D", "E"}
    client = wsc.KalshiWSClient("k", Path("/nonexistent.pem"), tickers=lambda: want)
    client._subscribed = {"A", "Z"}
    ws = _FakeWS()

    async def run():
        task = asyncio.create_task(client._sync_subscription(ws, sid=7))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(run())
    adds = [m for m in ws.sent if m["params"]["action"] == "add_markets"]
    dels = [m for m in ws.sent if m["params"]["action"] == "delete_markets"]
    assert [m["params"]["market_tickers"] for m in adds] == [["B", "C"], ["D", "E"]]
    assert [m["params"]["market_tickers"] for m in dels] == [["Z"]]
    assert all(m["cmd"] == "update_subscription" and m["params"]["sids"] == [7] for m in ws.sent)
    assert client._subscribed == want
    assert len({m["id"] for m in ws.sent}) == len(ws.sent)


def test_sync_never_empties_the_subscription():
    client = wsc.KalshiWSClient("k", Path("/nonexistent.pem"), tickers=lambda: [])
    client._subscribed = {"A"}
    ws = _FakeWS()

    async def run():
        task = asyncio.create_task(client._sync_subscription(ws, sid=1))
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(run())
    assert ws.sent == [] and client._subscribed == {"A"}
