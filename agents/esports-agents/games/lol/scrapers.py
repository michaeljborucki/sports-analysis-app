"""LoL match data scrapers via Oracle's Elixir and Riot data."""
import logging
import os
from datetime import datetime, timedelta

log = logging.getLogger(__name__)

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    log.warning("[lol] pandas not installed — Oracle's Elixir integration unavailable")


_oe_cache: dict = {}  # {year: (timestamp, dataframe)}
OE_CACHE_TTL = 86400  # 24 hours

# Oracle's Elixir base URL template
OE_URL_TEMPLATE = "https://oracleselixir.com/tools/downloads/download/{year}_LoL_esports_match_data_from_OraclesElixir.csv"


def _oe_url(year: int) -> str:
    return OE_URL_TEMPLATE.format(year=year)


def _load_oe_data(year: int | None = None):
    """Load Oracle's Elixir CSV data for the given year, with caching."""
    if not PANDAS_AVAILABLE:
        return None

    if year is None:
        year = datetime.now().year

    now = datetime.now().timestamp()
    if year in _oe_cache:
        ts, df = _oe_cache[year]
        if now - ts < OE_CACHE_TTL:
            return df

    url = _oe_url(year)
    try:
        df = pd.read_csv(url, low_memory=False)
        _oe_cache[year] = (now, df)
        log.info("[lol] Loaded Oracle's Elixir data for %d: %d rows", year, len(df))
        return df
    except Exception as e:
        log.warning("[lol] Failed to load Oracle's Elixir data for %d: %s", year, e)
        return None


def _filter_team_rows(df, team_name: str):
    """Filter dataframe for rows matching a team name (case-insensitive)."""
    if df is None:
        return None
    name_lower = team_name.lower()
    mask = df["teamname"].str.lower().str.contains(name_lower, na=False)
    team_df = df[mask]
    return team_df if not team_df.empty else None


def _compute_win_rate(team_df) -> float:
    """Compute overall win rate from team rows filtered to team-level rows."""
    if team_df is None or team_df.empty:
        return 0.0
    team_level = team_df[team_df["datacompleteness"] == "complete"] if "datacompleteness" in team_df.columns else team_df
    if "result" not in team_level.columns:
        return 0.0
    results = team_level["result"].dropna()
    if len(results) == 0:
        return 0.0
    return float(results.mean())


def _compute_side_win_rate(team_df, side: str) -> float:
    """Compute win rate for a specific side (Blue/Red)."""
    if team_df is None or team_df.empty:
        return 0.0
    if "side" not in team_df.columns or "result" not in team_df.columns:
        return 0.0
    side_df = team_df[team_df["side"].str.lower() == side.lower()]
    if side_df.empty:
        return 0.0
    return float(side_df["result"].mean())


def _compute_avg_game_duration(team_df) -> float:
    """Compute average game duration in minutes."""
    if team_df is None or team_df.empty:
        return 0.0
    if "gamelength" not in team_df.columns:
        return 0.0
    durations = team_df["gamelength"].dropna()
    if durations.empty:
        return 0.0
    # gamelength is in seconds in OE data
    return float(durations.mean() / 60)


def _compute_stat_rate(team_df, col: str) -> float:
    """Compute a rate for a binary stat column (first blood, first tower, etc.)."""
    if team_df is None or team_df.empty:
        return 0.0
    if col not in team_df.columns:
        return 0.0
    vals = team_df[col].dropna()
    if vals.empty:
        return 0.0
    return float(vals.mean())


def _compute_gold_diff_15(team_df) -> float:
    """Compute average gold differential at 15 minutes."""
    if team_df is None or team_df.empty:
        return 0.0
    col = "golddiffat15"
    if col not in team_df.columns:
        return 0.0
    vals = team_df[col].dropna()
    if vals.empty:
        return 0.0
    return float(vals.mean())


