"""CLV snap-close agent.

Run pre-kickoff (~15 min before earliest match). Fetches current odds for each
active league, matches to today's pending bets, and records close_market_prob +
CLV in the bet log. CLV = close_market_prob - market_prob (at bet time).

Positive CLV = line moved toward our side after we bet = we got the better price.
"""
from __future__ import annotations
import logging
from datetime import date

import click
import pandas as pd

from config import ACTIVE_LEAGUES
from scrapers.odds import get_soccer_odds, american_to_implied_prob, power_devig
from tracker import load_bets, update_close_prob

logger = logging.getLogger("mirofish.clv_snapshotter")


def _implied_for_side(bet_type: str, side: str, odds_obj) -> float | None:
    """Extract the devigged implied prob for this bet's side from an OddsData object."""
    implied = odds_obj.implied_probs or {}
    side = str(side).lower().strip()

    if bet_type == "asian_handicap":
        if side.startswith("home"):
            return implied.get("ah_home")
        if side.startswith("away"):
            return implied.get("ah_away")
    elif bet_type == "total":
        if side.startswith("over"):
            return implied.get("over")
        if side.startswith("under"):
            return implied.get("under")
    elif bet_type == "btts":
        if side == "yes":
            return implied.get("btts_yes")
        if side == "no":
            return implied.get("btts_no")
    return None


def snap_close_for_date(game_date: str | None = None, leagues: list[str] | None = None) -> dict:
    game_date = game_date or date.today().isoformat()
    leagues = leagues or ACTIVE_LEAGUES

    df = load_bets()
    pending_mask = (
        (df["date"] == game_date)
        & (~df["result"].isin(["W", "L", "P"]))
        & (pd.to_numeric(df["close_market_prob"], errors="coerce").isna())
    )
    pending = df[pending_mask]
    if pending.empty:
        logger.info("No pending bets without close snapshots for %s", game_date)
        return {"updated": 0, "skipped": 0, "pending_total": 0}

    odds_by_game: dict[str, object] = {}
    for lg in leagues:
        try:
            for o in get_soccer_odds(league=lg) or []:
                odds_by_game[f"{o.away}@{o.home}"] = o
        except Exception as e:
            logger.error("CLV snapshot: failed to fetch %s odds: %s", lg, e)

    updated = skipped = 0
    for idx, row in pending.iterrows():
        key = str(row["game"])
        odds_obj = odds_by_game.get(key)
        if not odds_obj:
            skipped += 1
            continue
        close_prob = _implied_for_side(row["bet_type"], row["side"], odds_obj)
        if close_prob is None or close_prob <= 0:
            skipped += 1
            continue
        update_close_prob(int(idx), float(close_prob))
        updated += 1
        logger.info(
            "CLV snap %s | %s %s | bet=%.4f close=%.4f clv=%+.4f",
            key, row["bet_type"], row["side"],
            float(row.get("market_prob") or 0), close_prob,
            close_prob - float(row.get("market_prob") or 0),
        )

    logger.info("CLV snapshot: updated=%d, skipped=%d, total_pending=%d",
                updated, skipped, len(pending))
    return {"updated": updated, "skipped": skipped, "pending_total": len(pending)}


@click.command()
@click.option("--date", "game_date", default=None, help="Date (YYYY-MM-DD), default today")
def main(game_date):
    """Snapshot closing market prob for today's pending bets."""
    result = snap_close_for_date(game_date)
    click.echo(
        f"CLV snapshot: {result['updated']} updated, {result['skipped']} skipped "
        f"(of {result['pending_total']} pending)"
    )


if __name__ == "__main__":
    main()
