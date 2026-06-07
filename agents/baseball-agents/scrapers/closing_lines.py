"""Capture and look up consensus closing lines for CLV tracking.

A "closing line" snapshot is the consensus market price taken near first pitch
(default window: T-15 to T-5 minutes). Captures are deterministic — they only
fetch odds and apply the existing power-method devig. No LLM calls.

CSV: data/closing_lines.csv with one row per (date, game, market, side, line).
"""
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Iterable

import pandas as pd

from config import DATA_DIR
from scrapers.odds import (
    OddsData,
    american_to_implied_prob,
    get_additional_odds,
    get_historical_event_odds,
    get_historical_mlb_odds,
    get_mlb_odds,
    power_devig,
    _HIST_EVENT_DEFAULT_MARKETS,
    _parse_additional_markets,
)

logger = logging.getLogger("mirofish.closing_lines")

CLOSING_LINES_CSV = os.path.join(DATA_DIR, "closing_lines.csv")
COLUMNS = [
    "date", "game", "market", "side", "line",
    "close_odds", "close_prob_devig", "captured_at", "player_name",
]
_csv_lock = threading.Lock()

CAPTURE_WINDOW_MINUTES = (5, 30)  # capture if first pitch is between T-5 and T-30

PROP_MARKETS = {
    "pitcher_strikeouts", "pitcher_earned_runs", "pitcher_outs", "pitcher_hits_allowed",
    "batter_total_bases", "batter_rbis", "batter_hits", "batter_runs_scored",
    "batter_hits_runs_rbis", "batter_strikeouts",
}


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
                         line_a: float | str = "", line_b: float | str = "") -> list[dict]:
    """Produce two CLV rows for any two-sided market."""
    p_a, p_b = _two_sided_devig(odds_a, odds_b)
    return [
        {"market": market, "side": side_a, "line": line_a,
         "close_odds": int(odds_a), "close_prob_devig": round(p_a, 6)},
        {"market": market, "side": side_b, "line": line_b,
         "close_odds": int(odds_b), "close_prob_devig": round(p_b, 6)},
    ]


def extract_closing_rows(odds: OddsData) -> list[dict]:
    """Convert an OddsData snapshot into a list of CLV rows (no date/game/timestamp yet)."""
    rows: list[dict] = []

    if odds.moneyline.get("home") and odds.moneyline.get("away"):
        rows += _rows_from_two_sided(
            "moneyline", "home", "away",
            odds.moneyline["home"], odds.moneyline["away"],
        )

    rl = odds.run_line
    if rl and "home_odds" in rl and "away_odds" in rl:
        home_pt = rl.get("home", -1.5)
        away_pt = rl.get("away", 1.5)
        rows += _rows_from_two_sided(
            "run_line", "home", "away",
            rl["home_odds"], rl["away_odds"],
            line_a=home_pt, line_b=away_pt,
        )

    for market_attr, market_name in [
        ("total", "total"),
        ("f5_total", "first_5_total"),
        ("f3_total", "first_3_total"),
        ("team_total_home", "team_total_home"),
        ("team_total_away", "team_total_away"),
    ]:
        m = getattr(odds, market_attr, None) or {}
        if "over_odds" in m and "under_odds" in m and "line" in m:
            rows += _rows_from_two_sided(
                market_name, "over", "under",
                m["over_odds"], m["under_odds"],
                line_a=m["line"], line_b=m["line"],
            )

    # f1_total → NRFI/YRFI (under = NRFI, over = YRFI)
    f1t = odds.f1_total or {}
    if "over_odds" in f1t and "under_odds" in f1t:
        rows += _rows_from_two_sided(
            "nrfi", "NRFI", "YRFI",
            f1t["under_odds"], f1t["over_odds"],
            line_a=f1t.get("line", 0.5), line_b=f1t.get("line", 0.5),
        )

    # F1 / F3 / F5 spreads (run_line variants)
    for market_attr, market_name in [
        ("f1_spread", "first_1_rl"),
        ("f3_spread", "first_3_rl"),
        ("f5_spread", "first_5_rl"),
    ]:
        spread = getattr(odds, market_attr, None) or {}
        if "home_odds" in spread and "away_odds" in spread:
            rows += _rows_from_two_sided(
                market_name, "home", "away",
                spread["home_odds"], spread["away_odds"],
                line_a=spread.get("home", 0.0), line_b=spread.get("away", 0.0),
            )

    # F5 ML / F3 ML
    for market_attr, market_name in [
        ("f5_moneyline", "first_5_ml"),
        ("f3_moneyline", "first_3_ml"),
    ]:
        m = getattr(odds, market_attr, None) or {}
        if "home" in m and "away" in m:
            rows += _rows_from_two_sided(
                market_name, "home", "away",
                m["home"], m["away"],
            )

    return rows


