from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from .mapping import PERIOD_SUFFIX, PROP_STAT_TO_MARKET_KEY


logger = logging.getLogger(__name__)


BOOK_KEY = "coral33"


try:
    from zoneinfo import ZoneInfo
    _CORAL_TZ = ZoneInfo("America/Denver")
except Exception:
    _CORAL_TZ = timezone(-__import__("datetime").timedelta(hours=6))  # MDT fallback


def _parse_coral_datetime(s: str) -> datetime:
    """coral33 datetimes are naive strings like '2026-05-03 12:20:01.000' in
    the server's local timezone (America/Denver — MDT/MST). Confirmed
    2026-05-03 by paired-game probe across MLB/NBA/NHL/soccer: every sport
    showed a consistent +6h delta between the naive emission and Odds API
    UTC, ruling out the brief 2026-05-03 ET-experiment hypothesis. Parse
    as Denver-local, convert to UTC for matching."""
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


# coral33's alt-line subtypes tag team names with one of these suffixes —
# e.g. MLB's "MLB ALT LINE" endpoint returns Team1ID = "White Sox Alt RL"
# (Alt RunLine). Strip before event matching so the team falls back to the
# short-form name the alias table knows about.
_ALT_SUFFIXES = (
    " Alt Line",
    " Alternate Line",
    " Alt RL",           # MLB run-line alts
    " Alt Run Line",     # defensive — seen in some older coral captures
    " Series",
    " Games",            # tennis — same player, but games-level markets
                         # (set-level markets live on the bare-name line)
)


