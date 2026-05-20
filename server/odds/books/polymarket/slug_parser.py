"""Polymarket market-slug parser.

Phase 1 supported only clean h2h slugs (`<sport>-<a>-<b>-<date>`). Phase 2
extends to the full alt-market grammar:

  H2H (US sports, 2-way):
    nba-sas-okc-2026-05-20
    mlb-bal-tb-2026-05-20
    nhl-las-col-2026-05-20

  Spread (alt-line ladder):
    nba-sas-okc-2026-05-20-spread-home-14pt5    ← home = team_b (slug second)
    nba-sas-okc-2026-05-20-spread-away-3pt5     ← away = team_a (slug first)

  Total (Over/Under ladder):
    nba-sas-okc-2026-05-20-total-207pt5
    mlb-bal-tb-2026-05-20-total-7pt5
    nhl-las-col-2026-05-20-total-6pt5

  Soccer 3-way (one binary market per outcome):
    epl-cry-ars-2026-05-24-cry      ← team_a wins
    epl-cry-ars-2026-05-24-ars      ← team_b wins
    epl-cry-ars-2026-05-24-draw

  NBA player points prop:
    nba-sas-okc-2026-05-20-points-victor-wembanyama-24pt5
    nba-sas-okc-2026-05-20-points-deaaron-fox-14pt5

Number encoding: `Npt5` = N.5 (more generally `NptF` = N.F). Split on
`pt` then concatenate with a `.` for the float. `14pt5` → 14.5, `207pt0`
→ 207.0.

Anything else (1H/1Q period markets, team-to-score-first, rebounds/assists
props, esports, tennis match-winner, futures with non-canonical slugs)
returns None — the normalizer's dispatcher skips silently.
"""
from __future__ import annotations

import re


# ─── Base 4-segment header ────────────────────────────────────────────────
# All supported slugs start with `<sport>-<team_a>-<team_b>-<YYYY-MM-DD>`.
# Codes are 2-4 lowercase chars (canonical ESPN-style for US sports, 3-char
# Polymarket-specific codes for soccer leagues).
_BASE_HEADER_RX = re.compile(
    r"^(?P<sport>[a-z0-9]+)"
    r"-(?P<a>[a-z]{2,4})"
    r"-(?P<b>[a-z]{2,4})"
    r"-(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?P<rest>.*)$"
)


# ─── Suffix patterns (anchored AFTER the header) ───────────────────────────
# All suffix patterns expect the leading dash (or "" for the bare h2h case).
#
# Spread: `-spread-(home|away)-<strike>`
# Total : `-total-<strike>`
# Player points: `-points-<player-slug>-<strike>`
# Soccer 3-way: `-(cry|ars|draw)` etc. — validated against the slug's
#   team codes; literal `draw` allowed.
#
# `<strike>` = one or more digits, then `pt`, then one or more digits.
# Examples: `14pt5`, `207pt5`, `7pt0`, `14pt25` (unlikely but parses).
_STRIKE_RX_TEXT = r"(?P<strike>\d+pt\d+)"

_SPREAD_RX = re.compile(rf"^-spread-(?P<side>home|away)-{_STRIKE_RX_TEXT}$")
_TOTAL_RX  = re.compile(rf"^-total-{_STRIKE_RX_TEXT}$")
_PLAYER_POINTS_RX = re.compile(
    rf"^-points-(?P<player>[a-z][a-z0-9]*(?:-[a-z0-9]+)*)-{_STRIKE_RX_TEXT}$"
)
# Soccer 3-way is validated against team codes at dispatch time — just
# capture the trailing segment.
_TRAILING_SEGMENT_RX = re.compile(r"^-(?P<segment>[a-z]{2,5})$")


def _decode_strike(s: str) -> float | None:
    """Decode `Npt5` / `NptF` → float.

    `14pt5`   → 14.5
    `207pt5`  → 207.5
    `7pt0`    → 7.0
    Returns None on malformed input.
    """
    if not s or "pt" not in s:
        return None
    try:
        whole, frac = s.split("pt", 1)
        # Both halves must be all digits.
        if not (whole.isdigit() and frac.isdigit()):
            return None
        return float(f"{whole}.{frac}")
    except (ValueError, AttributeError):
        return None


