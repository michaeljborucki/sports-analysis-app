from __future__ import annotations

import re
from typing import TypedDict


HEADER_DATE_RE = re.compile(r"MIROFISH BET CARD\s+—\s+(\d{4}-\d{2}-\d{2})")
GAME_HEADER_RE = re.compile(r"^\s{2}([A-Z]{2,4}@[A-Z]{2,4})\s*$")
PICK_LINE_RE = re.compile(
    r"^\s+(?P<bet_type>[a-z_0-9]+)\s*\|\s*"
    r"(?P<side>[^|]+?)\s*\|\s*"
    r"(?P<odds>[+-]\d+)\s*\|\s*"
    r"Mkt:\s*(?P<mkt>[\d.]+)%\s*\|\s*"
    r"Model:\s*(?P<model>[\d.]+)%\s*\|\s*"
    r"Edge:\s*(?P<edge>[\d.\-]+)%\s*\|\s*"
    r"Kelly:\s*(?P<kelly>[\d.\-]+)%"
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


def parse_bet_card(text: str) -> CardDict:
    date_match = HEADER_DATE_RE.search(text)
    if not date_match:
        raise ValueError("Bet card missing date header")

    games: list[GameDict] = []
    current: GameDict | None = None

    for line in text.splitlines():
        if (m := GAME_HEADER_RE.match(line)):
            current = {"game_label": m.group(1), "picks": []}
            games.append(current)
            continue
        if current is not None and (m := PICK_LINE_RE.match(line)):
            current["picks"].append({
                "bet_type": m.group("bet_type"),
                "side": m.group("side").strip(),
                "odds_american": int(m.group("odds")),
                "market_prob": float(m.group("mkt")) / 100.0,
                "model_prob": float(m.group("model")) / 100.0,
                "edge": float(m.group("edge")) / 100.0,
                "kelly_pct": float(m.group("kelly")) / 100.0,
            })

    games = [g for g in games if g["picks"]]
    return {"date": date_match.group(1), "games": games}
