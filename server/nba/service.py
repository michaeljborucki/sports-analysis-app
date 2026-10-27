"""NBA possession-efficiency projections: ESPN data loader + per-day slate.

Data comes from ESPN's public (keyless, unmetered) site API:

  * scoreboard per calendar month (`dates=YYYYMM`) — schedule, final
    scores, season type, team identity; and per day for the slate itself;
  * game summary per completed game — box-score FGA / FTA / offensive
    rebounds / turnovers for the possession estimate.

Ratings come from regular-season games only (no preseason, play-in or
playoffs). A team with fewer than MIN_CURRENT_GAMES games this season is
rated on LAST season's full regular season instead — so opening week runs
entirely on last year's numbers, and each team switches over on its own
once it has a real sample.

A completed game's box score never changes, so each is fetched once and
kept in `server/data/nba_boxscores_<season>.json` (gitignored), along with
fully-completed past months' scoreboards. The first build of a season pulls
~1,230 summaries; after that only new games are fetched.
"""
from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from ..systems.team_names import TeamIndex
from . import sgp
from .sgp import parse_player_lines
from .efficiency import (
    GameBox,
    TeamGame,
    TeamRating,
    build_ratings,
    parse_counts,
    possessions,
    predict_pace_matched,
    predict_points,
)


logger = logging.getLogger(__name__)

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
REFRESH_SECONDS = 300
SUMMARY_CONCURRENCY = 8
REGULAR_SEASON = 2
# Below this many games a team is rated on last season instead.
MIN_CURRENT_GAMES = 10
# A slate day's games tip at 16:00Z at the earliest; the previous night's
# late West Coast games tip by ~03:30Z. Anything that started before 10:00Z
# on the target day belongs to an earlier slate.
DAY_CUTOFF_HOUR_UTC = 10
# Odds feed vs ESPN tip-off disagreement tolerated when pairing a line.
MARKET_MATCH_SECONDS = 6 * 3600


def season_months(season: int) -> list[tuple[int, int]]:
    """(year, month) pairs an NBA season can span: October through June."""
    return [(season - 1, m) for m in (10, 11, 12)] + [(season, m) for m in range(1, 7)]


