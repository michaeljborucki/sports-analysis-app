from __future__ import annotations

import re
from typing import TypedDict


# "MIROFISH BET CARD — 2026-04-01" (baseball)
# "MIROFISH TENNIS BET CARD — 2026-04-19" (tennis; extra sport word)
HEADER_DATE_RE = re.compile(
    r"MIROFISH\s+(?:\w+\s+)?BET CARD\s+—\s+(\d{4}-\d{2}-\d{2})"
)


class PickDict(TypedDict):
    bet_type: str
    side: str
    odds_american: int
    market_prob: float
    model_prob: float
    edge: float
    kelly_pct: float


class GameDict(TypedDict):
    game_label: str
    picks: list[PickDict]


class CardDict(TypedDict):
    date: str
    games: list[GameDict]


def _is_separator(stripped: str) -> bool:
    """Separator lines in bet cards are only '=' or '-' characters."""
    return bool(stripped) and set(stripped) <= {"=", "-"}


def _is_header_noise(stripped: str) -> bool:
    """Lines from the ASCII card header that aren't pick data."""
    if "MIROFISH" in stripped and "BET CARD" in stripped:
        return True
    # "N picks across M games" / "N picks across M matches"
    if re.match(r"^\d+\s+picks?\s+across\s+\d+\s+(games?|matches?)", stripped):
        return True
    return False


def _parse_pick_line(stripped: str) -> PickDict | None:
    """Parse a single pick line. Accepts both the full baseball format (with
    Mkt/Model explicit) and the tennis format (Mkt/Model omitted — derived
    from odds + edge).

    Format: bet_type | side | +/-odds | [Mkt: X%] | [Model: Y%] | Edge: Z% | Kelly: W%
    """
    if "|" not in stripped or "Edge:" not in stripped:
        return None
    parts = [p.strip() for p in stripped.split("|")]
    if len(parts) < 4:
        return None
    bet_type = parts[0]
    side = parts[1]
    odds_match = re.search(r"[+-]\d+", parts[2])
    if not odds_match:
        return None
    odds = int(odds_match.group())

    mkt = model = edge = kelly = None
    label_re = re.compile(r"^(Mkt|Model|Edge|Kelly):\s*([+-]?[\d.]+)")
    for p in parts[3:]:
        m = label_re.match(p)
        if not m:
            continue
        label, val = m.group(1), float(m.group(2))
        if label == "Mkt":
            mkt = val
        elif label == "Model":
            model = val
        elif label == "Edge":
            edge = val
        elif label == "Kelly":
            kelly = val

    if edge is None or kelly is None:
        return None

    # Derive implied market probability from odds if the card didn't print it
    if mkt is None:
        mkt = (100 / (odds + 100) * 100) if odds > 0 else (-odds / (-odds + 100) * 100)
    # Derive model probability as market + edge
    if model is None:
        model = mkt + edge

    return {
        "bet_type": bet_type,
        "side": side,
        "odds_american": odds,
        "market_prob": mkt / 100.0,
        "model_prob": model / 100.0,
        "edge": edge / 100.0,
        "kelly_pct": kelly / 100.0,
    }


def parse_bet_card(text: str) -> CardDict:
    date_match = HEADER_DATE_RE.search(text)
    if not date_match:
        raise ValueError("Bet card missing date header")

    games: list[GameDict] = []
    current: GameDict | None = None

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if _is_separator(stripped):
            continue
        if _is_header_noise(stripped):
            continue

        pick = _parse_pick_line(stripped)
        if pick is not None:
            if current is None:
                # Pick before any game header — attach to an "Unknown" block
                current = {"game_label": "Unknown", "picks": []}
                games.append(current)
            current["picks"].append(pick)
            continue

        # Otherwise, treat as a new game header. Handles both "WSH@PHI"
        # (baseball) and "F. Cobolli vs B. Shelton" (tennis).
        current = {"game_label": stripped, "picks": []}
        games.append(current)

    games = [g for g in games if g["picks"]]
    return {"date": date_match.group(1), "games": games}
