"""Self-optimizer: analyzes performance and tunes edge thresholds + Kelly fraction."""
import click
import json
from datetime import date, timedelta
import pandas as pd

from tracker import load_bets, get_summary


def analyze_by_bet_type(df: pd.DataFrame) -> dict:
    """Break down performance by bet type."""
    results = {}
    for bt in df["bet_type"].unique():
        subset = df[df["bet_type"] == bt]
        settled = subset[subset["result"].isin(["W", "L", "P"])]
        if settled.empty:
            continue

        wins = len(settled[settled["result"] == "W"])
        losses = len(settled[settled["result"] == "L"])
        total = len(settled)
        profit = float(settled["profit"].sum())

        results[bt] = {
            "total": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total, 3),
            "profit": round(profit, 2),
            "roi": round(profit / total * 100, 1),
            "avg_edge": round(float(settled["edge"].mean()), 4),
            "avg_odds": round(float(settled["odds"].mean()), 0),
        }

    return results


def analyze_by_edge_bucket(df: pd.DataFrame) -> dict:
    """Break down performance by edge size buckets."""
    settled = df[df["result"].isin(["W", "L", "P"])].copy()
    if settled.empty:
        return {}

    settled["edge_float"] = settled["edge"].astype(float)
    buckets = [
        ("3-5%", 0.03, 0.05),
        ("5-8%", 0.05, 0.08),
        ("8-12%", 0.08, 0.12),
        ("12%+", 0.12, 1.0),
    ]

    results = {}
    for label, lo, hi in buckets:
        subset = settled[(settled["edge_float"] >= lo) & (settled["edge_float"] < hi)]
        if subset.empty:
            continue
        wins = len(subset[subset["result"] == "W"])
        total = len(subset)
        profit = float(subset["profit"].sum())
        results[label] = {
            "total": total,
            "win_rate": round(wins / total, 3),
            "profit": round(profit, 2),
            "roi": round(profit / total * 100, 1),
        }

    return results


def analyze_by_odds_range(df: pd.DataFrame) -> dict:
    """Break down by odds range (heavy fav, slight fav, dog, big dog)."""
    settled = df[df["result"].isin(["W", "L", "P"])].copy()
    if settled.empty:
        return {}

    settled["odds_float"] = settled["odds"].astype(float)
    ranges = [
        ("Heavy Fav (<-200)", -9999, -200),
        ("Fav (-200 to -110)", -200, -110),
        ("Pick (-110 to +110)", -110, 110),
        ("Dog (+110 to +200)", 110, 200),
        ("Big Dog (>+200)", 200, 9999),
    ]

    results = {}
    for label, lo, hi in ranges:
        subset = settled[(settled["odds_float"] >= lo) & (settled["odds_float"] <= hi)]
        if subset.empty:
            continue
        wins = len(subset[subset["result"] == "W"])
        total = len(subset)
        profit = float(subset["profit"].sum())
        results[label] = {
            "total": total,
            "win_rate": round(wins / total, 3),
            "profit": round(profit, 2),
            "roi": round(profit / total * 100, 1),
        }

    return results


def analyze_recent_trend(df: pd.DataFrame, window_days: int = 14) -> dict:
    """Compare recent performance vs overall."""
    settled = df[df["result"].isin(["W", "L", "P"])].copy()
    if settled.empty:
        return {}

    settled["date_parsed"] = pd.to_datetime(settled["date"])
    cutoff = pd.Timestamp(date.today() - timedelta(days=window_days))
    recent = settled[settled["date_parsed"] >= cutoff]

    if recent.empty:
        return {"status": "no_recent_data"}

    overall_roi = float(settled["profit"].sum()) / len(settled) * 100
    recent_roi = float(recent["profit"].sum()) / len(recent) * 100

    return {
        "overall_roi": round(overall_roi, 1),
        "recent_roi": round(recent_roi, 1),
        "recent_bets": len(recent),
        "trend": "improving" if recent_roi > overall_roi else "declining",
    }


def recommend_adjustments(by_type: dict, by_edge: dict) -> list[str]:
    """Generate actionable recommendations based on analysis."""
    recs = []

    # Check each bet type
    for bt, stats in by_type.items():
        if stats["total"] < 20:
            recs.append(f"  {bt}: Only {stats['total']} bets — need more data to evaluate")
            continue

        if stats["roi"] < -10:
            recs.append(
                f"  {bt}: LOSING (ROI {stats['roi']:+.1f}%) — "
                f"raise edge threshold or disable this bet type"
            )
        elif stats["roi"] < 0:
            recs.append(
                f"  {bt}: Slightly negative (ROI {stats['roi']:+.1f}%) — "
                f"consider raising edge threshold by 1-2%"
            )
        elif stats["roi"] > 5:
            recs.append(
                f"  {bt}: PROFITABLE (ROI {stats['roi']:+.1f}%) — "
                f"current thresholds working well, could lower slightly for more volume"
            )

    # Check edge buckets
    for bucket, stats in by_edge.items():
        if stats["total"] >= 10 and stats["roi"] < -5:
            recs.append(
                f"  Edge bucket {bucket}: Negative ROI ({stats['roi']:+.1f}%) — "
                f"raise minimum edge threshold above this range"
            )

    if not recs:
        recs.append("  No strong signals yet — keep collecting data")

    return recs


