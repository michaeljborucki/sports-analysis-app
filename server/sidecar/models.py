"""Shared dataclasses for the sidecar package."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from server.odds.books.coral33.accounts import AccountCredential
from server.sidecar.settings import KellyFraction


SplitStatus = Literal[
    "planned", "below_minimum", "no_eligible_account", "partial_fill",
]


@dataclass
class LegSpec:
    """Minimal snapshot of the +EV leg at fire time. Mirrors the fields the
    Coral33 insertWagerParlay payload requires per-leg.

    Fields with `0` / `""` defaults are "Coral-side" details that the EV
    scanner doesn't know — they get filled in by the placer via a
    just-in-time Get_LeagueLines2 lookup (see Coral33Placer._lookup_coral_context).
    The lookup context fields below (sport_key, home_team, away_team,
    market_kind, outcome_name) carry just enough info from the EV row
    for the placer to find the matching Coral game."""
    sport_type: str
    sport_sub_type: str
    period: str
    line_type: str            # 'M' (moneyline), 'S' (spread), 'T' (total)
    game_num: int
    chosen_team_id: str
    rot_num: int              # team1 rotation number used in description
    price_american: int       # e.g. 475
    price_decimal: float      # e.g. 5.75
    price_numerator: int
    price_denominator: int
    spread: float = 0.0
    total_points: float = 0.0
    game_datetime: str = ""   # ISO-ish string from Coral's response
    description: str = ""     # e.g. "Soccer #225390 New Zealand +475 - For Game "
    # --- Lookup context (set by resolve.py, used by Coral33Placer for
    # the just-in-time fill if Coral-side fields above are unset). ---
    sport_key: str = ""       # our cache key (e.g. "mlb", "nba", "soccer")
    home_team: str = ""       # cache row's home_team
    away_team: str = ""       # cache row's away_team
    market_kind: str = ""     # 'h2h' | 'spreads' | 'totals' | …
    outcome_name: str = ""    # cache row's outcome_name (e.g. "Chicago Cubs")
    point: float | None = None  # cache row's outcome_point (None for h2h)


@dataclass
class AccountSnapshot:
    """Per-account state used by the splitter."""
    credential: AccountCredential
    available_balance: float
    agent_id: str | None = None
    store: str | None = None
    cust_profile: str | None = None

    @property
    def customer_id(self) -> str:
        return self.credential.customer_id

    @property
    def max_parlay_stake(self) -> int:
        return self.credential.max_parlay_stake


@dataclass
class SplitAssignment:
    account: AccountSnapshot
    amount: int               # whole dollars


@dataclass
class SplitPlan:
    assignments: list[SplitAssignment] = field(default_factory=list)
    status: SplitStatus = "planned"
    target: int = 0           # the dollar target the splitter was asked to fill

    @property
    def filled(self) -> int:
        return sum(a.amount for a in self.assignments)

    @property
    def unfilled(self) -> int:
        return self.target - self.filled


@dataclass
class SidecarPlaceRequest:
    ev_row_id: str
    ev_leg: LegSpec
    kelly_full_pct: float       # the +EV row's full-Kelly %
    kelly_fraction: KellyFraction
    bankroll: int
    trigger_source: str = "user"            # 'user' | 'delta_tick'
    # Delta-tick path uses this to bypass Kelly recompute; user-triggered
    # placements leave it None.
    stake_override_dollars: int | None = None
