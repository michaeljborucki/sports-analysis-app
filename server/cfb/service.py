"""College-football PPP projections: ESPN data loader + per-week slate.

Data comes from ESPN's public (keyless, unmetered) site API:

  * scoreboard per regular-season week, per division: `groups=80` = every
    game with an FBS team (incl. FBS vs FCS), `groups=81` = every game with
    an FCS team — so FBS-vs-FCS games appear in both and are de-duplicated
    (the FBS copy wins). Schedule, final scores, team identity;
  * game summary per completed game — box-score pass/rush attempts.

A completed game's box score never changes, so each is fetched once and
kept in `server/data/cfb_boxscores_<season>.json` (gitignored). Completed
past weeks' scoreboards are cached there too; only the current and
requested weeks are re-read, at most every REFRESH_SECONDS.
"""
from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ..systems.team_names import TeamIndex
from .ppp import GameBox, TeamGame, build_ratings, parse_plays, predict_points


logger = logging.getLogger(__name__)

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
REFRESH_SECONDS = 600
SUMMARY_CONCURRENCY = 8
REGULAR_SEASON = 2
# ESPN scoreboard group per division. Cache keys: FBS weeks keep the bare
# week number (pre-FCS cache files stay valid), FCS weeks are "fcs:<n>".
DIVISIONS = {"fbs": 80, "fcs": 81}


def _week_key(division: str, week: int) -> str:
    return str(week) if division == "fbs" else f"{division}:{week}"


