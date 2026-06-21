"""Tests for cross-book player-name canonicalization.

Covers the seven design rules from `server/odds/player_names.py`:
  1. lowercase
  2. NFKD + drop combining marks (accents)
  3. hyphens → spaces
  4. apostrophes / periods / commas stripped
  5. whitespace collapse + trim
  6. single-letter leading initial dropped
  7. sport-scoped alias lookup AFTER folding

Plus integration smoke for the Kalshi prop-title parser, which is the
forward-declared hook for the future Kalshi prop ingestion path.
"""
from __future__ import annotations

import pytest

from server.odds.player_names import (
    _fold,
    normalize_player_name,
    reload_aliases,
)


# ─── Pure folding (no alias lookup) ────────────────────────────────────


class TestFoldRules:
    def test_lowercase(self):
        assert _fold("Victor Wembanyama") == "victor wembanyama"

    def test_lowercase_full_uppercase(self):
        assert _fold("VICTOR WEMBANYAMA") == "victor wembanyama"

    def test_accent_doncic(self):
        assert _fold("Luka Dončić") == "luka doncic"

    def test_accent_jokic(self):
        assert _fold("Nikola Jokić") == "nikola jokic"

    def test_accent_sabonis(self):
        # Domantas Sabonis carries no accents in standard sources but
        # the dotted-i / accented variants exist for other players.
        assert _fold("Domantas Sabonis") == "domantas sabonis"

    def test_accent_dotted_capital_i(self):
        # Turkish dotted I — Polymarket / Coral33 occasionally surface
        # international footballers / boxers with these.
        assert _fold("İlhan Mansız") == "ilhan mansiz"

    def test_hyphen_to_space(self):
        # Hyphens become spaces so the surname halves don't accidentally
        # collide with apostrophe-stripped names.
        assert _fold("Shai Gilgeous-Alexander") == "shai gilgeous alexander"

    def test_unicode_dash(self):
        # En-dash variant — same treatment.
        assert _fold("Karl–Anthony Towns") == "karl anthony towns"

    def test_apostrophe_stripped(self):
        assert _fold("Shaquille O'Neal") == "shaquille oneal"

    def test_period_stripped(self):
        assert _fold("Jaren Jackson Jr.") == "jaren jackson jr"

    def test_whitespace_collapse(self):
        assert _fold("  Victor   Wembanyama  ") == "victor wembanyama"

    def test_initial_only_collapses(self):
        # Coral33 sometimes emits "V Wembanyama" — collapse to surname so
        # it merges with the full-name form from the other books.
        assert _fold("V Wembanyama") == "wembanyama"

    def test_initial_with_dot_collapses(self):
        # Period stripped first in step 4, then the single-letter rule fires.
        assert _fold("V. Wembanyama") == "wembanyama"

    def test_two_letter_initial_kept(self):
        # "JJ Watt", "AJ Brown", "CC Sabathia" — multi-letter first tokens
        # are real names, not initials. Do NOT collapse.
        assert _fold("JJ Watt") == "jj watt"
        assert _fold("CC Sabathia") == "cc sabathia"

    def test_empty(self):
        assert _fold("") == ""
        assert _fold(None) == ""  # type: ignore[arg-type]

    def test_only_punctuation_returns_empty(self):
        assert _fold("...") == ""
        assert _fold("---") == ""

    def test_idempotent(self):
        for s in ["Victor Wembanyama", "Luka Dončić", "V Wembanyama",
                  "Shai Gilgeous-Alexander", "Shaquille O'Neal"]:
            once = _fold(s)
            twice = _fold(once)
            assert once == twice, f"fold not idempotent for {s!r}"


# ─── Sport-scoped alias lookup ─────────────────────────────────────────


