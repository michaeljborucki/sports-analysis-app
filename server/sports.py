"""
Sport registry — single source of truth for which sports the backend supports,
which Odds API sport keys to pull for each, where each sport's agent writes its
picks, and which markets config file to use.

To add a sport: append a `Sport(...)` entry here, create
`config/markets.<key>.toml`, and the frontend's `lib/sports.ts` entry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Sport:
    key: str                                  # URL / config identifier: "mlb", "tennis", ...
    label: str                                # Display label
    # Odds API sport keys. If any string ends in "*" it's a prefix match against
    # /sports (used for tennis's per-tournament sport keys).
    odds_api_sport_keys: tuple[str, ...]
    agent_dir: Path                           # where the sibling agent writes bet_card + bets.csv
    markets_config: str                       # filename in server/config/ (e.g. "markets.mlb.toml")
    # Market families this sport exposes. Drives both main-grid market tabs and
    # the per-game expansion tabs (main + alt lines). Order matters.
    market_groups: tuple["MarketGroup", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MarketGroup:
    label: str                 # "Moneyline", "Run Line", "Game Spread", ...
    main_key: str              # Odds API market_key for the main line
    alt_key: str | None = None # alternates market_key
    # Shape of the line — drives how the expansion panel renders the point:
    # "spread" (+1.5 / -1.5) | "total" (Over/Under 8.5) | "moneyline" (no point)
    display: str = "moneyline"


HOME = Path.home()


SPORTS: dict[str, Sport] = {
    "mlb": Sport(
        key="mlb",
        label="MLB",
        odds_api_sport_keys=("baseball_mlb",),
        agent_dir=HOME / "personal_workspace/agents/baseball-agents/data",
        markets_config="markets.mlb.toml",
        market_groups=(
            MarketGroup("Moneyline", main_key="h2h", display="moneyline"),
            MarketGroup("Run Line", main_key="spreads", alt_key="alternate_spreads", display="spread"),
            MarketGroup("Total", main_key="totals", alt_key="alternate_totals", display="total"),
            MarketGroup("F5 ML", main_key="h2h_1st_5_innings", display="moneyline"),
            MarketGroup("F5 RL", main_key="spreads_1st_5_innings", display="spread"),
            MarketGroup("F5 Total", main_key="totals_1st_5_innings", display="total"),
        ),
    ),
    "tennis": Sport(
        key="tennis",
        label="Tennis",
        odds_api_sport_keys=("tennis_atp_*", "tennis_wta_*"),
        agent_dir=HOME / "personal_workspace/agents/tennis-agents/data",
        markets_config="markets.tennis.toml",
        market_groups=(
            MarketGroup("Moneyline", main_key="h2h", display="moneyline"),
            MarketGroup("Game Spread", main_key="spreads", alt_key="alternate_spreads", display="spread"),
            MarketGroup("Total Games", main_key="totals", alt_key="alternate_totals", display="total"),
        ),
    ),
    "nba": Sport(
        key="nba",
        label="NBA",
        odds_api_sport_keys=("basketball_nba",),
        agent_dir=HOME / "personal_workspace/agents/nba-agents/data",
        markets_config="markets.nba.toml",
        market_groups=(
            MarketGroup("Moneyline", main_key="h2h", display="moneyline"),
            MarketGroup("Spread", main_key="spreads", alt_key="alternate_spreads", display="spread"),
            MarketGroup("Total", main_key="totals", alt_key="alternate_totals", display="total"),
            MarketGroup("1H ML", main_key="h2h_h1", display="moneyline"),
            MarketGroup("1H Spread", main_key="spreads_h1", alt_key="alternate_spreads_h1", display="spread"),
            MarketGroup("1H Total", main_key="totals_h1", alt_key="alternate_totals_h1", display="total"),
            MarketGroup("Q1 ML", main_key="h2h_q1", display="moneyline"),
            MarketGroup("Q1 Spread", main_key="spreads_q1", alt_key="alternate_spreads_q1", display="spread"),
            MarketGroup("Q1 Total", main_key="totals_q1", alt_key="alternate_totals_q1", display="total"),
        ),
    ),
    "nhl": Sport(
        key="nhl",
        label="NHL",
        odds_api_sport_keys=("icehockey_nhl",),
        # No NHL agent dir today; path is a placeholder so the picks reader
        # gracefully returns no_picks_today until/unless one is created.
        agent_dir=HOME / "personal_workspace/agents/nhl-agents/data",
        markets_config="markets.nhl.toml",
        market_groups=(
            MarketGroup("Moneyline", main_key="h2h", display="moneyline"),
            MarketGroup("Puck Line", main_key="spreads", alt_key="alternate_spreads", display="spread"),
            MarketGroup("Total", main_key="totals", alt_key="alternate_totals", display="total"),
            MarketGroup("1P ML", main_key="h2h_p1", display="moneyline"),
            MarketGroup("1P Spread", main_key="spreads_p1", alt_key="alternate_spreads_p1", display="spread"),
            MarketGroup("1P Total", main_key="totals_p1", alt_key="alternate_totals_p1", display="total"),
        ),
    ),
    "baseball_ncaa": Sport(
        key="baseball_ncaa",
        label="NCAA Baseball",
        odds_api_sport_keys=("baseball_ncaa",),
        agent_dir=HOME / "personal_workspace/agents/baseball-ncaa-agents/data",
        markets_config="markets.baseball_ncaa.toml",
        market_groups=(
            MarketGroup("Moneyline", main_key="h2h", display="moneyline"),
            MarketGroup("Run Line", main_key="spreads", alt_key="alternate_spreads", display="spread"),
            MarketGroup("Total", main_key="totals", alt_key="alternate_totals", display="total"),
            MarketGroup("F5 ML", main_key="h2h_1st_5_innings", display="moneyline"),
            MarketGroup("F5 RL", main_key="spreads_1st_5_innings", display="spread"),
            MarketGroup("F5 Total", main_key="totals_1st_5_innings", display="total"),
        ),
    ),
}


def get(key: str) -> Sport:
    if key not in SPORTS:
        raise KeyError(f"Unknown sport: {key}")
    return SPORTS[key]


def all_sports() -> list[Sport]:
    return list(SPORTS.values())