class NbaPredictionService:
    def __init__(self, snapshot_service=None, data_dir: Path = DATA_DIR) -> None:
        self._snapshot_service = snapshot_service
        self._data_dir = data_dir
        self._lock = asyncio.Lock()
        self._memo: dict[str | None, tuple[float, dict]] = {}
        # season -> store, loaded once. The store files are only ever
        # written by this service, so memory is the source of truth.
        self._stores: dict[int, dict] = {}
        self._sgp_memo: dict[str | None, tuple[float, dict]] = {}

    async def get(self, day: date | None = None) -> dict:
        key = day.isoformat() if day else None
        hit = self._memo.get(key)
        if hit and time.monotonic() - hit[0] < REFRESH_SECONDS:
            return await self._with_market(hit[1])
        async with self._lock:
            hit = self._memo.get(key)
            if not hit or time.monotonic() - hit[0] >= REFRESH_SECONDS:
                payload = await self._build(day)
                self._memo[key] = (time.monotonic(), payload)
                hit = self._memo[key]
        return await self._with_market(hit[1])

    async def get_sgp(self, day: date | None = None) -> dict:
        key = day.isoformat() if day else None
        hit = self._sgp_memo.get(key)
        if hit and time.monotonic() - hit[0] < REFRESH_SECONDS:
            return hit[1]
        async with self._lock:
            hit = self._sgp_memo.get(key)
            if not hit or time.monotonic() - hit[0] >= REFRESH_SECONDS:
                self._sgp_memo[key] = (time.monotonic(), await self._build_sgp(day))
                hit = self._sgp_memo[key]
        return hit[1]

    # ───────────────────────── SGP screener ─────────────────────────

    async def _build_sgp(self, day: date | None) -> dict:
        """The three-step screen (server/nba/sgp.py) for every rostered player
        on the slate. Every evaluated player is returned with per-criterion
        flags — the UI filters, nothing is dropped here."""
        ctx = await self._load(day)
        board, season = ctx["board"], ctx["season"]
        cur_store, prior_store = await self._store(season), await self._store(season - 1)
        cur_games = sgp.player_games(ctx["current"], cur_store["players"])
        prior_games = sgp.player_games(ctx["prior"], prior_store["players"])
        cur_tot = sgp.team_used(cur_store["boxes"], cur_games)
        prior_tot = sgp.team_used(prior_store["boxes"], prior_games)

        by_player_cur: dict[str, list] = {}
        by_player_prior: dict[str, list] = {}
        for g in cur_games:
            by_player_cur.setdefault(g.athlete_id, []).append(g)
        for g in prior_games:
            by_player_prior.setdefault(g.athlete_id, []).append(g)

        # Positional defense: this season once a team has MIN_CURRENT_GAMES.
        cur_counts: dict[str, int] = {}
        for b in ctx["current_boxes"]:
            for tid in (b.home.team_id, b.away.team_id):
                cur_counts[tid] = cur_counts.get(tid, 0) + 1
        cur_dvp, prior_dvp = sgp.dvp(cur_games), sgp.dvp(prior_games)
        cur_ranks, prior_ranks = sgp.dvp_ranks(cur_dvp), sgp.dvp_ranks(prior_dvp)

        def defense(tid: str) -> tuple[dict | None, dict | None, str]:
            if cur_counts.get(tid, 0) >= MIN_CURRENT_GAMES and tid in cur_ranks:
                return cur_dvp[tid], cur_ranks[tid], "current"
            if tid in prior_ranks:
                return prior_dvp[tid], prior_ranks[tid], "last_season"
            return None, None, "current"

        teams: dict[str, dict] = {}
        for ev in (*ctx["prior_events"], *ctx["current_events"], *board.get("events", [])):
            for c in ev["competitions"][0]["competitors"]:
                _remember_team(teams, c.get("team") or {})

        slate_events = []
        for ev in board.get("events", []):
            sides = {c["homeAway"]: c for c in ev["competitions"][0]["competitors"]}
            if "home" in sides and "away" in sides:
                slate_events.append((ev, str(sides["home"]["team"]["id"]),
                                     str(sides["away"]["team"]["id"])))

        # Finished games: the players who actually played (today's roster
        # would be wrong after trades) and their real lines, so the screen
        # can be checked. Upcoming games: ESPN's current roster + injuries.
        finished = [ev for ev, _, _ in slate_events
                    if ev["competitions"][0]["status"]["type"].get("completed")]
        if finished:
            await self._boxes(season, finished)
        played: dict[tuple[str, str], dict[str, list]] = {}
        for ev in finished:
            for tid, rows in (cur_store["players"].get(ev["id"]) or {}).items():
                played[(ev["id"], tid)] = {r[0]: r for r in rows}

        rosters: dict[str, list[dict]] = {}
        upcoming_teams = {t for ev, h, a in slate_events
                          if not ev["competitions"][0]["status"]["type"].get("completed")
                          for t in (h, a)}
        async with httpx.AsyncClient(timeout=20.0) as client:
            async def roster(tid: str) -> None:
                try:
                    data = await self._get(client, f"teams/{tid}/roster", {})
                    rosters[tid] = data.get("athletes") or []
                except Exception as exc:
                    logger.warning("nba roster %s failed: %s", tid, exc)
                    rosters[tid] = []
            await asyncio.gather(*(roster(t) for t in upcoming_teams))

        games_out = []
        for ev, home_id, away_id in slate_events:
            players = []
            for tid, opp in ((away_id, home_id), (home_id, away_id)):
                opp_dvp, opp_rank, dvp_src = defense(opp)
                box = played.get((ev["id"], tid))
                athletes = rosters.get(tid, []) if box is None else [
                    {"id": r[0], "displayName": r[1], "position": {"abbreviation": r[2]}}
                    for r in box.values()
                ]
                for ath in athletes:
                    aid = str(ath.get("id"))
                    cur = by_player_cur.get(aid, [])
                    if len(cur) >= sgp.MIN_SAMPLE:
                        sample, src, totals = cur, "current", cur_tot
                    elif by_player_prior.get(aid):
                        sample, src, totals = by_player_prior[aid], "last_season", prior_tot
                    elif cur:
                        sample, src, totals = cur, "current", cur_tot
                    else:
                        continue  # no NBA box score in either season
                    pos = (ath.get("position") or {}).get("abbreviation")
                    pos = pos if pos in sgp.POSITION_GROUPS else sgp.position_group(pos)
                    usage = sgp.usage_pct(sample, totals)
                    rank = opp_rank.get(pos) if opp_rank else None
                    ev_res = sgp.evaluate_player(sample)
                    injuries = ath.get("injuries") or []
                    # A hit rate needs a real sample: 1-for-1 is not "100%".
                    legs_ok = (len(sample) >= sgp.MIN_SAMPLE
                               and all(v is not None for v in ev_res["legs"].values()))
                    line = box.get(aid) if box is not None else None
                    actual = (
                        {"points": line[7], "rebounds": line[8], "assists": line[9]}
                        if line else None
                    )
                    players.append({
                        "athlete_id": aid,
                        "name": ath.get("displayName") or sample[-1].name,
                        "headshot": (ath.get("headshot") or {}).get("href")
                        or f"https://a.espncdn.com/i/headshots/nba/players/full/{aid}.png",
                        "team_id": tid,
                        "opp_id": opp,
                        "position": pos,
                        "injury": injuries[0].get("status") if injuries else None,
                        "source": src,
                        "games": len(sample),
                        "current_games": len(cur),
                        "minutes": sum(g.minutes for g in sample) / len(sample),
                        "usage": usage,
                        "opp_dvp": opp_dvp.get(pos) if opp_dvp else None,
                        "opp_dvp_rank": rank,
                        "opp_dvp_source": dvp_src,
                        "pass_usage": usage is not None and usage >= sgp.USAGE_MIN,
                        "pass_matchup": rank is not None and rank <= sgp.DVP_BOTTOM,
                        "pass_legs": legs_ok,
                        "actual": actual,
                        "parlay_hit": (
                            all(actual[s] >= ev_res["legs"][s]["line"] for s in sgp.LADDERS)
                            if actual and legs_ok else None
                        ),
                        **ev_res,
                    })
            players.sort(key=lambda p: -(p["usage"] or 0))
            games_out.append({
                "event_id": ev["id"],
                "commence_time": ev["date"],
                "completed": bool(ev["competitions"][0]["status"]["type"].get("completed")),
                "home": teams.get(home_id, {"team_id": home_id, "name": home_id}),
                "away": teams.get(away_id, {"team_id": away_id, "name": away_id}),
                "players": players,
            })
        games_out.sort(key=lambda g: g["commence_time"])
        return {
            "season": season,
            "date": ctx["slate_day"].isoformat(),
            "today": _today_et().isoformat(),
            "criteria": {
                "usage_min": sgp.USAGE_MIN,
                "dvp_bottom": sgp.DVP_BOTTOM,
                "hit_min": sgp.HIT_MIN,
                "min_sample": sgp.MIN_SAMPLE,
                "fantasy_scoring": "FanDuel: PTS + 1.2 REB + 1.5 AST + 3 STL + 3 BLK − TOV",
                "ladders": {k: list(v) for k, v in sgp.LADDERS.items()},
            },
            "built_at": datetime.now(timezone.utc).isoformat(),
            "games": games_out,
        }

    # ───────────────────────── build ─────────────────────────

    async def _load(self, day: date | None) -> dict:
        """The slate board plus every usable game feeding it: this season's
        before the slate day, and all of last season's. Box scores (team +
        player lines) are fetched for any game not yet in the store."""
        # No date = today (US Eastern). ESPN's undated scoreboard keeps serving
        # yesterday until its own late-morning rollover, which pinned the page
        # (and the "today" stepper link) to the previous day.
        slate_day = day or _today_et()
        async with httpx.AsyncClient(timeout=20.0) as client:
            board = await self._get(client, "scoreboard",
                                    {"dates": slate_day.strftime("%Y%m%d")})
            season = _season_of(board, slate_day)
            cutoff = datetime(slate_day.year, slate_day.month, slate_day.day,
                              DAY_CUTOFF_HOUR_UTC, tzinfo=timezone.utc)

            current_events = await self._season_events(client, season, until=slate_day)
            prior_events = await self._season_events(client, season - 1, until=None)

        current = [ev for ev in current_events if _usable(ev) and _start(ev) < cutoff]
        prior = [ev for ev in prior_events if _usable(ev)]
        return {
            "board": board,
            "slate_day": slate_day,
            "season": season,
            "current_events": current_events,
            "prior_events": prior_events,
            "current": current,
            "prior": prior,
            "current_boxes": await self._boxes(season, current),
            "prior_boxes": await self._boxes(season - 1, prior),
        }

    async def _build(self, day: date | None) -> dict:
        ctx = await self._load(day)
        board, slate_day, season = ctx["board"], ctx["slate_day"], ctx["season"]
        current_events, prior_events = ctx["current_events"], ctx["prior_events"]
        current = ctx["current"]
        current_boxes, prior_boxes = ctx["current_boxes"], ctx["prior_boxes"]

        current_r = build_ratings(current_boxes)
        prior_r = build_ratings(prior_boxes)

        teams: dict[str, dict] = {}
        for ev in (*prior_events, *current_events, *board.get("events", [])):
            for c in ev["competitions"][0]["competitors"]:
                _remember_team(teams, c.get("team") or {})

        def rating_for(tid: str) -> tuple[TeamRating | None, str]:
            cur = current_r.get(tid)
            if cur and cur.games >= MIN_CURRENT_GAMES:
                return cur, "current"
            last = prior_r.get(tid)
            if last and last.games:
                return last, "last_season"
            return cur, "current"

        slate = []
        for ev in board.get("events", []):
            comp = ev["competitions"][0]
            sides = {c["homeAway"]: c for c in comp["competitors"]}
            if "home" not in sides or "away" not in sides:
                continue
            home_id, away_id = str(sides["home"]["team"]["id"]), str(sides["away"]["team"]["id"])
            (home_r, home_src), (away_r, away_src) = rating_for(home_id), rating_for(away_id)
            both = home_r is not None and away_r is not None
            home_p = predict_points(home_r, away_r) if both else None
            away_p = predict_points(away_r, home_r) if both else None
            home_m = predict_pace_matched(home_r, away_r) if both else None
            away_m = predict_pace_matched(away_r, home_r) if both else None
            status = comp["status"]["type"]
            slate.append({
                "event_id": ev["id"],
                "commence_time": ev["date"],
                "neutral_site": bool(comp.get("neutralSite")),
                "season_type": int((ev.get("season") or {}).get("type") or REGULAR_SEASON),
                "completed": bool(status.get("completed")),
                "status_detail": status.get("shortDetail") or status.get("detail"),
                "home": _side(teams, home_id, home_r, home_src, home_p, home_m, sides["home"], status),
                "away": _side(teams, away_id, away_r, away_src, away_p, away_m, sides["away"], status),
                "predicted_total": (
                    home_p["points"] + away_p["points"] if home_p and away_p else None
                ),
                # Home-perspective spread, betting sign: -7 = home favored by 7.
                "predicted_spread_home": (
                    away_p["points"] - home_p["points"] if home_p and away_p else None
                ),
                "pace_matched_total": (
                    home_m + away_m if home_m is not None and away_m is not None else None
                ),
                "pace_matched_spread_home": (
                    away_m - home_m if home_m is not None and away_m is not None else None
                ),
            })
        slate.sort(key=lambda g: g["commence_time"])

        team_rows = []
        for tid in sorted(set(current_r) | set(prior_r)):
            r, src = rating_for(tid)
            if not r or not r.games or tid not in teams:
                continue
            cur = current_r.get(tid)
            team_rows.append({
                **teams[tid],
                "source": src,
                "current_games": cur.games if cur else 0,
                **_rating_fields(r),
                "points_for_per_game": r.points_for / r.games,
                "points_against_per_game": r.points_against / r.games,
            })
        team_rows.sort(key=lambda t: t["name"])

        return {
            "season": season,
            "date": slate_day.isoformat(),
            "today": _today_et().isoformat(),
            "min_current_games": MIN_CURRENT_GAMES,
            "games_used": len(current_boxes),
            "games_skipped": len(current) - len(current_boxes),
            "prior_games_used": len(prior_boxes),
            "built_at": datetime.now(timezone.utc).isoformat(),
            "games": slate,
            "teams": team_rows,
        }

    async def _season_events(
        self, client: httpx.AsyncClient, season: int, until: date | None,
    ) -> list[dict]:
        """Every event of `season` from its monthly scoreboards, through the
        month of `until` (None = the whole season). Fully-final past months
        are served from the store."""
        store = await self._store(season)
        today = _today_et()
        events: list[dict] = []
        changed = False
        for year, month in season_months(season):
            if until is not None and (year, month) > (until.year, until.month):
                break
            if (year, month) > (today.year, today.month):
                break
            key = f"{year:04d}{month:02d}"
            board = store["months"].get(key)
            if board is None:
                board = await self._get(client, "scoreboard", {"dates": key, "limit": 1000})
                board = {"events": [_slim(e) for e in board.get("events") or []]}
                if (year, month) < (today.year, today.month) and _all_final(board):
                    store["months"][key] = board
                    changed = True
            events.extend(board["events"])
        if changed:
            await asyncio.to_thread(self._save_store, season, store)
        return events

    async def _boxes(self, season: int, events: list[dict]) -> list[GameBox]:
        store = await self._store(season)
        missing = [
            ev["id"] for ev in events
            if ev["id"] not in store["boxes"] or ev["id"] not in store["players"]
        ]
        if missing:
            logger.info("nba: fetching %d box scores for %d", len(missing), season)
            sem = asyncio.Semaphore(SUMMARY_CONCURRENCY)
            async with httpx.AsyncClient(timeout=20.0) as client:
                async def fetch(eid: str) -> None:
                    async with sem:
                        try:
                            counts, players = await self._summary(client, eid)
                            store["boxes"][eid] = counts
                            store["players"][eid] = players
                        except Exception as exc:  # transient — retry next build
                            logger.warning("nba summary %s failed: %s", eid, exc)

                await asyncio.gather(*(fetch(eid) for eid in missing))
            await asyncio.to_thread(self._save_store, season, store)
        return [b for ev in events if (b := _game_box(ev, store["boxes"].get(ev["id"])))]

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
            odds_games = list(snapshot.non_prop_games_by_sport.get("nba", ()))
        except Exception:
            logger.exception("nba: odds snapshot unavailable")
            return payload

        index = TeamIndex()
        for g in games:
            for side in ("home", "away"):
                t = g[side]
                index.add(t["team_id"], t["team_id"], t["name"], t.get("location"),
                          t.get("short_name"), mascot=t.get("mascot"))
        # NBA teams meet 2-4 times a season, so a team pair alone would hang
        # the next meeting's line on a past game: the tip-off must agree too.
        by_pair: dict[tuple[str, str], list[dict]] = {}
        for og in odds_games:
            h, a = index.resolve(og["home_team"]), index.resolve(og["away_team"])
            if h and a:
                by_pair.setdefault((h, a), []).append(og)

        def find(home_id: str, away_id: str, tip: datetime) -> dict | None:
            for og in by_pair.get((home_id, away_id), ()):
                if abs((_as_dt(og.get("commence_time")) - tip).total_seconds()) <= MARKET_MATCH_SECONDS:
                    return og
            return None

        out = []
        for g in games:
            tip = _start({"date": g["commence_time"]})
            og = find(g["home"]["team_id"], g["away"]["team_id"], tip)
            flipped = False
            if og is None:
                og = find(g["away"]["team_id"], g["home"]["team_id"], tip)
                flipped = og is not None
            spread = total = None
            if og is not None:
                spread_team = og["away_team"] if flipped else og["home_team"]
                spread = _main_point(og, "spreads", spread_team)
                total = _main_point(og, "totals", "Over")
            out.append({**g, "market_spread_home": spread, "market_total": total})
        return {**payload, "games": out}

    # ───────────────────────── ESPN I/O ─────────────────────────

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict) -> dict:
        r = await client.get(f"{ESPN}/{path}", params=params)
        r.raise_for_status()
        return r.json()

    async def _summary(self, client: httpx.AsyncClient, event_id: str) -> tuple[dict, dict]:
        """(team possession counts, player lines) from one game summary."""
        data = await self._get(client, "summary", {"event": event_id})
        box = data.get("boxscore") or {}
        counts = {
            str(t["team"]["id"]): parse_counts(t.get("statistics") or [])
            for t in box.get("teams") or []
        }
        players = {
            str(t["team"]["id"]): parse_player_lines(t)
            for t in box.get("players") or []
        }
        return counts, players

    def _store_path(self, season: int) -> Path:
        return self._data_dir / f"nba_boxscores_{season}.json"

    async def _store(self, season: int) -> dict:
        if season not in self._stores:
            self._stores[season] = await asyncio.to_thread(self._load_store, season)
        return self._stores[season]

    def _load_store(self, season: int) -> dict:
        try:
            store = json.loads(self._store_path(season).read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            store = {}
        store.setdefault("boxes", {})
        store.setdefault("months", {})
        store.setdefault("players", {})
        # Files written before events were slimmed carried ESPN's full
        # payload (~20 MB a season); slim on load, persisted on next save.
        for board in store["months"].values():
            board["events"] = [_slim(e) for e in board.get("events") or []]
        return store

    def _save_store(self, season: int, store: dict) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        path = self._store_path(season)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(store))
        tmp.replace(path)


