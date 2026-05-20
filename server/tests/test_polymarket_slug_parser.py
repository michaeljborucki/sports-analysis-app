"""Unit tests for the Polymarket Phase 2 slug parser.

Covers every supported `kind` plus the rejection paths. The parser is
expected to be strict: anything not in the supported grammar returns None
so the normalizer skips silently.
"""
from __future__ import annotations

import pytest

from server.odds.books.polymarket.slug_parser import parse_slug, _decode_strike


# ─── Strike decoding ───────────────────────────────────────────────────


class TestDecodeStrike:
    def test_half_strike(self):
        assert _decode_strike("14pt5") == 14.5

    def test_whole_strike(self):
        assert _decode_strike("7pt0") == 7.0

    def test_large_strike(self):
        assert _decode_strike("207pt5") == 207.5

    def test_decimal_under_one(self):
        assert _decode_strike("0pt5") == 0.5

    def test_quarter_strike(self):
        # The grammar permits any number of fractional digits.
        assert _decode_strike("14pt25") == 14.25

    def test_missing_pt_returns_none(self):
        assert _decode_strike("14") is None

    def test_empty_returns_none(self):
        assert _decode_strike("") is None

    def test_non_digit_returns_none(self):
        assert _decode_strike("abc")  is None
        assert _decode_strike("aptb")  is None


# ─── h2h (Phase 1 compatibility) ───────────────────────────────────────


class TestH2H:
    def test_nba_h2h(self):
        out = parse_slug("nba-sas-okc-2026-05-20")
        assert out is not None
        assert out["sport_prefix"] == "nba"
        assert out["team_a_code"] == "sas"
        assert out["team_b_code"] == "okc"
        assert out["date"] == "2026-05-20"
        assert out["kind"] == "h2h"
        assert out["strike"] is None
        assert out["details"] == ""

    def test_mlb_h2h(self):
        out = parse_slug("mlb-bal-tb-2026-05-20")
        assert out is not None
        assert out["sport_prefix"] == "mlb"
        assert out["team_a_code"] == "bal"
        assert out["team_b_code"] == "tb"
        assert out["kind"] == "h2h"

    def test_nhl_h2h(self):
        out = parse_slug("nhl-las-col-2026-05-20")
        assert out is not None
        assert out["sport_prefix"] == "nhl"
        assert out["kind"] == "h2h"

    def test_wnba_h2h(self):
        out = parse_slug("wnba-nyl-conn-2026-06-15")
        assert out is not None
        assert out["sport_prefix"] == "wnba"
        assert out["team_a_code"] == "nyl"
        assert out["team_b_code"] == "conn"  # 4-char code
        assert out["kind"] == "h2h"


# ─── Spread ─────────────────────────────────────────────────────────────


class TestSpread:
    def test_home_spread_half_strike(self):
        out = parse_slug("nba-sas-okc-2026-05-20-spread-home-14pt5")
        assert out is not None
        assert out["kind"] == "spread"
        assert out["strike"] == 14.5
        assert out["details"] == "home"

    def test_away_spread(self):
        out = parse_slug("nba-sas-okc-2026-05-20-spread-away-3pt5")
        assert out is not None
        assert out["kind"] == "spread"
        assert out["strike"] == 3.5
        assert out["details"] == "away"

    def test_mlb_spread(self):
        out = parse_slug("mlb-bal-tb-2026-05-20-spread-home-1pt5")
        assert out is not None
        assert out["kind"] == "spread"
        assert out["sport_prefix"] == "mlb"
        assert out["strike"] == 1.5

    def test_whole_strike(self):
        out = parse_slug("nba-sas-okc-2026-05-20-spread-home-7pt0")
        assert out is not None
        assert out["strike"] == 7.0

    def test_invalid_side_rejected(self):
        # Only home/away are valid sides.
        assert parse_slug("nba-sas-okc-2026-05-20-spread-middle-3pt5") is None

    def test_period_spread_rejected(self):
        # 1H / 1Q period markets are out of scope.
        assert parse_slug("nba-sas-okc-2026-05-20-1h-spread-home-4pt5") is None


# ─── Total ──────────────────────────────────────────────────────────────


class TestTotal:
    def test_nba_total(self):
        out = parse_slug("nba-sas-okc-2026-05-20-total-207pt5")
        assert out is not None
        assert out["kind"] == "total"
        assert out["strike"] == 207.5
        assert out["details"] == ""

    def test_mlb_total(self):
        out = parse_slug("mlb-bal-tb-2026-05-20-total-7pt5")
        assert out is not None
        assert out["kind"] == "total"
        assert out["strike"] == 7.5

    def test_nhl_total(self):
        out = parse_slug("nhl-las-col-2026-05-20-total-6pt5")
        assert out is not None
        assert out["kind"] == "total"
        assert out["strike"] == 6.5

    def test_malformed_strike_rejected(self):
        # `pt` separator required.
        assert parse_slug("nba-sas-okc-2026-05-20-total-207") is None

    def test_period_total_rejected(self):
        assert parse_slug("nba-sas-okc-2026-05-20-1h-total-111pt5") is None


