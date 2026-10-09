import asyncio

import pytest

from server.odds.books.novig.ws_feed import NovigBboStream, bbo_book


def _stream():
    changed, lost = [], []
    s = NovigBboStream(
        signer=None, desired=lambda: [],
        on_change=changed.append, on_lost=lambda m: lost.append(set(m)),
    )
    s.connected = True
    s._subscribed.add("e1")
    return s, changed, lost


def _snapshot(seq=5, status="OPEN"):
    return {"snapshot": {"m1": {
        "eventId": "e1",
        "bbo": {"seq": seq, "bbo": {
            "a": {"price": "0.40", "qty": 1000},
            "b": {"price": "0.55", "qty": 300},
        }},
        "lifecycle": {"seq": 1, "status": status},
    }}}


def test_snapshot_makes_market_live_and_parses_levels():
    s, changed, _ = _stream()
    s._handle(_snapshot())
    assert s.covers("m1")
    assert s.state["m1"] == {"a": (0.40, 1000), "b": (0.55, 300)}
    assert changed == ["m1"]
    assert bbo_book(s.state["m1"]) == {"orders": {
        "a": [{"price": 0.40, "qty": 1000}], "b": [{"price": 0.55, "qty": 300}],
    }}


def test_in_order_delta_updates_and_removes_levels():
    s, changed, _ = _stream()
    s._handle(_snapshot(seq=5))
    s._handle({"delta": {"m1": {"eventId": "e1", "bbo": {"seq": 6, "deltas": [
        {"outcomeId": "a", "bbo": {"price": "0.42", "qty": 50}},
        {"outcomeId": "b"},                      # last bid left the book
    ]}}}})
    assert s.state["m1"] == {"a": (0.42, 50)}
    assert changed == ["m1", "m1"]
    assert s.covers("m1")


def test_seq_gap_drops_market_back_to_poller():
    async def run():
        s, _, lost = _stream()
        s._handle(_snapshot(seq=5))
        s._handle({"delta": {"m1": {"eventId": "e1", "bbo": {"seq": 9, "deltas": [
            {"outcomeId": "a", "bbo": {"price": "0.42", "qty": 50}},
        ]}}}})
        assert not s.covers("m1")
        assert lost == [{"m1"}]
        assert s.gaps == 1
        await asyncio.sleep(0)               # let the resnapshot task run (no socket)
    asyncio.run(run())


def test_closed_market_clears_quotes():
    s, _, _ = _stream()
    s._handle(_snapshot())
    s._handle({"delta": {"m1": {"eventId": "e1", "lifecycle": {"seq": 2, "deltas": [
        {"kind": "CLOSE", "status": "CLOSED"},
    ]}}}})
    assert s.state["m1"] == {}


def test_disconnect_reports_every_live_market():
    s, _, lost = _stream()
    s._handle(_snapshot())
    s._drop_all()
    assert not s.covers("m1")
    assert lost == [{"m1"}]


def test_market_opened_after_event_subscribe_goes_live_from_seq_zero():
    s, changed, _ = _stream()
    s._handle({"delta": {"m2": {"eventId": "e1", "bbo": {"seq": 1, "deltas": [
        {"outcomeId": "x", "bbo": {"price": "0.30", "qty": 10}},
    ]}}}})
    assert s.covers("m2")
    assert s.state["m2"] == {"x": (0.30, 10)}
    assert changed == ["m2"]


def test_failed_subscribe_is_retried_and_rate_limit_pauses():
    s, _, _ = _stream()
    s._subscribed.add("e9")
    s._pending[7] = ["e9"]
    s._handle({"code": "RATE_LIMIT_EXCEEDED", "message": "slow down", "nonce": 7})
    assert "e9" not in s._subscribed
    assert s._pause_until > 0


def test_watch_cap_takes_soonest_events_that_fit(monkeypatch):
    import server.odds.books.novig.ws_feed as wf
    monkeypatch.setattr(wf, "MAX_MARKETS", 100)
    s = NovigBboStream(signer=None, desired=lambda: [("a", 60), ("b", 70), ("c", 30)],
                       on_change=lambda m: None, on_lost=lambda m: None)
    assert s._want_events() == ["a", "c"]


def test_refuses_non_read_methods():
    s, _, _ = _stream()
    for method in ("place", "cancel", "cancel_all"):
        with pytest.raises(RuntimeError, match="read-only"):
            asyncio.run(s._send(method, {}))


def test_new_market_after_subscribe_notifies_fetcher():
    new = []
    s = NovigBboStream(signer=None, desired=lambda: [], on_change=lambda m: None,
                       on_lost=lambda m: None, on_new_market=new.append)
    s.connected = True
    s._subscribed.add("e1")
    s._handle({"delta": {"m3": {"eventId": "e1", "lifecycle": {"seq": 1, "deltas": [
        {"kind": "OPEN", "status": "OPEN"}]}}}})
    assert new == ["m3"]
