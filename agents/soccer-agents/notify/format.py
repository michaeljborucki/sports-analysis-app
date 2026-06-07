"""Format filtered bets into Discord-ready messages for soccer picks.

Discord flavor: ``` for code blocks, **bold**, _italic_. Each message capped
at 1900 chars (Discord limit is 2000; headroom for code fences).
"""

DISCORD_MAX = 1900


def filter_bets(bets: list[dict], allowed_types: list[str],
                min_edge: float = 0.0, min_kelly: float = 0.0) -> list[dict]:
    """Keep only bets whose type is in `allowed_types` and meet edge/Kelly floors."""
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


def _format_bet_line(bet: dict) -> str:
    odds = int(bet["odds"])
    odds_str = f"+{odds}" if odds > 0 else str(odds)
    sim = float(bet["sim_prob"]) * 100
    edge = float(bet["edge"]) * 100
    kelly = float(bet["kelly_pct"]) * 100
    return (
        f"  {bet['bet_type']:<14} | {str(bet['side']):<18} | "
        f"{odds_str:>5} | Model {sim:5.1f}% | Edge {edge:5.1f}% | "
        f"Kelly {kelly:5.2f}%"
    )


def format_game_block(game_key: str, picks: list[dict]) -> str:
    sorted_picks = sorted(picks, key=lambda b: -float(b.get("edge", 0)))
    body = f"{game_key}\n{'-' * 40}\n" + "\n".join(_format_bet_line(b) for b in sorted_picks)
    return f"```\n{body}\n```"


def format_header(game_date: str, n_picks: int, n_games: int) -> str:
    return (
        f"**MIROFISH SOCCER BET CARD — {game_date}**\n"
        f"_{n_picks} picks across {n_games} matches_"
    )


def _split_oversized_block(game_key: str, picks: list[dict], char_limit: int) -> list[str]:
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


def split_to_messages(game_date: str, bets: list[dict],
                      char_limit: int = DISCORD_MAX) -> list[str]:
    """Split bets into messages, each ≤ char_limit chars. Header first, then
    greedy pack of per-match code blocks.
    """
    if not bets:
        return [f"**MIROFISH SOCCER BET CARD — {game_date}**\n_No picks._"]

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
