"""Self-optimizer: analyzes performance and tunes edge thresholds + Kelly fraction."""
import click
import json
import os
from datetime import date, timedelta
import pandas as pd

from tracker import load_bets, get_summary
from config import EDGE_THRESHOLDS, DATA_DIR, MODEL_PREDICTIONS_CSV


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


def compute_model_brier_scores() -> dict:
    """Compute per-model, per-bet-type Brier scores from prediction logs and graded bets.

    Joins model_predictions.csv with bets.csv on (date, game, bet_type).
    Only includes model/slot combos with 10+ graded samples.
    Returns {model: {bet_type: brier_score}}.
    """
    # Load predictions CSV (may be corrupted with extra columns)
    if not os.path.exists(MODEL_PREDICTIONS_CSV):
        return {}
    try:
        raw = pd.read_csv(MODEL_PREDICTIONS_CSV, on_bad_lines="skip")
    except Exception:
        return {}
    if raw.empty:
        return {}

    real_cols = ["date", "game", "model", "bet_type", "side",
                 "sim_prob", "market_prob", "edge", "temperature", "run_index"]

    # Try to find the real data columns: check if named columns exist
    if "date" in raw.columns and "game" in raw.columns:
        # Clean CSV with proper headers
        preds = raw[real_cols].copy()
    elif raw.shape[1] >= 20:
        # Corrupted CSV: real data is in columns 10-19 (0-indexed)
        preds = raw.iloc[:, 10:20].copy()
        preds.columns = real_cols
    elif raw.shape[1] >= 10:
        # Fallback: take last 10 columns
        preds = raw.iloc[:, -10:].copy()
        preds.columns = real_cols
    else:
        return {}

    preds["sim_prob"] = pd.to_numeric(preds["sim_prob"], errors="coerce")
    preds = preds.dropna(subset=["sim_prob", "game", "date"])

    if preds.empty:
        return {}

    # Load settled bets
    bets = load_bets()
    settled = bets[bets["result"].isin(["W", "L"])].copy()
    if settled.empty:
        return {}

    # Merge predictions with settled bets on (date, game, bet_type)
    settled["outcome"] = (settled["result"] == "W").astype(float)
    merged = preds.merge(
        settled[["date", "game", "bet_type", "outcome"]],
        on=["date", "game", "bet_type"],
        how="inner",
    )

    if merged.empty:
        return {}

    # Compute Brier score per (model, bet_type)
    merged["brier"] = (merged["sim_prob"] - merged["outcome"]) ** 2
    grouped = merged.groupby(["model", "bet_type"])["brier"]

    scores = {}
    for (model, bt), group in grouped:
        if len(group) >= 10:
            scores.setdefault(model, {})[bt] = round(group.mean(), 4)

    return scores


def update_model_weights(brier_scores: dict) -> dict:
    """Update model weights based on Brier scores. Lower Brier = higher weight.

    Normalizes so mean weight per slot = 1.0.
    Clamps to [0.3, 3.0].
    Returns the new weights dict.
    """
    from ensemble.weights import load_weights, save_weights, BET_SLOTS, default_weights

    weights = default_weights()

    for slot in BET_SLOTS:
        # Collect brier scores for this slot across all models
        slot_scores = {}
        for model, model_scores in brier_scores.items():
            if slot in model_scores:
                slot_scores[model] = max(model_scores[slot], 0.01)

        if not slot_scores:
            # No scores for this slot, leave weights at 1.0
            continue

        # raw_weight = 1.0 / brier_score
        raw = {m: 1.0 / s for m, s in slot_scores.items()}
        mean_raw = sum(raw.values()) / len(raw)

        for model, raw_w in raw.items():
            # Normalize so average = 1.0
            normalized = raw_w / mean_raw
            # Clamp to [0.3, 3.0]
            clamped = max(0.3, min(3.0, normalized))
            weights.setdefault(model, {})[slot] = round(clamped, 4)

    save_weights(weights)
    return weights


def compute_threshold_overrides() -> dict:
    """Compute edge threshold overrides based on historical ROI per bet type.

    Rules (require 30+ settled bets):
    - ROI < -15% -> disable (null)
    - ROI between -15% and -5% -> raise threshold by 2 percentage points
    - ROI > +5% -> lower threshold by 1 percentage point (floor at 3%)
    - Otherwise -> no override

    Returns dict to write to edge_overrides.json.
    """
    df = load_bets()
    by_type = analyze_by_bet_type(df)
    overrides = {}

    for bt, stats in by_type.items():
        if stats["total"] < 30:
            continue
        roi = stats["roi"]
        current_threshold = EDGE_THRESHOLDS.get(bt, 0.05)

        if roi < -15:
            overrides[bt] = None  # disabled
        elif roi < -5:
            overrides[bt] = round(current_threshold + 0.02, 4)
        elif roi > 5:
            overrides[bt] = round(max(current_threshold - 0.01, 0.03), 4)

    # Save to data/edge_overrides.json
    overrides_path = os.path.join(DATA_DIR, "edge_overrides.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(overrides_path, "w") as f:
        json.dump(overrides, f, indent=2)

    return overrides


def apply_learnings():
    """Post-grade learning step: update model weights and edge thresholds."""
    click.echo("\n" + "=" * 60)
    click.echo("  MIROFISH LEARNING LOOP")
    click.echo("=" * 60)

    # Update model weights from Brier scores
    click.echo("\n  --- Model Weight Update ---")
    brier_scores = compute_model_brier_scores()
    if brier_scores:
        weights = update_model_weights(brier_scores)
        for model, model_scores in brier_scores.items():
            for bt, score in model_scores.items():
                w = weights.get(model, {}).get(bt, 1.0)
                click.echo(f"    {model:12s} | {bt:20s} | Brier: {score:.4f} | Weight: {w:.4f}")
    else:
        click.echo("    No Brier scores available (need 10+ graded predictions per model/slot)")

    # Update edge threshold overrides
    click.echo("\n  --- Edge Threshold Overrides ---")
    overrides = compute_threshold_overrides()
    if overrides:
        for bt, threshold in overrides.items():
            if threshold is None:
                click.echo(f"    {bt:20s} | DISABLED (ROI < -15%)")
            else:
                current = EDGE_THRESHOLDS.get(bt, 0.05)
                direction = "raised" if threshold > current else "lowered"
                click.echo(f"    {bt:20s} | {direction} to {threshold:.2%} (was {current:.2%})")
    else:
        click.echo("    No overrides needed (insufficient data or all types performing OK)")

    click.echo("\n  Learning loop complete.")
    click.echo("=" * 60 + "\n")


@click.command()
@click.option("--min-bets", default=30, help="Minimum settled bets to analyze")
def main(min_bets):
    """Analyze historical performance and recommend threshold adjustments."""
    run_optimizer(min_bets)


if __name__ == "__main__":
    main()
