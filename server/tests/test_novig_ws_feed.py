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
    s._pending[7] = (["e9"], 0.0)
    s._handle({"code": "RATE_LIMIT_EXCEEDED", "message": "slow down", "nonce": 7})
    assert "e9" not in s._subscribed
    assert s._pause_until > 0
    assert s.rate_limited == 1


def test_unanswered_subscribe_is_retried_after_timeout():
    """An error reply that can't be matched to its request (or no reply at
    all) must not leave events marked subscribed with no data forever."""
    import server.odds.books.novig.ws_feed as wf
    s, _, _ = _stream()                       # e1 subscribed
    s._subscribed.update({"e8", "e9"})
    s._pending[3] = (["e1", "e8"], 100.0)
    s._pending[4] = (["e9"], 100.0 + wf.PENDING_TIMEOUT_S)
    s._handle({"code": "RATE_LIMIT_EXCEEDED", "message": "slow down"})   # no nonce
    s._handle(_snapshot())                    # e1 did deliver
    s._expire_pending(100.0 + wf.PENDING_TIMEOUT_S + 1)
    assert "e8" not in s._subscribed          # retried
    assert "e1" in s._subscribed              # had its snapshot
    assert "e9" in s._subscribed and 4 in s._pending   # not timed out yet
    assert s.retried == 1


def test_subscribes_are_batched_by_market_count_and_paced(monkeypatch):
    import server.odds.books.novig.ws_feed as wf
    monkeypatch.setattr(wf, "SUB_BATCH_MARKETS", 100)
    monkeypatch.setattr(wf, "STREAM_REFILL_PER_S", 1e6)   # no real waiting
    sent, sleeps = [], []
    s = NovigBboStream(signer=None, desired=lambda: [("a", 60), ("b", 70), ("c", 500), ("d", 5)],
                       on_change=lambda m: None, on_lost=lambda m: None)

    async def fake_send(method, payload):
        sent.append((method, sorted(payload["events"])))
        return len(sent)

    real_sleep = asyncio.sleep

    async def fake_sleep(t):
        sleeps.append(t)
        await real_sleep(0)

    monkeypatch.setattr(s, "_send", fake_send)
    monkeypatch.setattr(wf.asyncio, "sleep", fake_sleep)
    asyncio.run(s._subscribe_paced(s._want_events()))
    assert sent == [("subscribe", ["a", "b"]), ("subscribe", ["c"]), ("subscribe", ["d"])]
    assert sleeps == [130 / 1e6, 500 / 1e6, 5 / 1e6]
    assert s._subscribed == {"a", "b", "c", "d"} and set(s._pending) == {1, 2, 3}


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