# ─── Player prop (NBA points) ──────────────────────────────────────────


class TestPlayerProp:
    def test_simple_two_part_name(self):
        out = parse_slug("nba-sas-okc-2026-05-20-points-victor-wembanyama-24pt5")
        assert out is not None
        assert out["kind"] == "player_prop"
        assert out["strike"] == 24.5
        assert out["details"] == "victor-wembanyama"

    def test_single_token_name(self):
        out = parse_slug("nba-sas-okc-2026-05-20-points-tatum-30pt5")
        assert out is not None
        assert out["kind"] == "player_prop"
        assert out["details"] == "tatum"

    def test_apostrophe_stripped_name(self):
        # Polymarket strips apostrophes — "De'Aaron Fox" → "deaaron-fox"
        out = parse_slug("nba-sas-okc-2026-05-20-points-deaaron-fox-14pt5")
        assert out is not None
        assert out["details"] == "deaaron-fox"
        assert out["strike"] == 14.5

    def test_hyphenated_surname(self):
        out = parse_slug(
            "nba-sas-okc-2026-05-20-points-shai-gilgeous-alexander-28pt5"
        )
        assert out is not None
        assert out["details"] == "shai-gilgeous-alexander"
        assert out["strike"] == 28.5

    def test_rebounds_prop_rejected(self):
        # Phase 2 scope = points only; rebounds/assists return None.
        assert parse_slug(
            "nba-sas-okc-2026-05-20-rebounds-victor-wembanyama-13pt5"
        ) is None

    def test_assists_prop_rejected(self):
        assert parse_slug(
            "nba-sas-okc-2026-05-20-assists-victor-wembanyama-2pt5"
        ) is None


# ─── Soccer 3-way ───────────────────────────────────────────────────────


class TestSoccer3Way:
    def test_team_a_win(self):
        out = parse_slug("epl-cry-ars-2026-05-24-cry")
        assert out is not None
        assert out["kind"] == "soccer_3way"
        assert out["team_a_code"] == "cry"
        assert out["team_b_code"] == "ars"
        assert out["details"] == "cry"

    def test_team_b_win(self):
        out = parse_slug("epl-cry-ars-2026-05-24-ars")
        assert out is not None
        assert out["kind"] == "soccer_3way"
        assert out["details"] == "ars"

    def test_draw(self):
        out = parse_slug("epl-cry-ars-2026-05-24-draw")
        assert out is not None
        assert out["kind"] == "soccer_3way"
        assert out["details"] == "draw"

    def test_manchester_city_special_code(self):
        # Polymarket uses `mac` for Manchester City, not `mci`. The parser
        # only cares that the trailing segment matches one of the slug's
        # codes; mapping happens downstream.
        out = parse_slug("epl-mac-ast-2026-05-24-mac")
        assert out is not None
        assert out["kind"] == "soccer_3way"
        assert out["team_a_code"] == "mac"

    def test_unrelated_3char_suffix_rejected(self):
        # A trailing 3-char suffix that doesn't match either team code or
        # "draw" should not parse as soccer_3way.
        assert parse_slug("epl-cry-ars-2026-05-24-xyz") is None


# ─── Hard rejections ────────────────────────────────────────────────────


class TestRejections:
    def test_empty_string(self):
        assert parse_slug("") is None

    def test_none_input(self):
        assert parse_slug(None) is None  # type: ignore[arg-type]

    def test_non_string_input(self):
        assert parse_slug(12345) is None  # type: ignore[arg-type]

    def test_too_few_segments(self):
        assert parse_slug("nba-sas-okc") is None

    def test_bad_date_shape(self):
        # Date must be YYYY-MM-DD.
        assert parse_slug("nba-sas-okc-2026-5-20") is None
        assert parse_slug("nba-sas-okc-26-05-20") is None

    def test_team_to_score_first_rejected(self):
        # Not part of Phase 2 scope.
        assert parse_slug("nba-sas-okc-2026-05-20-team-to-score-first") is None

    def test_odd_even_rejected(self):
        # Special yes/no market.
        assert parse_slug("nba-sas-okc-2026-05-20-odd-even") is None

    def test_period_moneyline_rejected(self):
        # 1H moneyline.
        assert parse_slug("nba-sas-okc-2026-05-20-1h-moneyline") is None

    def test_futures_event_rejected(self):
        # Conference/championship futures use entirely different slug shapes.
        assert parse_slug(
            "will-the-cleveland-cavaliers-win-the-nba-eastern-conference-finals"
        ) is None

    def test_uppercase_rejected(self):
        # Polymarket slugs are lowercase; uppercase variants shouldn't parse.
        assert parse_slug("NBA-SAS-OKC-2026-05-20") is None