def run_optimizer(min_bets: int = 30):
    """Run full optimization analysis and print report."""
    click.echo("\n" + "=" * 60)
    click.echo("  MIROFISH SELF-OPTIMIZER")
    click.echo("=" * 60)

    df = load_bets()
    settled = df[df["result"].isin(["W", "L", "P"])]

    if len(settled) < min_bets:
        click.echo(f"\nInsufficient data: {len(settled)} settled bets (need {min_bets})")
        click.echo("Keep collecting data. Run again after more games.\n")
        return

    summary = get_summary()
    click.echo(f"\n  Overall: {summary['record']} | {summary['profit']:+.2f} units | ROI: {summary['roi']}%")
    click.echo(f"  Settled: {len(settled)} bets\n")

    # By bet type
    click.echo("  --- Performance by Bet Type ---")
    by_type = analyze_by_bet_type(df)
    for bt, stats in by_type.items():
        click.echo(
            f"    {bt:12s} | {stats['wins']}-{stats['losses']} "
            f"({stats['win_rate']:.0%}) | {stats['profit']:+.2f}u | ROI: {stats['roi']:+.1f}%"
        )

    # By edge bucket
    click.echo("\n  --- Performance by Edge Size ---")
    by_edge = analyze_by_edge_bucket(df)
    for bucket, stats in by_edge.items():
        click.echo(
            f"    {bucket:12s} | {stats['total']:3d} bets | "
            f"Win: {stats['win_rate']:.0%} | {stats['profit']:+.2f}u | ROI: {stats['roi']:+.1f}%"
        )

    # By odds range
    click.echo("\n  --- Performance by Odds Range ---")
    by_odds = analyze_by_odds_range(df)
    for rng, stats in by_odds.items():
        click.echo(
            f"    {rng:24s} | {stats['total']:3d} bets | "
            f"Win: {stats['win_rate']:.0%} | {stats['profit']:+.2f}u | ROI: {stats['roi']:+.1f}%"
        )

    # Recent trend
    click.echo("\n  --- Recent Trend (14 days) ---")
    trend = analyze_recent_trend(df)
    if trend.get("status") == "no_recent_data":
        click.echo("    No recent data")
    elif trend:
        arrow = "↑" if trend["trend"] == "improving" else "↓"
        click.echo(
            f"    Overall ROI: {trend['overall_roi']:+.1f}% | "
            f"Last 14d ROI: {trend['recent_roi']:+.1f}% {arrow} "
            f"({trend['recent_bets']} bets)"
        )

    # Recommendations
    click.echo("\n  --- Recommendations ---")
    recs = recommend_adjustments(by_type, by_edge)
    for rec in recs:
        click.echo(rec)

    click.echo("\n" + "=" * 60 + "\n")


def compute_model_brier_scores(preds_df: pd.DataFrame, bets_df: pd.DataFrame) -> dict:
    """Compute per-model, per-bet-type Brier scores from prediction logs and results."""
    if preds_df.empty or bets_df.empty:
        return {}

    scores = {}
    for model in preds_df["model"].unique():
        model_preds = preds_df[preds_df["model"] == model]
        scores[model] = {}
        for bt in model_preds["bet_type"].unique():
            bt_preds = model_preds[model_preds["bet_type"] == bt]
            brier_values = []
            for _, pred in bt_preds.iterrows():
                matching = bets_df[
                    (bets_df["bet_type"] == bt) &
                    (bets_df["result"].isin(["W", "L"]))
                ]
                if matching.empty:
                    continue
                outcome = 1.0 if matching.iloc[0]["result"] == "W" else 0.0
                brier_values.append((pred["sim_prob"] - outcome) ** 2)

            if brier_values:
                scores[model][bt] = round(sum(brier_values) / len(brier_values), 4)

    return scores


def update_model_weights(brier_scores: dict, bet_slots: list[str] = None,
                         weights_path: str = None) -> None:
    """Update model weights based on Brier scores. Lower Brier = higher weight."""
    from ensemble.weights import load_weights, save_weights

    if bet_slots is None:
        raise ValueError("update_model_weights requires bet_slots parameter")

    weights = load_weights(bet_slots, weights_path)

    for slot in bet_slots:
        slot_scores = {}
        for model, scores in brier_scores.items():
            if slot in scores:
                slot_scores[model] = max(scores[slot], 0.01)  # floor at 0.01

        if not slot_scores:
            continue

        raw = {m: 1.0 / s for m, s in slot_scores.items()}
        total = sum(raw.values())
        n = len(raw)
        for model, raw_w in raw.items():
            weights.setdefault(model, {})[slot] = round(raw_w / total * n, 4)

    save_weights(weights, weights_path)


@click.command()
@click.option("--min-bets", default=30, help="Minimum settled bets to analyze")
def main(min_bets):
    """Analyze historical performance and recommend threshold adjustments."""
    run_optimizer(min_bets)


if __name__ == "__main__":
    main()
