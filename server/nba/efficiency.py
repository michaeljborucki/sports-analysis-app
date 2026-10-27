"""NBA possession-efficiency score projection.

For team A against team B (the user's formula):

    off_est = pace_A × off_eff_A        (A's pace × A's own scoring rate)
    def_est = pace_A × def_eff_B        (A's pace × what B's defense allows)
    predicted_A = (off_est + def_est) / 2

From completed regular-season box scores:

    pace     = own possessions / games
    off_eff  = points scored  / own possessions
    def_eff  = points allowed / opponents' possessions

Possessions = FGA − offensive rebounds + turnovers + 0.44 × FTA (the
standard box-score estimate; turnovers include team turnovers).

The formula scores each team at its OWN pace, so the two teams in one game
are projected over different possession counts. `predict_pace_matched` is
the same efficiencies over one shared pace (the average of both), shown
alongside as a check — it is not the headline number.
"""
from __future__ import annotations

from dataclasses import dataclass


FTA_WEIGHT = 0.44


@dataclass(frozen=True)
class TeamGame:
    """One team's line from one completed game."""
    team_id: str
    points: int
    possessions: float


@dataclass(frozen=True)
class GameBox:
    event_id: str
    home: TeamGame
    away: TeamGame


@dataclass
class TeamRating:
    team_id: str
    games: int = 0
    possessions: float = 0.0
    points_for: int = 0
    points_against: int = 0
    opp_possessions: float = 0.0

    @property
    def pace(self) -> float | None:
        return self.possessions / self.games if self.games else None

    @property
    def off_eff(self) -> float | None:
        return self.points_for / self.possessions if self.possessions else None

    @property
    def def_eff(self) -> float | None:
        return self.points_against / self.opp_possessions if self.opp_possessions else None


def parse_counts(statistics: list[dict]) -> dict | None:
    """FGA / FTA / offensive rebounds / turnovers from an ESPN box-score team
    block. Returns None when any piece is missing, so a partial box score
    never counts as a zero-possession game."""
    by_name = {s.get("name"): s.get("displayValue") for s in statistics}
    try:
        fga = int(str(by_name["fieldGoalsMade-fieldGoalsAttempted"]).split("-")[-1])
        fta = int(str(by_name["freeThrowsMade-freeThrowsAttempted"]).split("-")[-1])
        oreb = int(by_name["offensiveRebounds"])
        tov_raw = by_name.get("totalTurnovers")
        tov = int(tov_raw if tov_raw not in (None, "") else by_name["turnovers"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"fga": fga, "fta": fta, "oreb": oreb, "tov": tov}


def possessions(counts: dict) -> float:
    return counts["fga"] - counts["oreb"] + counts["tov"] + FTA_WEIGHT * counts["fta"]


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
            r.possessions += us.possessions
            r.points_for += us.points
            r.points_against += them.points
            r.opp_possessions += them.possessions
    return ratings


def predict_points(team: TeamRating, opponent: TeamRating) -> dict | None:
    """The user's formula for `team`'s points against `opponent`."""
    pace = team.pace
    if pace is None or team.off_eff is None or opponent.def_eff is None:
        return None
    off_est = pace * team.off_eff
    def_est = pace * opponent.def_eff
    return {
        "off_estimate": off_est,
        "def_estimate": def_est,
        "points": (off_est + def_est) / 2,
    }


def predict_pace_matched(team: TeamRating, opponent: TeamRating) -> float | None:
    """Same efficiencies, but both teams over one shared pace."""
    if None in (team.pace, opponent.pace, team.off_eff, opponent.def_eff):
        return None
    game_pace = (team.pace + opponent.pace) / 2
    return game_pace * (team.off_eff + opponent.def_eff) / 2
