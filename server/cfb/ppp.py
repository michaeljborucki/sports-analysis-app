"""College-football points-per-play score projection.

For team A against team B:

    off_est = plays_A × off_ppp_A        (A's pace × A's own scoring rate)
    def_est = plays_A × def_ppp_B        (A's pace × what B's defense allows)
    predicted_A = (off_est + def_est) / 2

Season-to-date, from every completed game box score:

    plays per game = offensive plays / games
    off_ppp        = points scored  / own offensive plays
    def_ppp        = points allowed / opponents' offensive plays

Offensive plays = pass attempts + rush attempts. College rushing attempts
already include sacks, so this is the NCAA's own "total plays" count.
Points are the final score, so defensive / return touchdowns count toward
the scoring team's rate — a deliberate simplification of a basic model.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TeamGame:
    """One team's line from one completed game."""
    team_id: str
    points: int
    plays: int


@dataclass(frozen=True)
class GameBox:
    event_id: str
    home: TeamGame
    away: TeamGame


@dataclass
class TeamRating:
    team_id: str
    games: int = 0
    plays: int = 0
    points_for: int = 0
    points_against: int = 0
    opp_plays: int = 0
    names: dict = field(default_factory=dict)

    @property
    def plays_per_game(self) -> float | None:
        return self.plays / self.games if self.games else None

    @property
    def off_ppp(self) -> float | None:
        return self.points_for / self.plays if self.plays else None

    @property
    def def_ppp(self) -> float | None:
        return self.points_against / self.opp_plays if self.opp_plays else None


def parse_plays(statistics: list[dict]) -> int | None:
    """Pass attempts + rush attempts from an ESPN box-score team block.

    `completionAttempts` reads "25/38" (completions/attempts). Returns None
    when either piece is missing, so a partial box score never counts as a
    zero-play game.
    """
    by_name = {s.get("name"): s.get("displayValue") for s in statistics}
    comp_att = by_name.get("completionAttempts")
    rushes = by_name.get("rushingAttempts")
    if not comp_att or rushes in (None, ""):
        return None
    try:
        attempts = int(str(comp_att).split("/")[-1].split("-")[-1])
        return attempts + int(rushes)
    except ValueError:
        return None


def build_ratings(boxes: list[GameBox]) -> dict[str, TeamRating]:
    ratings: dict[str, TeamRating] = {}

    def rating(team_id: str) -> TeamRating:
        if team_id not in ratings:
            ratings[team_id] = TeamRating(team_id)
        return ratings[team_id]

    for box in boxes:
        for us, them in ((box.home, box.away), (box.away, box.home)):
            r = rating(us.team_id)
            r.games += 1
            r.plays += us.plays
            r.points_for += us.points
            r.points_against += them.points
            r.opp_plays += them.plays
    return ratings


def predict_points(team: TeamRating, opponent: TeamRating) -> dict | None:
    """The user's formula for `team`'s points against `opponent`."""
    plays = team.plays_per_game
    if plays is None or team.off_ppp is None or opponent.def_ppp is None:
        return None
    off_est = plays * team.off_ppp
    def_est = plays * opponent.def_ppp
    return {
        "off_estimate": off_est,
        "def_estimate": def_est,
        "points": (off_est + def_est) / 2,
    }
