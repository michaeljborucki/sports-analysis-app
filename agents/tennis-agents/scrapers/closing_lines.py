"""Capture and look up consensus closing lines for CLV tracking.

A "closing line" is the consensus market price taken at (or near) match start.
We default to historical backfill via The Odds API's `/historical/sports/{key}/odds`
endpoint so no long-running daemon is required — backfill once per day after the
grader runs and close-line CSV rows are deterministic per `(date, game, market, side, line)`.

Storage: `data/closing_lines.csv` — one row per (date, game, market, side, line) with
`close_odds`, `close_prob_devig`, `captured_at`.
"""
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from config import DATA_DIR, ODDS_API_BASE, ODDS_API_KEY, TOUR_CONFIG
from scrapers.odds import (
    OddsData,
    _flip_odds,
    _last_name,
    american_to_implied_prob,
    power_devig,
)

logger = logging.getLogger("mirofish.closing_lines")

CLOSING_LINES_CSV = os.path.join(DATA_DIR, "closing_lines.csv")
COLUMNS = [
    "date", "game", "tour", "market", "side", "line",
    "close_odds", "close_prob_devig", "captured_at",
]
_csv_lock = threading.Lock()


def _ensure_csv() -> None:
    os.makedirs(os.path.dirname(CLOSING_LINES_CSV), exist_ok=True)
    if not os.path.exists(CLOSING_LINES_CSV):
        pd.DataFrame(columns=COLUMNS).to_csv(CLOSING_LINES_CSV, index=False)


def _two_sided_devig(odds_a: int, odds_b: int) -> tuple[float, float]:
    raw_a = american_to_implied_prob(odds_a)
    raw_b = american_to_implied_prob(odds_b)
    return power_devig(raw_a, raw_b)


def _rows_from_two_sided(market: str, side_a: str, side_b: str,
                         odds_a: int, odds_b: int,
                         line_a="", line_b="") -> list[dict]:
    p_a, p_b = _two_sided_devig(odds_a, odds_b)
    return [
        {"market": market, "side": side_a, "line": line_a,
         "close_odds": int(odds_a), "close_prob_devig": round(p_a, 6)},
        {"market": market, "side": side_b, "line": line_b,
         "close_odds": int(odds_b), "close_prob_devig": round(p_b, 6)},
    ]


def extract_closing_rows(odds: OddsData) -> list[dict]:
    """Convert an OddsData snapshot into CLV rows (no date/game/timestamp yet)."""
    rows: list[dict] = []

    ml = odds.moneyline or {}
    if "player_a" in ml and "player_b" in ml:
        rows += _rows_from_two_sided(
            "moneyline", "player_a", "player_b",
            ml["player_a"], ml["player_b"],
        )

    gh = odds.game_handicap or {}
    if "player_a_odds" in gh and "player_b_odds" in gh:
        rows += _rows_from_two_sided(
            "game_handicap", "player_a", "player_b",
            gh["player_a_odds"], gh["player_b_odds"],
            line_a=gh.get("player_a_point", 0),
            line_b=gh.get("player_b_point", 0),
        )

    tg = odds.total_games or {}
    if "over_odds" in tg and "under_odds" in tg and "line" in tg:
        rows += _rows_from_two_sided(
            "total_games", "over", "under",
            tg["over_odds"], tg["under_odds"],
            line_a=tg["line"], line_b=tg["line"],
        )

    return rows


def _normalize_line(value) -> str:
    if value is None or value == "":
        return ""
    s = str(value)
    if s.lower() == "nan":
        return ""
    return s


def load_closing_lines(game_date: str | None = None) -> pd.DataFrame:
    if not os.path.exists(CLOSING_LINES_CSV):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(CLOSING_LINES_CSV)
    if game_date is not None:
        df = df[df["date"] == game_date]
    return df


def find_closing_line(game_date: str, game: str, market: str,
                      side: str, line: float | str | None = None) -> dict | None:
    """Return the most-recent closing-line row matching the bet, or None."""
    df = load_closing_lines(game_date)
    if df.empty:
        return None
    mask = (
        (df["game"].astype(str) == str(game))
        & (df["market"].astype(str) == str(market))
        & (df["side"].astype(str) == str(side))
    )
    if line is not None and _normalize_line(line) != "":
        mask &= (df["line"].astype(str) == str(line))
    matches = df[mask]
    if matches.empty:
        return None
    matches = matches.sort_values("captured_at")
    return matches.iloc[-1].to_dict()


