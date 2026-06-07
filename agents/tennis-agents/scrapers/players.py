"""Player profiles backed by the local Sackmann-shaped archive.

Reads from ``data/sackmann/{tour}/`` only — no network fetching. The archive
is populated by:
  - A one-time bootstrap of Sackmann's 2020-2024 CSVs (``scripts/bootstrap_player_data.sh``)
  - Daily appends from ``scrapers/sackmann_sync.py`` (api-tennis `get_fixtures`)

The 2025+ rows written by ``sackmann_sync`` carry pre-computed percentage
columns (``w_1stSvPct`` etc.) because api-tennis returns percentages directly
rather than the raw counts Sackmann's 2020-2024 rows use. ``_calc_serve_stats``
and ``_calc_return_stats`` prefer the percentage columns when present and
fall back to count-based computation otherwise.
"""
import csv
import logging
import os
from datetime import date, datetime
from typing import Optional

from config import SACKMANN_LOCAL_DIR

logger = logging.getLogger("mirofish.scrapers.players")

# ---------------------------------------------------------------------------
# Elo constants
# ---------------------------------------------------------------------------
ELO_K = 32
ELO_START = 1500
ELO_HISTORY_START_YEAR = 2020


# ---------------------------------------------------------------------------
# CSV reading (local-only, no fetching)
# ---------------------------------------------------------------------------


def _local_path(tour: str, filename: str) -> str:
    return os.path.join(SACKMANN_LOCAL_DIR, tour, filename)


def _fetch_csv(tour: str, filename: str) -> list[dict]:
    """Read a local CSV from the Sackmann archive. Returns [] if missing."""
    path = _local_path(tour, filename)
    if not os.path.exists(path):
        logger.warning("Missing local archive file: %s (run bootstrap + backfill)", path)
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        logger.error("Failed to read %s: %s", path, e)
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(val) -> Optional[float]:
    """Return float or None for empty/invalid values."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    val = str(val).strip()
    if val == "" or val.lower() == "nan":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """Safe division; returns None when inputs are missing or denominator is zero."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _player_won(name: str, match: dict) -> bool:
    return name.lower() in match.get("winner_name", "").lower()


def _is_player(name: str, match: dict) -> bool:
    name_lower = name.lower()
    return (
        name_lower in match.get("winner_name", "").lower()
        or name_lower in match.get("loser_name", "").lower()
    )


def _is_h2h(a: str, b: str, match: dict) -> bool:
    names = {match.get("winner_name", "").lower(), match.get("loser_name", "").lower()}
    return a.lower() in str(names) and b.lower() in str(names)


def _winner_is(name: str, match: dict) -> bool:
    return name.lower() in match.get("winner_name", "").lower()


# ---------------------------------------------------------------------------
# Stat calculators
# ---------------------------------------------------------------------------


