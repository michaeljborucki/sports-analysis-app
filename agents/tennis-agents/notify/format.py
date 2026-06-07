"""Format filtered bets into Discord-ready messages.

Discord uses its own Markdown flavor: ``` for code blocks, **bold**, _italic_.
Messages are capped at 2000 chars per webhook post — we target 1900 to leave
headroom for code fences.

Unit convention (tennis): favorites risk |odds|/100 to win 1u, underdogs risk
1u to win odds/100. Sourced from ``tracker._profit_units`` / ``_stake_units``
so notify output stays in lockstep with what's persisted in bets.csv.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from scrapers.odds import prob_to_american, american_be_with_wiggle
from tracker import _profit_units, _stake_units

DISCORD_MAX = 1900

# Local display timezone — matches the grade-tick convention so operator-facing
# output is consistent across picks / grades / bet-card channels.
DISPLAY_TZ = ZoneInfo("America/Denver")


def format_start_time_local(start_time: str) -> str:
    """Render an ISO-8601 UTC timestamp as e.g. ``'8:00 AM MT'``.

    Input: ``'2026-04-23T14:00:00Z'`` (schedule scraper format) or an
    ISO-8601 variant with ``+00:00``. Returns empty string if ``start_time``
    is empty or unparseable — callers skip the time-suffix cleanly.
    """
    if not start_time:
        return ""
    try:
        clean = str(start_time).strip().replace("Z", "+00:00")
        utc_dt = datetime.fromisoformat(clean)
        local_dt = utc_dt.astimezone(DISPLAY_TZ)
        hour = local_dt.strftime("%I").lstrip("0") or "0"
        return f"{hour}:{local_dt.strftime('%M %p')} MT"
    except (ValueError, TypeError):
        return ""


def _first_start_time(picks: list[dict]) -> str:
    """Find the first non-empty ``start_time`` across a match's picks.
    All picks in a match share the same start_time, but be defensive in
    case some rows were logged without it.
    """
    for p in picks:
        st = p.get("start_time")
        if st:
            return str(st)
    return ""


def _resolve_side(game: str, side: str) -> str:
    """Replace 'player_a' / 'player_b' tokens in a side string with actual names from the game key."""
    if not game or " vs " not in str(game) or not side:
        return str(side)
    left, right = str(game).split(" vs ", 1)
    return str(side).replace("player_a", left.strip()).replace("player_b", right.strip())


def filter_bets(bets: list[dict], allowed_types: list[str],
                min_edge: float = 0.0, min_kelly: float = 0.0) -> list[dict]:
    """Keep bets whose type is in `allowed_types` and meet thresholds."""
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
    f"  {'TYPE':<14} | {'SIDE':<20} | "
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
    except (ValueError, TypeError):
        be_str = "N/A"
    side_display = _resolve_side(bet.get("game", ""), bet.get("side", ""))
    return (
        f"  {str(bet['bet_type']):<14} | {side_display:<20} | "
        f"{odds_str:>5} | {sim:4.1f}% | {edge:4.1f}% | {be_str:>5}"
    )


def format_match_block(match_key: str, picks: list[dict]) -> str:
    sorted_picks = sorted(picks, key=lambda b: -float(b.get("edge", 0)))
    time_str = format_start_time_local(_first_start_time(picks))
    header = f"{match_key} — {time_str}" if time_str else match_key
    body = (
        f"{header}\n{'-' * 40}\n"
        f"{_HEADER_LINE}\n"
        + "\n".join(_format_bet_line(b) for b in sorted_picks)
    )
    return f"```\n{body}\n```"


def format_header(game_date: str, n_picks: int, n_matches: int) -> str:
    return (
        f"**Bet Card — {game_date}**\n"
        f"_{n_picks} picks across {n_matches} matches_"
    )


def _split_oversized_block(match_key: str, picks: list[dict], char_limit: int) -> list[str]:
    sorted_picks = sorted(picks, key=lambda b: -float(b.get("edge", 0)))
    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []
    for pick in sorted_picks:
        current_chunk.append(pick)
        if len(format_match_block(match_key, current_chunk)) > char_limit:
            popped = current_chunk.pop()
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = [popped]
    if current_chunk:
        chunks.append(current_chunk)
    return [format_match_block(match_key, c) for c in chunks]


_GRADE_HEADER_LINE = (
    f"  {'TYPE':<14} | {'SIDE':<20} | "
    f"{'ODDS':>5} | {'RESULT':<6} | {'UNITS':>6} | {'CLV':>5}"
)


def unit_profit_and_risk(odds: int, result: str) -> tuple[float, float]:
    """Per-bet (profit, risk) in tennis convention.

    Delegates to ``tracker._profit_units`` / ``_stake_units`` so ROI here
    matches what's persisted in bets.csv. Pushes are excluded from the risk
    denominator (stake returned).
    """
    odds = int(odds)
    profit = _profit_units(odds, result)
    risk = _stake_units(odds) if result in ("W", "L") else 0.0
    return profit, risk


def _format_clv_cents(bet: dict) -> str:
    """Render CLV cents as a signed compact string, or ``  n/a`` if not tracked."""
    raw = bet.get("clv_cents")
    if raw is None or str(raw).strip() in ("", "nan", "NaN"):
        return "  n/a"
    try:
        cents = int(float(raw))
    except (TypeError, ValueError):
        return "  n/a"
    return f"{cents:+4d}"


def _format_grade_line(bet: dict) -> str:
    odds = int(bet["odds"])
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    result = str(bet.get("result", "")).upper()
    profit, _ = unit_profit_and_risk(odds, result)
    units_str = f"{profit:+.2f}" if result in ("W", "L") else " 0.00"
    side_display = _resolve_side(bet.get("game", ""), bet.get("side", ""))
    clv_str = _format_clv_cents(bet)
    return (
        f"  {str(bet['bet_type']):<14} | {side_display:<20} | "
        f"{odds_str:>5} | {result:<6} | {units_str:>6} | {clv_str:>5}"
    )


def format_grade_match_block(match_key: str, picks: list[dict]) -> str:
    sorted_picks = sorted(picks, key=lambda b: {"W": 0, "L": 1, "P": 2}.get(
        str(b.get("result", "")).upper(), 3))
    time_str = format_start_time_local(_first_start_time(picks))
    header = f"{match_key} — {time_str}" if time_str else match_key
    body = (
        f"{header}\n{'-' * 40}\n"
        f"{_GRADE_HEADER_LINE}\n"
        + "\n".join(_format_grade_line(b) for b in sorted_picks)
    )
    return f"```\n{body}\n```"


def _aggregate(bets: list[dict]) -> tuple[int, int, int, float, float]:
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


def _aggregate_clv(bets: list[dict]) -> dict:
    """Count +CLV / -CLV / flat / untracked bets and average CLV%.

    'untracked' = bet has no closing line captured (API miss, book not carried, etc.)
    Returns zeros cleanly when the input is empty.
    """
    beat = lost = flat = untracked = 0
    pcts = []
    for b in bets:
        raw_cents = b.get("clv_cents")
        if raw_cents is None or str(raw_cents).strip() in ("", "nan", "NaN"):
            untracked += 1
            continue
        try:
            cents = int(float(raw_cents))
            pct = float(b.get("clv_pct", 0) or 0)
        except (TypeError, ValueError):
            untracked += 1
            continue
        pcts.append(pct)
        if cents > 0:
            beat += 1
        elif cents < 0:
            lost += 1
        else:
            flat += 1
    avg_pct = round((sum(pcts) / len(pcts)) * 100, 1) if pcts else 0.0
    return {"beat": beat, "lost": lost, "flat": flat, "untracked": untracked,
            "tracked": len(pcts), "avg_pct": avg_pct}


def format_season_summary(through_date: str, graded_bets: list[dict]) -> str:
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
    for bt in sorted(by_type, key=lambda t: -len(by_type[t])):
        w, l, p, pr, rk = _aggregate(by_type[bt])
        rec = f"{w}-{l}-{p}"
        r = (pr / rk * 100) if rk > 0 else 0.0
        lines.append(f"• `{bt:<14}` {rec:<9} · {pr:+.2f}u · ROI {r:+.1f}%")
    return "\n".join(lines)


def _format_clv_summary_line(clv: dict) -> str:
    """Render CLV aggregate as '· CLV avg +3.2% · 2↑ 1↓ 0= (1 untracked)'."""
    if clv["tracked"] == 0 and clv["untracked"] == 0:
        return ""
    pieces = [f"CLV avg {clv['avg_pct']:+.1f}%"]
    if clv["tracked"]:
        pieces.append(f"{clv['beat']}↑ {clv['lost']}↓ {clv['flat']}=")
    if clv["untracked"]:
        pieces.append(f"{clv['untracked']} untracked")
    return " · ".join(pieces)


def format_grade_header(game_date: str, graded_bets: list[dict]) -> str:
    wins, losses, pushes, profit, risk = _aggregate(graded_bets)
    clv = _aggregate_clv(graded_bets)
    record = f"{wins}-{losses}-{pushes}"
    roi = (profit / risk * 100) if risk > 0 else 0.0
    summary_bits = [f"Record: {record}", f"{profit:+.2f}u", f"ROI {roi:+.1f}%"]
    clv_line = _format_clv_summary_line(clv)
    if clv_line:
        summary_bits.append(clv_line)
    lines = [
        f"**Grades — {game_date}**",
        f"_{' · '.join(summary_bits)}_",
    ]
    by_type: dict[str, list[dict]] = {}
    for b in graded_bets:
        by_type.setdefault(b["bet_type"], []).append(b)
    for bt in sorted(by_type, key=lambda t: -len(by_type[t])):
        w, l, p, pr, _ = _aggregate(by_type[bt])
        bt_clv = _aggregate_clv(by_type[bt])
        clv_suffix = f" · CLV {bt_clv['avg_pct']:+.1f}%" if bt_clv["tracked"] else ""
        lines.append(f"• `{bt:<14}` {w}-{l}-{p} · {pr:+.2f}u{clv_suffix}")
    return "\n".join(lines)


def format_grade_card_header(game_date: str, n_bets: int, n_matches: int) -> str:
    """Date-stamped title for the grades channel (channel 2).

    Posted ahead of the per-match grade blocks so scrollback clearly
    associates blocks with the date they cover.
    """
    return (
        f"**Grades — {game_date}**\n"
        f"_{n_bets} graded pick(s) across {n_matches} match(es)_"
    )


def split_grade_blocks(game_date: str, graded_bets: list[dict],
                       char_limit: int = DISCORD_MAX) -> list[str]:
    if not graded_bets:
        return [f"**Grades — {game_date}**\n_No graded picks for this date._"]

    by_match: dict[str, list[dict]] = {}
    for b in graded_bets:
        by_match.setdefault(b["game"], []).append(b)

    messages: list[str] = [format_grade_card_header(game_date, len(graded_bets), len(by_match))]
    current = ""
    for match in sorted(by_match):
        block = format_grade_match_block(match, by_match[match])
        if len(block) > char_limit:
            if current:
                messages.append(current)
                current = ""
            messages.append(block[:char_limit])
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


def split_to_messages(game_date: str, bets: list[dict],
                      char_limit: int = DISCORD_MAX) -> list[str]:
    if not bets:
        return [f"**Bet Card — {game_date}**\n_No picks._"]

    by_match: dict[str, list[dict]] = {}
    for b in bets:
        by_match.setdefault(b["game"], []).append(b)

    messages = [format_header(game_date, len(bets), len(by_match))]
    current = ""
    for match in sorted(by_match):
        block = format_match_block(match, by_match[match])
        if len(block) > char_limit:
            if current:
                messages.append(current)
                current = ""
            messages.extend(_split_oversized_block(match, by_match[match], char_limit))
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