def _is_tennis_games_line(raw_team_name: str) -> bool:
    """coral33 tennis returns two lines per match: a bare-name line carrying
    set-level totals + moneyline, and a " Games"-suffixed line carrying the
    game-level spread + total. We branch market emission on this flag."""
    return (raw_team_name or "").rstrip().endswith(" Games")


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
    match_event: Callable[[str, str, str, datetime], dict | None],
    is_alternate: bool = False,
) -> list[dict]:
    """Take a Get_LeagueLines2 response for a (sport, period) pull and produce
    cache rows. Events that don't match an existing Odds API event are dropped
    silently (with a log entry) so we never write orphan rows.

    match_event: callable(sport_key, home, away, commence) -> dict or None.
        The dict returns {event_id, home_team, away_team} with the canonical
        Odds API team names. We store those (not the short coral33 names) so
        outcome buckets merge across books when the matrix assembles rows.
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

    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
    rows: list[dict] = []
    orphans = 0
    circled = 0
    live = 0
    for line in lines:
        if line.get("Status") != "O":
            circled += 1
            continue
        raw_t1 = line.get("Team1ID", "")
        raw_t2 = line.get("Team2ID", "")
        # Tennis: coral33 emits two lines per match ("J Sinner" for set-level
        # markets + ML, "J Sinner Games" for game-level spread + total). Detect
        # the suffix on the raw team string before _clean_team strips it.
        is_games_line = sport_key == "tennis" and (
            _is_tennis_games_line(raw_t1) or _is_tennis_games_line(raw_t2)
        )
        team1 = _clean_team(raw_t1)
        team2 = _clean_team(raw_t2)
        if not team1 or not team2:
            continue
        try:
            commence = _parse_coral_datetime(line.get("GameDateTime", ""))
        except ValueError:
            continue
        # Skip live / in-progress games — coral33's in-play prices move in ways
        # the sharp-book devig model doesn't trust, so users explicitly don't
        # want them polluting EV / arb output.
        if commence <= now:
            live += 1
            continue

        # coral33 Team1 = home, Team2 = away (their convention — confirmed from
        # sample data: "Portland Trail Blazers @ San Antonio Spurs" where Spurs
        # are in home position Team2). Adjust the call accordingly.
        # However, Odds API uses home_team/away_team explicitly — we match by
        # team set regardless of orientation, so pass Team1 as "away" and Team2
        # as "home" by convention.
        coral_away = team1
        coral_home = team2

        matched = match_event(sport_key, coral_home, coral_away, commence)
        if matched is None:
            orphans += 1
            continue
        event_id = matched["event_id"]
        # Use Odds API canonical team names for STORAGE so coral33 and Odds
        # API share outcome buckets. Fall back to coral names if the matcher
        # didn't provide canonicals (shouldn't happen but defensive).
        home = matched.get("home_team") or coral_home
        away = matched.get("away_team") or coral_away
        # Extractors use team1/team2 as outcome-name literals — remap them to
        # canonicals so emitted outcome_name strings match what Odds API emits.
        team1_canon = away   # coral Team1 was away
        team2_canon = home   # coral Team2 was home

        base = {
            "event_id": event_id,
            "sport_key": sport_key,
            "home_team": home,
            "away_team": away,
            "commence_time": commence,
            "bookmaker_key": BOOK_KEY,
            "fetched_at": fetched_at,
        }

        if sport_key == "tennis":
            # Tennis market emission diverges from team-sport emission:
            #   bare-name line  → moneyline only (set-level totals have no
            #                     counterpart in Odds API and would create
            #                     orphan markets nothing else compares to).
            #   " Games" line   → game-level spreads + totals (these DO map to
            #                     Odds API's `spreads` / `totals` tennis keys).
            # Team totals aren't a thing in tennis, skip them entirely.
            if is_games_line:
                rows.extend(_extract_spread(line, suffix, base, team1_canon, team2_canon, market_prefix_spread, team1, team2))
                rows.extend(_extract_total(line, suffix, base, market_prefix_total))
            else:
                if include_ml:
                    rows.extend(_extract_moneyline(line, suffix, base, team1_canon, team2_canon))
        else:
            if include_ml:
                rows.extend(_extract_moneyline(line, suffix, base, team1_canon, team2_canon))
            rows.extend(_extract_spread(line, suffix, base, team1_canon, team2_canon, market_prefix_spread, team1, team2))
            rows.extend(_extract_total(line, suffix, base, market_prefix_total))
            rows.extend(_extract_team_totals(line, suffix, base, team1_canon, team2_canon, market_prefix_tt))

    if orphans or circled or live:
        logger.info(
            "coral33 %s %s: %d rows, %d orphans, %d circled, %d live (from %d lines)",
            sport_key, period, len(rows), orphans, circled, live, len(lines),
        )
    return rows


def normalize_player_props(
    response: dict,
    sport_key: str,
    fetched_at: datetime,
    game_num_lookup: Callable[[object], dict | None],
) -> list[dict]:
    """Decode a Get_LeagueLines2 response from a PLAYERPRO subtype (one row per
    player-stat Over/Under) into cache rows.

    Prop rows don't carry home/away teams directly. They share a
    `CorrelationID` string (e.g. "503-g") with the parent game's main-tier
    row; `game_num_lookup(correlation_id)` returns a dict with `event_id`,
    `home_team`, `away_team`, `commence_time` for that parent, or None.
    Rows without a match are dropped as orphans.

    (Historical note: `GameNum` looked like the right key but coral33
    generates a *per-row* GameNum on prop endpoints, not a per-game one.)

    Outcome naming matches the rest of the pipeline: "<Player Name> Over" /
    "<Player Name> Under", matching what `_encode_outcome_name` produces for
    the Odds API pipeline. That way the EV scanner's per-player bucket
    logic pairs coral33 prices with sharp anchors cleanly.
    """
    stat_map = PROP_STAT_TO_MARKET_KEY.get(sport_key)
    if not stat_map:
        return []

    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
    lines = response.get("Lines") or []
    rows: list[dict] = []
    orphans = 0
    circled = 0
    live = 0
    unknown_stat = 0
    for line in lines:
        if line.get("Status") != "O":
            circled += 1
            continue
        player = _clean_team(line.get("Team1ID", ""))
        stat = (line.get("Team2ID") or "").strip()
        if not player or not stat:
            continue
        market_key = stat_map.get(stat)
        if market_key is None:
            unknown_stat += 1
            continue
        point = _float_or_none(line.get("TotalPoints"))
        over = _int_or_none(line.get("TtlPtsAdj1"))
        under = _int_or_none(line.get("TtlPtsAdj2"))
        if point is None or over is None or under is None:
            continue

        correlation_id = (line.get("CorrelationID") or "").strip()
        if not correlation_id:
            orphans += 1
            continue
        ref = game_num_lookup(correlation_id)
        if ref is None:
            orphans += 1
            continue
        commence = ref.get("commence_time")
        if isinstance(commence, str):
            commence = datetime.fromisoformat(commence.replace("Z", "+00:00"))
        if commence is not None and commence.tzinfo is None:
            commence = commence.replace(tzinfo=timezone.utc)
        if commence is not None and commence <= now:
            live += 1
            continue

        base = {
            "event_id": ref["event_id"],
            "sport_key": sport_key,
            "home_team": ref["home_team"],
            "away_team": ref["away_team"],
            "commence_time": commence,
            "bookmaker_key": BOOK_KEY,
            "fetched_at": fetched_at,
        }
        rows.append({**base, "market_key": market_key,
                     "outcome_name": f"{player} Over",
                     "outcome_point": point, "price_american": over})
        rows.append({**base, "market_key": market_key,
                     "outcome_name": f"{player} Under",
                     "outcome_point": point, "price_american": under})

    if orphans or circled or live or unknown_stat:
        logger.info(
            "coral33 %s props: %d rows, %d orphans, %d circled, %d live, "
            "%d unknown-stat (from %d lines)",
            sport_key, len(rows), orphans, circled, live, unknown_stat,
            len(lines),
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
        # Market-key selection for 3-way:
        #  - soccer → `h2h` (Odds API's soccer `h2h` IS 3-way — write there
        #    so rows merge across books).
        #  - other sports (e.g. hockey with MoneyLineDraw present) → use
        #    `h2h_3_way` so the 3-way feed stays distinct from the 2-way
        #    `h2h` feed (hockey's `h2h` includes OT → 2 outcomes).
        sport_key = base.get("sport_key")
        mk = f"h2h{suffix}" if sport_key == "soccer" else f"h2h_3_way{suffix}"
        out.append({**base, "market_key": mk, "outcome_name": team1, "outcome_point": None, "price_american": ml1})
        out.append({**base, "market_key": mk, "outcome_name": "Draw", "outcome_point": None, "price_american": ml_draw})
        out.append({**base, "market_key": mk, "outcome_name": team2, "outcome_point": None, "price_american": ml2})
    elif ml1 is not None and ml2 is not None:
        mk = f"h2h{suffix}"
        out.append({**base, "market_key": mk, "outcome_name": team1, "outcome_point": None, "price_american": ml1})
        out.append({**base, "market_key": mk, "outcome_name": team2, "outcome_point": None, "price_american": ml2})
    return out


def _extract_spread(
    line: dict, suffix: str, base: dict,
    team1: str, team2: str, market_prefix: str,
    coral_team1: str | None = None, coral_team2: str | None = None,
) -> list[dict]:
    """Extract the spread pair.

    team1/team2 are the *canonical* (Odds API) names used for storage.
    coral_team1/coral_team2 are the original *coral33* short names used
    to resolve `FavoredTeamID` (which coral33 emits in its own short form).
    If coral names aren't passed, falls back to team1/team2 — acceptable
    when no canonicalization has happened (callers that don't use the
    event matcher).
    """
    spread = _float_or_none(line.get("Spread"))
    adj1 = _int_or_none(line.get("SpreadAdj1"))
    adj2 = _int_or_none(line.get("SpreadAdj2"))
    if spread is None or adj1 is None or adj2 is None:
        return []
    fav_id = _clean_team(line.get("FavoredTeamID", ""))
    fav_t1 = coral_team1 if coral_team1 is not None else team1
    fav_t2 = coral_team2 if coral_team2 is not None else team2
    if fav_id and fav_id == fav_t1:
        pt1, pt2 = spread, -spread
    elif fav_id and fav_id == fav_t2:
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


# ─── Extras normalizer ──────────────────────────────────────────────
# Dispatches per-`kind` for subtypes configured under `[[sports.<x>.extras]]`
# in coral33.toml. Each kind has a dedicated line shape, team-name suffix,
# and market_key policy.
#
# Kinds currently supported:
#   reg_time             — NHL REG TIME — regulation-time spread + total
#   hre                  — MLB H-R-E    — hits+runs+errors game total
#   team_score_first     — MLB TEAMSCOR 1ST / NBA GPROPS (subset) —
#                           2-way ML, which team scores first
#   score_first_inning   — MLB SCORE IN 1ST — Yes/No, does either team
#                           score in the 1st inning
#   game_props           — NBA GPROPS (generic dispatcher inside the kind)

_EXTRA_SUFFIXES_BY_KIND: dict[str, tuple[str, ...]] = {
    "reg_time":         (" (Reg Time)",),
    "hre":              (" H+R+E",),
    "team_score_first": (" score first",),
    "game_props":       (" score first", " 10 pts first", " 15 pts first", " 20 pts first"),
}


def _strip_any_suffix(s: str, suffixes: tuple[str, ...]) -> tuple[str, str | None]:
    """Return (stripped_name, matched_suffix_or_None)."""
    for suf in suffixes:
        if s.endswith(suf):
            return s[: -len(suf)].strip(), suf
    return s.strip(), None


def _parse_score_first_inning_teams(team1_id: str) -> tuple[str, str] | None:
    """'Yes White Sox/Diamondbacks score 1st Inn' → ('White Sox','Diamondbacks').
    Returns None if the expected structure isn't found."""
    s = team1_id.strip()
    for prefix in ("Yes ", "No "):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    else:
        return None
    for suf in (" score 1st Inn", " score in 1st Inn", " scores 1st Inn"):
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    if "/" not in s:
        return None
    a, b = s.split("/", 1)
    a, b = a.strip(), b.strip()
    return (a, b) if a and b else None