class CfbPredictionService:
    def __init__(self, snapshot_service=None, data_dir: Path = DATA_DIR) -> None:
        self._snapshot_service = snapshot_service
        self._data_dir = data_dir
        self._lock = asyncio.Lock()
        self._memo: dict[int | None, tuple[float, dict]] = {}

    async def get(self, week: int | None = None) -> dict:
        hit = self._memo.get(week)
        if hit and time.monotonic() - hit[0] < REFRESH_SECONDS:
            return await self._with_market(hit[1])
        async with self._lock:
            hit = self._memo.get(week)
            if not hit or time.monotonic() - hit[0] >= REFRESH_SECONDS:
                payload = await self._build(week)
                self._memo[week] = (time.monotonic(), payload)
                hit = self._memo[week]
        return await self._with_market(hit[1])

    # ───────────────────────── build ─────────────────────────

    async def _build(self, week: int | None) -> dict:
        async with httpx.AsyncClient(timeout=20.0) as client:
            current = await self._scoreboard(client, None, DIVISIONS["fbs"])
            season = int(current["season"]["year"])
            current_week = int((current.get("week") or {}).get("number") or 1)
            target_week = week or current_week

            store = self._load_store(season)
            # (division, week) -> scoreboard
            weeks: dict[tuple[str, int], dict] = {("fbs", current_week): current}
            for division, group in DIVISIONS.items():
                for w in range(1, max(current_week, target_week) + 1):
                    if (division, w) in weeks:
                        continue
                    key = _week_key(division, w)
                    cached = store["scoreboards"].get(key)
                    if cached is not None and w < current_week:
                        weeks[(division, w)] = cached
                        continue
                    weeks[(division, w)] = await self._scoreboard(client, w, group)
                    if w < current_week and _all_completed(weeks[(division, w)]):
                        store["scoreboards"][key] = weeks[(division, w)]

            # Ratings use only games from weeks BEFORE the target week, so a
            # past week's projections are what the model would have said
            # going in (no peeking at that week's results). Both divisions
            # feed one rating pool: an FCS team's rates come from all its
            # games, FBS opponents included.
            teams: dict[str, dict] = {}
            fcs_teams: set[str] = set()
            completed: list[dict] = []
            seen: set[str] = set()
            ordered = sorted(weeks.items(), key=lambda kv: (kv[0][1], kv[0][0] != "fbs"))
            for (division, w), board in ordered:
                for ev in board.get("events", []):
                    if ev["id"] in seen:  # FBS vs FCS: already taken from groups=80
                        continue
                    seen.add(ev["id"])
                    comp = ev["competitions"][0]
                    for c in comp["competitors"]:
                        _remember_team(teams, c.get("team") or {})
                        if division == "fcs" and (c.get("team") or {}).get("id") is not None:
                            fcs_teams.add(str(c["team"]["id"]))
                    if w < target_week and comp["status"]["type"].get("completed"):
                        completed.append(ev)
            # After de-dup, groups=81 events are FCS vs FCS only, so anyone
            # who played in one is FCS; everyone else is FBS.
            for tid, t in teams.items():
                t["division"] = "fcs" if tid in fcs_teams else "fbs"

            missing = [ev["id"] for ev in completed if ev["id"] not in store["boxes"]]
            if missing:
                sem = asyncio.Semaphore(SUMMARY_CONCURRENCY)

                async def fetch(eid: str) -> None:
                    async with sem:
                        try:
                            store["boxes"][eid] = await self._summary_plays(client, eid)
                        except Exception as exc:  # transient — retry next build
                            logger.warning("cfb summary %s failed: %s", eid, exc)

                await asyncio.gather(*(fetch(eid) for eid in missing))
            self._save_store(season, store)

        boxes = [b for ev in completed if (b := _game_box(ev, store["boxes"].get(ev["id"])))]
        ratings = build_ratings(boxes)

        slate = []
        target_events: dict[str, tuple[str, dict]] = {}
        for division in DIVISIONS:  # FBS first: its copy of a shared game wins
            for ev in weeks[(division, target_week)].get("events", []):
                target_events.setdefault(ev["id"], (division, ev))
        for division, ev in target_events.values():
            comp = ev["competitions"][0]
            sides = {c["homeAway"]: c for c in comp["competitors"]}
            if "home" not in sides or "away" not in sides:
                continue
            home_id, away_id = str(sides["home"]["team"]["id"]), str(sides["away"]["team"]["id"])
            home_r, away_r = ratings.get(home_id), ratings.get(away_id)
            home_p = predict_points(home_r, away_r) if home_r and away_r else None
            away_p = predict_points(away_r, home_r) if home_r and away_r else None
            status = comp["status"]["type"]
            slate.append({
                "event_id": ev["id"],
                "commence_time": ev["date"],
                "neutral_site": bool(comp.get("neutralSite")),
                # fbs = at least one FBS team (ESPN groups=80); fcs = FCS vs FCS.
                "division": division,
                "completed": bool(status.get("completed")),
                "status_detail": status.get("shortDetail") or status.get("detail"),
                "home": _side(teams, home_id, home_r, home_p, sides["home"], status),
                "away": _side(teams, away_id, away_r, away_p, sides["away"], status),
                "predicted_total": (
                    home_p["points"] + away_p["points"] if home_p and away_p else None
                ),
                # Home-perspective spread, betting sign: -7 = home favored by 7.
                "predicted_spread_home": (
                    away_p["points"] - home_p["points"] if home_p and away_p else None
                ),
            })
        slate.sort(key=lambda g: g["commence_time"])

        team_rows = sorted(
            (
                {
                    **teams.get(tid, {"team_id": tid, "name": tid}),
                    "games": r.games,
                    "plays_per_game": r.plays_per_game,
                    "off_ppp": r.off_ppp,
                    "def_ppp": r.def_ppp,
                    "points_for_per_game": r.points_for / r.games,
                    "points_against_per_game": r.points_against / r.games,
                }
                for tid, r in ratings.items()
                if r.games
            ),
            key=lambda t: t["name"],
        )
        return {
            "season": season,
            "week": target_week,
            "current_week": current_week,
            "games_used": len(boxes),
            "games_skipped": len(completed) - len(boxes),
            "built_at": datetime.now(timezone.utc).isoformat(),
            "games": slate,
            "teams": team_rows,
        }

    # ───────────────────────── market lines ─────────────────────────

    async def _with_market(self, payload: dict) -> dict:
        """Attach the consensus main spread/total from the odds snapshot.
        Read-only; recomputed per request so lines stay current while the
        ESPN-derived projections are memoized."""
        games = payload["games"]
        if self._snapshot_service is None or not games:
            return payload
        try:
            snapshot = await self._snapshot_service.get()
            odds_games = list(snapshot.non_prop_games_by_sport.get("ncaaf", ()))
        except Exception:
            logger.exception("cfb: odds snapshot unavailable")
            return payload

        index = TeamIndex()
        for g in games:
            for side in ("home", "away"):
                t = g[side]
                index.add(t["team_id"], t["team_id"], t["name"], t.get("location"),
                          t.get("short_name"), mascot=t.get("mascot"))
        by_pair: dict[tuple[str, str], dict] = {}
        for og in odds_games:
            h, a = index.resolve(og["home_team"]), index.resolve(og["away_team"])
            if h and a:
                by_pair[(h, a)] = og

        out = []
        for g in games:
            og = by_pair.get((g["home"]["team_id"], g["away"]["team_id"]))
            flipped = False
            if og is None:
                og = by_pair.get((g["away"]["team_id"], g["home"]["team_id"]))
                flipped = og is not None
            spread = total = None
            if og is not None:
                # Odds feed's home team might be ESPN's away (neutral sites).
                spread_team = og["away_team"] if flipped else og["home_team"]
                spread = _main_point(og, "spreads", spread_team)
                total = _main_point(og, "totals", "Over")
            out.append({**g, "market_spread_home": spread, "market_total": total})
        return {**payload, "games": out}

    # ───────────────────────── ESPN I/O ─────────────────────────

    async def _scoreboard(
        self, client: httpx.AsyncClient, week: int | None, group: int,
    ) -> dict:
        params = {"groups": group, "limit": 400}
        if week is not None:
            params.update(week=week, seasontype=REGULAR_SEASON)
        r = await client.get(f"{ESPN}/scoreboard", params=params)
        r.raise_for_status()
        return r.json()

    async def _summary_plays(self, client: httpx.AsyncClient, event_id: str) -> dict:
        r = await client.get(f"{ESPN}/summary", params={"event": event_id})
        r.raise_for_status()
        teams = (r.json().get("boxscore") or {}).get("teams") or []
        return {
            str(t["team"]["id"]): parse_plays(t.get("statistics") or [])
            for t in teams
        }

    def _store_path(self, season: int) -> Path:
        return self._data_dir / f"cfb_boxscores_{season}.json"

    def _load_store(self, season: int) -> dict:
        try:
            store = json.loads(self._store_path(season).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            store = {}
        store.setdefault("boxes", {})
        store.setdefault("scoreboards", {})
        return store

    def _save_store(self, season: int, store: dict) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        path = self._store_path(season)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(store))
        tmp.replace(path)


