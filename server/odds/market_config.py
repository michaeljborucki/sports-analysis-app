from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "markets.toml"

# Tier names — one per [section] in the toml. "main" is special: game-level
# endpoint, one API call covers every event. All others are per-event tiers.
MAIN_TIER = "main"
PER_EVENT_TIERS = ("alternates", "first_innings", "player_props")
PROP_TIER = "player_props"


@dataclass(frozen=True)
class TierConfig:
    name: str
    enabled: bool
    interval_seconds: int
    regions: list[str]
    markets: list[str]
    games_window_hours: int | None = None  # only meaningful on player_props

    @property
    def is_main(self) -> bool:
        return self.name == MAIN_TIER

    @property
    def is_per_event(self) -> bool:
        return self.name in PER_EVENT_TIERS


@dataclass(frozen=True)
class OnDemandConfig:
    enabled: bool
    debounce_seconds: int


@dataclass(frozen=True)
class MarketConfig:
    tiers: dict[str, TierConfig] = field(default_factory=dict)
    on_demand: OnDemandConfig = field(
        default_factory=lambda: OnDemandConfig(enabled=True, debounce_seconds=60)
    )

    @classmethod
    def load(cls, path: Path | None = None) -> "MarketConfig":
        cfg_path = path or DEFAULT_CONFIG_PATH
        raw = tomllib.loads(cfg_path.read_text())

        tiers: dict[str, TierConfig] = {}
        for name in (MAIN_TIER, *PER_EVENT_TIERS):
            if name not in raw:
                continue
            section = raw[name]
            tiers[name] = TierConfig(
                name=name,
                enabled=bool(section.get("enabled", True)),
                interval_seconds=int(section.get("interval_seconds", 60)),
                regions=list(section.get("regions", ["us"])),
                markets=list(section.get("markets", [])),
                games_window_hours=section.get("games_window_hours"),
            )

        on_demand_raw = raw.get("on_demand", {})
        on_demand = OnDemandConfig(
            enabled=bool(on_demand_raw.get("enabled", True)),
            debounce_seconds=int(on_demand_raw.get("debounce_seconds", 60)),
        )

        return cls(tiers=tiers, on_demand=on_demand)

    def enabled_tiers(self) -> list[TierConfig]:
        return [t for t in self.tiers.values() if t.enabled]

    def prop_tier(self) -> TierConfig | None:
        return self.tiers.get(PROP_TIER)


# Prefix-based classifier — anything starting with pitcher_ or batter_ is a prop.
PROP_MARKET_PREFIXES = ("pitcher_", "batter_")


def is_prop_market(market_key: str) -> bool:
    return market_key.startswith(PROP_MARKET_PREFIXES)
