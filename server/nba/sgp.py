"""NBA same-game-parlay screener (the user's three-step method).

1. Usage rate ≥ USAGE_MIN — someone the offense runs through.
2. Opponent is in the bottom DVP_BOTTOM defenses at the player's position:
   the teams that allow the MOST fantasy points per game to that position
   group (G / F / C). Fantasy points use FanDuel scoring, no bonuses:
   PTS + 1.2 REB + 1.5 AST + 3 STL + 3 BLK − TOV.
3. Points, rebounds and assists alternate lines, each the HIGHEST rung that
   hit in ≥ HIT_MIN of the sample games. Sample = this season once the player
   has MIN_SAMPLE games, otherwise last season (the "season just started" rule).

The three legs are then combined. True probability is the EMPIRICAL joint
rate — the share of sample games where all three legs hit together — not the
product of the three rates: points / rebounds / assists all ride on minutes,
so they are correlated. The product and the union floor (1 − Σ miss rates,
which holds under any correlation) are returned for comparison, plus a
conservative estimate (Wilson lower bound) because a 19-for-20 hit rate is
consistent with a true rate well under 95%. Each probability comes with the
break-even American price: the SGP has value only when the book pays better
than that.

Usage % (per player, over his sample games):

    100 × Σ (FGA + 0.44 FTA + TOV)
        / Σ (MIN ÷ (team MIN / 5) × (team FGA + 0.44 team FTA + team TOV))
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass


USAGE_MIN = 24.0
DVP_BOTTOM = 10
HIT_MIN = 0.93
MIN_SAMPLE = 10
# Lowest rung offered per stat: books' alternate ladders start around here,
# and a 1+ assist "leg" is not a bet anyone can place.
POINTS_LINES = (10, 15, 20, 25, 30, 35, 40, 45, 50)
REBOUNDS_LINES = tuple(range(3, 21))
ASSISTS_LINES = tuple(range(2, 21))
LADDERS = {"points": POINTS_LINES, "rebounds": REBOUNDS_LINES, "assists": ASSISTS_LINES}
# One-sided 90% Wilson bound.
WILSON_Z = 1.2816
POSITION_GROUPS = ("G", "F", "C")


@dataclass(frozen=True)
class PlayerGame:
    athlete_id: str
    name: str
    position: str          # G / F / C
    team_id: str
    opp_id: str
    event_id: str
    start: str             # ISO tip-off
    minutes: int
    fga: int
    fta: int
    tov: int
    points: int
    rebounds: int
    assists: int
    steals: int
    blocks: int

    @property
    def fantasy(self) -> float:
        return (self.points + 1.2 * self.rebounds + 1.5 * self.assists
                + 3 * self.steals + 3 * self.blocks - self.tov)

    @property
    def used(self) -> float:
        return self.fga + 0.44 * self.fta + self.tov


def position_group(abbr: str | None) -> str:
    """ESPN listed position → G / F / C ("PG", "SG", "G-F" → G; "SF", "PF" → F)."""
    a = (abbr or "").upper()
    if a.startswith("C"):
        return "C"
    if a.startswith(("PG", "SG", "G")):
        return "G"
    return "F"


def parse_player_lines(team_block: dict) -> list[list]:
    """Played athletes from one ESPN summary `boxscore.players[]` team block as
    compact rows [id, name, pos, min, fga, fta, tov, pts, reb, ast, stl, blk].
    DNPs and zero-minute cameos are dropped."""
    out: list[list] = []
    for stats in team_block.get("statistics") or []:
        keys = stats.get("keys") or []
        idx = {k: i for i, k in enumerate(keys)}
        need = ("minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
                "freeThrowsMade-freeThrowsAttempted", "rebounds", "assists",
                "turnovers", "steals", "blocks")
        if any(k not in idx for k in need):
            continue
        for a in stats.get("athletes") or []:
            s = a.get("stats") or []
            if a.get("didNotPlay") or len(s) < len(keys):
                continue
            try:
                minutes = int(s[idx["minutes"]] or 0)
                if minutes <= 0:
                    continue
                ath = a.get("athlete") or {}
                out.append([
                    str(ath["id"]),
                    ath.get("displayName") or str(ath["id"]),
                    position_group((ath.get("position") or {}).get("abbreviation")),
                    minutes,
                    int(str(s[idx["fieldGoalsMade-fieldGoalsAttempted"]]).split("-")[-1]),
                    int(str(s[idx["freeThrowsMade-freeThrowsAttempted"]]).split("-")[-1]),
                    int(s[idx["turnovers"]]),
                    int(s[idx["points"]]),
                    int(s[idx["rebounds"]]),
                    int(s[idx["assists"]]),
                    int(s[idx["steals"]]),
                    int(s[idx["blocks"]]),
                ])
            except (KeyError, TypeError, ValueError):
                continue
    return out


def player_games(events: list[dict], players: dict) -> list[PlayerGame]:
    """Every played line from `events`, given the store's `players[eid][tid]` rows."""
    out: list[PlayerGame] = []
    for ev in events:
        by_team = players.get(ev["id"])
        if not by_team:
            continue
        ids = [str(c["team"]["id"]) for c in ev["competitions"][0]["competitors"]]
        if len(ids) != 2:
            continue
        for tid, opp in ((ids[0], ids[1]), (ids[1], ids[0])):
            for r in by_team.get(tid) or ():
                out.append(PlayerGame(r[0], r[1], r[2], tid, opp, ev["id"], ev["date"], *r[3:]))
    return out


