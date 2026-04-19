from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

from .bet_card_parser import parse_bet_card, PickDict
from .track_record import compute_30d_record


# Kelly %-based tier cutoffs (stored as fraction; 0.10 = 10%)
KELLY_HIGH = 0.10
KELLY_SWEET = 0.03


def _tier_from_kelly(kelly: float) -> str:
    if kelly >= KELLY_HIGH:
        return "high"
    if kelly >= KELLY_SWEET:
        return "sweet"
    return "lean"


def _stake_from_kelly(kelly: float) -> float:
    if kelly >= 0.15:
        return 1.5
    if kelly >= 0.07:
        return 1.0
    if kelly >= 0.02:
        return 0.5
    return 0.25


def _market_label(bet_type: str, side: str) -> str:
    readable = bet_type.replace("_", " ").title()
    return f"{readable}: {side}"


def _synthesize_reasoning(pick: PickDict) -> str:
    model_pct = pick["model_prob"] * 100
    market_pct = pick["market_prob"] * 100
    edge_pct = pick["edge"] * 100
    kelly_pct = pick["kelly_pct"] * 100
    return (
        f"Model projects {model_pct:.1f}% probability vs. market-implied "
        f"{market_pct:.1f}% — a {edge_pct:+.1f}% edge. "
        f"Full-Kelly sizing would be {kelly_pct:.1f}%."
    )


def _stable_id(game_label: str, bet_type: str, side: str) -> str:
    raw = f"{game_label}|{bet_type}|{side}".encode()
    return hashlib.md5(raw).hexdigest()[:12]


class PicksReader:
    def __init__(self, bet_card_dir: Path, bets_csv: Path):
        self.bet_card_dir = Path(bet_card_dir)
        self.bets_csv = Path(bets_csv)

    def _card_path(self, for_date: date) -> Path:
        return self.bet_card_dir / f"bet_card_{for_date.isoformat()}.txt"

    def get_picks_for_date(self, for_date: date) -> dict:
        path = self._card_path(for_date)
        now = datetime.now(timezone.utc)
        if not path.exists():
            return {
                "picks": [],
                "status": "no_picks_today",
                "last_checked_at": now,
                "bet_card_date": None,
            }

        card = parse_bet_card(path.read_text())
        record = compute_30d_record(self.bets_csv, reference_date=for_date)

        picks: list[dict] = []
        for game in card["games"]:
            for p in game["picks"]:
                picks.append({
                    "id": _stable_id(game["game_label"], p["bet_type"], p["side"]),
                    "tier": _tier_from_kelly(p["kelly_pct"]),
                    "game_label": game["game_label"],
                    "market_label": _market_label(p["bet_type"], p["side"]),
                    "pick_side": p["side"],
                    "odds_american": p["odds_american"],
                    "best_book": None,
                    "stake_units": _stake_from_kelly(p["kelly_pct"]),
                    "probability_pct": round(p["model_prob"] * 100, 1),
                    "market_probability_pct": round(p["market_prob"] * 100, 1),
                    "edge_pct": round(p["edge"] * 100, 1),
                    "stats": [
                        {"label": "Mkt", "value": f"{p['market_prob']*100:.1f}%"},
                        {"label": "Model", "value": f"{p['model_prob']*100:.1f}%"},
                        {"label": "Edge", "value": f"{p['edge']*100:+.1f}%"},
                        {"label": "Kelly", "value": f"{p['kelly_pct']*100:.1f}%"},
                    ],
                    "reasoning": _synthesize_reasoning(p),
                    "agent_key": "baseball-agents",
                    "agent_record_30d": record["label"],
                    "commence_time": None,
                })

        picks.sort(key=lambda p: (-p["edge_pct"], -p["stake_units"]))

        return {
            "picks": picks,
            "status": "ok",
            "last_checked_at": now,
            "bet_card_date": card["date"],
        }

    def get_todays_event_ids(self, for_date: date) -> set[str]:
        """Stub: bet card game labels are team abbrevs, not Odds API event IDs.
        Returning empty = fetcher enriches all games (v1 policy)."""
        return set()