def _slim(ev: dict) -> dict:
    """Only the event fields the model and the slate read."""
    comp = ev["competitions"][0]
    status = (comp.get("status") or {}).get("type") or {}
    return {
        "id": ev["id"],
        "date": ev["date"],
        "season": {"type": (ev.get("season") or {}).get("type"),
                   "year": (ev.get("season") or {}).get("year")},
        "competitions": [{
            "type": {"abbreviation": (comp.get("type") or {}).get("abbreviation")},
            "neutralSite": comp.get("neutralSite"),
            "status": {"type": {"completed": status.get("completed"), "name": status.get("name")}},
            "competitors": [
                {
                    "homeAway": c.get("homeAway"),
                    "score": c.get("score"),
                    "team": {k: (c.get("team") or {}).get(k) for k in (
                        "id", "displayName", "shortDisplayName", "location", "name",
                        "abbreviation", "logo",
                    )},
                }
                for c in comp.get("competitors") or []
            ],
        }],
    }


def _today_et() -> date:
    # ESPN files NBA days on US Eastern; a fixed UTC−5 is close enough to
    # decide which months can still change.
    return (datetime.now(timezone.utc) - timedelta(hours=5)).date()


def _season_of(board: dict, slate_day: date) -> int:
    for ev in board.get("events") or []:
        year = (ev.get("season") or {}).get("year")
        if year:
            return int(year)
    year = (board.get("season") or {}).get("year")
    if year:
        return int(year)
    return slate_day.year + 1 if slate_day.month >= 8 else slate_day.year


