"""Normalizer + registration tests for the new sports added 2026-05-01:
UFC (MMA), Boxing, Cricket.

Each sport's HAR-captured Get_LeagueLines2 response lives under
`server/tests/fixtures/coral33/probes/`. These tests assert:
  1. The sport is registered in the Sport registry with correct
     Odds API keys + market groups.
  2. The coral33.toml config contains the right (sport_type, subtypes)
     mapping.
  3. The markets.<sport>.toml config parses and exposes h2h.
  4. The normalizer emits expected h2h (and totals where applicable)
     rows when fed the captured probe response.
"""
from __future__ import annotations

import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.sports import SPORTS
from server.odds.books.coral33.mapping import load_coral33_config
from server.odds.books.coral33.normalizer import normalize_league_lines


PROBES = Path(__file__).parent / "fixtures" / "coral33" / "probes"
CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load_probe(name: str) -> dict:
    return json.loads((PROBES / f"{name}.json").read_text())


def _load_market_config(filename: str) -> dict:
    with (CONFIG_DIR / filename).open("rb") as f:
        return tomllib.load(f)


def _stub_matcher(sport, home, away, commence):
    """Always-match stub. Returns a dict matching what the real matcher
    produces — `event_id` plus canonical home/away. We pass coral33's names
    through unchanged here; team-aliasing is tested separately."""
    return {
        "event_id": f"EV:{sport}:{home}|{away}",
        "home_team": home,
        "away_team": away,
    }


# ─────────────────────────── Sport registry ───────────────────────────


def test_ufc_registered_with_mma_odds_api_key():
    sport = SPORTS["ufc"]
    assert sport.label == "UFC"
    assert sport.odds_api_sport_keys == ("mma_mixed_martial_arts",)
    market_keys = {g.main_key for g in sport.market_groups}
    assert "h2h" in market_keys
    assert "totals" in market_keys


def test_boxing_registered_with_boxing_odds_api_key():
    sport = SPORTS["boxing"]
    assert sport.label == "Boxing"
    assert sport.odds_api_sport_keys == ("boxing_boxing",)
    market_keys = {g.main_key for g in sport.market_groups}
    assert "h2h" in market_keys
    assert "totals" in market_keys


def test_cricket_registered_with_two_odds_api_keys():
    """Cricket bundles IPL + International T20 under one app sport_key,
    matching the asian_baseball pattern (NPB + KBO under one sport)."""
    sport = SPORTS["cricket"]
    assert sport.label == "Cricket"
    assert sport.odds_api_sport_keys == (
        "cricket_ipl", "cricket_international_t20",
    )
    market_keys = {g.main_key for g in sport.market_groups}
    assert market_keys == {"h2h"}, "cricket is h2h-only on Odds API"


# ─────────────────────────── coral33 config ───────────────────────────


def test_coral33_config_has_ufc_two_subtypes():
    cfg = load_coral33_config(CONFIG_DIR / "coral33.toml")
    ufc = cfg.sports["ufc"]
    assert ufc.sport_type == "MARTIAL ARTS"
    assert ufc.subtypes_main == ["MMA - UFC", "MMA - UFC2"]
    assert ufc.periods == ["Game"]


def test_coral33_config_has_boxing_five_card_subtypes():
    cfg = load_coral33_config(CONFIG_DIR / "coral33.toml")
    boxing = cfg.sports["boxing"]
    assert boxing.sport_type == "BOXING"
    # All 5 coral33 boxing card subtypes — they merge under a single
    # boxing_boxing Odds API key at match time.
    assert boxing.subtypes_main == [
        "MATCHUPS", "BOX MATCHU", "BOX FIGHTS", "BOXING OTHER", "BOXING",
    ]


def test_coral33_config_has_cricket_subtypes():
    cfg = load_coral33_config(CONFIG_DIR / "coral33.toml")
    cricket = cfg.sports["cricket"]
    assert cricket.sport_type == "CRICKET"
    # `ICCINTERCUP` is the literal coral33 subtype; despite the name, the
    # underlying league is the real IPL (mislabeled in their catalog).
    assert "ICCINTERCUP" in cricket.subtypes_main
    assert "TWENTY20INTE" in cricket.subtypes_main


# ─────────────────────────── markets.X.toml ───────────────────────────