def normalize_extras(
    response: dict,
    kind: str,
    sport_key: str,
    fetched_at: datetime,
    match_event: Callable[[str, str, str, datetime], dict | None],
) -> list[dict]:
    """Decode one extras-tier Get_LeagueLines2 response into cache rows."""
    lines = response.get("Lines") or []
    now = fetched_at if fetched_at.tzinfo else fetched_at.replace(tzinfo=timezone.utc)
    rows: list[dict] = []
    orphans = 0
    circled = 0
    live = 0
    unparsed = 0

    for line in lines:
        if line.get("Status") != "O":
            circled += 1
            continue
        raw_t1 = (line.get("Team1ID") or "").strip()
        raw_t2 = (line.get("Team2ID") or "").strip()
        if not raw_t1 or not raw_t2:
            continue
        try:
            commence = _parse_coral_datetime(line.get("GameDateTime", ""))
        except ValueError:
            continue
        if commence <= now:
            live += 1
            continue

        # Kind-specific team extraction + market emission.
        if kind == "score_first_inning":
            teams = _parse_score_first_inning_teams(raw_t1)
            if teams is None:
                unparsed += 1
                continue
            coral_home, coral_away = teams[1], teams[0]   # coral: away/home is team1/team2 convention
            matched = match_event(sport_key, coral_home, coral_away, commence)
            if matched is None:
                orphans += 1
                continue
            ml1 = _int_or_none(line.get("MoneyLine1"))
            ml2 = _int_or_none(line.get("MoneyLine2"))
            if ml1 is None or ml2 is None:
                continue
            home = matched.get("home_team") or coral_home
            away = matched.get("away_team") or coral_away
            base = _extra_base(matched["event_id"], sport_key, home, away, commence, fetched_at)
            # Emit as `nrfi` (the Odds API canonical key) rather than
            # `yes_no_score_first_inning` so coral33 prices pair with sharp
            # NRFI lines in the EV/arb scanner. Outcome names "Yes"/"No"
            # match Odds API convention.
            rows.append({**base, "market_key": "nrfi",
                         "outcome_name": "Yes", "outcome_point": 0.0,
                         "price_american": ml1})
            rows.append({**base, "market_key": "nrfi",
                         "outcome_name": "No",  "outcome_point": 0.0,
                         "price_american": ml2})
            continue

        # For everything else: strip a kind-appropriate suffix off both teams.
        suffixes = _EXTRA_SUFFIXES_BY_KIND.get(kind, ())
        t1, s1 = _strip_any_suffix(raw_t1, suffixes)
        t2, s2 = _strip_any_suffix(raw_t2, suffixes)
        if not t1 or not t2:
            unparsed += 1
            continue
        # coral convention: team1=away, team2=home. Keep the short-form names
        # separately from the canonical names — _extract_spread needs the
        # short forms to resolve FavoredTeamID (which coral33 emits unaliased).
        coral_t1, coral_t2 = t1, t2
        coral_away, coral_home = coral_t1, coral_t2
        matched = match_event(sport_key, coral_home, coral_away, commence)
        if matched is None:
            orphans += 1
            continue
        # Canonicalize against Odds API names so outcome buckets merge across
        # books. Extractors below that take positional team names use the
        # canonicalized home/away directly.
        home = matched.get("home_team") or coral_home
        away = matched.get("away_team") or coral_away
        event_id = matched["event_id"]
        base = _extra_base(event_id, sport_key, home, away, commence, fetched_at)
        # For _extract_spread/_extract_total, mirror the main-normalizer's
        # (team1_canon, team2_canon) convention: team1 = away, team2 = home.
        team1_canon, team2_canon = away, home

        if kind == "reg_time":
            # Regulation-time spread + total. Reuses the main spread/total
            # extractors — which consult FavoredTeamID via the short-form
            # coral team names — so sign mapping is correct even when coral's
            # Team1/Team2 orientation differs from Odds API's home/away.
            rows.extend(_extract_spread(
                line, "", base, team1_canon, team2_canon,
                "spreads_reg_time", coral_t1, coral_t2,
            ))
            rows.extend(_extract_total(line, "", base, "totals_reg_time"))
            continue

        if kind == "hre":
            tp = _float_or_none(line.get("TotalPoints"))
            ta1 = _int_or_none(line.get("TtlPtsAdj1"))
            ta2 = _int_or_none(line.get("TtlPtsAdj2"))
            if tp is None or ta1 is None or ta2 is None:
                continue
            rows.append({**base, "market_key": "totals_hits_runs_errors",
                         "outcome_name": "Over", "outcome_point": tp,
                         "price_american": ta1})
            rows.append({**base, "market_key": "totals_hits_runs_errors",
                         "outcome_name": "Under", "outcome_point": tp,
                         "price_american": ta2})
            continue

        if kind == "team_score_first":
            ml1 = _int_or_none(line.get("MoneyLine1"))
            ml2 = _int_or_none(line.get("MoneyLine2"))
            if ml1 is None or ml2 is None:
                continue
            rows.append({**base, "market_key": "team_to_score_first",
                         "outcome_name": away, "outcome_point": 0.0,
                         "price_american": ml1})
            rows.append({**base, "market_key": "team_to_score_first",
                         "outcome_name": home, "outcome_point": 0.0,
                         "price_american": ml2})
            continue

        if kind == "game_props":
            # NBA GPROPS — suffix identifies the specific game-prop type.
            # Map to mirror Odds API naming where possible.
            market_key_by_suffix = {
                " score first":   "team_to_score_first",
                " 10 pts first":  "team_to_10_points_first",
                " 15 pts first":  "team_to_15_points_first",
                " 20 pts first":  "team_to_20_points_first",
            }
            mk = market_key_by_suffix.get(s1 or "")
            if mk is None:
                unparsed += 1
                continue
            ml1 = _int_or_none(line.get("MoneyLine1"))
            ml2 = _int_or_none(line.get("MoneyLine2"))
            if ml1 is None or ml2 is None:
                continue
            rows.append({**base, "market_key": mk,
                         "outcome_name": away, "outcome_point": 0.0,
                         "price_american": ml1})
            rows.append({**base, "market_key": mk,
                         "outcome_name": home, "outcome_point": 0.0,
                         "price_american": ml2})
            continue

    if orphans or circled or live or unparsed:
        logger.info(
            "coral33 %s extras/%s: %d rows, %d orphans, %d circled, "
            "%d live, %d unparsed (from %d lines)",
            sport_key, kind, len(rows), orphans, circled, live, unparsed,
            len(lines),
        )
    return rows


def _extra_base(
    event_id: str, sport_key: str, home: str, away: str,
    commence: datetime, fetched_at: datetime,
) -> dict:
    return {
        "event_id": event_id,
        "sport_key": sport_key,
        "home_team": home,
        "away_team": away,
        "commence_time": commence,
        "bookmaker_key": BOOK_KEY,
        "fetched_at": fetched_at,
    }
