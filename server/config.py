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
    coral33_customer_id: str
    coral33_password: str
    coral33_enabled: bool
    kalshi_api_key: str
    kalshi_private_key_path: Path | None
    # Which store the odds READ path serves rows from.
    #   "native"     — today's behavior: server/cache.db's odds_snapshot,
    #                  populated by this repo's own fetchers. DEFAULT.
    #   "betting_db" — read Odds-API rows from the central betting-db
    #                  SQLite (read-only), unioned with this repo's
    #                  direct-book rows (coral33 / kalshi / polymarket).
    # The native fetcher keeps running in BOTH modes; this flag only
    # changes what the read entry points return.
    odds_source: str
    # Path to betting-db's SQLite file. Only consulted when
    # odds_source == "betting_db"; opened read-only.
    betting_db_path: Path
    # Master switch for THIS repo's Odds API fetcher — scheduled polls,
    # the UI's refresh-all button, and per-event refresh. Default True =
    # today's behavior. Set false when odds come from betting-db instead,
    # so betting-site stops spending Odds API credits of its own.
    #
    # Deliberately narrower than cache_mode: cache_mode=latest silences
    # EVERY fetcher including coral33/kalshi/polymarket, which are free,
    # directly-polled, and must keep running. This gate touches only the
    # metered Odds API path.
    odds_api_fetcher_enabled: bool

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
            coral33_customer_id=os.environ.get("CORAL33_CUSTOMER_ID", "").strip(),
            coral33_password=os.environ.get("CORAL33_PASSWORD", ""),
            coral33_enabled=os.environ.get("CORAL33_ENABLED", "false").lower()
            not in ("false", "0", "no", "off"),
            kalshi_api_key=os.environ.get("KALSHI_API_KEY", "").strip(),
            kalshi_private_key_path=(
                Path(p).expanduser().resolve()
                if (p := os.environ.get("KALSHI_PRIVATE_KEY_PATH", "").strip())
                else None
            ),
            odds_source=os.getenv("ODDS_SOURCE", "native"),
            odds_api_fetcher_enabled=os.environ.get(
                "ODDS_API_FETCHER_ENABLED", "true",
            ).strip().lower() not in ("false", "0", "no", "off"),
            betting_db_path=Path(os.environ.get(
                "BETTING_DB_PATH",
                str(Path.home() / "personal_workspace/betting-db/data/odds.db"),
            )),
        )
