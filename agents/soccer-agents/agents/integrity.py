"""Integrity auditor: orphan bets + team-name mapping guardian.

Two checks, both safe to run daily:

1. audit_orphans()
   - Rows in bets.csv older than 48h with empty `result`.
   - Attempts to re-grade via results_grader; reports remaining orphans.

2. audit_name_mappings()
   - For each active league, fetches current Odds API team list.
   - Resolves each team via normalize_team_name → ESPN standings.
   - Flags any team whose profile comes back empty (record="") — a recent
     scraper/name-map drift that would silently produce zero-stat briefings.
"""
from __future__ import annotations
import logging
from datetime import date, timedelta

import click
import pandas as pd

from config import ACTIVE_LEAGUES
from tracker import load_bets
from scrapers.odds import get_soccer_odds
from scrapers.name_map import normalize_team_name
from scrapers.team_stats import get_team_profile

logger = logging.getLogger("mirofish.integrity")


def audit_orphans(stale_days: int = 2, attempt_regrade: bool = True) -> dict:
    df = load_bets()
    if df.empty or "date" not in df:
        return {"orphans": 0, "regraded": 0, "remaining": 0}

    parsed = pd.to_datetime(df["date"], errors="coerce")
    cutoff = pd.Timestamp(date.today() - timedelta(days=stale_days))
    stale_mask = (parsed <= cutoff) & (~df["result"].isin(["W", "L", "P"]))
    orphans = df[stale_mask]
    logger.info("Integrity: found %d orphan bet(s) older than %d days", len(orphans), stale_days)

    regraded_count = 0
    if attempt_regrade and len(orphans):
        from agents.results_grader import run_results_grader

        dates_to_regrade = sorted({d for d in orphans["date"].tolist() if d})
        for d in dates_to_regrade:
            logger.info("Integrity: attempting re-grade for %s", d)
            try:
                run_results_grader(d)
                regraded_count += 1
            except Exception as e:
                logger.error("Integrity: re-grade failed for %s: %s", d, e)

    # Re-check orphans after regrade
    df2 = load_bets()
    parsed2 = pd.to_datetime(df2["date"], errors="coerce")
    stale2 = (parsed2 <= cutoff) & (~df2["result"].isin(["W", "L", "P"]))
    remaining = int(stale2.sum())

    return {
        "orphans": int(len(orphans)),
        "regrade_dates": regraded_count,
        "remaining": remaining,
    }


def audit_name_mappings(leagues: list[str] | None = None) -> dict:
    leagues = leagues or ACTIVE_LEAGUES
    unmapped: dict[str, list[str]] = {}

    for lg in leagues:
        try:
            odds_list = get_soccer_odds(league=lg)
        except Exception as e:
            logger.error("Integrity: odds fetch failed for %s: %s", lg, e)
            continue

        missed = []
        seen: set[str] = set()
        for o in odds_list or []:
            for raw_name in (o.home, o.away):
                if not raw_name or raw_name in seen:
                    continue
                seen.add(raw_name)
                normalized = normalize_team_name(raw_name, lg)
                profile = get_team_profile(normalized, league=lg)
                if not profile.get("record"):
                    missed.append(f"{raw_name!r} → {normalized!r}")
        unmapped[lg] = missed
        if missed:
            logger.warning("Integrity: %s has %d unmapped team(s): %s", lg, len(missed), missed)
        else:
            logger.info("Integrity: %s name mappings OK (%d teams)", lg, len(seen))

    return unmapped


@click.group()
def cli():
    pass


@cli.command("orphans")
@click.option("--stale-days", default=2, help="Mark bets stale after this many days")
@click.option("--no-regrade", is_flag=True, help="Only report, don't attempt regrade")
def orphans(stale_days, no_regrade):
    result = audit_orphans(stale_days=stale_days, attempt_regrade=not no_regrade)
    click.echo(f"\nOrphan audit: {result['orphans']} initial, "
               f"{result['regrade_dates']} dates regraded, "
               f"{result['remaining']} still orphaned")


@cli.command("names")
def names():
    result = audit_name_mappings()
    total_missed = sum(len(v) for v in result.values())
    click.echo(f"\nName mapping audit: {total_missed} unmapped across {len(result)} leagues")
    for lg, items in result.items():
        status = f"{len(items)} unmapped" if items else "OK"
        click.echo(f"  {lg}: {status}")
        for item in items:
            click.echo(f"    - {item}")


if __name__ == "__main__":
    cli()