def _build_recent_form(team_df, n: int = 5) -> list[dict]:
    """Build recent form list from the last N games."""
    if team_df is None or team_df.empty:
        return []
    needed_cols = {"date", "result", "teamname"}
    if not needed_cols.issubset(set(team_df.columns)):
        return []

    # Sort by date descending
    try:
        sorted_df = team_df.sort_values("date", ascending=False)
    except Exception:
        sorted_df = team_df

    rows = []
    for _, row in sorted_df.head(n).iterrows():
        opponent = row.get("opponent", "") if "opponent" in team_df.columns else ""
        rows.append({
            "date": str(row.get("date", "")),
            "opponent": str(opponent),
            "result": "W" if row.get("result", 0) == 1 else "L",
            "tournament": str(row.get("league", "")),
        })
    return rows


def fetch_team_profile(team_name: str, region: str = "") -> dict:
    """Fetch LoL team profile. Uses Oracle's Elixir data when available."""
    df = _load_oe_data()

    team_df = _filter_team_rows(df, team_name) if df is not None else None

    if team_df is not None and not team_df.empty:
        log.info("[lol] Found %d rows for team '%s' in Oracle's Elixir", len(team_df), team_name)
        # Infer region from league if not provided
        if not region and "league" in team_df.columns:
            leagues = team_df["league"].dropna().unique()
            region = str(leagues[0]) if len(leagues) > 0 else ""

        # Derive roster from player names
        roster = []
        if "playername" in team_df.columns:
            players = team_df["playername"].dropna().unique().tolist()
            roster = [str(p) for p in players[:5]]

        return {
            "name": team_name,
            "region": region,
            "league_standing": "",
            "win_rate": _compute_win_rate(team_df),
            "blue_side_wr": _compute_side_win_rate(team_df, "Blue"),
            "red_side_wr": _compute_side_win_rate(team_df, "Red"),
            "avg_game_duration": _compute_avg_game_duration(team_df),
            "first_blood_rate": _compute_stat_rate(team_df, "firstblood"),
            "first_tower_rate": _compute_stat_rate(team_df, "firsttower"),
            "first_dragon_rate": _compute_stat_rate(team_df, "firstdragon"),
            "gold_diff_15": _compute_gold_diff_15(team_df),
            "roster": roster,
            "coach": "",
            "days_since_roster_change": 999,
            "recent_form": _build_recent_form(team_df),
        }

    # Fallback stub when no data available
    return {
        "name": team_name,
        "region": region,
        "league_standing": "",
        "win_rate": 0.0,
        "blue_side_wr": 0.0,
        "red_side_wr": 0.0,
        "avg_game_duration": 0.0,
        "first_blood_rate": 0.0,
        "first_tower_rate": 0.0,
        "first_dragon_rate": 0.0,
        "gold_diff_15": 0.0,
        "roster": [],
        "coach": "",
        "days_since_roster_change": 999,
        "recent_form": [],
    }


def fetch_upcoming_matches() -> list[dict]:
    """Fetch upcoming LoL matches.

    Oracle's Elixir only covers completed matches; upcoming matches would need
    a live schedule source. Returns empty list until a live schedule scraper
    is wired in.
    """
    return []


