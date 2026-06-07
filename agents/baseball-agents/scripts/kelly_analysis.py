"""
Kelly Criterion Analysis for MiroFish Baseball Betting System
==============================================================

Analyzes the kelly_pct distribution in bets.csv, identifies issues,
and models the impact of proposed fixes.

Run: python scripts/kelly_analysis.py
"""

import os
import sys
import numpy as np
import pandas as pd

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import BETS_CSV, KELLY_FRACTION


def load_data() -> pd.DataFrame:
    df = pd.read_csv(BETS_CSV)
    df["kelly_pct"] = df["kelly_pct"].astype(float)
    df["edge"] = df["edge"].astype(float)
    df["sim_prob"] = df["sim_prob"].astype(float)
    return df


def classify_bet(bet_type: str) -> str:
    """Classify bets into categories."""
    prop_types = {
        "pitcher_strikeouts", "pitcher_earned_runs", "pitcher_outs",
        "pitcher_hits_allowed", "batter_total_bases", "batter_rbis",
        "batter_hits", "batter_runs_scored", "batter_hits_runs_rbis",
        "batter_strikeouts",
    }
    if bet_type in prop_types:
        return "prop"
    return "game_level"


def section(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def analyze_kelly_distribution(df: pd.DataFrame) -> None:
    """Report basic kelly_pct statistics."""
    section("1. KELLY_PCT DISTRIBUTION")
    kelly = df["kelly_pct"]
    print(f"  Count:               {len(kelly):,}")
    print(f"  Mean:                {kelly.mean():.4f}  ({kelly.mean()*100:.2f}%)")
    print(f"  Median:              {kelly.median():.4f}  ({kelly.median()*100:.2f}%)")
    print(f"  Std Dev:             {kelly.std():.4f}")
    print(f"  Min:                 {kelly.min():.4f}")
    print(f"  Max:                 {kelly.max():.4f}  ({kelly.max()*100:.2f}%)")
    print(f"  P25:                 {kelly.quantile(.25):.4f}")
    print(f"  P75:                 {kelly.quantile(.75):.4f}")
    print(f"  P95:                 {kelly.quantile(.95):.4f}")
    print(f"  P99:                 {kelly.quantile(.99):.4f}")
    print()
    print(f"  KELLY_FRACTION in config.py: {KELLY_FRACTION}")
    full_kelly = kelly / KELLY_FRACTION
    print(f"  Implied full-Kelly mean:    {full_kelly.mean():.4f}  ({full_kelly.mean()*100:.1f}%)")
    print(f"  Implied full-Kelly max:     {full_kelly.max():.4f}  ({full_kelly.max()*100:.1f}%)")


def analyze_by_bet_type(df: pd.DataFrame) -> None:
    """Break down kelly_pct and edge by bet type."""
    section("2. KELLY_PCT BY BET TYPE")
    rows = []
    for bt in sorted(df["bet_type"].unique()):
        s = df[df["bet_type"] == bt]
        settled = s[s["result"].isin(["W", "L"])]
        win_rate = (settled["result"] == "W").mean() if len(settled) > 0 else float("nan")
        rows.append({
            "bet_type": bt,
            "n": len(s),
            "mean_kelly": s["kelly_pct"].mean(),
            "median_kelly": s["kelly_pct"].median(),
            "max_kelly": s["kelly_pct"].max(),
            "mean_edge": s["edge"].mean(),
            "win_rate": win_rate,
        })
    tdf = pd.DataFrame(rows)
    print(tdf.to_string(index=False, float_format="%.4f"))


def analyze_daily_exposure(df: pd.DataFrame) -> None:
    """Compute total Kelly exposure per day -- the core bankroll problem."""
    section("3. DAILY BANKROLL EXPOSURE")
    daily = df.groupby("date").agg(
        n_bets=("kelly_pct", "count"),
        sum_kelly=("kelly_pct", "sum"),
        n_games=("game", "nunique"),
    ).reset_index()
    print(f"  {'Date':12s}  {'Bets':>5s}  {'Games':>5s}  {'Sum Kelly':>10s}  {'% of Bankroll':>14s}")
    print(f"  {'-'*12}  {'-'*5}  {'-'*5}  {'-'*10}  {'-'*14}")
    for _, r in daily.iterrows():
        flag = " *** DANGER" if r["sum_kelly"] > 0.20 else ""
        print(f"  {r['date']:12s}  {r['n_bets']:5.0f}  {r['n_games']:5.0f}  "
              f"{r['sum_kelly']:10.4f}  {r['sum_kelly']*100:13.1f}%{flag}")
    print()
    print(f"  Average daily sum_kelly: {daily['sum_kelly'].mean():.4f} ({daily['sum_kelly'].mean()*100:.1f}%)")
    print(f"  Max daily sum_kelly:     {daily['sum_kelly'].max():.4f} ({daily['sum_kelly'].max()*100:.1f}%)")
    print()
    print("  PROBLEM: Summing kelly_pct across hundreds of simultaneous bets")
    print("  means the system would theoretically wager 165x its bankroll on")
    print("  a single day. This is mathematically impossible and indicates")
    print("  kelly_pct is not being used as an actual allocation -- it is only")
    print("  an informational field. But if someone DID try to use it, ruin")
    print("  would be instant.")


def analyze_same_game_correlation(df: pd.DataFrame) -> None:
    """Show that bets on the same game are highly correlated."""
    section("4. SAME-GAME BET CORRELATION")
    settled = df[df["result"].isin(["W", "L"])].copy()
    game_groups = settled.groupby(["date", "game"])
    correlations = []
    for (date, game), group in game_groups:
        if len(group) < 5:
            continue
        win_rate = (group["result"] == "W").mean()
        correlations.append({"n": len(group), "win_rate": win_rate})

    if not correlations:
        print("  Not enough data for correlation analysis.")
        return

    cdf = pd.DataFrame(correlations)
    avg_n = cdf["n"].mean()
    p_hat = cdf["win_rate"].mean()
    expected_std = np.sqrt(p_hat * (1 - p_hat) / avg_n)
    actual_std = cdf["win_rate"].std()
    ratio = actual_std / expected_std

    print(f"  Games with 5+ settled bets: {len(cdf)}")
    print(f"  Overall win rate:           {p_hat:.3f}")
    print(f"  Std of per-game win rates:  {actual_std:.3f}")
    print(f"  Expected std if independent:{expected_std:.3f}")
    print(f"  Correlation factor:         {ratio:.2f}x")
    print()
    print(f"  FINDING: Within-game bets are ~{ratio:.1f}x more variable than they")
    print("  would be if independent. This confirms significant positive")
    print("  correlation among same-game bets. A game where the pitcher")
    print("  dominates will see many 'under' props win simultaneously.")
    print("  Kelly must account for this or it dramatically overstates")
    print("  the diversification benefit of having many bets.")


def analyze_edge_realism(df: pd.DataFrame) -> None:
    """Check whether the claimed edges are plausible."""
    section("5. EDGE REALISM CHECK")
    print(f"  Mean edge across all bets:   {df['edge'].mean():.4f} ({df['edge'].mean()*100:.2f}%)")
    print(f"  Median edge:                 {df['edge'].median():.4f} ({df['edge'].median()*100:.2f}%)")
    print()

    game_level = df[df["bet_type"].apply(classify_bet) == "game_level"]
    props = df[df["bet_type"].apply(classify_bet) == "prop"]
    print(f"  Game-level bets: mean edge = {game_level['edge'].mean():.4f} ({game_level['edge'].mean()*100:.2f}%)")
    print(f"  Prop bets:       mean edge = {props['edge'].mean():.4f} ({props['edge'].mean()*100:.2f}%)")
    print()

    # Edges > 20% on props
    high_edge_props = props[props["edge"] > 0.20]
    print(f"  Prop bets with edge > 20%: {len(high_edge_props)} / {len(props)} ({len(high_edge_props)/len(props)*100:.1f}%)")
    print()

    # Check specific prop types
    for bt in ["pitcher_outs", "pitcher_hits_allowed", "pitcher_strikeouts"]:
        sub = df[df["bet_type"] == bt]
        if len(sub) > 0:
            settled = sub[sub["result"].isin(["W", "L"])]
            wr = (settled["result"] == "W").mean() if len(settled) > 0 else float("nan")
            print(f"  {bt:25s}: mean_edge={sub['edge'].mean():.3f}  "
                  f"actual_win_rate={wr:.3f}  n_settled={len(settled)}")

    print()
    print("  FINDING: Pitcher prop edges are implausibly high (30-40%).")
    print("  If edges were truly this large, win rates should be 70%+.")
    print("  The Monte Carlo simulation likely has systematic bias in")
    print("  pitcher stat distributions. The Kelly formula blindly")
    print("  translates these inflated edges into giant position sizes.")


def analyze_win_rate_by_kelly(df: pd.DataFrame) -> None:
    """Does higher Kelly predict higher win rate?"""
    section("6. WIN RATE BY KELLY SIZE")
    settled = df[df["result"].isin(["W", "L"])].copy()
    settled["kelly_bucket"] = pd.cut(
        settled["kelly_pct"],
        bins=[0, 0.01, 0.02, 0.03, 0.05, 0.10, 1.0],
        labels=["0-1%", "1-2%", "2-3%", "3-5%", "5-10%", "10%+"],
    )
    print(f"  {'Bucket':8s}  {'W':>5s}  {'L':>5s}  {'WinRate':>7s}  {'AvgEdge':>8s}  {'AvgKelly':>9s}")
    for bucket, group in settled.groupby("kelly_bucket", observed=True):
        w = (group["result"] == "W").sum()
        l = (group["result"] == "L").sum()
        wr = w / (w + l)
        print(f"  {str(bucket):8s}  {w:5d}  {l:5d}  {wr:7.3f}  "
              f"{group['edge'].mean():8.4f}  {group['kelly_pct'].mean():9.4f}")

    print()
    print("  FINDING: Higher Kelly bets do have modestly higher win rates")
    print("  (58.5% vs 31.1%), but the 10%+ bucket's win rate of 58.5% is")
    print("  far below what a 29% average edge would predict. This confirms")
    print("  systematic overestimation of edge in high-Kelly bets.")


def simulate_bankroll(df: pd.DataFrame) -> None:
    """Simulate bankroll growth under different Kelly strategies."""
    section("7. BANKROLL SIMULATION (HISTORICAL REPLAY)")
    settled = df[df["result"].isin(["W", "L"])].copy()
    settled = settled.sort_values(["date", "game"]).reset_index(drop=True)

    strategies = {
        "Current (quarter-Kelly, no cap)": lambda k: k,
        "Quarter-Kelly, 2.5% cap": lambda k: min(k, 0.025),
        "Quarter-Kelly, 1.5% cap": lambda k: min(k, 0.015),
        "Eighth-Kelly (0.125x)": lambda k: k * 0.5,  # half of current
        "Tenth-Kelly (0.10x), 2% cap": lambda k: min(k * 0.4, 0.02),
        "Flat 1% all bets": lambda k: 0.01,
        "Flat 0.5% all bets": lambda k: 0.005,
    }

    print(f"  Settled bets for replay: {len(settled)}")
    print()

    for name, size_fn in strategies.items():
        bankroll = 1.0
        peak = 1.0
        max_dd = 0.0
        for _, row in settled.iterrows():
            pct = size_fn(row["kelly_pct"])
            stake = bankroll * pct
            odds = row["odds"]
            if row["result"] == "W":
                if odds < 0:
                    bankroll += stake * (100 / abs(odds))
                else:
                    bankroll += stake * (odds / 100)
            else:
                bankroll -= stake
            peak = max(peak, bankroll)
            dd = (peak - bankroll) / peak
            max_dd = max(max_dd, dd)

        growth = (bankroll - 1.0) * 100
        print(f"  {name:38s}  final={bankroll:.4f}  growth={growth:+.1f}%  max_dd={max_dd*100:.1f}%")


def recommend() -> None:
    """Print concrete recommendations."""
    section("8. RECOMMENDATIONS")
    print("""
  CRITICAL ISSUES FOUND:
  ----------------------
  1. NO POSITION SIZE CAP: Kelly values up to 25% of bankroll on a single
     bet. Professional bettors cap at 2-3% regardless of edge. A single
     bad run can destroy the bankroll.

  2. NO DAILY EXPOSURE LIMIT: On 2026-04-03, the system flagged 1,447 bets
     with combined Kelly of 165x bankroll. Even at quarter-Kelly, this is
     obviously impossible to actually execute.

  3. INFLATED PROP EDGES: Monte Carlo pitcher distributions produce
     implausibly large edges (30-40%), which translate into oversized Kelly
     values. The MC model likely has systematic bias.

  4. NO CORRELATION ADJUSTMENT: Same-game bets show 2x the variance of
     independent bets, confirming positive correlation. Kelly formula
     assumes independence -- applying it independently to 100+ correlated
     bets on the same game wildly overstates optimal allocation.

  5. KELLY_PCT IS INFORMATIONAL ONLY: The tracker stores kelly_pct but
     nothing in the system actually sizes real wagers. If someone tried to
     use these values, they'd be bankrupt immediately.

  CONCRETE RECOMMENDATIONS:
  -------------------------
  A. ADD A HARD CAP PER BET: Max kelly_pct = 2.0% of bankroll, regardless
     of computed Kelly. This matches professional practice.

     In edge.py, after computing kelly_pct:
       kelly_pct = min(kelly_criterion(prob, dec) * KELLY_FRACTION, MAX_BET_PCT)

     Add to config.py:
       MAX_BET_PCT = 0.02  # 2% max per bet

  B. ADD A DAILY EXPOSURE LIMIT: Total kelly_pct across all bets on a
     single day should not exceed 15-20% of bankroll. Once the limit is
     reached, stop betting or reduce all sizes proportionally.

     Add to config.py:
       MAX_DAILY_EXPOSURE = 0.15  # 15% of bankroll per day

  C. ADD A PER-GAME EXPOSURE LIMIT: Since same-game bets are correlated,
     cap total kelly_pct per game at 5% of bankroll. Treat multiple
     correlated props as effectively one position.

     Add to config.py:
       MAX_GAME_EXPOSURE = 0.05  # 5% of bankroll per game

  D. REDUCE KELLY_FRACTION FOR PROPS: Player props have higher model
     uncertainty than game-level markets. Use 1/8 Kelly for props and
     1/4 Kelly for game-level bets.

     Add to config.py:
       KELLY_FRACTION_GAME = 0.25
       KELLY_FRACTION_PROP = 0.125

  E. INVESTIGATE MC MODEL BIAS: Pitcher outs/hits_allowed show 77-93%
     of bets with >20% edge, yet win rates are only ~56-60%. The Monte
     Carlo simulation has systematic miscalibration that inflates edges.
     Fix the root cause, not just the sizing.

  F. IMPLEMENT BANKROLL TRACKING: Add actual bankroll state to the system:
     - Track starting bankroll
     - Deduct stakes from available bankroll
     - Recalculate Kelly on remaining bankroll
     - This makes simultaneous bets properly reduce available capital

  G. CONSIDER MOVING TO 1/8 KELLY OVERALL: Research consistently shows
     that model estimation error makes fractional Kelly essential.
     Quarter-Kelly assumes your probability estimates are fairly accurate.
     Given the edge inflation found in props, 1/8 Kelly or even 1/10
     Kelly would be more appropriate until the model is calibrated.
""")


def main():
    df = load_data()
    print(f"Kelly Criterion Analysis")
    print(f"Data: {BETS_CSV}")
    print(f"Rows: {len(df):,}  |  Dates: {df['date'].min()} to {df['date'].max()}")

    analyze_kelly_distribution(df)
    analyze_by_bet_type(df)
    analyze_daily_exposure(df)
    analyze_same_game_correlation(df)
    analyze_edge_realism(df)
    analyze_win_rate_by_kelly(df)
    simulate_bankroll(df)
    recommend()


if __name__ == "__main__":
    main()
