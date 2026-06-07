"""Match context: rest-days, fixture congestion, motivation, derby flags.

Replaces the legacy stub. Uses the same ESPN team-schedule endpoint
`scrapers.team_stats` hits, so no new network dependency.

Outputs (all best-effort — missing fields default to safe neutral values):
  - home_rest_days / away_rest_days  (int | None)
  - home_matches_last_10 / away_matches_last_10
  - home_congested / away_congested  (bool)
  - home_motivation / away_motivation  (short string)
  - fixture_congestion  (human-readable summary)
  - dead_rubber  (bool)
  - derby  (bool)
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

import requests

logger = logging.getLogger("mirofish.scrapers.context")

LEAGUE_SLUGS = {
    "MLS": "usa.1",
    "Eredivisie": "ned.1",
    "Serie A": "ita.1",
    "EPL": "eng.1",
    "Bundesliga": "ger.1",
    "La Liga": "esp.1",
    "Ligue 1": "fra.1",
}

# Continental / cup competitions that imply squad rotation within 72h.
ROTATION_COMPETITIONS = {
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Conference League", "Copa Libertadores", "CONCACAF Champions Cup",
    "CONCACAF Champions League", "FA Cup", "EFL Cup", "Coppa Italia",
    "KNVB Cup", "DFB Pokal", "US Open Cup",
}

# Well-known derbies (paired set; order-independent).
DERBIES = {
    # EPL
    frozenset({"Manchester City", "Manchester United"}),
    frozenset({"Liverpool", "Everton"}),
    frozenset({"Arsenal", "Tottenham Hotspur"}),
    frozenset({"Chelsea", "Arsenal"}),
    # Serie A
    frozenset({"AC Milan", "Internazionale"}),
    frozenset({"Juventus", "Torino"}),
    frozenset({"AS Roma", "Lazio"}),
    # Eredivisie
    frozenset({"Ajax Amsterdam", "Feyenoord Rotterdam"}),
    frozenset({"PSV Eindhoven", "Ajax Amsterdam"}),
    # MLS
    frozenset({"LA Galaxy", "LAFC"}),
    frozenset({"New York City FC", "Red Bull New York"}),
    frozenset({"Seattle Sounders FC", "Portland Timbers"}),
}


def _fetch_schedule(team_id: str, slug: str) -> list[dict]:
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams/{team_id}/schedule"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json().get("events", [])
    except Exception as e:
        logger.debug("context: schedule fetch failed for team_id=%s: %s", team_id, e)
        return []


def _team_id(team_name: str, slug: str) -> str | None:
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    for grp in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        t = grp.get("team", {})
        if t.get("displayName") == team_name:
            return t.get("id")
    return None


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _team_congestion(team_name: str, slug: str, now: datetime) -> dict:
    """Compute rest-days + fixture-congestion flags for one team."""
    tid = _team_id(team_name, slug)
    if not tid:
        return {}
    events = _fetch_schedule(tid, slug)
    if not events:
        return {}

    last_complete: datetime | None = None
    matches_last_10 = 0
    upcoming_rotation = False

    for ev in events:
        comp = (ev.get("competitions") or [{}])[0]
        status = comp.get("status", {}).get("type", {}).get("name", "")
        when = _parse_iso(ev.get("date", ""))
        if not when:
            continue
        comp_name = (ev.get("season", {}).get("type", {}).get("name", "")
                     or ev.get("leagues", [{}])[0].get("name", "")
                     or comp.get("note", ""))

        if status in ("STATUS_FINAL", "STATUS_FULL_TIME") and when <= now:
            if last_complete is None or when > last_complete:
                last_complete = when
            if (now - when).days <= 10:
                matches_last_10 += 1
        elif when > now and (when - now).total_seconds() <= 72 * 3600:
            if any(c in comp_name for c in ROTATION_COMPETITIONS):
                upcoming_rotation = True

    rest_days = (now - last_complete).days if last_complete else None
    congested = (
        (rest_days is not None and rest_days < 4)
        or matches_last_10 >= 3
        or upcoming_rotation
    )
    return {
        "rest_days": rest_days,
        "matches_last_10": matches_last_10,
        "upcoming_rotation": upcoming_rotation,
        "congested": congested,
    }


def _motivation_from_standings(team_name: str, league: str) -> str:
    """Classify stakes from league position. Defaults to 'mid-table' on failure."""
    from scrapers.team_stats import _load_standings, _find_stat

    entries = _load_standings(league)
    if not entries:
        return "Standard league match"

    total_teams = len(entries)
    for entry in entries:
        td = entry.get("team", {})
        if td.get("displayName") != team_name:
            continue
        stats = entry.get("stats", [])
        rank = int(_find_stat(stats, "rank", 0) or 0)
        gp = int(_find_stat(stats, "gamesPlayed", 0) or 0)
        if not rank:
            break

        if rank <= 4:
            return f"Top-4 race ({rank}{_ord(rank)})"
        if rank <= 7 and league != "MLS":
            return f"European spot chase ({rank}{_ord(rank)})"
        if rank >= total_teams - 2 and league != "MLS":
            return f"Relegation battle ({rank}{_ord(rank)} of {total_teams})"
        if league == "MLS" and rank <= 9:
            return f"Playoff race ({rank}{_ord(rank)} conf)"
        return f"Mid-table ({rank}{_ord(rank)})"

    return "Standard league match"


def _ord(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def get_match_context(home_team: str, away_team: str, league: str = "MLS") -> dict:
    slug = LEAGUE_SLUGS.get(league, "usa.1")
    now = datetime.now(timezone.utc)

    home_cong = _team_congestion(home_team, slug, now)
    away_cong = _team_congestion(away_team, slug, now)

    home_motiv = _motivation_from_standings(home_team, league)
    away_motiv = _motivation_from_standings(away_team, league)

    # Headline fixture-congestion string
    parts = []
    for label, c in (("Home", home_cong), ("Away", away_cong)):
        if not c:
            continue
        rd = c.get("rest_days")
        if c.get("upcoming_rotation"):
            parts.append(f"{label} has continental/cup fixture within 72h")
        elif rd is not None and rd < 4:
            parts.append(f"{label} on {rd}d rest")
        elif c.get("matches_last_10", 0) >= 3:
            parts.append(f"{label} played {c['matches_last_10']} in last 10d")
    fixture_summary = "; ".join(parts) if parts else "Normal schedule"

    pair = frozenset({home_team, away_team})
    is_derby = pair in DERBIES

    # Dead-rubber heuristic: both teams in "Mid-table" motivation AND late season.
    # Crude — flagged for refinement in roadmap.
    dead = (home_motiv.startswith("Mid-table") and away_motiv.startswith("Mid-table"))

    ctx = {
        "home_motivation": home_motiv,
        "away_motivation": away_motiv,
        "home_rest_days": home_cong.get("rest_days"),
        "away_rest_days": away_cong.get("rest_days"),
        "home_matches_last_10": home_cong.get("matches_last_10"),
        "away_matches_last_10": away_cong.get("matches_last_10"),
        "home_congested": bool(home_cong.get("congested")),
        "away_congested": bool(away_cong.get("congested")),
        "fixture_congestion": fixture_summary,
        "derby": is_derby,
        "dead_rubber": dead,
        "manager_notes": "",
    }
    logger.info(
        "context: %s vs %s | rest %s/%s | %s | derby=%s",
        home_team, away_team,
        ctx["home_rest_days"], ctx["away_rest_days"],
        fixture_summary, is_derby,
    )
    return ctx