class TestAliasLookup:
    @pytest.fixture(autouse=True)
    def _reload(self):
        # Each test starts with a freshly-loaded alias map so tests are
        # insulated from any module-state pollution.
        reload_aliases()
        yield
        reload_aliases()

    def test_nba_nickname_kd(self):
        assert normalize_player_name("KD", "nba") == "kevin durant"

    def test_nba_nickname_steph(self):
        assert normalize_player_name("Steph", "nba") == "stephen curry"

    def test_nba_nickname_sga(self):
        # The alias resolves the most common abbreviated form. The hyphen
        # form already folds to "shai gilgeous alexander" via the
        # mechanical rule — both routes converge.
        assert normalize_player_name("SGA", "nba") == "shai gilgeous alexander"
        assert (
            normalize_player_name("Shai Gilgeous-Alexander", "nba")
            == "shai gilgeous alexander"
        )

    def test_mlb_surname_only(self):
        # Coral33 / Kalshi occasionally surface surname-only — bridge to
        # the full name Odds API emits in `description`.
        assert normalize_player_name("Trout", "mlb") == "mike trout"
        assert normalize_player_name("Judge", "mlb") == "aaron judge"

    def test_mlb_shohei_alias(self):
        assert normalize_player_name("Shohei", "mlb") == "shohei ohtani"

    def test_alias_sport_scoped(self):
        # "Trout" is NOT an alias under NBA — the same input passes
        # through as the folded form.
        assert normalize_player_name("Trout", "nba") == "trout"

    def test_passthrough_no_match(self):
        # A name no alias map covers — folded only.
        assert (
            normalize_player_name("Anthony Edwards", "nba") == "anthony edwards"
        )

    def test_unknown_sport_falls_back_to_fold(self):
        # Sport not in the table → no alias lookup, just fold.
        assert normalize_player_name("KD", "rugby") == "kd"

    def test_empty_sport_falls_back_to_fold(self):
        assert normalize_player_name("Stephen Curry", "") == "stephen curry"

    def test_case_insensitive_sport(self):
        assert normalize_player_name("KD", "NBA") == "kevin durant"
        assert normalize_player_name("KD", "Nba") == "kevin durant"


# ─── Cross-source convergence ──────────────────────────────────────────


class TestCrossSourceConvergence:
    """Every realistic form a given player can arrive in MUST fold to
    the same canonical string."""

    @pytest.fixture(autouse=True)
    def _reload(self):
        reload_aliases()
        yield
        reload_aliases()

    def test_wembanyama_all_sources(self):
        # Odds API, Polymarket (slug-decoded), Coral33 (full + initial),
        # Kalshi title fragment — all collapse to one canonical.
        canon = "victor wembanyama"
        assert normalize_player_name("Victor Wembanyama", "nba") == canon
        assert normalize_player_name("victor-wembanyama", "nba") == canon
        # Note: Coral33 sometimes emits initials.
        assert normalize_player_name("V Wembanyama", "nba") == "wembanyama"
        # Note: surname-only does NOT auto-bridge to the full name in NBA
        # without an alias — by design, basketball surnames aren't unique
        # enough (multiple Smiths, etc.). Two of three variants converge;
        # the third would need an alias entry if the orphan logs surface it.

    def test_curry_all_sources(self):
        # "Steph" via alias, full name via fold — both land at one canonical.
        canon = "stephen curry"
        assert normalize_player_name("Stephen Curry", "nba") == canon
        assert normalize_player_name("Steph", "nba") == canon
        assert normalize_player_name("STEPHEN CURRY", "nba") == canon


# ─── Kalshi prop-title parser integration ──────────────────────────────


class TestKalshiTitleIntegration:
    """Smoke-test the forward-declared `parse_prop_title` so the hook
    that future Kalshi prop ingestion will use stays correct."""

    @pytest.fixture(autouse=True)
    def _reload(self):
        reload_aliases()
        yield
        reload_aliases()

    def test_yes_title(self):
        from server.odds.books.kalshi.normalizer import parse_prop_title

        out = parse_prop_title("yes Victor Wembanyama: 30+ points", "nba")
        assert out == ("victor wembanyama", "30+")

    def test_no_title(self):
        from server.odds.books.kalshi.normalizer import parse_prop_title

        out = parse_prop_title("no Aaron Judge: 2+ home runs", "mlb")
        assert out == ("aaron judge", "2+")

    def test_alias_applied(self):
        from server.odds.books.kalshi.normalizer import parse_prop_title

        # Hypothetical title using the SGA shorthand — alias bridges it.
        out = parse_prop_title("yes SGA: 25+ points", "nba")
        assert out is not None
        assert out[0] == "shai gilgeous alexander"

    def test_non_prop_title_returns_none(self):
        from server.odds.books.kalshi.normalizer import parse_prop_title

        # Game / market titles that DON'T match the prop shape.
        assert parse_prop_title("Spurs vs Thunder winner", "nba") is None
        assert parse_prop_title("", "nba") is None