def team_used(boxes: dict, games: list[PlayerGame]) -> dict[tuple[str, str], tuple[float, int]]:
    """(event, team) → (team possessions used, team minutes)."""
    minutes: dict[tuple[str, str], int] = defaultdict(int)
    for g in games:
        minutes[(g.event_id, g.team_id)] += g.minutes
    out = {}
    for (eid, tid), mins in minutes.items():
        c = (boxes.get(eid) or {}).get(tid)
        if c:
            out[(eid, tid)] = (c["fga"] + 0.44 * c["fta"] + c["tov"], mins)
    return out


def usage_pct(games: list[PlayerGame], team_totals: dict) -> float | None:
    num = den = 0.0
    for g in games:
        t = team_totals.get((g.event_id, g.team_id))
        if not t or not t[1] or not t[0]:
            continue
        num += g.used
        den += g.minutes / (t[1] / 5) * t[0]
    return 100 * num / den if den else None


def dvp(games: list[PlayerGame]) -> dict[str, dict[str, float]]:
    """team → position group → fantasy points allowed per game."""
    allowed: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    played: dict[str, set[str]] = defaultdict(set)
    for g in games:
        allowed[g.opp_id][g.position] += g.fantasy
        played[g.opp_id].add(g.event_id)
    return {
        tid: {pos: allowed[tid][pos] / len(played[tid]) for pos in POSITION_GROUPS}
        for tid in played
    }


def dvp_ranks(table: dict[str, dict[str, float]]) -> dict[str, dict[str, int]]:
    """Rank 1 = allows the MOST to that position (worst defense)."""
    ranks: dict[str, dict[str, int]] = defaultdict(dict)
    for pos in POSITION_GROUPS:
        order = sorted(table, key=lambda t: table[t][pos], reverse=True)
        for i, tid in enumerate(order, 1):
            ranks[tid][pos] = i
    return ranks


def best_rung(values: list[int], rungs: tuple[int, ...]) -> dict | None:
    """Highest rung hit in ≥ HIT_MIN of games (None if even the lowest misses)."""
    n = len(values)
    best = None
    for line in rungs:
        hits = sum(v >= line for v in values)
        if n and hits / n >= HIT_MIN:
            best = {"line": line, "hits": hits, "n": n, "rate": hits / n}
        else:
            break
    return best


def wilson_lower(k: int, n: int, z: float = WILSON_Z) -> float | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / denom)


def breakeven_american(p: float | None) -> int | None:
    """The price the book must BEAT for `p` to be +EV. None at p ≥ 1 or p ≤ 0."""
    if p is None or p <= 0 or p >= 1:
        return None
    if p >= 0.5:
        return -round(100 * p / (1 - p))
    return round(100 * (1 - p) / p)


def evaluate_player(games: list[PlayerGame]) -> dict:
    """Legs + combined probabilities over one player's sample games."""
    legs = {
        stat: best_rung([getattr(g, stat) for g in games], rungs)
        for stat, rungs in LADDERS.items()
    }
    out: dict = {"legs": legs, "n": len(games)}
    if not games or any(v is None for v in legs.values()):
        out.update(joint=None, product=None, floor=None, conservative=None,
                   breakeven=None, conservative_breakeven=None)
        return out
    n = len(games)
    joint_hits = sum(
        all(getattr(g, stat) >= legs[stat]["line"] for stat in LADDERS) for g in games
    )
    product = math.prod(legs[s]["rate"] for s in LADDERS)
    floor = max(0.0, 1 - sum(1 - legs[s]["rate"] for s in LADDERS))
    conservative = wilson_lower(joint_hits, n)
    out.update(
        joint={"hits": joint_hits, "n": n, "rate": joint_hits / n},
        product=product,
        floor=floor,
        conservative=conservative,
        breakeven=breakeven_american(joint_hits / n),
        conservative_breakeven=breakeven_american(conservative),
    )
    return out
