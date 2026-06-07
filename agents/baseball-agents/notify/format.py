"""Format filtered bets into Discord-ready messages.

Discord uses its own Markdown flavor: ``` for code blocks, **bold**, _italic_.
Messages are capped at 2000 chars per webhook post — we target 1900 to leave
headroom for code fences.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from scrapers.odds import prob_to_american, american_be_with_wiggle

DISCORD_MAX = 1900
_ET = ZoneInfo("America/New_York")


def _format_et_time(iso_utc) -> str:
    """Convert an ISO-8601 UTC timestamp to '8:40 PM ET' (12-hour, ET with DST).

    Returns "" for empty, NaN, or unparseable input so callers can render a
    plain header without branching.
    """
    if iso_utc is None:
        return ""
    s = str(iso_utc).strip()
    if not s or s.lower() == "nan":
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return ""
    local = dt.astimezone(_ET)
    hour12 = local.hour % 12 or 12
    suffix = "AM" if local.hour < 12 else "PM"
    return f"{hour12}:{local.minute:02d} {suffix} ET"


def filter_bets(bets: list[dict], allowed_types: list[str],
                min_edge: float = 0.0, min_kelly: float = 0.0) -> list[dict]:
    """Keep only bets whose type is in `allowed_types` and meet thresholds.

    `min_edge` / `min_kelly` are decimal fractions (0.05 = 5%).
    """
    types = set(allowed_types)
    out = []
    for b in bets:
        if b.get("bet_type") not in types:
            continue
        try:
            if float(b.get("edge", 0)) < min_edge:
                continue
            if float(b.get("kelly_pct", 0)) < min_kelly:
                continue
        except (TypeError, ValueError):
            continue
        out.append(b)
    return out


_HEADER_LINE = (
    f"  {'TYPE':<14} | {'SIDE':<14} | "
    f"{'ODDS':>5} | {'MODEL':>5} | {'EDGE':>5} | {'BE':>5}"
)


def _format_bet_line(bet: dict) -> str:
    odds = int(bet["odds"])
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    sim = float(bet["sim_prob"]) * 100
    edge = float(bet["edge"]) * 100
    try:
        be = american_be_with_wiggle(prob_to_american(float(bet["sim_prob"])))
        be_str = f"+{be}" if be > 0 else str(be)
    except ValueError:
        be_str = "N/A"
    return (
        f"  {bet['bet_type']:<14} | {str(bet['side']):<14} | "
        f"{odds_str:>5} | {sim:4.1f}% | {edge:4.1f}% | {be_str:>5}"
    )


def format_game_block(game_key: str, picks: list[dict]) -> str:
    sorted_picks = sorted(picks, key=lambda b: -float(b.get("edge", 0)))
    time_str = ""
    for p in picks:
        time_str = _format_et_time(p.get("game_time"))
        if time_str:
            break
    header = f"{game_key} — {time_str}" if time_str else game_key
    body = (
        f"{header}\n{'-' * 40}\n"
        f"{_HEADER_LINE}\n"
        + "\n".join(_format_bet_line(b) for b in sorted_picks)
    )
    return f"```\n{body}\n```"


def format_header(game_date: str, n_picks: int, n_games: int) -> str:
    return (
        f"**Bet Card — {game_date}**\n"
        f"_{n_picks} picks across {n_games} games_"
    )


def _split_oversized_block(game_key: str, picks: list[dict], char_limit: int) -> list[str]:
    """Split a too-large game's picks into multiple smaller code blocks."""
    sorted_picks = sorted(picks, key=lambda b: -float(b.get("edge", 0)))
    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []

    for pick in sorted_picks:
        current_chunk.append(pick)
        if len(format_game_block(game_key, current_chunk)) > char_limit:
            popped = current_chunk.pop()
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = [popped]
    if current_chunk:
        chunks.append(current_chunk)

    return [format_game_block(game_key, c) for c in chunks]


