from server.sidecar.ev_row_id import build_ev_row_id, parse_ev_row_id


def test_round_trip_with_point():
    rid = build_ev_row_id(
        event_id="evt-123", market_kind="totals", point=2.5,
        outcome_name="Over", book="coral33",
    )
    assert rid == "evt-123|totals|2.5|Over|coral33"
    parsed = parse_ev_row_id(rid)
    assert parsed["event_id"] == "evt-123"
    assert parsed["market_kind"] == "totals"
    assert parsed["point"] == 2.5
    assert parsed["outcome_name"] == "Over"
    assert parsed["book"] == "coral33"


def test_round_trip_with_none_point():
    rid = build_ev_row_id(
        event_id="evt-X", market_kind="h2h", point=None,
        outcome_name="New Zealand", book="coral33",
    )
    assert rid == "evt-X|h2h||New Zealand|coral33"
    parsed = parse_ev_row_id(rid)
    assert parsed["point"] is None


def test_outcome_name_with_pipe_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        build_ev_row_id(
            event_id="e", market_kind="h2h", point=None,
            outcome_name="Bad|name", book="coral33",
        )


def test_malformed_row_id_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        parse_ev_row_id("not-enough-parts")
