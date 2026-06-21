"""Player-name canonicalization for cross-book prop merging.

Problem: the same player appears with slightly different spellings in every
source we ingest:

  - Odds API description:    "Victor Wembanyama"
  - Polymarket slug-decoded: "Victor-Wembanyama" / "victor-wembanyama"
  - Coral33 Team1ID field:   "Victor Wembanyama" or "V Wembanyama"
  - Kalshi market title:     "yes Victor Wembanyama: 30+"

Each variant lands as a DIFFERENT outcome_name row in the cache (the PK
includes outcome_name), so cross-book EV/arb on player props fails to
pair the same player's prices across books — leaving phantom orphan
rows per book.

Solution: a deterministic folding function `normalize_player_name` that
EVERY player-prop emission path calls before constructing outcome_name.
The cache stores the canonical form only; original display names are
recoverable from the underlying source if ever needed (no current UI
use case requires it).

Folding rules (applied in order):
  1. NFKD-normalize Unicode + strip combining marks (accents/diacritics).
  2. Lowercase.
  3. Replace hyphens with spaces ("Gilgeous-Alexander" → "gilgeous alexander").
  4. Strip ALL other punctuation (apostrophes, periods, commas, parens, ...).
  5. Collapse runs of whitespace to single spaces; trim ends.
  6. If the leading token is a single letter (with or without a trailing
     dot in step 4, that's already gone), drop it — handles "V Wembanyama"
     → "wembanyama". Two-letter initials ("JJ Watt", "AJ Brown") are NOT
     collapsed — those are real names in the wild.
  7. Look up the result in the per-sport alias table; replace if found.

Sport-scoping is required: surname-only ("trout") is unique in MLB but
collides with literal "Trout" if used elsewhere. We never reach into
another sport's alias table.

After folding, the canonical form is stable and case/punct-insensitive.
"""
from __future__ import annotations

import logging
import re
import tomllib
import unicodedata
from pathlib import Path


logger = logging.getLogger(__name__)


_ALIASES_PATH = Path(__file__).resolve().parent.parent / "config" / "player_aliases.toml"


# Per-sport alias map. Populated lazily on first call to `_get_aliases`.
# Structure: {sport_key: {folded_input: folded_output}}.
_ALIASES: dict[str, dict[str, str]] | None = None


# Match a single letter followed by either whitespace or end-of-string.
# Applied AFTER folding, so we only see lowercase ASCII letters here.
_LEADING_INITIAL_RX = re.compile(r"^([a-z])\s+(.+)$")

# Characters we treat as word separators (collapse to a single space).
_HYPHEN_LIKE = "-‐‑‒–—―"

# Whitespace collapser.
_WS_RX = re.compile(r"\s+")


# Latin-extended letters whose NFKD form doesn't reduce to ASCII because
# they're independent code points, not base+combining. Manually fold to
# the closest ASCII letter so e.g. Turkish "ı" / "Mansız" matches the
# Odds-API-side description "Mansiz".
_LATIN_EXTENDED_FOLD = {
    "ı": "i",   # Turkish dotless i (U+0131) — separate letter, no decompose
    "ł": "l",   # Polish ł
    "Ł": "L",
    "ø": "o",   # Norwegian/Danish ø
    "Ø": "O",
    "æ": "ae",
    "Æ": "AE",
    "œ": "oe",
    "Œ": "OE",
    "ß": "ss",  # German Eszett
    "ð": "d",   # Icelandic
    "Ð": "D",
    "þ": "th",  # Icelandic thorn
    "Þ": "Th",
}