def get_historical_tennis_odds(snapshot_iso: str, tour: str = "atp") -> list[OddsData]:
    """Fetch a historical tennis odds snapshot. Iterates all active sub-tournaments."""
    from scrapers.odds import get_tennis_odds  # reuse _parse logic later if needed
    sport_prefix = TOUR_CONFIG[tour]["odds_sport_key"]

    # Discover active tournaments
    sports_resp = requests.get(
        f"{ODDS_API_BASE}/sports",
        params={"apiKey": ODDS_API_KEY, "all": "true"},
        timeout=15,
    )
    sports_resp.raise_for_status()
    sport_keys = [
        s["key"] for s in sports_resp.json()
        if s.get("key", "").startswith(sport_prefix + "_")
    ]

    results: list[OddsData] = []
    for sport_key in sport_keys:
        url = f"{ODDS_API_BASE}/historical/sports/{sport_key}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
            "date": snapshot_iso,
        }
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code == 404:
            continue
        resp.raise_for_status()
        payload = resp.json()
        events = payload.get("data", []) if isinstance(payload, dict) else payload
        for event in events:
            results.append(_event_to_odds_data(event))
    return results


def _event_to_odds_data(event: dict) -> OddsData:
    player_a = event.get("home_team", "")
    player_b = event.get("away_team", "")
    o = OddsData(
        player_a=player_a, player_b=player_b,
        commence_time=event.get("commence_time", ""),
    )
    for bk in event.get("bookmakers", []):
        markets = {m["key"]: m for m in bk.get("markets", [])}
        if "h2h" in markets and "player_a" not in o.moneyline:
            for outcome in markets["h2h"]["outcomes"]:
                key = "player_a" if outcome["name"] == player_a else "player_b"
                o.moneyline[key] = outcome["price"]
        if "spreads" in markets and "player_a_odds" not in o.game_handicap:
            for outcome in markets["spreads"]["outcomes"]:
                if outcome["name"] == player_a:
                    o.game_handicap["player_a_point"] = outcome.get("point", 0)
                    o.game_handicap["player_a_odds"] = outcome["price"]
                else:
                    o.game_handicap["player_b_point"] = outcome.get("point", 0)
                    o.game_handicap["player_b_odds"] = outcome["price"]
        if "totals" in markets and "over_odds" not in o.total_games:
            for outcome in markets["totals"]["outcomes"]:
                if outcome["name"] == "Over":
                    o.total_games["line"] = outcome.get("point", 0)
                    o.total_games["over_odds"] = outcome["price"]
                else:
                    o.total_games["under_odds"] = outcome["price"]
    return o


def _existing_capture_keys(game_date: str) -> set:
    if not os.path.exists(CLOSING_LINES_CSV):
        return set()
    df = pd.read_csv(CLOSING_LINES_CSV, dtype={"line": str}, keep_default_na=False)
    if df.empty:
        return set()
    today = df[df["date"] == game_date]
    return {
        (str(r["game"]), str(r["market"]), str(r["side"]), _normalize_line(r["line"]))
        for _, r in today.iterrows()
    }


def _match_by_last_name(target: OddsData, snapshot: list[OddsData]) -> OddsData | None:
    """Find an event in `snapshot` whose last-name pair matches `target`. Flips if reversed."""
    ta = _last_name(target.player_a)
    tb = _last_name(target.player_b)
    if not ta or not tb or ta == tb:
        return None
    target_pair = {ta, tb}
    for o in snapshot:
        oa = _last_name(o.player_a)
        ob = _last_name(o.player_b)
        if {oa, ob} != target_pair:
            continue
        return o if oa == ta else _flip_odds(o)
    return None


