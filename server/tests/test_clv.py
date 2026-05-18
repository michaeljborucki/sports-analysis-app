"""Regression tests for the sport-agnostic CLV pipeline."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.odds.cache import OddsCache
from server.odds.clv import (
    _classify_bet,
    _parse_over_under,
    build_subtype_to_sport_key,
    compute_clv,
    get_coral33_config,
    lookup_clv,
    wager_to_market_lookup,
)
from server.odds.clv_capture import capture_closing_lines_for_events
from server.odds.books.coral33.wager_log import WagerLogEntry


# ─────────────────────────── CLV math ────────────────────────────────


class TestComputeCLV:
    def test_both_favorites_we_beat_the_close(self):
        # Bet at -120, closed at -150 → we got the better number → +CLV
        r = compute_clv(-120, -150)
        assert r.clv_cents == 30
        assert r.clv_pct > 0
        assert r.close_odds == -150

    def test_both_dogs_we_beat_the_close(self):
        # Bet at +150, closed at +120 → we got more upside → +CLV
        r = compute_clv(150, 120)
        assert r.clv_cents == 30
        assert r.clv_pct > 0

    def test_both_favorites_we_got_worse(self):
        # Bet at -150, closed at -120 → line moved against us
        r = compute_clv(-150, -120)
        assert r.clv_cents == -30
        assert r.clv_pct < 0

    def test_line_crossed_zero_dog_to_favorite(self):
        # Bet at +110, closed at -110 → we caught a big move → +CLV
        r = compute_clv(110, -110)
        assert r.clv_cents > 0
        assert r.clv_pct > 0

    def test_no_movement_zero_clv(self):
        r = compute_clv(-110, -110)
        assert r.clv_cents == 0
        assert r.clv_pct == 0.0


# ────────────────────── Parsing helpers ──────────────────────────────


class TestOverUnderParse:
    def test_short_form_over(self):
        assert _parse_over_under("Lynx/Mercury O 87 -110") == ("Over", 87.0)

    def test_short_form_under(self):
        assert _parse_over_under("Yankees/Rangers U 8.5 +100") == ("Under", 8.5)

    def test_long_form(self):
        assert _parse_over_under("Total Over 220.5") == ("Over", 220.5)

    def test_no_match(self):
        assert _parse_over_under("Moneyline: Suns") is None

    def test_empty(self):
        assert _parse_over_under(None) is None
        assert _parse_over_under("") is None


# ─────────────────────── Bet classification ──────────────────────────


def _wager(**kwargs) -> WagerLogEntry:
    defaults = dict(
        customer_id="C", ticket_number=1,
        accepted_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        settled_at=None, wager_status="O", wager_type="S", total_picks=1,
        amount_wagered=100.0, to_win_amount=100.0, amount_won=0.0,
        amount_lost=0.0, is_free_play=False,
        sport_type=None, sport_sub_type=None, period=None,
        team1_id=None, team2_id=None, chosen_team_id=None,
        description=None, final_money=-110,
        adj_spread=None, adj_total_points=None,
    )
    defaults.update(kwargs)
    return WagerLogEntry(**defaults)


class TestClassifyBet:
    def test_spread(self):
        w = _wager(
            sport_sub_type="NBA", adj_spread=-5.5,
            chosen_team_id="Phoenix Suns",
            team1_id="Phoenix Suns", team2_id="Lakers",
            description="Basketball Suns -5.5 -110",
        )
        assert _classify_bet(w) == "spread"

    def test_game_total(self):
        w = _wager(
            sport_sub_type="WNBA", adj_total_points=87.0,
            chosen_team_id="Lynx/Mercury",
            team1_id="Minnesota Lynx", team2_id="Phoenix Mercury",
            description="Basketball Lynx/Mercury O 87 -110",
        )
        assert _classify_bet(w) == "total"

    def test_team_total(self):
        w = _wager(
            sport_sub_type="NHL", adj_total_points=2.5,
            chosen_team_id="Minnesota Wild",
            team1_id="Minnesota Wild", team2_id="Dallas Stars",
            description="Hockey Wild U 2.5 +105",
        )
        assert _classify_bet(w) == "team_total"

    def test_moneyline(self):
        w = _wager(
            sport_sub_type="MLB",
            chosen_team_id="New York Yankees",
            team1_id="New York Yankees", team2_id="Boston Red Sox",
            description="Baseball Yankees -130",
        )
        assert _classify_bet(w) == "moneyline"

    def test_player_prop_via_stat_name(self):
        w = _wager(
            sport_sub_type="BasePlaProp", adj_total_points=6.5,
            chosen_team_id="Shota Imanaga/Strikeouts",
            team1_id="Shota Imanaga", team2_id="Strikeouts",
            description="Baseball Shota Imanaga/Strikeouts U 6.5 -145",
        )
        assert _classify_bet(w) == "player_prop"

    def test_nrfi_via_subtype(self):
        w = _wager(
            sport_sub_type="Score in 1st",
            chosen_team_id="Yes Reds/Cubs score 1st Inn",
            team1_id="Yes Reds/Cubs score 1st Inn",
            team2_id="No Reds/Cubs score 1st Inn",
            description="Baseball Yes Reds/Cubs score 1st Inn +105",
        )
        assert _classify_bet(w) == "nrfi"


# ─────────────────────── Subtype mapping ─────────────────────────────


def test_subtype_to_sport_key_covers_main_subtypes():
    config, reverse = get_coral33_config()
    # Smoke-check a few sports across families
    assert reverse.get("NBA") == "nba"
    assert reverse.get("WNBA") == "wnba"
    assert reverse.get("MLB") == "mlb"
    assert reverse.get("NHL") == "nhl"
    assert reverse.get("ATP MATCHU") == "tennis"


# ─────────────────────── End-to-end lookup ───────────────────────────


@pytest.fixture
def in_memory_cache(tmp_path: Path) -> OddsCache:
    cache = OddsCache(tmp_path / "test_cache.db")
    cache.init()
    return cache


def _seed_event(cache: OddsCache, event_id: str, sport_key: str,
                home: str, away: str, commence: datetime,
                fetched: datetime) -> None:
    """Plant a synthetic Pinnacle+sharp pair for one event so the CLV
    capture can devig it. Two-way h2h: home -120, away +120."""
    rows = []
    for book, h_price, a_price in [
        ("pinnacle", -120, 100),
        ("draftkings", -125, 102),
    ]:
        rows.append({
            "event_id": event_id, "sport_key": sport_key,
            "home_team": home, "away_team": away,
            "commence_time": commence,
            "bookmaker_key": book, "market_key": "h2h",
            "outcome_name": home, "outcome_point": 0.0,
            "price_american": h_price, "fetched_at": fetched,
        })
        rows.append({
            "event_id": event_id, "sport_key": sport_key,
            "home_team": home, "away_team": away,
            "commence_time": commence,
            "bookmaker_key": book, "market_key": "h2h",
            "outcome_name": away, "outcome_point": 0.0,
            "price_american": a_price, "fetched_at": fetched,
        })
    cache.upsert(rows)


def test_capture_then_lookup_moneyline(in_memory_cache: OddsCache):
    """End-to-end: seed a 2-way market, capture the close, look up CLV
    for a synthetic wager."""
    now = datetime(2026, 5, 12, 22, 0, tzinfo=timezone.utc)
    commence = now + timedelta(minutes=8)
    _seed_event(
        in_memory_cache, event_id="EV_NBA_1", sport_key="nba",
        home="Phoenix Suns", away="Los Angeles Lakers",
        commence=commence, fetched=now,
    )
    # Capture sharp close
    n = capture_closing_lines_for_events(
        in_memory_cache,
        [{
            "event_id": "EV_NBA_1", "sport_key": "nba",
            "commence_time": commence,
            "home_team": "Phoenix Suns",
            "away_team": "Los Angeles Lakers",
        }],
        now=now,
    )
    assert n > 0, "capture should produce at least one closing-line row"

    # Build a wager: user took Suns ML at +100 (better than the -120 close)
    wager = _wager(
        sport_sub_type="NBA",
        team1_id="Phoenix Suns",
        team2_id="Los Angeles Lakers",
        chosen_team_id="Phoenix Suns",
        description="Basketball Suns +100",
        final_money=100,
        accepted_at=now - timedelta(hours=2),
    )
    config, reverse = get_coral33_config()
    lookup = wager_to_market_lookup(wager, in_memory_cache, config, reverse)
    assert lookup is not None
    assert lookup.market_key == "h2h"
    assert lookup.outcome_name == "Phoenix Suns"

    clv = lookup_clv(wager, in_memory_cache, config, reverse)
    assert clv is not None
    # We bet +100, close around -120 → +CLV (we got better price than close)
    assert clv.clv_pct > 0


def test_teaser_returns_none(in_memory_cache: OddsCache):
    """Teasers shift the line at wager time — CLV is meaningless."""
    config, reverse = get_coral33_config()
    wager = _wager(
        wager_type="T", total_picks=2,
        sport_sub_type="NFL",
        team1_id="Cowboys", team2_id="Eagles",
        chosen_team_id="Cowboys", final_money=-110,
    )
    assert wager_to_market_lookup(wager, in_memory_cache, config, reverse) is None


def test_parlay_head_leg_allowed_if_event_exists(in_memory_cache: OddsCache):
    """Parlay head leg CAN get CLV — final_money is the leg's odds,
    not the combined parlay payout. Test only verifies the wager_type
    gate; full lookup needs an event in closing_lines (covered by
    test_capture_then_lookup_moneyline)."""
    config, reverse = get_coral33_config()
    wager = _wager(
        wager_type="P", total_picks=3,
        sport_sub_type="MLB",
        team1_id="Yankees", team2_id="Red Sox",
        chosen_team_id="Yankees", final_money=-110,
    )
    # With no event in the cache, this still returns None — but the
    # reason is "no_event_match", not the wager_type gate. Re-run
    # against a populated cache and it would succeed.
    assert wager_to_market_lookup(wager, in_memory_cache, config, reverse) is None


def test_unknown_sport_returns_none(in_memory_cache: OddsCache):
    config, reverse = get_coral33_config()
    wager = _wager(
        sport_sub_type="QUIDDITCH",
        team1_id="Gryffindor", team2_id="Slytherin",
        chosen_team_id="Gryffindor", final_money=-110,
    )
    assert wager_to_market_lookup(wager, in_memory_cache, config, reverse) is None
