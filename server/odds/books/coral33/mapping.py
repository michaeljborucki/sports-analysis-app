from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


# coral33 period string -> our market-key suffix. Empty string = main market
# (h2h, spreads, totals, team_totals with no suffix). Extend as we learn
# which sports/periods exist on their platform.
PERIOD_SUFFIX: dict[str, str] = {
    "Game": "",
    "1st Half": "_h1",
    "2nd Half": "_h2",
    "1st Quarter": "_q1",
    "2nd Quarter": "_q2",
    "3rd Quarter": "_q3",
    "4th Quarter": "_q4",
    "1st Period": "_p1",
    "2nd Period": "_p2",
    "3rd Period": "_p3",
    "1st 5 Innings": "_f5",
    "1st 3 Innings": "_f3",
    "1st 7 Innings": "_f7",
}


@dataclass
class Coral33SportConfig:
    sport_key: str              # our sport key (mlb, nba, nhl, tennis, baseball_ncaa)
    sport_type: str             # coral33 sportType (BASKETBALL, HOCKEY, BASEBALL, TENNIS)
    subtypes_main: list[str]    # e.g. ["NBA"]
    subtypes_alt: list[str] = field(default_factory=list)     # e.g. ["NBA+ALT+LINE"]
    subtypes_prop: list[str] = field(default_factory=list)    # deferred
    periods: list[str] = field(default_factory=lambda: ["Game"])

    @property
    def main_period_calls(self) -> list[tuple[str, str, str]]:
        """Tuples of (sportType, sportSubType, period) for main+period pulls."""
        out = []
        for sst in self.subtypes_main:
            for p in self.periods:
                out.append((self.sport_type, sst, p))
        return out

    @property
    def alt_calls(self) -> list[tuple[str, str, str]]:
        return [(self.sport_type, sst, "Game") for sst in self.subtypes_alt]


@dataclass
class Coral33Config:
    sports: dict[str, Coral33SportConfig]    # keyed by sport_key
    team_aliases: dict[str, dict[str, str]]  # {sport_key: {normalized: canonical}}


def load_coral33_config(path: Path) -> Coral33Config:
    """Load server/config/coral33.toml."""
    with path.open("rb") as f:
        raw = tomllib.load(f)
    sports: dict[str, Coral33SportConfig] = {}
    for key, cfg in (raw.get("sports") or {}).items():
        sports[key] = Coral33SportConfig(
            sport_key=key,
            sport_type=cfg["sport_type"],
            subtypes_main=list(cfg.get("subtypes_main") or []),
            subtypes_alt=list(cfg.get("subtypes_alt") or []),
            subtypes_prop=list(cfg.get("subtypes_prop") or []),
            periods=list(cfg.get("periods") or ["Game"]),
        )
    aliases_raw = raw.get("team_aliases") or {}
    team_aliases: dict[str, dict[str, str]] = {}
    for sport, table in aliases_raw.items():
        team_aliases[sport] = {k: v for k, v in table.items()}
    return Coral33Config(sports=sports, team_aliases=team_aliases)


# Alias so the public symbol in __init__ matches what's imported elsewhere.
Coral33SportMap = Coral33SportConfig
