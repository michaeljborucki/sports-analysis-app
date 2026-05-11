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
            # NRFI = "no run first inning". Equivalent to U/O 0.5 runs in
            # the 1st inning — books post it as its own dedicated market.
            # Coral33 SCORE IN 1ST normalizer emits market_key="nrfi" (since
            # 2026-05-03) so it pairs against Odds API's nrfi.
            MarketGroup("NRFI", main_key="nrfi", display="yes_no"),
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
    # WNBA — Coral33 has WNBA game/1H/Q1 lines, no alts/props/GPROPS in
    # their catalog (probed 2026-05-09). Odds API exposes the full NBA-
    # style market tree, so the cross-shop universe is game/1H/Q1 only;
    # alts + player props live as Odds-API-only display surface.
    "wnba": Sport(
        key="wnba",
        label="WNBA",
        odds_api_sport_keys=("basketball_wnba",),
        agent_dir=HOME / "personal_workspace/agents/wnba-agents/data",
        markets_config="markets.wnba.toml",
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
    # Asian Baseball — NPB (Japan) + KBO (Korea) share a single app sport_key.
    # Both Odds API keys resolve to the same slate; coral33 bundles them under
    # its `WBC` sportSubType (display "Asian Baseball").
    "asian_baseball": Sport(
        key="asian_baseball",
        label="Asian Baseball",
        odds_api_sport_keys=("baseball_npb", "baseball_kbo"),
        agent_dir=HOME / "personal_workspace/agents/asian-baseball-agents/data",
        markets_config="markets.asian_baseball.toml",
        market_groups=(
            MarketGroup("Moneyline", main_key="h2h", display="moneyline"),
            MarketGroup("Run Line", main_key="spreads", alt_key="alternate_spreads", display="spread"),
            MarketGroup("Total", main_key="totals", alt_key="alternate_totals", display="total"),
        ),
    ),
    # UFC / MMA — single Odds API key, two coral33 subtypes (UFC main PPVs +
    # Fight Night). h2h is universal, totals is rounds over/under (limited
    # book coverage). No alternates / props / per-round markets on the Odds
    # API for MMA.
    "ufc": Sport(
        key="ufc",
        label="UFC",
        odds_api_sport_keys=("mma_mixed_martial_arts",),
        agent_dir=HOME / "personal_workspace/agents/ufc-agents/data",
        markets_config="markets.ufc.toml",
        market_groups=(
            MarketGroup("Moneyline", main_key="h2h", display="moneyline"),
            MarketGroup("Total Rounds", main_key="totals", display="total"),
        ),
    ),
    # Boxing — single Odds API key. Coral33 splits cards into five separate
    # subtypes (one per headline card); the fetcher iterates all five and
    # rows merge under shared event_ids at the cache.
    "boxing": Sport(
        key="boxing",
        label="Boxing",
        odds_api_sport_keys=("boxing_boxing",),
        agent_dir=HOME / "personal_workspace/agents/boxing-agents/data",
        markets_config="markets.boxing.toml",
        market_groups=(
            MarketGroup("Moneyline", main_key="h2h", display="moneyline"),
            MarketGroup("Total Rounds", main_key="totals", display="total"),
        ),
    ),
    # Cricket — h2h only on both Odds API and coral33. Two subtypes feed
    # this one sport key:
    #   cricket_ipl                  — Indian Premier League (T20)
    #   cricket_international_t20    — generic international T20
    # Coral33's `ICCINTERCUP` subtype is mislabeled in their catalog (the
    # display name says "Indian Premier League") — games confirmed via
    # probe to be real IPL matches.
    "cricket": Sport(
        key="cricket",
        label="Cricket",
        odds_api_sport_keys=("cricket_ipl", "cricket_international_t20"),
        agent_dir=HOME / "personal_workspace/agents/cricket-agents/data",
        markets_config="markets.cricket.toml",
        market_groups=(
            MarketGroup("Moneyline", main_key="h2h", display="moneyline"),
        ),
    ),
    # Soccer — pre-match only, curated to a top-tier league set. `h2h` is
    # 3-way (home/draw/away) for soccer in both Odds API and coral33 — the
    # normalizer writes 3-way to `h2h` (not `h2h_3_way`) so rows merge.
    "soccer": Sport(
        key="soccer",
        label="Soccer",
        odds_api_sport_keys=(
            # Europe — top five + UEFA competitions
            "soccer_epl",
            "soccer_spain_la_liga",
            "soccer_italy_serie_a",
            "soccer_germany_bundesliga",
            "soccer_france_ligue_one",
            "soccer_uefa_champs_league",
            "soccer_uefa_europa_league",
            # Americas
            "soccer_usa_mls",
            "soccer_mexico_ligamx",
            "soccer_brazil_campeonato",
            "soccer_conmebol_copa_libertadores",
            # Asia-Pacific
            "soccer_japan_j_league",
        ),
        agent_dir=HOME / "personal_workspace/agents/soccer-agents/data",
        markets_config="markets.soccer.toml",
        market_groups=(
            # h2h is 3-way for soccer — the odds grid renders 2 outcomes per
            # game today, so ML is exposed here for completeness (will show
            # home + away only in the grid; draw needs UI work). The data is
            # stored correctly as 3 rows under h2h for scanner consumption.
            MarketGroup("Moneyline", main_key="h2h", display="moneyline"),
            MarketGroup("Spread", main_key="spreads", display="spread"),
            MarketGroup("Total", main_key="totals", display="total"),
        ),
    ),
}


def get(key: str) -> Sport:
    if key not in SPORTS:
        raise KeyError(f"Unknown sport: {key}")
    return SPORTS[key]


def all_sports() -> list[Sport]:
    return list(SPORTS.values())