def fetch_head_to_head(team_a: str, team_b: str) -> dict:
    """Fetch H2H history between two teams from Oracle's Elixir data."""
    df = _load_oe_data()
    if df is None or "teamname" not in df.columns:
        return {
            "total_matches": 0,
            "team_a_wins": 0,
            "team_b_wins": 0,
            "recent_5": [],
        }

    # A "match" in OE is at the game level; we look for games where both teams appear
    name_a_lower = team_a.lower()
    name_b_lower = team_b.lower()

    if "gameid" not in df.columns or "result" not in df.columns:
        return {"total_matches": 0, "team_a_wins": 0, "team_b_wins": 0, "recent_5": []}

    try:
        # Find all game IDs that feature team_a
        a_games = set(df[df["teamname"].str.lower().str.contains(name_a_lower, na=False)]["gameid"].dropna().unique())
        # Find all game IDs that feature team_b
        b_games = set(df[df["teamname"].str.lower().str.contains(name_b_lower, na=False)]["gameid"].dropna().unique())
        # H2H game IDs
        h2h_games = a_games & b_games

        if not h2h_games:
            return {"total_matches": 0, "team_a_wins": 0, "team_b_wins": 0, "recent_5": []}

        h2h_df = df[df["gameid"].isin(h2h_games)]

        a_wins = int(h2h_df[
            (h2h_df["teamname"].str.lower().str.contains(name_a_lower, na=False)) &
            (h2h_df["result"] == 1)
        ]["gameid"].nunique())

        b_wins = int(h2h_df[
            (h2h_df["teamname"].str.lower().str.contains(name_b_lower, na=False)) &
            (h2h_df["result"] == 1)
        ]["gameid"].nunique())

        total = len(h2h_games)

        # Build recent 5 results
        recent_5 = []
        if "date" in h2h_df.columns:
            sorted_games = (
                h2h_df[h2h_df["teamname"].str.lower().str.contains(name_a_lower, na=False)]
                .sort_values("date", ascending=False)
                .head(5)
            )
            for _, row in sorted_games.iterrows():
                recent_5.append({
                    "date": str(row.get("date", "")),
                    "result": "W" if row.get("result", 0) == 1 else "L",
                    "tournament": str(row.get("league", "")),
                })

        return {
            "total_matches": total,
            "team_a_wins": a_wins,
            "team_b_wins": b_wins,
            "recent_5": recent_5,
        }

    except Exception as e:
        log.warning("[lol] H2H lookup failed for %s vs %s: %s", team_a, team_b, e)
        return {"total_matches": 0, "team_a_wins": 0, "team_b_wins": 0, "recent_5": []}


def fetch_match_result(team_a: str, team_b: str, date: str) -> dict:
    """Fetch completed match result for grading.

    Looks up the most recent H2H game on or near the given date in
    Oracle's Elixir data.
    """
    df = _load_oe_data()
    if df is None:
        return {"winner": "", "score": "0-0", "maps_played": 0, "game_details": []}

    if "teamname" not in df.columns or "gameid" not in df.columns:
        return {"winner": "", "score": "0-0", "maps_played": 0, "game_details": []}

    try:
        name_a_lower = team_a.lower()
        name_b_lower = team_b.lower()

        a_games = set(df[df["teamname"].str.lower().str.contains(name_a_lower, na=False)]["gameid"].dropna().unique())
        b_games = set(df[df["teamname"].str.lower().str.contains(name_b_lower, na=False)]["gameid"].dropna().unique())
        h2h_games = a_games & b_games

        if not h2h_games:
            return {"winner": "", "score": "0-0", "maps_played": 0, "game_details": []}

        h2h_df = df[df["gameid"].isin(h2h_games)].copy()

        # Filter near the requested date if available
        if "date" in h2h_df.columns and date:
            try:
                target = datetime.strptime(date, "%Y-%m-%d")
                h2h_df["_date_parsed"] = pd.to_datetime(h2h_df["date"], errors="coerce")
                within_window = h2h_df[
                    abs((h2h_df["_date_parsed"] - target).dt.days) <= 3
                ]
                if not within_window.empty:
                    h2h_df = within_window
            except Exception:
                pass

        # Group by gameid to determine per-game winners
        game_details = []
        for gid in h2h_df["gameid"].unique():
            game_rows = h2h_df[h2h_df["gameid"] == gid]
            winner_row = game_rows[game_rows["result"] == 1]
            winner_name = ""
            if not winner_row.empty:
                winner_name = str(winner_row.iloc[0].get("teamname", ""))
            game_details.append({"gameid": str(gid), "winner": winner_name})

        if not game_details:
            return {"winner": "", "score": "0-0", "maps_played": 0, "game_details": []}

        maps_played = len(game_details)
        a_wins = sum(1 for g in game_details if name_a_lower in g["winner"].lower())
        b_wins = sum(1 for g in game_details if name_b_lower in g["winner"].lower())
        winner = team_a if a_wins > b_wins else team_b if b_wins > a_wins else ""
        score = f"{a_wins}-{b_wins}"

        return {
            "winner": winner,
            "score": score,
            "maps_played": maps_played,
            "game_details": game_details,
        }

    except Exception as e:
        log.warning("[lol] fetch_match_result failed for %s vs %s: %s", team_a, team_b, e)
        return {"winner": "", "score": "0-0", "maps_played": 0, "game_details": []}