def _start(ev: dict) -> datetime:
    return datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))


def _as_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _usable(ev: dict) -> bool:
    """Completed regular-season game. ESPN files the All-Star round robin
    under the regular season too (competition type ALLSTAR) — those teams
    aren't franchises and would leak into the ratings."""
    comp = ev["competitions"][0]
    return (
        int((ev.get("season") or {}).get("type") or 0) == REGULAR_SEASON
        and (comp.get("type") or {}).get("abbreviation") != "ALLSTAR"
        and bool(comp["status"]["type"].get("completed"))
    )


def _all_final(board: dict) -> bool:
    events = board.get("events") or []
    return bool(events) and all(
        e["competitions"][0]["status"]["type"].get("completed")
        or e["competitions"][0]["status"]["type"].get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED")
        for e in events
    )


def _remember_team(teams: dict[str, dict], team: dict) -> None:
    tid = team.get("id")
    if tid is None:
        return
    # Later seasons overwrite earlier ones, so names/logos are current.
    teams[str(tid)] = {
        "team_id": str(tid),
        "name": team.get("displayName") or team.get("location") or str(tid),
        "short_name": team.get("shortDisplayName"),
        "location": team.get("location"),
        "mascot": team.get("name"),
        "abbreviation": team.get("abbreviation"),
        "logo": team.get("logo"),
    }