def _all_completed(scoreboard: dict) -> bool:
    events = scoreboard.get("events") or []
    return bool(events) and all(
        e["competitions"][0]["status"]["type"].get("completed") for e in events
    )


def _remember_team(teams: dict[str, dict], team: dict) -> None:
    tid = team.get("id")
    if tid is None or str(tid) in teams:
        return
    teams[str(tid)] = {
        "team_id": str(tid),
        "name": team.get("displayName") or team.get("location") or str(tid),
        "short_name": team.get("shortDisplayName"),
        "location": team.get("location"),
        "mascot": team.get("name"),
        "abbreviation": team.get("abbreviation"),
        "logo": team.get("logo"),
    }


def _game_box(event: dict, plays: dict | None) -> GameBox | None:
    """A completed game is usable only when both teams have a score and a
    box-score play count."""
    if not plays:
        return None
    sides = {c["homeAway"]: c for c in event["competitions"][0]["competitors"]}
    try:
        lines = {}
        for ha in ("home", "away"):
            c = sides[ha]
            tid = str(c["team"]["id"])
            p = plays.get(tid)
            if p is None or not p:
                return None
            lines[ha] = TeamGame(tid, int(c["score"]), int(p))
    except (KeyError, TypeError, ValueError):
        return None
    return GameBox(event["id"], lines["home"], lines["away"])


def _side(
    teams: dict, tid: str, rating, pred: dict | None, competitor: dict, status: dict,
) -> dict:
    t = teams.get(tid, {"team_id": tid, "name": tid})
    # ESPN reports "0" before kickoff — only a finished game has a real score.
    score = competitor.get("score") if status.get("completed") else None
    return {
        **t,
        "games": rating.games if rating else 0,
        "plays_per_game": rating.plays_per_game if rating else None,
        "off_ppp": rating.off_ppp if rating else None,
        "def_ppp": rating.def_ppp if rating else None,
        "off_estimate": pred["off_estimate"] if pred else None,
        "def_estimate": pred["def_estimate"] if pred else None,
        "predicted_points": pred["points"] if pred else None,
        "actual_points": int(score) if score not in (None, "") else None,
    }


def _main_point(game: dict, market_key: str, outcome_name: str) -> float | None:
    """The main line for one outcome: the point quoted by the most books
    (median as tie-break), from the main (non-alternate) market only."""
    for m in game.get("markets", []):
        if m.get("market_key") != market_key:
            continue
        counts: dict[float, int] = {}
        for out in m.get("outcomes", []):
            if out.get("outcome_name") != outcome_name:
                continue
            for p in out.get("prices") or []:
                pt = p.get("point")
                if pt is not None:
                    counts[float(pt)] = counts.get(float(pt), 0) + 1
        if not counts:
            return None
        top = max(counts.values())
        return statistics.median(pt for pt, n in counts.items() if n == top)
    return None
