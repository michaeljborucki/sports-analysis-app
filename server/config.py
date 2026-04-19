from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    odds_api_key: str
    bet_card_dir: Path
    bets_csv: Path
    odds_poll_interval: int
    api_budget_floor: int
    host: str
    port: int
    cache_db: Path
    picks_date_override: str  # YYYY-MM-DD; empty string = use today
    fetcher_enabled: bool     # false = don't poll the Odds API (frozen snapshot mode)

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            odds_api_key=os.environ.get("ODDS_API_KEY", ""),
            bet_card_dir=Path(os.environ.get(
                "BET_CARD_DIR",
                str(Path.home() / "personal_workspace/agents/baseball-agents/data"),
            )),
            bets_csv=Path(os.environ.get(
                "BETS_CSV",
                str(Path.home() / "personal_workspace/agents/baseball-agents/data/bets.csv"),
            )),
            odds_poll_interval=int(os.environ.get("ODDS_POLL_INTERVAL", "30")),
            api_budget_floor=int(os.environ.get("API_BUDGET_FLOOR", "100")),
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8000")),
            cache_db=Path(__file__).parent / "cache.db",
            picks_date_override=os.environ.get("PICKS_DATE_OVERRIDE", "").strip(),
            fetcher_enabled=os.environ.get("FETCHER_ENABLED", "true").lower()
            not in ("false", "0", "no", "off"),
        )