def _game_box(event: dict, counts: dict | None) -> GameBox | None:
    """A completed game is usable only when both teams have a score and a
    full box-score possession count."""
    if not counts:
        return None
    sides = {c["homeAway"]: c for c in event["competitions"][0]["competitors"]}
    try:
        lines = {}
        for ha in ("home", "away"):
            c = sides[ha]
            tid = str(c["team"]["id"])
            cnt = counts.get(tid)
            if not cnt:
                return None
            poss = possessions(cnt)
            if poss <= 0:
                return None
            lines[ha] = TeamGame(tid, int(c["score"]), poss)
    except (KeyError, TypeError, ValueError):
        return None
    return GameBox(event["id"], lines["home"], lines["away"])


def _rating_fields(r: TeamRating | None) -> dict:
    return {
        "games": r.games if r else 0,
        "pace": r.pace if r else None,
        "off_eff": r.off_eff if r else None,
        "def_eff": r.def_eff if r else None,
    }


def _side(
    teams: dict, tid: str, rating, source: str, pred: dict | None,
    pace_matched: float | None, competitor: dict, status: dict,
) -> dict:
    t = teams.get(tid, {"team_id": tid, "name": tid})
    # ESPN reports "0" before tip — only a finished game has a real score.
    score = competitor.get("score") if status.get("completed") else None
    return {
        **t,
        "source": source,
        **_rating_fields(rating),
        "off_estimate": pred["off_estimate"] if pred else None,
        "def_estimate": pred["def_estimate"] if pred else None,
        "predicted_points": pred["points"] if pred else None,
        "pace_matched_points": pace_matched,
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