def capture_closing_lines_for_date(game_date: str,
                                   tour: str | None = None,
                                   now_utc: datetime | None = None,
                                   snapshot_offset_min: int = 5) -> dict:
    """Snapshot closing lines for matches on `game_date` via the historical endpoint.

    Strategy: one enumeration snapshot at day start to discover events + their true
    commence_times; then one close snapshot per match (bucketed to 5 min to dedup).
    Matching is by last-name pair — tolerant to "F. Cobolli" vs "Flavio Cobolli".

    Args:
        game_date: YYYY-MM-DD
        tour: 'atp' | 'wta' | None (both)
        now_utc: only used for test determinism; defaults to actual now
        snapshot_offset_min: minutes before true commence_time to snapshot

    Returns summary: {captured_games, captured_rows, snapshot_calls, skipped}.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    tours = ["atp", "wta"] if tour is None else [tour]

    existing = _existing_capture_keys(game_date)
    new_rows: list[dict] = []
    captured_games = 0
    snapshot_calls = 0
    skipped = 0

    for t in tours:
        bets_events = _enumerate_scheduled_events(game_date, t)
        if not bets_events:
            continue

        enum_snap_iso = f"{game_date}T12:00:00Z"
        try:
            enum_snapshot = get_historical_tennis_odds(enum_snap_iso, tour=t)
        except Exception as e:
            logger.warning("enumeration snapshot %s (%s) failed: %s", enum_snap_iso, t, e)
            continue
        snapshot_calls += 1

        # Map each bet to its true commence_time from the API snapshot.
        matched: list[tuple[OddsData, OddsData]] = []
        for bet_ev in bets_events:
            real = _match_by_last_name(bet_ev, enum_snapshot)
            if real is None:
                skipped += 1
                continue
            matched.append((bet_ev, real))

        # Group per-match close snapshots by 5-min bucket to dedup API calls.
        buckets: dict[str, list[tuple[OddsData, OddsData]]] = {}
        for bet_ev, real in matched:
            try:
                ct = datetime.fromisoformat(real.commence_time.replace("Z", "+00:00"))
            except ValueError:
                skipped += 1
                continue
            if ct > now_utc:
                skipped += 1
                continue
            snap_dt = ct - timedelta(minutes=snapshot_offset_min)
            snap_dt = snap_dt.replace(minute=(snap_dt.minute // 5) * 5,
                                      second=0, microsecond=0)
            snap_iso = snap_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            buckets.setdefault(snap_iso, []).append((bet_ev, real))

        for snap_iso, pairs in sorted(buckets.items()):
            try:
                snapshot = get_historical_tennis_odds(snap_iso, tour=t)
            except Exception as e:
                logger.warning("close snapshot %s (%s) failed: %s", snap_iso, t, e)
                continue
            snapshot_calls += 1

            for bet_ev, _real in pairs:
                close_o = _match_by_last_name(bet_ev, snapshot)
                if close_o is None:
                    continue
                game_key = f"{bet_ev.player_a} vs {bet_ev.player_b}"
                rows = extract_closing_rows(close_o)
                rows_added = 0
                for r in rows:
                    ek = (game_key, r["market"], r["side"],
                          _normalize_line(r.get("line", "")))
                    if ek in existing:
                        continue
                    new_rows.append({
                        "date": game_date,
                        "game": game_key,
                        "tour": t,
                        "market": r["market"],
                        "side": r["side"],
                        "line": r.get("line", ""),
                        "close_odds": r["close_odds"],
                        "close_prob_devig": r["close_prob_devig"],
                        "captured_at": snap_iso,
                    })
                    existing.add(ek)
                    rows_added += 1
                if rows_added:
                    captured_games += 1

    if new_rows:
        with _csv_lock:
            _ensure_csv()
            df = pd.read_csv(CLOSING_LINES_CSV)
            df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
            df.to_csv(CLOSING_LINES_CSV, index=False)

    return {
        "captured_games": captured_games,
        "captured_rows": len(new_rows),
        "snapshot_calls": snapshot_calls,
        "skipped": skipped,
    }


def _enumerate_scheduled_events(game_date: str, tour: str) -> list[OddsData]:
    """Enumerate match start times for `game_date` + `tour` from bets.csv.

    bets.csv has a row per logged bet with `start_time` and `game` — the matches we
    actually need CLV for. For today/future dates where bets.csv may be empty, we
    fall back to the live /odds feed so a capture run before grading still works.
    """
    from tracker import load_bets
    try:
        df = load_bets()
    except Exception as e:
        logger.warning("load_bets failed: %s", e)
        df = None

    events: list[OddsData] = []
    seen: set = set()
    if df is not None and not df.empty:
        for _, row in df[df["date"].astype(str) == game_date].iterrows():
            game = str(row.get("game", ""))
            start_time = str(row.get("start_time", ""))
            if not game or " vs " not in game or not start_time or start_time == "nan":
                continue
            if game in seen:
                continue
            seen.add(game)
            pa, pb = game.split(" vs ", 1)
            commence_iso = _coerce_commence_time(start_time)
            if not commence_iso:
                continue
            events.append(OddsData(
                player_a=pa.strip(), player_b=pb.strip(),
                commence_time=commence_iso,
            ))
    if events:
        return events

    # Fallback: live feed (captures same-day before grade).
    from scrapers.odds import get_tennis_odds
    try:
        all_events = get_tennis_odds(tour)
    except Exception as e:
        logger.warning("live enumerate for %s %s failed: %s", game_date, tour, e)
        return []
    result = []
    for ev in all_events:
        if not ev.commence_time:
            continue
        try:
            ct = datetime.fromisoformat(ev.commence_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ct.date().isoformat() == game_date:
            result.append(ev)
    return result


def _coerce_commence_time(value: str) -> str:
    """Convert a bets.csv start_time ('YYYY-MM-DD HH:MM' or ISO) to a UTC ISO string."""
    value = str(value).strip()
    if not value or value.lower() == "nan":
        return ""
    try:
        # Accept both "2026-04-19 13:30" (assumed UTC) and full ISO strings.
        if "T" in value:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return ""
