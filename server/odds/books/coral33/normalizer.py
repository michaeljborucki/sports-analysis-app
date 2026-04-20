from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from .mapping import PERIOD_SUFFIX


logger = logging.getLogger(__name__)


BOOK_KEY = "coral33"


try:
    from zoneinfo import ZoneInfo
    _CORAL_TZ = ZoneInfo("America/Denver")
except Exception:
    _CORAL_TZ = timezone(-__import__("datetime").timedelta(hours=6))  # MDT fallback


def _parse_coral_datetime(s: str) -> datetime:
    """coral33 datetimes are naive strings like '2026-04-19 19:00:01.000' in
    the server's local timezone (empirically America/Denver — MDT/MST).
    Parse as local time, convert to UTC for matching against Odds API
    commence_time."""
    if not s:
        raise ValueError("empty datetime")
    s = s.strip()
    if "." in s:
        s = s.split(".")[0]
    s = s.replace(" ", "T")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_CORAL_TZ)
    return dt.astimezone(timezone.utc)


_ALT_SUFFIXES = (" Alt Line", " Alternate Line", " Series")


def _clean_team(name: str) -> str:
    n = (name or "").strip()
    # Strip alt/series suffixes so event matching finds the underlying game.
    for suf in _ALT_SUFFIXES:
        if n.endswith(suf):
            n = n[: -len(suf)]
            break
    return n


def _int_or_none(v) -> int | None:
    """American-odds fields arrive as int. 0 means market not posted — return
    None so we skip emitting a row."""
    try:
        i = int(v)
    except (TypeError, ValueError):
        return None
    return i if i != 0 else None


