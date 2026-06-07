"""Plate appearance outcome sampling using the odds-ratio method."""
import random

OUTCOMES = ["K", "BB", "HBP", "1B", "2B", "3B", "HR", "OUT"]

# Times-through-the-order penalty (TTOP, 2026-05-07).
# Index = number of times this pitcher has gone through the lineup so far,
# clamped to [0, 1, 2] (3rd+ all share the penalty). Multipliers are applied
# to the *pitcher's* contribution to the matchup, not the league baseline.
TTOP_K_MULTIPLIER = (1.04, 1.00, 0.94)
TTOP_BB_MULTIPLIER = (0.96, 1.00, 1.06)
TTOP_HR_MULTIPLIER = (0.92, 1.00, 1.10)

# Platoon multipliers (Tier 4, 2026-05-07). Applied to the BATTER side of
# the matchup. Magnitudes calibrated to ~5-10% wOBA shift, which matches
# Fangraphs platoon-splits data for 2024.
PLATOON_MULTIPLIERS = {
    "same":    {"k_pct": 1.05, "bb_pct": 0.95, "hr_pct": 0.92,
                "single_pct": 0.95, "double_pct": 0.95, "triple_pct": 1.0},
    "opposite":{"k_pct": 0.95, "bb_pct": 1.05, "hr_pct": 1.10,
                "single_pct": 1.05, "double_pct": 1.05, "triple_pct": 1.0},
    "neutral": {"k_pct": 1.0,  "bb_pct": 1.0,  "hr_pct": 1.0,
                "single_pct": 1.0,  "double_pct": 1.0,  "triple_pct": 1.0},
}


def platoon_matchup(bat_side: str | None, pitch_hand: str | None) -> str:
    """Classify a matchup as 'same', 'opposite', or 'neutral'.

    Switch hitters ("S") always get the platoon advantage and are treated
    as opposite-handed regardless of pitcher hand. Missing/unknown values
    fall back to 'neutral' so legacy stat dicts behave as before.
    """
    if not bat_side or not pitch_hand:
        return "neutral"
    if bat_side == "S":
        return "opposite"
    if bat_side not in ("L", "R") or pitch_hand not in ("L", "R"):
        return "neutral"
    return "same" if bat_side == pitch_hand else "opposite"

LEAGUE_AVERAGES = {
    "k_pct": 0.224,
    "bb_pct": 0.084,
    "hbp_pct": 0.0108,
    "hr_pct": 0.033,
    "single_pct": 0.152,
    "double_pct": 0.044,
    "triple_pct": 0.004,
    "out_pct": 0.459,
}


def matchup_probability(batter_rate: float, pitcher_rate: float, league_rate: float) -> float:
    """Combine batter and pitcher rates using log5 on odds scale.

    The naive odds-ratio (b*p/l) overestimates extreme rates. The proper
    log5 formulation works in odds-space, correctly handling probabilities
    far from 0.5 (e.g., HR ~3%, triples ~0.4%).
    """
    if league_rate <= 0 or league_rate >= 1:
        return batter_rate
    if batter_rate <= 0 or batter_rate >= 1:
        return batter_rate
    if pitcher_rate <= 0 or pitcher_rate >= 1:
        return pitcher_rate
    bo = batter_rate / (1 - batter_rate)
    po = pitcher_rate / (1 - pitcher_rate)
    lo = league_rate / (1 - league_rate)
    combined_odds = bo * po / lo
    return combined_odds / (1 + combined_odds)


def normalize_probs(raw: dict) -> dict:
    """Normalize probability dict to sum to 1.0."""
    total = sum(raw.values())
    if total <= 0:
        n = len(raw)
        return {k: 1.0 / n for k in raw}
    return {k: v / total for k, v in raw.items()}


def _build_matchup_probs(
    batter: dict, pitcher: dict,
    park_factor_runs: float = 1.0, park_factor_hr: float = 1.0,
    ttop_index: int = 0,
) -> dict:
    """Build normalized outcome probabilities for a batter-pitcher matchup.

    `ttop_index` ∈ {0,1,2}: 0=first time through, 1=second, 2=third+.
    Multipliers are applied to the pitcher's K/BB/HR rates before the
    odds-ratio combination, so the effect compounds with batter quality
    (a strong batter will exploit a fading pitcher more than a weak one).
    """
    pitcher_eff = pitcher
    if ttop_index:
        idx = max(0, min(int(ttop_index), 2))
        pitcher_eff = dict(pitcher)
        pitcher_eff["k_pct"] = pitcher.get("k_pct", LEAGUE_AVERAGES["k_pct"]) * TTOP_K_MULTIPLIER[idx]
        pitcher_eff["bb_pct"] = pitcher.get("bb_pct", LEAGUE_AVERAGES["bb_pct"]) * TTOP_BB_MULTIPLIER[idx]
        pitcher_eff["hr_pct"] = pitcher.get("hr_pct", LEAGUE_AVERAGES["hr_pct"]) * TTOP_HR_MULTIPLIER[idx]

    matchup_kind = platoon_matchup(batter.get("bat_side"), pitcher.get("pitch_hand"))
    batter_eff = batter
    if matchup_kind != "neutral":
        mults = PLATOON_MULTIPLIERS[matchup_kind]
        batter_eff = dict(batter)
        for key, m in mults.items():
            if m != 1.0:
                batter_eff[key] = batter.get(key, LEAGUE_AVERAGES[key]) * m

    raw = {}
    outcome_keys = [
        ("K", "k_pct"),
        ("BB", "bb_pct"),
        ("HBP", "hbp_pct"),
        ("HR", "hr_pct"),
        ("1B", "single_pct"),
        ("2B", "double_pct"),
        ("3B", "triple_pct"),
        ("OUT", "out_pct"),
    ]
    for outcome, key in outcome_keys:
        b_rate = batter_eff.get(key, LEAGUE_AVERAGES[key])
        p_rate = pitcher_eff.get(key, LEAGUE_AVERAGES[key])
        l_rate = LEAGUE_AVERAGES[key]
        raw[outcome] = matchup_probability(b_rate, p_rate, l_rate)

    # Apply park factors before normalization
    if park_factor_hr != 1.0:
        raw["HR"] *= park_factor_hr
    if park_factor_runs != 1.0:
        for hit in ("1B", "2B", "3B"):
            raw[hit] *= park_factor_runs

    return normalize_probs(raw)


def sample_pa(
    batter: dict, pitcher: dict,
    park_factor_runs: float = 1.0, park_factor_hr: float = 1.0,
    ttop_index: int = 0,
) -> str:
    """Sample a single plate appearance outcome."""
    probs = _build_matchup_probs(batter, pitcher, park_factor_runs, park_factor_hr, ttop_index)
    r = random.random()
    cumulative = 0.0
    for outcome in OUTCOMES:
        cumulative += probs[outcome]
        if r < cumulative:
            return outcome
    return OUTCOMES[-1]
