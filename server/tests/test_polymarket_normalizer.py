"""Tests for the Polymarket soccer 3-way normalizer (M6 partial emission)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


_NOW = datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc)
# Game commences several hours in the future so _resolve_event_canon's
# live/past check (real_commence <= now → return None) passes.
_KICKOFF = _NOW + timedelta(hours=8)


def _mock_match_event(sport_key, canon_a, canon_b, anchor):
    """Stub that always resolves to a Palace v Arsenal game on 2026-06-21."""
    return {
        "event_id": "ev_palace_v_arsenal",
        "home_team": "Crystal Palace",
        "away_team": "Arsenal",
        "commence_time": _KICKOFF,
    }


def _market(best_ask: float, best_bid: float, token_yes="tok_y", token_no="tok_n") -> dict:
    return {
        "outcomes": json.dumps(["Yes", "No"]),
        "clobTokenIds": json.dumps([token_yes, token_no]),
        "bestAsk": str(best_ask),
        "bestBid": str(best_bid),
    }


def _slug(details: str) -> dict:
    return {
        "kind": "soccer_3way",
        "team_a_code": "cry",
        "team_b_code": "ars",
        "date": "2026-06-21",
        "details": details,
    }


def test_soccer_3way_emits_partial_when_draw_missing():
    """Only home + away present (no draw yet) → 2 rows emitted."""
    from server.odds.books.polymarket.normalizer import _normalize_soccer_3way_event
    parsed_markets = [
        (_market(best_ask=0.45, best_bid=0.43, token_yes="tok_cry_y"), _slug("cry")),
        (_market(best_ask=0.40, best_bid=0.38, token_yes="tok_ars_y"), _slug("ars")),
        # "draw" intentionally missing
    ]
    rows = _normalize_soccer_3way_event(
        parsed_markets, sport_key="soccer", fetched_at=_NOW,
        match_event=_mock_match_event,
    )
    outcome_names = {r["outcome_name"] for r in rows}
    assert "Crystal Palace" in outcome_names
    assert "Arsenal" in outcome_names
    assert "Draw" not in outcome_names
    assert len(rows) == 2


def test_soccer_3way_full_set_emits_3():
    """3-of-3 happy path unchanged."""
    from server.odds.books.polymarket.normalizer import _normalize_soccer_3way_event
    parsed_markets = [
        (_market(best_ask=0.40, best_bid=0.38), _slug("cry")),
        (_market(best_ask=0.35, best_bid=0.33), _slug("ars")),
        (_market(best_ask=0.25, best_bid=0.23), _slug("draw")),
    ]
    rows = _normalize_soccer_3way_event(
        parsed_markets, sport_key="soccer", fetched_at=_NOW,
        match_event=_mock_match_event,
    )
    assert len(rows) == 3
    outcome_names = {r["outcome_name"] for r in rows}
    assert outcome_names == {"Crystal Palace", "Arsenal", "Draw"}


def test_soccer_3way_no_segments_returns_empty():
    """If parsed_markets is empty (or all segments unknown), return []."""
    from server.odds.books.polymarket.normalizer import _normalize_soccer_3way_event
    rows = _normalize_soccer_3way_event(
        [], sport_key="soccer", fetched_at=_NOW,
        match_event=_mock_match_event,
    )
    assert rows == []


def test_soccer_3way_overround_gate_only_applies_to_full_set():
    """Partials skip the 3-way overround sanity check (it requires all 3
    YES probs to sum sensibly). A 2-of-2 with high implied probs that
    would have failed the 3-way check still emits."""
    from server.odds.books.polymarket.normalizer import _normalize_soccer_3way_event
    # Two outcomes each at 0.55 implied → sum would be 1.10 which would
    # blow the 3-way overround gate, but the gate only fires on 3-of-3.
    parsed_markets = [
        (_market(best_ask=0.55, best_bid=0.53), _slug("cry")),
        (_market(best_ask=0.55, best_bid=0.53), _slug("ars")),
    ]
    rows = _normalize_soccer_3way_event(
        parsed_markets, sport_key="soccer", fetched_at=_NOW,
        match_event=_mock_match_event,
    )
    assert len(rows) == 2