_GRADE_HEADER_LINE = (
    f"  {'TYPE':<14} | {'SIDE':<14} | "
    f"{'ODDS':>5} | {'RESULT':<6} | {'UNITS':>6} | {'CLV':>5}"
)


def unit_profit_and_risk(odds: int, result: str) -> tuple[float, float]:
    """Per-bet (profit, risk) using flat 1u stake on every bet.

    - Stake: 1.0u regardless of odds.
    - Favorite (odds < 0) win: payout = 100/|odds|  (e.g. -140 → +0.71u).
    - Underdog (odds > 0) win: payout = odds/100    (e.g. +140 → +1.40u).
    - Loss: -1.0u. Push: profit = 0, risk = 0 (stake returned).
    """
    odds = int(odds)
    if result == "W":
        payout = 100.0 / abs(odds) if odds < 0 else odds / 100.0
        return payout, 1.0
    if result == "L":
        return -1.0, 1.0
    return 0.0, 0.0


def _format_grade_line(bet: dict) -> str:
    odds = int(bet["odds"])
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    result = str(bet.get("result", "")).upper()
    profit, _ = unit_profit_and_risk(odds, result)
    units_str = f"{profit:+.2f}" if result in ("W", "L") else " 0.00"
    # CLV in cents — empty string / NaN renders as "  --"
    clv_raw = bet.get("clv_cents")
    if clv_raw is None or str(clv_raw).strip() in ("", "nan"):
        clv_str = "  --"
    else:
        try:
            clv_int = int(float(clv_raw))
            clv_str = f"{clv_int:+d}"
        except (TypeError, ValueError):
            clv_str = "  --"
    return (
        f"  {bet['bet_type']:<14} | {str(bet['side']):<14} | "
        f"{odds_str:>5} | {result:<6} | {units_str:>6} | {clv_str:>5}"
    )


def format_grade_game_block(game_key: str, picks: list[dict]) -> str:
    sorted_picks = sorted(picks, key=lambda b: {"W": 0, "L": 1, "P": 2}.get(
        str(b.get("result", "")).upper(), 3))
    body = (
        f"{game_key}\n{'-' * 40}\n"
        f"{_GRADE_HEADER_LINE}\n"
        + "\n".join(_format_grade_line(b) for b in sorted_picks)
    )
    return f"```\n{body}\n```"


# Required display order for per-bet-type breakdowns in grade and season
# summaries. Anything outside this list sorts alphabetically after the
# explicit entries so the mainline types the operator cares about always
# lead the list.
_BET_TYPE_DISPLAY_ORDER = (
    "moneyline",
    "run_line",
    "total",
    "nrfi",
    "team_total_home",
    "team_total_away",
)
_BET_TYPE_ORDER_INDEX = {bt: i for i, bt in enumerate(_BET_TYPE_DISPLAY_ORDER)}


def _bet_type_sort_key(bt: str) -> tuple[int, str]:
    return (_BET_TYPE_ORDER_INDEX.get(bt, len(_BET_TYPE_DISPLAY_ORDER)), bt)


def _aggregate(bets: list[dict]) -> tuple[int, int, int, float, float]:
    """Return (wins, losses, pushes, profit, risk) for a list of graded bets."""
    wins = losses = pushes = 0
    profit = risk = 0.0
    for b in bets:
        r = str(b.get("result", "")).upper()
        if r == "W":
            wins += 1
        elif r == "L":
            losses += 1
        elif r == "P":
            pushes += 1
        p, k = unit_profit_and_risk(int(b["odds"]), r)
        profit += p
        risk += k
    return wins, losses, pushes, profit, risk