def test_markets_ufc_config_h2h_and_totals_enabled():
    cfg = _load_market_config("markets.ufc.toml")
    assert cfg["main"]["enabled"] is True
    assert "h2h" in cfg["main"]["markets"]
    assert "totals" in cfg["main"]["markets"]
    # No alts / periods / props on Odds API for MMA.
    assert cfg["alternates"]["enabled"] is False
    assert cfg["periods"]["enabled"] is False
    assert cfg["player_props"]["enabled"] is False


def test_markets_boxing_config_h2h_and_totals_enabled():
    cfg = _load_market_config("markets.boxing.toml")
    assert cfg["main"]["enabled"] is True
    assert "h2h" in cfg["main"]["markets"]
    assert "totals" in cfg["main"]["markets"]


def test_markets_cricket_config_is_h2h_only():
    cfg = _load_market_config("markets.cricket.toml")
    assert cfg["main"]["enabled"] is True
    assert "h2h" in cfg["main"]["markets"]
    # Odds API does NOT expose cricket totals — explicitly absent.
    assert "totals" not in cfg["main"]["markets"]


# ─────────────────────────── Normalizer behavior ───────────────────────────


def test_normalize_ufc_main_card_emits_h2h_rows():
    """UFC main PPV (UFC 328) — h2h-only fights."""
    response = _load_probe("ufc")
    fetched = datetime(2026, 5, 1, 0, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        response, period="Game", sport_key="ufc",
        fetched_at=fetched, match_event=_stub_matcher,
    )
    market_keys = {r["market_key"] for r in rows}
    assert "h2h" in market_keys
    # Probe captured: Sean Strickland vs Khamzat Chimaev (one ML missing,
    # one side @ 340), Tatsuro Taira (-190) vs Joshua Van (150), etc.
    h2h_rows = [r for r in rows if r["market_key"] == "h2h"]
    fighters = {r["outcome_name"] for r in h2h_rows}
    assert "Tatsuro Taira" in fighters
    assert "Joshua Van" in fighters
    # Spread rows should be absent — UFC doesn't post spreads.
    assert not any(r["market_key"] == "spreads" for r in rows)


def test_normalize_ufc_fight_night_includes_rounds_totals():
    """UFC2 (Fight Night) — h2h + rounds totals (e.g., O/U 2.5 rounds)."""
    response = _load_probe("ufc2")
    fetched = datetime(2026, 5, 1, 0, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        response, period="Game", sport_key="ufc",
        fetched_at=fetched, match_event=_stub_matcher,
    )
    market_keys = {r["market_key"] for r in rows}
    assert "h2h" in market_keys
    # Probe shows Total 2.5 rounds present on multiple fights.
    assert "totals" in market_keys
    totals_rows = [r for r in rows if r["market_key"] == "totals"]
    points = {r["outcome_point"] for r in totals_rows}
    # At least one of these standard rounds-total lines should be present.
    assert points & {2.5, 1.5, 3.5}


def test_normalize_boxing_emits_h2h_for_all_card_subtypes():
    """All five boxing 'card' subtypes parse identically — h2h rows
    keyed by fighter name."""
    fetched = datetime(2026, 5, 1, 0, tzinfo=timezone.utc)
    # Pick a fighter known to have Status='O' on each card. Status='I' rows
    # are skipped as in-progress (correctly), so picking a circled fight
    # would falsely fail this test.
    cards = [
        ("boxing_main", "Jaime Munguia"),
        ("boxing_matchups", "Kazuto Ioka"),
        ("boxing_boxmatchu", "Raeese Aleem"),
        ("boxing_fights", "Daniel Dubois"),
        ("boxing_other", "Misael Rodriguez"),
    ]
    for fixture_name, expected_fighter in cards:
        response = _load_probe(fixture_name)
        rows = normalize_league_lines(
            response, period="Game", sport_key="boxing",
            fetched_at=fetched, match_event=_stub_matcher,
        )
        h2h_rows = [r for r in rows if r["market_key"] == "h2h"]
        fighters = {r["outcome_name"] for r in h2h_rows}
        assert expected_fighter in fighters, (
            f"{fixture_name}: expected {expected_fighter!r} in {fighters}"
        )


def test_normalize_boxing_main_includes_rounds_totals():
    """Coral33's main BOXING subtype on the Munguia card has rounds totals."""
    response = _load_probe("boxing_main")
    fetched = datetime(2026, 5, 1, 0, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        response, period="Game", sport_key="boxing",
        fetched_at=fetched, match_event=_stub_matcher,
    )
    totals = [r for r in rows if r["market_key"] == "totals"]
    assert totals, "Munguia card had Total 10.5 rounds in probe"
    # Probe captured Total 10.5 on this card.
    assert any(r["outcome_point"] == 10.5 for r in totals)