def _float_or_none(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def normalize_league_lines(
    response: dict,
    period: str,
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[[str, str, str, datetime], str | None],
    is_alternate: bool = False,
) -> list[dict]:
    """Take a Get_LeagueLines2 response for a (sport, period) pull and produce
    cache rows. Events that don't match an existing Odds API event are dropped
    silently (with a log entry) so we never write orphan rows.

    match_event: callable(sport_key, home, away, commence) -> event_id | None.
    is_alternate: True when the call was made against an *_ALT_LINE subtype;
        emits `alternate_spreads` / `alternate_totals` / `alternate_team_totals`
        instead of the base market keys.
    """
    lines = response.get("Lines") or []
    suffix = PERIOD_SUFFIX.get(period)
    if suffix is None:
        logger.warning("coral33: unknown period %r — dropping %d lines", period, len(lines))
        return []
    market_prefix_spread = "alternate_spreads" if is_alternate else "spreads"
    market_prefix_total  = "alternate_totals"  if is_alternate else "totals"
    market_prefix_tt     = "alternate_team_totals" if is_alternate else "team_totals"
    # alt lines don't carry a meaningful h2h (their ML is usually absent or
    # noise); skip ML extraction in alt mode.
    include_ml = not is_alternate

    rows: list[dict] = []
    orphans = 0
    circled = 0
    for line in lines:
        if line.get("Status") != "O":
            circled += 1
            continue
        team1 = _clean_team(line.get("Team1ID", ""))
        team2 = _clean_team(line.get("Team2ID", ""))
        if not team1 or not team2:
            continue
        try:
            commence = _parse_coral_datetime(line.get("GameDateTime", ""))
        except ValueError:
            continue

        # coral33 Team1 = home, Team2 = away (their convention — confirmed from
        # sample data: "Portland Trail Blazers @ San Antonio Spurs" where Spurs
        # are in home position Team2). Adjust the call accordingly.
        # However, Odds API uses home_team/away_team explicitly — we match by
        # team set regardless of orientation, so pass Team1 as "away" and Team2
        # as "home" by convention.
        away = team1
        home = team2

        event_id = match_event(sport_key, home, away, commence)
        if event_id is None:
            orphans += 1
            continue

        base = {
            "event_id": event_id,
            "sport_key": sport_key,
            "home_team": home,
            "away_team": away,
            "commence_time": commence,
            "bookmaker_key": BOOK_KEY,
            "fetched_at": fetched_at,
        }

        if include_ml:
            rows.extend(_extract_moneyline(line, suffix, base, team1, team2))
        rows.extend(_extract_spread(line, suffix, base, team1, team2, market_prefix_spread))
        rows.extend(_extract_total(line, suffix, base, market_prefix_total))
        rows.extend(_extract_team_totals(line, suffix, base, team1, team2, market_prefix_tt))

    if orphans or circled:
        logger.info(
            "coral33 %s %s: %d rows, %d orphans, %d circled (from %d lines)",
            sport_key, period, len(rows), orphans, circled, len(lines),
        )
    return rows


def _extract_moneyline(
    line: dict, suffix: str, base: dict, team1: str, team2: str
) -> list[dict]:
    ml1 = _int_or_none(line.get("MoneyLine1"))
    ml2 = _int_or_none(line.get("MoneyLine2"))
    ml_draw = _int_or_none(line.get("MoneyLineDraw"))
    out: list[dict] = []
    if ml1 is not None and ml2 is not None and ml_draw is not None:
        mk = f"h2h_3_way{suffix}"
        # 3-way order: team1, draw, team2 (soccer/tennis edge case — most of
        # our sports won't hit this branch).
        out.append({**base, "market_key": mk, "outcome_name": team1, "outcome_point": None, "price_american": ml1})
        out.append({**base, "market_key": mk, "outcome_name": "Draw", "outcome_point": None, "price_american": ml_draw})
        out.append({**base, "market_key": mk, "outcome_name": team2, "outcome_point": None, "price_american": ml2})
    elif ml1 is not None and ml2 is not None:
        mk = f"h2h{suffix}"
        out.append({**base, "market_key": mk, "outcome_name": team1, "outcome_point": None, "price_american": ml1})
        out.append({**base, "market_key": mk, "outcome_name": team2, "outcome_point": None, "price_american": ml2})
    return out


def _extract_spread(
    line: dict, suffix: str, base: dict, team1: str, team2: str, market_prefix: str
) -> list[dict]:
    spread = _float_or_none(line.get("Spread"))
    adj1 = _int_or_none(line.get("SpreadAdj1"))
    adj2 = _int_or_none(line.get("SpreadAdj2"))
    if spread is None or adj1 is None or adj2 is None:
        return []
    fav_id = _clean_team(line.get("FavoredTeamID", ""))
    if fav_id and fav_id == team1:
        pt1, pt2 = spread, -spread
    elif fav_id and fav_id == team2:
        pt1, pt2 = -spread, spread
    else:
        pt1, pt2 = spread, -spread
    mk = f"{market_prefix}{suffix}"
    return [
        {**base, "market_key": mk, "outcome_name": team1, "outcome_point": pt1, "price_american": adj1},
        {**base, "market_key": mk, "outcome_name": team2, "outcome_point": pt2, "price_american": adj2},
    ]


def _extract_total(line: dict, suffix: str, base: dict, market_prefix: str) -> list[dict]:
    pt = _float_or_none(line.get("TotalPoints"))
    over = _int_or_none(line.get("TtlPtsAdj1"))
    under = _int_or_none(line.get("TtlPtsAdj2"))
    if pt is None or over is None or under is None:
        return []
    mk = f"{market_prefix}{suffix}"
    return [
        {**base, "market_key": mk, "outcome_name": "Over",  "outcome_point": pt, "price_american": over},
        {**base, "market_key": mk, "outcome_name": "Under", "outcome_point": pt, "price_american": under},
    ]


def _extract_team_totals(
    line: dict, suffix: str, base: dict, team1: str, team2: str, market_prefix: str
) -> list[dict]:
    out: list[dict] = []
    for idx, team in ((1, team1), (2, team2)):
        pt = _float_or_none(line.get(f"Team{idx}TotalPoints"))
        over = _int_or_none(line.get(f"Team{idx}TtlPtsAdj1"))
        under = _int_or_none(line.get(f"Team{idx}TtlPtsAdj2"))
        if pt is None or over is None or under is None:
            continue
        mk = f"{market_prefix}{suffix}"
        out.append({**base, "market_key": mk, "outcome_name": f"{team} Over",  "outcome_point": pt, "price_american": over})
        out.append({**base, "market_key": mk, "outcome_name": f"{team} Under", "outcome_point": pt, "price_american": under})
    return out