def format_season_summary(through_date: str, graded_bets: list[dict]) -> str:
    """Standalone message: rolling season record + per-bet-type breakdown with ROI.

    `graded_bets` should already be filtered to configured bet types and
    results (W/L/P) through `through_date`.
    """
    if not graded_bets:
        return f"**Season Totals — as of {through_date}**\n_No graded picks yet._"

    wins, losses, pushes, profit, risk = _aggregate(graded_bets)
    record = f"{wins}-{losses}-{pushes}"
    roi = (profit / risk * 100) if risk > 0 else 0.0
    lines = [
        f"**Season Totals — as of {through_date}**",
        f"_Record: {record} · {profit:+.2f}u · ROI {roi:+.1f}%_",
    ]
    by_type: dict[str, list[dict]] = {}
    for b in graded_bets:
        by_type.setdefault(b["bet_type"], []).append(b)
    for bt in sorted(by_type, key=_bet_type_sort_key):
        w, l, p, pr, rk = _aggregate(by_type[bt])
        rec = f"{w}-{l}-{p}"
        r = (pr / rk * 100) if rk > 0 else 0.0
        lines.append(f"• `{bt:<10}` {rec:<9} · {pr:+.2f}u · ROI {r:+.1f}%")
    return "\n".join(lines)


def format_grade_header(game_date: str, graded_bets: list[dict]) -> str:
    wins, losses, pushes, profit, risk = _aggregate(graded_bets)
    record = f"{wins}-{losses}-{pushes}"
    roi = (profit / risk * 100) if risk > 0 else 0.0
    lines = [
        f"**Grades — {game_date}**",
        f"_Record: {record} · {profit:+.2f}u · ROI {roi:+.1f}%_",
    ]
    by_type: dict[str, list[dict]] = {}
    for b in graded_bets:
        by_type.setdefault(b["bet_type"], []).append(b)
    for bt in sorted(by_type, key=_bet_type_sort_key):
        w, l, p, pr, _ = _aggregate(by_type[bt])
        lines.append(f"• `{bt:<10}` {w}-{l}-{p} · {pr:+.2f}u")
    return "\n".join(lines)


def split_grade_blocks(game_date: str, graded_bets: list[dict],
                       char_limit: int = DISCORD_MAX) -> list[str]:
    """Format graded bets as per-game code blocks, each message prefixed with
    a bold date header so the grades channel reads chronologically even when a
    date is split across multiple messages.

    Groups by game, chunks to respect the char limit.
    """
    date_header = f"**Grades — {game_date}**\n"
    effective_limit = char_limit - len(date_header)

    if not graded_bets:
        return [f"{date_header}_No graded picks._"]

    by_game: dict[str, list[dict]] = {}
    for b in graded_bets:
        by_game.setdefault(b["game"], []).append(b)

    messages: list[str] = []
    current = ""
    for game in sorted(by_game):
        block = format_grade_game_block(game, by_game[game])
        if len(block) > effective_limit:
            if current:
                messages.append(current)
                current = ""
            messages.append(block[:effective_limit])
            continue
        if not current:
            current = block
        elif len(current) + len(block) + 1 <= effective_limit:
            current = current + "\n" + block
        else:
            messages.append(current)
            current = block
    if current:
        messages.append(current)
    return [f"{date_header}{m}" for m in messages]


def split_to_messages(game_date: str, bets: list[dict],
                      char_limit: int = DISCORD_MAX) -> list[str]:
    """Format bets into Discord messages, each <= `char_limit` chars.

    Strategy:
      - First message is a header
      - Subsequent messages pack one or more game blocks greedily up to the limit
      - Single oversized game blocks are sub-split into multiple messages
    """
    if not bets:
        return [f"**Bet Card — {game_date}**\n_No picks._"]

    by_game: dict[str, list[dict]] = {}
    for b in bets:
        by_game.setdefault(b["game"], []).append(b)

    messages = [format_header(game_date, len(bets), len(by_game))]
    current = ""
    for game in sorted(by_game):
        block = format_game_block(game, by_game[game])
        if len(block) > char_limit:
            if current:
                messages.append(current)
                current = ""
            messages.extend(_split_oversized_block(game, by_game[game], char_limit))
            continue
        if not current:
            current = block
        elif len(current) + len(block) + 1 <= char_limit:
            current = current + "\n" + block
        else:
            messages.append(current)
            current = block
    if current:
        messages.append(current)
    return messages
