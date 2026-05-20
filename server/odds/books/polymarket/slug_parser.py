"""Polymarket market-slug parser.

Per-game h2h moneyline slugs follow the convention:
  <sport>-<team_a_code>-<team_b_code>-<YYYY-MM-DD>

Examples:
  nba-sas-okc-2026-05-20  → NBA Spurs vs Thunder on 2026-05-20
  mlb-bal-tb-2026-05-20   → MLB Orioles vs Rays
  nhl-las-col-2026-05-20  → NHL Vegas (LAS) vs Colorado

Phase 1 ONLY accepts slugs with exactly this shape — no suffixes. Alt
markets like spreads/totals/props add extra dash-separated components
(e.g. `-spread-home-14pt5`, `-total-207pt5`, `-points-victor-wembanyama-24pt5`)
which we reject here; Phase 2 will own those.

Slug rejection examples (Phase 1 returns None):
  nba-sas-okc-2026-05-20-spread-home-14pt5
  mlb-bal-tb-2026-05-20-total-8pt5
  nba-sas-okc-2026-05-20-points-victor-wembanyama-24pt5
"""
from __future__ import annotations

import re


# Strict pattern: 4 dash-separated segments where the last carries the date
# YYYY-MM-DD (note: the date itself has internal dashes, so we treat it as a
# tail and split LEFT-anchored).
#
# Group breakdown:
#   sport_prefix : lowercase letters/digits (nba, mlb, nhl, wnba, atp, ...)
#   team_a_code  : 2-4 lowercase chars (sas, okc, bal, tb, las, ...)
#   team_b_code  : 2-4 lowercase chars
#   date         : YYYY-MM-DD
#
# Anchored start AND end — anything after the date (alt-market suffix)
# fails the match.
_H2H_SLUG_RX = re.compile(
    r"^(?P<sport>[a-z0-9]+)"
    r"-(?P<a>[a-z]{2,4})"
    r"-(?P<b>[a-z]{2,4})"
    r"-(?P<date>\d{4}-\d{2}-\d{2})$"
)


def parse_slug(slug: str) -> dict | None:
    """Parse a Polymarket market slug.

    Phase 1: accepts ONLY h2h-shaped slugs. Returns:
      {
        "sport_prefix": "nba",
        "team_a_code":  "sas",   # typically AWAY in slug ordering
        "team_b_code":  "okc",   # typically HOME
        "date":         "2026-05-20",
        "kind":         "h2h",
        "strike":       None,    # populated by Phase 2 alt parsers
        "details":      "",      # unused in Phase 1
      }

    Returns None for:
      - empty / non-string input
      - slugs with extra dash segments past the date (alt markets)
      - slugs with bad date shape
      - slugs that don't start with `<sport>-<code>-<code>-`

    The team-code length cap (2-4 chars) matches the standard ESPN-style
    abbreviations we use in TEAM_CODE_TO_CANONICAL. Phase 2 will widen
    this for soccer/tennis where slug forms differ (and parse longer
    suffix chains for alts).
    """
    if not slug or not isinstance(slug, str):
        return None
    m = _H2H_SLUG_RX.match(slug)
    if m is None:
        return None
    return {
        "sport_prefix": m.group("sport"),
        "team_a_code":  m.group("a"),
        "team_b_code":  m.group("b"),
        "date":         m.group("date"),
        "kind":         "h2h",
        "strike":       None,
        "details":      "",
    }