def test_normalize_cricket_ipl_is_h2h_only():
    """IPL match — h2h only, no spreads, no totals."""
    response = _load_probe("cricket_ipl")
    fetched = datetime(2026, 5, 1, 0, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        response, period="Game", sport_key="cricket",
        fetched_at=fetched, match_event=_stub_matcher,
    )
    market_keys = {r["market_key"] for r in rows}
    # Probe game (Chennai Super Kings vs Mumbai Indians) was Status='I'
    # which the normalizer skips. So we may get zero rows. If rows do
    # emerge, they should be h2h only.
    assert market_keys.issubset({"h2h"}), \
        f"unexpected non-h2h rows for cricket: {market_keys - {'h2h'}}"


def test_normalize_cricket_t20_is_h2h_only():
    """International T20 match — same h2h-only shape."""
    response = _load_probe("cricket_t20")
    fetched = datetime(2026, 5, 1, 0, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        response, period="Game", sport_key="cricket",
        fetched_at=fetched, match_event=_stub_matcher,
    )
    market_keys = {r["market_key"] for r in rows}
    assert market_keys.issubset({"h2h"})


# ─────────────────────────── WNBA (added 2026-05-09) ───────────────────────


def test_wnba_registered_with_basketball_odds_api_key():
    sport = SPORTS["wnba"]
    assert sport.label == "WNBA"
    assert sport.odds_api_sport_keys == ("basketball_wnba",)
    market_keys = {g.main_key for g in sport.market_groups}
    # Game tier
    assert "h2h" in market_keys
    assert "spreads" in market_keys
    assert "totals" in market_keys
    # 1H + Q1 (period coverage Coral33 supports + Odds API has)
    assert "h2h_h1" in market_keys
    assert "h2h_q1" in market_keys


def test_coral33_config_has_wnba_game_period_subtypes():
    cfg = load_coral33_config(CONFIG_DIR / "coral33.toml")
    wnba = cfg.sports["wnba"]
    assert wnba.sport_type == "BASKETBALL"
    assert wnba.subtypes_main == ["WNBA"]
    # No alts / props in coral33's WNBA catalog (probed 2026-05-09).
    assert wnba.subtypes_alt == []
    assert wnba.subtypes_prop == []
    assert wnba.periods == ["Game", "1st Half", "1st Quarter"]


def test_markets_wnba_config_full_tree():
    cfg = _load_market_config("markets.wnba.toml")
    assert cfg["main"]["enabled"] is True
    assert {"h2h", "spreads", "totals"}.issubset(cfg["main"]["markets"])
    # Odds API exposes alts + player props for WNBA, so those tiers
    # should be on (Coral33 won't populate them but the Odds API will).
    assert cfg["alternates"]["enabled"] is True
    assert cfg["periods"]["enabled"] is True
    assert cfg["player_props"]["enabled"] is True
    # Probed: blocks/steals/turnovers don't come back for WNBA — make
    # sure the config didn't regress to including them.
    pp = set(cfg["player_props"]["markets"])
    assert "player_blocks" not in pp
    assert "player_steals" not in pp
    assert "player_turnovers" not in pp


def test_normalize_wnba_main_lines_emit_full_market_set():
    """Probed Coral33 WNBA Game pull (2026-05-09) had Atlanta Dream @
    Minnesota Lynx with ML/spread/total all live. Normalizer should emit
    h2h + spreads + totals rows (team_totals depends on per-line data)."""
    response = _load_probe("wnba_main")
    fetched = datetime(2026, 5, 9, 17, tzinfo=timezone.utc)
    rows = normalize_league_lines(
        response, period="Game", sport_key="wnba",
        fetched_at=fetched, match_event=_stub_matcher,
    )
    market_keys = {r["market_key"] for r in rows}
    assert "h2h" in market_keys
    assert "spreads" in market_keys
    assert "totals" in market_keys
    h2h_rows = [r for r in rows if r["market_key"] == "h2h"]
    teams = {r["outcome_name"] for r in h2h_rows}
    # The probe captured Atlanta Dream / Minnesota Lynx / Chicago Sky /
    # Portland Fire. At least one of them should appear in h2h.
    assert teams & {
        "Atlanta Dream", "Minnesota Lynx", "Chicago Sky", "Portland Fire",
    }