def _calc_serve_stats(player_matches: list[dict], name: str = "") -> dict:
    """Compute serve stats, preferring pre-computed percentage columns.

    For each match, a player's stats are under either ``w_*`` (if they won)
    or ``l_*`` (if they lost). Percentage columns (``w_1stSvPct`` etc.) are
    populated for 2025+ rows by ``sackmann_sync``. Historical rows
    (2020-2024) carry raw counts (``w_svpt``, ``w_1stIn`` etc.) and we
    back-compute percentages from those.
    """
    first_serve_pcts: list[float] = []
    first_serve_win_pcts: list[float] = []
    second_serve_win_pcts: list[float] = []
    ace_counts: list[float] = []
    df_counts: list[float] = []

    for m in player_matches:
        won = _player_won(name, m)
        pfx = "w_" if won else "l_"

        # Aces and DFs — always raw counts in both schemas
        aces = _safe_float(m.get(f"{pfx}ace"))
        dfs = _safe_float(m.get(f"{pfx}df"))
        if aces is not None:
            ace_counts.append(aces)
        if dfs is not None:
            df_counts.append(dfs)

        # 1st serve percentage — prefer pre-computed
        pct = _safe_float(m.get(f"{pfx}1stSvPct"))
        if pct is None:
            svpt = _safe_float(m.get(f"{pfx}svpt"))
            first_in = _safe_float(m.get(f"{pfx}1stIn"))
            pct = _safe_div(first_in, svpt)
        if pct is not None:
            first_serve_pcts.append(pct)

        # 1st serve points won % — prefer pre-computed
        fw = _safe_float(m.get(f"{pfx}1stWonPct"))
        if fw is None:
            first_won = _safe_float(m.get(f"{pfx}1stWon"))
            first_in = _safe_float(m.get(f"{pfx}1stIn"))
            fw = _safe_div(first_won, first_in)
        if fw is not None:
            first_serve_win_pcts.append(fw)

        # 2nd serve points won % — prefer pre-computed
        sw = _safe_float(m.get(f"{pfx}2ndWonPct"))
        if sw is None:
            svpt = _safe_float(m.get(f"{pfx}svpt"))
            first_in = _safe_float(m.get(f"{pfx}1stIn"))
            second_won = _safe_float(m.get(f"{pfx}2ndWon"))
            second_attempts = (svpt - first_in) if (svpt is not None and first_in is not None) else None
            sw = _safe_div(second_won, second_attempts) if second_attempts and second_attempts > 0 else None
        if sw is not None:
            second_serve_win_pcts.append(sw)

    def _avg(vals: list[float]) -> str:
        if not vals:
            return "N/A"
        return f"{sum(vals) / len(vals):.1%}"

    def _avg_count(vals: list[float]) -> str:
        if not vals:
            return "N/A"
        return f"{sum(vals) / len(vals):.1f}"

    return {
        "first_serve_pct": _avg(first_serve_pcts),
        "first_serve_win_pct": _avg(first_serve_win_pcts),
        "second_serve_win_pct": _avg(second_serve_win_pcts),
        "ace_rate": _avg_count(ace_counts),
        "df_rate": _avg_count(df_counts),
    }


def _calc_return_stats(player_matches: list[dict], name: str = "") -> dict:
    """Return stats, preferring pre-computed percentage columns.

    When the player won, the opponent's serve columns are ``l_*``.
    When the player lost, opponent's columns are ``w_*``.

    For 2025+ rows, we read the player's own return percentage columns
    (``{pfx}retPtsWonPct``, ``{pfx}bpConvPct``). For historical rows we
    back-compute from opponent counts (existing Sackmann math).
    """
    rp_pcts: list[float] = []
    bp_pcts: list[float] = []

    for m in player_matches:
        won = _player_won(name, m)
        own_pfx = "w_" if won else "l_"
        opp_pfx = "l_" if won else "w_"

        # Return points won % — prefer pre-computed
        rp = _safe_float(m.get(f"{own_pfx}retPtsWonPct"))
        if rp is None:
            opp_svpt = _safe_float(m.get(f"{opp_pfx}svpt"))
            opp_1st_won = _safe_float(m.get(f"{opp_pfx}1stWon"))
            opp_2nd_won = _safe_float(m.get(f"{opp_pfx}2ndWon"))
            if opp_svpt is not None and opp_1st_won is not None and opp_2nd_won is not None and opp_svpt > 0:
                return_won = opp_svpt - opp_1st_won - opp_2nd_won
                rp = return_won / opp_svpt
        if rp is not None:
            rp_pcts.append(rp)

        # BP conversion % — prefer pre-computed
        bp = _safe_float(m.get(f"{own_pfx}bpConvPct"))
        if bp is None:
            opp_bp_faced = _safe_float(m.get(f"{opp_pfx}bpFaced"))
            opp_bp_saved = _safe_float(m.get(f"{opp_pfx}bpSaved"))
            if opp_bp_faced is not None and opp_bp_saved is not None and opp_bp_faced > 0:
                bp_converted = opp_bp_faced - opp_bp_saved
                bp = bp_converted / opp_bp_faced
        if bp is not None:
            bp_pcts.append(bp)

    def _avg(vals: list[float]) -> str:
        if not vals:
            return "N/A"
        return f"{sum(vals) / len(vals):.1%}"

    return {
        "return_pts_won_pct": _avg(rp_pcts),
        "bp_conversion_pct": _avg(bp_pcts),
    }


