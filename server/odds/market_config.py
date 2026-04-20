from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# Tier names — one per [section] in the toml. "main" is special: game-level
# endpoint, one API call covers every event. All others are per-event tiers.
# Tier names used across all sports. The "periods" tier covers each sport's
# sub-game structure — baseball's 1st 1/3/5/7 innings, NBA's quarters and
# halves, NHL's periods. The tier key is neutral; sport-specific labels
# render in the UI (see frontend TIER_LABELS).
MAIN_TIER = "main"
PER_EVENT_TIERS = ("alternates", "periods", "player_props")
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
class PicksConfig:
    """Per-sport filter for /api/picks/<sport>. If `include_bet_types` is
    non-empty, only picks with a matching bet_type are surfaced. Empty list
    means surface everything (backwards compat)."""
    include_bet_types: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MarketConfig:
    tiers: dict[str, TierConfig] = field(default_factory=dict)
    on_demand: OnDemandConfig = field(
        default_factory=lambda: OnDemandConfig(enabled=True, debounce_seconds=60)
    )
    picks: PicksConfig = field(default_factory=PicksConfig)

    @classmethod
    def load(cls, filename: str | Path = "markets.mlb.toml") -> "MarketConfig":
        """Load a markets config by filename (resolved under server/config/) or
        by an absolute Path. Default preserves backwards compat with MLB."""
        if isinstance(filename, Path) and filename.is_absolute():
            cfg_path = filename
        else:
            cfg_path = CONFIG_DIR / str(filename)
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

        picks_raw = raw.get("picks", {})
        picks = PicksConfig(
            include_bet_types=tuple(picks_raw.get("include_bet_types", [])),
        )

        return cls(tiers=tiers, on_demand=on_demand, picks=picks)

    def enabled_tiers(self) -> list[TierConfig]:
        return [t for t in self.tiers.values() if t.enabled]

    def prop_tier(self) -> TierConfig | None:
        return self.tiers.get(PROP_TIER)


# Prefix-based classifier — player-level props across all sports.
PROP_MARKET_PREFIXES = ("pitcher_", "batter_", "player_")


def is_prop_market(market_key: str) -> bool:
    return market_key.startswith(PROP_MARKET_PREFIXES)
