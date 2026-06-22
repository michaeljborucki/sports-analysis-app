import asyncio
import pytest
from server.odds import events


@pytest.mark.asyncio
async def test_publish_broadcasts_typed_event_to_subscriber():
    events._reset_for_tests()
    q = events.subscribe()
    try:
        events.publish({"type": "sidecar_placement", "job_id": "j1",
                        "result": "placed", "stake": 100})
        # Should land in the queue effectively immediately
        msg = await asyncio.wait_for(q.get(), timeout=0.5)
        assert msg["type"] == "sidecar_placement"
        assert msg["job_id"] == "j1"
    finally:
        events.unsubscribe(q)


@pytest.mark.asyncio
async def test_publish_does_not_disturb_mark_dirty_coalescing():
    """publish() is a separate path; it shouldn't reset the mark_dirty
    debounce window."""
    events._reset_for_tests()
    q = events.subscribe()
    try:
        events.mark_dirty()
        events.publish({"type": "sidecar_placement", "job_id": "j2"})
        # mark_dirty is still pending until the next flush tick. publish
        # delivered immediately. So the queue has at least the publish.
        first = await asyncio.wait_for(q.get(), timeout=0.5)
        assert first["type"] == "sidecar_placement"
    finally:
        events.unsubscribe(q)


@pytest.mark.asyncio
async def test_publish_requires_type_field():
    events._reset_for_tests()
    with pytest.raises(ValueError):
        events.publish({"job_id": "j3"})


def test_sidecar_sse_helpers_emit_typed_events():
    """Each helper sets the correct type field."""
    from server.sidecar import sse

    events._reset_for_tests()
    captured: list[dict] = []

    def fake_publish(event):
        captured.append(event)

    original = events.publish
    events.publish = fake_publish  # type: ignore[assignment]
    try:
        sse.emit_placement({"job_id": "j1", "stake": 100})
        sse.emit_topup_required({"account": "VR11606"})
        sse.emit_signal_skipped({"ev_row_id": "rid"})
        sse.emit_partial_fill({"job_id": "j2", "unfilled": 50})
    finally:
        events.publish = original  # type: ignore[assignment]

    assert [e["type"] for e in captured] == [
        "sidecar_placement",
        "sidecar_topup_required",
        "sidecar_signal_skipped",
        "sidecar_partial_fill",
    ]
    assert captured[0]["stake"] == 100
    assert captured[1]["account"] == "VR11606"
    assert captured[2]["ev_row_id"] == "rid"
    assert captured[3]["unfilled"] == 50