def _calc_record(player_matches: list[dict], surface: str = None, name: str = "") -> str:
    """Return 'W-L' record, optionally filtered by surface."""
    filtered = player_matches
    if surface:
        filtered = [m for m in filtered if m.get("surface", "").lower() == surface.lower()]
    wins = sum(1 for m in filtered if _player_won(name, m))
    losses = len(filtered) - wins
    return f"{wins}-{losses}"


def _recent_form(player_matches: list[dict], name: str = "", n: int = 10) -> list[dict]:
    """Return the last *n* matches with opponent, result (W/L), and score."""
    recent = player_matches[-n:] if player_matches else []
    results: list[dict] = []
    for m in recent:
        won = _player_won(name, m)
        opponent = m.get("loser_name", "N/A") if won else m.get("winner_name", "N/A")
        results.append({
            "date": m.get("tourney_date", ""),
            "tournament": m.get("tourney_name", ""),
            "surface": m.get("surface", ""),
            "round": m.get("round", ""),
            "opponent": opponent,
            "result": "W" if won else "L",
            "score": m.get("score", ""),
        })
    return results


# ---------------------------------------------------------------------------
# Elo computation
# ---------------------------------------------------------------------------


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _compute_elo_ratings(tour: str = "atp") -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Build Elo tables from historical match data.

    Iterates ``{prefix}_matches_{year}.csv`` from 2020 through current year.
    Updates Elo in row order (Sackmann CSVs are chronological).

    Returns ``(overall_elo, surface_elo)`` where ``surface_elo`` maps
    ``player_name → {surface: rating}``.
    """
    prefix = "atp" if tour == "atp" else "wta"
    current_year = date.today().year
    overall: dict[str, float] = {}
    by_surface: dict[str, dict[str, float]] = {}

    for year in range(ELO_HISTORY_START_YEAR, current_year + 1):
        matches = _fetch_csv(tour, f"{prefix}_matches_{year}.csv")
        for m in matches:
            winner = m.get("winner_name", "").strip()
            loser = m.get("loser_name", "").strip()
            surface = m.get("surface", "").strip()
            if not winner or not loser:
                continue

            # Overall Elo
            w_elo = overall.get(winner, ELO_START)
            l_elo = overall.get(loser, ELO_START)
            exp_w = _expected_score(w_elo, l_elo)
            overall[winner] = w_elo + ELO_K * (1 - exp_w)
            overall[loser] = l_elo + ELO_K * (0 - (1 - exp_w))

            # Surface Elo
            if surface:
                surf_lower = surface.lower()
                w_surf = by_surface.setdefault(winner, {}).get(surf_lower, ELO_START)
                l_surf = by_surface.setdefault(loser, {}).get(surf_lower, ELO_START)
                exp_ws = _expected_score(w_surf, l_surf)
                by_surface[winner][surf_lower] = w_surf + ELO_K * (1 - exp_ws)
                by_surface.setdefault(loser, {})[surf_lower] = l_surf + ELO_K * (0 - (1 - exp_ws))

    return overall, by_surface


def _get_elo(name: str, surface: Optional[str], overall: dict[str, float],
             by_surface: dict[str, dict[str, float]]) -> tuple[int, int]:
    """Look up Elo for *name*, returning ``(overall_elo, surface_elo)``.

    Surface Elo is a 50/50 blend of overall and surface-specific Elo
    (per Sackmann's recommendation).
    """
    name_lower = name.lower()
    elo_overall = ELO_START
    for key, val in overall.items():
        if name_lower in key.lower():
            elo_overall = val
            break

    elo_surface = elo_overall  # default if no surface data
    if surface:
        surf_lower = surface.lower()
        for key, surf_dict in by_surface.items():
            if name_lower in key.lower():
                if surf_lower in surf_dict:
                    raw_surf = surf_dict[surf_lower]
                    elo_surface = (elo_overall + raw_surf) / 2
                break

    return round(elo_overall), round(elo_surface)


# ---------------------------------------------------------------------------
# Player lookup helpers
# ---------------------------------------------------------------------------


def _find_player(name: str, players: list[dict]) -> dict:
    name_lower = name.lower()
    for p in players:
        full = f"{p.get('name_first', '')} {p.get('name_last', '')}".strip().lower()
        last = p.get("name_last", "").lower()
        if name_lower == full or name_lower == last:
            return p
    return {}


def _find_ranking(name: str, rankings: list[dict], players: list[dict]) -> dict:
    player = _find_player(name, players)
    pid = player.get("player_id", "")
    if not pid:
        return {}
    for r in rankings:
        if r.get("player") == pid:
            return {"rank": r.get("rank", "N/A"), "points": r.get("points", "N/A")}
    return {}


def _days_since_last(matches: list[dict]) -> int:
    if not matches:
        return 999
    last = matches[-1]
    try:
        last_date = datetime.strptime(last.get("tourney_date", ""), "%Y%m%d")
        return (datetime.now() - last_date).days
    except (ValueError, TypeError):
        return 999


def _calc_age(dob: str) -> str:
    if not dob or len(dob) < 8:
        return "N/A"
    try:
        born = datetime.strptime(dob[:8], "%Y%m%d")
        today = date.today()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return str(age)
    except ValueError:
        return "N/A"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_player_profile(name: str, tour: str = "atp", surface: str = None) -> dict:
    year = date.today().year
    prefix = "atp" if tour == "atp" else "wta"
    rankings = _fetch_csv(tour, f"{prefix}_rankings_current.csv")
    players = _fetch_csv(tour, f"{prefix}_players.csv")
    player_info = _find_player(name, players)
    ranking_info = _find_ranking(name, rankings, players)
    matches = _fetch_csv(tour, f"{prefix}_matches_{year}.csv")
    player_matches = [m for m in matches if _is_player(name, m)]

    # Elo ratings (loaded once, covers 2020-current)
    overall_elo, surface_elo = _compute_elo_ratings(tour)
    elo, surf_elo = _get_elo(name, surface, overall_elo, surface_elo)

    return {
        "name": name,
        "ranking": ranking_info.get("rank", "N/A"),
        "ranking_points": ranking_info.get("points", "N/A"),
        "hand": player_info.get("hand", "N/A"),
        "backhand": player_info.get("backhand", "N/A"),
        "height": player_info.get("height", "N/A"),
        "age": _calc_age(player_info.get("dob", "")),
        "season_record": _calc_record(player_matches, name=name),
        "surface_record": _calc_record(player_matches, surface, name=name) if surface else "N/A",
        "serve_stats": _calc_serve_stats(player_matches, name=name),
        "return_stats": _calc_return_stats(player_matches, name=name),
        "recent_form": _recent_form(player_matches, name=name, n=10),
        "days_since_last_match": _days_since_last(player_matches),
        "elo": elo,
        "surface_elo": surf_elo,
    }


def get_head_to_head(
    player_a: str,
    player_b: str,
    tour: str = "atp",
    surface: str = None,
) -> dict:
    """Head-to-head record between two players.

    Returns ``{"overall": "W-L", "surface": "W-L", "last_3": [...]}``.
    """
    prefix = "atp" if tour == "atp" else "wta"
    year = date.today().year
    h2h: dict = {"overall": "0-0", "surface": "0-0", "last_3": []}
    all_h2h: list[dict] = []

    for y in range(year - 5, year + 1):
        matches = _fetch_csv(tour, f"{prefix}_matches_{y}.csv")
        for m in matches:
            if _is_h2h(player_a, player_b, m):
                all_h2h.append(m)

    if not all_h2h:
        return h2h

    a_wins = sum(1 for m in all_h2h if _winner_is(player_a, m))
    b_wins = len(all_h2h) - a_wins
    h2h["overall"] = f"{a_wins}-{b_wins}"

    if surface:
        surf_matches = [m for m in all_h2h if m.get("surface", "").lower() == surface.lower()]
        a_surf_wins = sum(1 for m in surf_matches if _winner_is(player_a, m))
        b_surf_wins = len(surf_matches) - a_surf_wins
        h2h["surface"] = f"{a_surf_wins}-{b_surf_wins}"

    last_3 = all_h2h[-3:]
    h2h["last_3"] = [
        {
            "date": m.get("tourney_date", ""),
            "tournament": m.get("tourney_name", ""),
            "surface": m.get("surface", ""),
            "winner": m.get("winner_name", ""),
            "score": m.get("score", ""),
        }
        for m in last_3
    ]

    return h2h