def _fold(name: str) -> str:
    """Pure-mechanical deterministic fold. No alias lookup.

    Idempotent: `_fold(_fold(x)) == _fold(x)`. Tested in
    `test_player_names.test_fold_idempotent`.
    """
    if not name:
        return ""

    # Step 1: NFKD-normalize and drop combining marks (accents).
    #   "Luka Dončić" → "Luka Doncic"
    #   "Jokić"       → "Jokic"
    #   "İlhan"       → "Ilhan"   (NFKD + drop combining handles the dotted-I)
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))

    # Step 1b: Latin-extended fold for letters NFKD doesn't reduce (ı, ł,
    # ø, æ, ...). These are independent Unicode code points so combining-
    # mark stripping has no effect.
    if any(c in _LATIN_EXTENDED_FOLD for c in stripped):
        stripped = "".join(_LATIN_EXTENDED_FOLD.get(c, c) for c in stripped)

    # Step 2: lowercase.
    s = stripped.lower()

    # Step 3: replace hyphens (including the Unicode hyphen variants) with
    # spaces. Done BEFORE general punctuation stripping so the surname
    # halves don't merge into one token.
    for h in _HYPHEN_LIKE:
        if h in s:
            s = s.replace(h, " ")

    # Step 4: drop all remaining non-alphanumeric, non-whitespace chars.
    #   "O'Neal"      → "oneal"
    #   "Jr."         → "jr"
    #   "Smith, Jr."  → "smith jr"
    #   "(P)"         → "p"
    s = "".join(c if (c.isalnum() or c.isspace()) else "" for c in s)

    # Step 5: collapse whitespace + trim.
    s = _WS_RX.sub(" ", s).strip()

    if not s:
        return ""

    # Step 6: single-letter leading initial → drop.
    #   "v wembanyama" → "wembanyama"
    #   "j sinner"     → "sinner"
    # Multi-letter first tokens (length >= 2) are kept verbatim — "jj watt",
    # "aj brown", "cc sabathia" are real names.
    m = _LEADING_INITIAL_RX.match(s)
    if m is not None:
        s = m.group(2)

    return s


def _load_aliases() -> dict[str, dict[str, str]]:
    """Read player_aliases.toml. Returns {} if the file is missing — the
    canonicalizer still works without aliases, just less effectively for
    nickname bridges."""
    if not _ALIASES_PATH.exists():
        logger.info("player_names: no alias file at %s — using empty map", _ALIASES_PATH)
        return {}
    try:
        raw = tomllib.loads(_ALIASES_PATH.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.warning("player_names: failed to parse %s (%s) — using empty map", _ALIASES_PATH, e)
        return {}

    # Validate + fold every key/value as a safety net. The TOML is hand-
    # maintained, so a typo in a key (extra whitespace, accidental caps)
    # would silently disable the alias otherwise.
    out: dict[str, dict[str, str]] = {}
    for sport, table in raw.items():
        if not isinstance(table, dict):
            continue
        folded_table: dict[str, str] = {}
        for k, v in table.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            fk = _fold(k)
            fv = _fold(v)
            if not fk or not fv:
                continue
            if fk != k.lower().strip():
                logger.info(
                    "player_names: alias key %r for sport %r re-folded to %r",
                    k, sport, fk,
                )
            folded_table[fk] = fv
        if folded_table:
            out[sport.lower()] = folded_table
    return out


def _get_aliases() -> dict[str, dict[str, str]]:
    """Lazy alias loader. The TOML is read on first call and cached for the
    process lifetime. Tests that need to reset it call `reload_aliases()`.
    """
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = _load_aliases()
    return _ALIASES


def reload_aliases() -> None:
    """Reset the alias cache so the next `normalize_player_name` re-reads
    the TOML. Useful for tests + a future hot-reload signal handler."""
    global _ALIASES
    _ALIASES = None


def normalize_player_name(name: str, sport: str) -> str:
    """Return the canonical form of a player name for the given sport.

    The canonical form is stable across casing, accents, hyphens,
    apostrophes, periods, and most "X Surname" initial variants. Sport-
    scoped alias lookup runs AFTER folding so e.g. "Trout" → "trout" →
    "mike trout" for MLB, but the same input under sport="nba" passes
    through as "trout".

    No match in the alias table = pass through the folded form. Empty /
    None input returns "".

    Args:
      name:  raw player string from any source.
      sport: sport_key. Case-insensitive ("NBA" == "nba"). If the sport
             isn't in the alias table, no alias lookup happens (fold only).

    Returns:
      Canonical folded name (lowercase ASCII, single-spaced).
    """
    folded = _fold(name)
    if not folded:
        return ""
    sport_key = (sport or "").strip().lower()
    if not sport_key:
        return folded
    table = _get_aliases().get(sport_key)
    if table is None:
        return folded
    return table.get(folded, folded)