def extract_prop_closing_rows(event_json: dict) -> list[dict]:
    """Extract prop closing rows directly from raw event JSON (historical or live).

    Each prop outcome is keyed by (player_name, line, side='over'|'under').
    Picks the median price across books to dampen book-specific weirdness;
    devigs the over/under pair with the power method.
    """
    rows: list[dict] = []
    by_market: dict[str, dict] = {}

    for bk in event_json.get("bookmakers", []):
        for m in bk.get("markets", []):
            mk = m["key"]
            if mk not in PROP_MARKETS:
                continue
            for outcome in m.get("outcomes", []):
                player = outcome.get("description", "") or ""
                side = (outcome.get("name", "") or "").lower()
                line = outcome.get("point")
                price = outcome.get("price")
                if not player or side not in ("over", "under") or line is None or price is None:
                    continue
                key = (mk, player, float(line))
                slot = by_market.setdefault(key, {"over": [], "under": []})
                slot[side].append(int(price))

    for (mk, player, line), sides in by_market.items():
        overs = sides.get("over", [])
        unders = sides.get("under", [])
        if not overs or not unders:
            continue
        overs.sort()
        unders.sort()
        med_over = overs[len(overs) // 2]
        med_under = unders[len(unders) // 2]
        try:
            p_over, p_under = _two_sided_devig(med_over, med_under)
        except Exception:
            continue
        rows.append({
            "market": mk, "side": "over", "line": line, "player_name": player,
            "close_odds": med_over, "close_prob_devig": round(p_over, 6),
        })
        rows.append({
            "market": mk, "side": "under", "line": line, "player_name": player,
            "close_odds": med_under, "close_prob_devig": round(p_under, 6),
        })

    return rows


def _normalize_line(value) -> str:
    """Normalize line value for dedup key (handles "", NaN, floats)."""
    if value is None or value == "":
        return ""
    s = str(value)
    if s.lower() == "nan":
        return ""
    return s


def _existing_capture_keys(game_date: str) -> set[tuple[str, str, str, str, str]]:
    """Return set of (game, market, side, line, player_name) already captured for this date."""
    if not os.path.exists(CLOSING_LINES_CSV):
        return set()
    df = pd.read_csv(CLOSING_LINES_CSV, dtype={"line": str, "player_name": str}, keep_default_na=False)
    if df.empty:
        return set()
    today = df[df["date"] == game_date]
    if "player_name" not in today.columns:
        today = today.assign(player_name="")
    return {
        (str(r["game"]), str(r["market"]), str(r["side"]),
         _normalize_line(r["line"]), str(r.get("player_name", "") or ""))
        for _, r in today.iterrows()
    }


def capture_closing_lines(game_date: str | None = None,
                          now_utc: datetime | None = None,
                          force: bool = False) -> dict:
    """Snapshot consensus closing lines for in-window games.

    A game is in-window if its first-pitch is between T-15 and T-5 minutes
    from `now_utc`. Set `force=True` to bypass the window and capture all
    upcoming games (useful for backfills / manual snapshots).

    Returns a dict summary: {captured_games, captured_rows, skipped_games}.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    if game_date is None:
        game_date = now_utc.date().isoformat()

    # Pre-check 1: skip entirely if the daily pipeline hasn't logged any bets
    # for today. No bets = no CLV to capture.
    if not force:
        try:
            from zoneinfo import ZoneInfo
            eastern_today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
            bets_csv = os.path.join(DATA_DIR, "bets.csv")
            if os.path.exists(bets_csv):
                today_df = pd.read_csv(bets_csv, usecols=["date"])
                has_bets_today = (today_df["date"] == eastern_today).any()
            else:
                has_bets_today = False
            if not has_bets_today:
                logger.info("CLV capture: no bets logged for %s, skipping (run daily pipeline first)",
                            eastern_today)
                return {"captured_games": 0, "captured_rows": 0, "skipped_games": 0}
        except Exception as e:
            logger.warning("Bets-today pre-check failed (%s), proceeding", e)

    # Pre-check 2: skip the Odds API call entirely if no MLB game is
    # scheduled within the T-15..T-5 window right now. This keeps idle
    # cron firings cheap during overnight hours.
    # Also detects "all today's games have started" → emits a distinct
    # message so the cron driver can auto-shutoff for the day.
    if not force:
        try:
            from scrapers.pitchers import get_probable_starters
            eastern_today_iso = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
            games_today = get_probable_starters(eastern_today_iso)
            tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
            games_tomorrow = get_probable_starters(tomorrow)

            any_in_window = False
            any_future_today = False
            latest_today_fp = None
            for g in games_today:
                gd = g.get("game_date") or ""
                if not gd:
                    continue
                try:
                    fp = datetime.fromisoformat(gd.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if latest_today_fp is None or fp > latest_today_fp:
                    latest_today_fp = fp
                delta_min = (fp - now_utc).total_seconds() / 60.0
                if delta_min > -5:
                    any_future_today = True
                if CAPTURE_WINDOW_MINUTES[0] <= delta_min <= CAPTURE_WINDOW_MINUTES[1]:
                    any_in_window = True

            if not any_in_window:
                # Check tomorrow too (late-night UTC edge case)
                for g in games_tomorrow:
                    gd = g.get("game_date") or ""
                    if not gd:
                        continue
                    try:
                        fp = datetime.fromisoformat(gd.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    delta_min = (fp - now_utc).total_seconds() / 60.0
                    if CAPTURE_WINDOW_MINUTES[0] <= delta_min <= CAPTURE_WINDOW_MINUTES[1]:
                        any_in_window = True
                        break

            # Distinct shutoff signal: all today's games already started AND
            # nothing imminent. The cron prompt watches for this exact phrase.
            if not any_in_window and not any_future_today and latest_today_fp is not None:
                logger.info("CLV capture: all of today's games have started — "
                            "CLV monitoring complete for today")
                return {"captured_games": 0, "captured_rows": 0,
                        "skipped_games": 0, "monitoring_complete_for_today": True}

            if not any_in_window:
                logger.info("CLV capture: no games near first-pitch window, skipping odds fetch")
                return {"captured_games": 0, "captured_rows": 0, "skipped_games": 0}
        except Exception as e:
            logger.warning("Schedule pre-check failed (%s), proceeding with odds fetch", e)

    odds_list = get_mlb_odds()
    in_window: list[OddsData] = []
    skipped = 0
    for o in odds_list:
        if not o.commence_time:
            continue
        try:
            ct = datetime.fromisoformat(o.commence_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        delta_min = (ct - now_utc).total_seconds() / 60.0
        if force or (CAPTURE_WINDOW_MINUTES[0] <= delta_min <= CAPTURE_WINDOW_MINUTES[1]):
            in_window.append(o)
        else:
            skipped += 1

    if not in_window:
        logger.info("CLV capture: no games in window (skipped %d)", skipped)
        return {"captured_games": 0, "captured_rows": 0, "skipped_games": skipped}

    # Enrich with additional + prop markets per event
    raw_props_per_event: dict[str, dict] = {}
    for o in in_window:
        if o.event_id:
            additional = get_additional_odds(o.event_id, markets=_HIST_EVENT_DEFAULT_MARKETS)
            if additional:
                _parse_additional_markets(o, additional)
                raw_props_per_event[o.event_id] = additional

    existing = _existing_capture_keys(game_date)
    captured_at = now_utc.isoformat()
    new_rows = []
    captured_games = 0
    for o in in_window:
        game_key = f"{o.away}@{o.home}"
        rows = extract_closing_rows(o)
        if o.event_id and o.event_id in raw_props_per_event:
            # additional dict has the same per-market shape we need for props
            rows.extend(extract_prop_closing_rows({"bookmakers": [{"key": "merged", "markets": list(raw_props_per_event[o.event_id].values())}]}))
        rows_added = 0
        for r in rows:
            ek = (game_key, r["market"], r["side"],
                  _normalize_line(r.get("line", "")), str(r.get("player_name", "") or ""))
            if ek in existing:
                continue
            new_rows.append({
                "date": game_date,
                "game": game_key,
                "market": r["market"],
                "side": r["side"],
                "line": r.get("line", ""),
                "close_odds": r["close_odds"],
                "close_prob_devig": r["close_prob_devig"],
                "captured_at": captured_at,
                "player_name": r.get("player_name", ""),
            })
            existing.add(ek)
            rows_added += 1
        if rows_added:
            captured_games += 1
            logger.info("CLV capture: %s → %d new rows", game_key, rows_added)

    if new_rows:
        with _csv_lock:
            _ensure_csv()
            df = pd.read_csv(CLOSING_LINES_CSV)
            df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
            df.to_csv(CLOSING_LINES_CSV, index=False)

    return {
        "captured_games": captured_games,
        "captured_rows": len(new_rows),
        "skipped_games": skipped,
    }


def historical_backfill_date(game_date: str,
                             include_additional: bool = True,
                             snapshot_offset_min: int = 7) -> dict:
    """Backfill closing lines for one date using The Odds API historical endpoint.

    For each scheduled game, snapshot at first_pitch_utc - snapshot_offset_min.
    Snapshots are deduped to nearest 5-min bucket (the API resolution), so multiple
    games in the same time window cost just one snapshot call.

    Args:
        game_date: 'YYYY-MM-DD' (game date in US/Eastern)
        include_additional: also fetch team_totals + NRFI per event (extra ~20 credits/game)
        snapshot_offset_min: minutes before first pitch to snapshot (default 7, mid-window)

    Returns: {captured_games, captured_rows, snapshot_calls, event_calls}.
    """
    from scrapers.pitchers import get_probable_starters

    games = get_probable_starters(game_date)
    if not games:
        logger.info("backfill %s: no scheduled games", game_date)
        return {"captured_games": 0, "captured_rows": 0, "snapshot_calls": 0, "event_calls": 0}

    # Bucket games by 5-min snapshot timestamp
    buckets: dict[str, list[dict]] = {}
    for g in games:
        gd = g.get("game_date") or ""
        if not gd:
            continue
        try:
            first_pitch = datetime.fromisoformat(gd.replace("Z", "+00:00"))
        except ValueError:
            continue
        snap_dt = first_pitch - timedelta(minutes=snapshot_offset_min)
        # Round down to 5-min bucket
        snap_dt = snap_dt.replace(minute=(snap_dt.minute // 5) * 5, second=0, microsecond=0)
        snap_iso = snap_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        buckets.setdefault(snap_iso, []).append(g)

    existing = _existing_capture_keys(game_date)
    new_rows: list[dict] = []
    captured_games = 0
    snapshot_calls = 0
    event_calls = 0

    for snap_iso, snap_games in sorted(buckets.items()):
        try:
            odds_list = get_historical_mlb_odds(snap_iso)
        except Exception as e:
            logger.warning("backfill snapshot %s failed: %s", snap_iso, e)
            continue
        snapshot_calls += 1

        # Group returned events by matchup (handles doubleheaders — same teams, two event_ids)
        by_matchup: dict[tuple[str, str], list] = {}
        for o in odds_list:
            by_matchup.setdefault((o.away, o.home), []).append(o)

        captured_at = snap_iso
        for g in snap_games:
            matchup = (g["away_team"], g["home_team"])
            candidates = by_matchup.get(matchup, [])
            if not candidates:
                continue

            # Pick the candidate whose commence_time is closest to the schedule's first pitch
            target_fp_iso = g.get("game_date") or ""
            o = candidates[0]
            if target_fp_iso and len(candidates) > 1:
                try:
                    target_fp = datetime.fromisoformat(target_fp_iso.replace("Z", "+00:00"))
                    def _delta(ev):
                        try:
                            evt = datetime.fromisoformat(ev.commence_time.replace("Z", "+00:00"))
                            return abs((evt - target_fp).total_seconds())
                        except (ValueError, TypeError):
                            return float("inf")
                    o = min(candidates, key=_delta)
                except (ValueError, TypeError):
                    pass

            # Fetch additional + prop markets (team_totals + NRFI + F1/F3/F5 + props)
            raw_event: dict = {}
            if include_additional and o.event_id:
                try:
                    extra, raw_event = get_historical_event_odds(o.event_id, snap_iso)
                    event_calls += 1
                    if extra:
                        _parse_additional_markets(o, extra)
                except Exception as e:
                    logger.warning("backfill event %s @ %s failed: %s", o.event_id, snap_iso, e)

            game_key = f"{o.away}@{o.home}"
            rows = extract_closing_rows(o)
            if raw_event:
                rows.extend(extract_prop_closing_rows(raw_event))

            rows_added = 0
            for r in rows:
                ek = (game_key, r["market"], r["side"],
                      _normalize_line(r.get("line", "")), str(r.get("player_name", "") or ""))
                if ek in existing:
                    continue
                new_rows.append({
                    "date": game_date,
                    "game": game_key,
                    "market": r["market"],
                    "side": r["side"],
                    "line": r.get("line", ""),
                    "close_odds": r["close_odds"],
                    "close_prob_devig": r["close_prob_devig"],
                    "captured_at": captured_at,
                    "player_name": r.get("player_name", ""),
                })
                existing.add(ek)
                rows_added += 1
            if rows_added:
                captured_games += 1
                logger.info("backfill: %s %s → %d new rows", game_date, game_key, rows_added)

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
        "event_calls": event_calls,
    }


def historical_backfill_range(start_date: str, end_date: str,
                              include_additional: bool = True) -> dict:
    """Backfill closing lines for a date range (inclusive)."""
    from datetime import date as date_cls
    start = date_cls.fromisoformat(start_date)
    end = date_cls.fromisoformat(end_date)
    if end < start:
        start, end = end, start

    totals = {"captured_games": 0, "captured_rows": 0, "snapshot_calls": 0, "event_calls": 0}
    cur = start
    while cur <= end:
        ds = cur.isoformat()
        logger.info("backfill: starting %s", ds)
        summary = historical_backfill_date(ds, include_additional=include_additional)
        for k in totals:
            totals[k] += summary.get(k, 0)
        cur += timedelta(days=1)

    return totals


def load_closing_lines(game_date: str | None = None) -> pd.DataFrame:
    """Load closing-lines CSV, optionally filtered by date."""
    if not os.path.exists(CLOSING_LINES_CSV):
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(CLOSING_LINES_CSV)
    if game_date is not None:
        df = df[df["date"] == game_date]
    return df


def find_closing_line(game_date: str, game: str, market: str,
                      side: str, line: float | None = None,
                      player_name: str = "") -> dict | None:
    """Return the closing line dict matching this bet, or None.

    Match rules:
      1. Filter to (date, game, market, side) and player_name (empty = mainline).
      2. If `line` is provided:
         a. Prefer exact line match (latest capture).
         b. Fall back to closest line available (line-relaxed CLV for line moves).
      3. Otherwise, return the latest capture that matches.
    """
    df = load_closing_lines(game_date)
    if df.empty:
        return None
    if "player_name" not in df.columns:
        df = df.assign(player_name="")
    df["player_name"] = df["player_name"].fillna("").astype(str)

    mask = (
        (df["game"] == game)
        & (df["market"] == market)
        & (df["side"].astype(str) == str(side))
        & (df["player_name"] == (player_name or ""))
    )
    subset = df[mask]
    if subset.empty:
        return None

    if line is None:
        result = subset.sort_values("captured_at").iloc[-1]
        return result.to_dict()

    # Exact line first
    exact = subset[subset["line"].astype(str) == str(line)]
    if not exact.empty:
        result = exact.sort_values("captured_at").iloc[-1]
        return result.to_dict()

    # Fall back to closest line
    def _as_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    subset = subset.copy()
    subset["_line_f"] = subset["line"].apply(_as_float)
    subset = subset[subset["_line_f"].notna()]
    if subset.empty:
        return None
    subset["_dist"] = (subset["_line_f"] - float(line)).abs()
    # Smallest distance first; among ties, latest capture
    closest = subset.sort_values(["_dist", "captured_at"], ascending=[True, False]).iloc[0]
    result = closest.drop(labels=["_line_f", "_dist"]).to_dict()
    return result