def parse_slug(slug: str) -> dict | None:
    """Parse a Polymarket market slug.

    Return shape:
      {
        "sport_prefix": str,            # "nba", "mlb", "epl", ...
        "team_a_code":  str,            # first team code in slug
        "team_b_code":  str,            # second team code in slug
        "date":         str,            # YYYY-MM-DD
        "kind":         str,            # "h2h" | "spread" | "total" |
                                        # "player_prop" | "soccer_3way"
        "strike":       float | None,   # only set for spread/total/player_prop
        "details":      str,            # kind-specific:
                                        #   spread       → "home" | "away"
                                        #   player_prop  → "victor-wembanyama"
                                        #   soccer_3way  → "cry" / "ars" / "draw"
                                        #   else         → ""
      }

    Returns None for any slug we don't support — caller should silently
    skip. The parser is intentionally strict so unsupported shapes never
    leak into the normalizer's dispatcher.
    """
    if not slug or not isinstance(slug, str):
        return None

    m = _BASE_HEADER_RX.match(slug)
    if m is None:
        return None
    sport = m.group("sport")
    code_a = m.group("a")
    code_b = m.group("b")
    date = m.group("date")
    rest = m.group("rest") or ""

    # ─── Bare h2h ─────────────────────────────────────────────────────────
    if rest == "":
        return {
            "sport_prefix": sport,
            "team_a_code":  code_a,
            "team_b_code":  code_b,
            "date":         date,
            "kind":         "h2h",
            "strike":       None,
            "details":      "",
        }

    # ─── Spread ───────────────────────────────────────────────────────────
    sm = _SPREAD_RX.match(rest)
    if sm is not None:
        strike = _decode_strike(sm.group("strike"))
        if strike is None:
            return None
        return {
            "sport_prefix": sport,
            "team_a_code":  code_a,
            "team_b_code":  code_b,
            "date":         date,
            "kind":         "spread",
            "strike":       strike,
            "details":      sm.group("side"),   # "home" or "away"
        }

    # ─── Total ────────────────────────────────────────────────────────────
    tm = _TOTAL_RX.match(rest)
    if tm is not None:
        strike = _decode_strike(tm.group("strike"))
        if strike is None:
            return None
        return {
            "sport_prefix": sport,
            "team_a_code":  code_a,
            "team_b_code":  code_b,
            "date":         date,
            "kind":         "total",
            "strike":       strike,
            "details":      "",
        }

    # ─── Player props (NBA points only for Phase 2) ──────────────────────
    pm = _PLAYER_POINTS_RX.match(rest)
    if pm is not None:
        strike = _decode_strike(pm.group("strike"))
        if strike is None:
            return None
        return {
            "sport_prefix": sport,
            "team_a_code":  code_a,
            "team_b_code":  code_b,
            "date":         date,
            "kind":         "player_prop",
            "strike":       strike,
            "details":      pm.group("player"),   # hyphenated, e.g. "victor-wembanyama"
        }

    # ─── Soccer 3-way ─────────────────────────────────────────────────────
    # The trailing segment is one of: team_a_code | team_b_code | "draw".
    # Validating against the slug's own codes prevents a stray 3-char
    # suffix from being parsed as a 3-way market.
    seg_m = _TRAILING_SEGMENT_RX.match(rest)
    if seg_m is not None:
        segment = seg_m.group("segment")
        if segment == code_a or segment == code_b or segment == "draw":
            return {
                "sport_prefix": sport,
                "team_a_code":  code_a,
                "team_b_code":  code_b,
                "date":         date,
                "kind":         "soccer_3way",
                "strike":       None,
                "details":      segment,
            }

    # Anything else — period markets, rebounds/assists props, special
    # yes/no markets like "team-to-score-first" — return None so the
    # caller skips silently.
    return None
