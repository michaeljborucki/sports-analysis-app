"""Full 9-inning baseball game simulation with state tracking."""
import random

from dataclasses import dataclass, field
from simulation.pa_engine import sample_pa, LEAGUE_AVERAGES


# Pitch count estimates by PA outcome
PITCHES_PER_PA = {
    "K": 4.8,
    "BB": 5.6,
    "HBP": 2.5,
    "HR": 3.5,
    "1B": 3.3,
    "2B": 3.4,
    "3B": 3.2,
    "OUT": 3.4,
}

# League-average reliever stats (Tier 5 refit, 2026-05-07).
# Modern (2024-2025) reliever splits: relievers walk MORE than starters in
# max-effort short stints, and homer rates are below starters with the
# sticky-stuff crackdown holding.
LEAGUE_RELIEVER = {
    "k_pct": 0.240,
    "bb_pct": 0.090,
    "hbp_pct": 0.0108,
    "hr_pct": 0.027,
    "single_pct": 0.145,
    "double_pct": 0.040,
    "triple_pct": 0.003,
    "out_pct": 0.462,
}

# MLB base advancement probabilities
# Tier 5 refit (2026-05-07) against Retrosheet 2023-24 PBP:
#   2B_r1_scores 0.50 → 0.43  (R1B-to-home on doubles is ~42-45%)
#   OUT_r3_scores 0.50 → 0.55 (R3B scores on productive out ~53-57%)
#   OUT_r2_to_3B 0.25 → 0.30  (R2B-to-3B on groundouts ~28-32%)
# Earlier (2026-04-27) bump to 1B_r2_scores=0.65 retained.
ADVANCE_PROBS = {
    "1B_r2_scores": 0.65,   # Runner on 2B scores on a single
    "1B_r1_to_3B": 0.27,    # Runner on 1B advances to 3B on a single
    "2B_r1_scores": 0.43,   # Runner on 1B scores on a double
    "OUT_r3_scores": 0.55,  # Runner on 3B scores on productive out (<2 outs)
    "OUT_r2_to_3B": 0.30,   # Runner on 2B advances to 3B on groundout
}

# Per-PA probability of extra advancement (WP, PB, SB) when runners on base.
# Bumped 2026-05-07 to 0.08 to reflect the post-2023 SB rule changes (+18%
# attempts) feeding through to runner-progress events.
EXTRA_ADVANCE_PROB = 0.08


@dataclass
class GameState:
    inning: int = 1
    half: str = "top"  # "top" = away bats, "bottom" = home bats
    outs: int = 0
    bases: list = field(default_factory=lambda: [0, 0, 0])  # [1B, 2B, 3B] — 0=empty, player_id=occupied
    score: dict = field(default_factory=lambda: {"away": 0, "home": 0})
    score_by_inning: dict = field(default_factory=lambda: {"away": [], "home": []})
    pitcher_stats: dict = field(default_factory=dict)
    batter_stats: dict = field(default_factory=dict)


def _init_pitcher_stats(pid: int, stats: dict) -> None:
    """Initialize pitcher stats entry if missing."""
    if pid not in stats:
        stats[pid] = {"k": 0, "bb": 0, "h": 0, "er": 0, "outs": 0,
                      "pitches": 0, "pa_faced": 0}


def _init_batter_stats(pid: int, stats: dict) -> None:
    """Initialize batter stats entry if missing."""
    if pid not in stats:
        stats[pid] = {
            "pa": 0, "h": 0, "hr": 0, "rbi": 0, "r": 0,
            "k": 0, "bb": 0, "tb": 0, "2b": 0, "3b": 0,
        }


def advance_runners(bases: list, hit_type: str, outs: int, batter_id: int = 0) -> tuple:
    """Advance runners with probabilistic MLB-realistic advancement.

    bases: [1B, 2B, 3B] where 0 = empty, positive int = player_id.
    Returns (new_bases, scored) where scored is a list of player IDs that scored.

    Probabilities sourced from Retrosheet 2015 play-by-play transition data.
    """
    scored = []
    new_bases = [0, 0, 0]

    if hit_type == "HR":
        for b in bases:
            if b:
                scored.append(b)
        scored.append(batter_id)
        return [0, 0, 0], scored, False

    if hit_type == "3B":
        for b in bases:
            if b:
                scored.append(b)
        new_bases[2] = batter_id
        return new_bases, scored, False

    if hit_type == "2B":
        # Runners on 3B and 2B always score on a double
        if bases[2]:
            scored.append(bases[2])
        if bases[1]:
            scored.append(bases[1])
        # Runner on 1B: 44% scores, 56% to 3B (Retrosheet)
        if bases[0]:
            if random.random() < ADVANCE_PROBS["2B_r1_scores"]:
                scored.append(bases[0])
            else:
                new_bases[2] = bases[0]
        new_bases[1] = batter_id
        return new_bases, scored, False

    if hit_type == "1B":
        # Runner on 3B always scores on a single
        if bases[2]:
            scored.append(bases[2])
        # Runner on 2B: 42% scores, 58% holds at 3B (Retrosheet)
        if bases[1]:
            if random.random() < ADVANCE_PROBS["1B_r2_scores"]:
                scored.append(bases[1])
            else:
                new_bases[2] = bases[1]
        # Runner on 1B: 27% to 3B (if open), else to 2B (Retrosheet)
        if bases[0]:
            if not new_bases[2] and random.random() < ADVANCE_PROBS["1B_r1_to_3B"]:
                new_bases[2] = bases[0]
            else:
                new_bases[1] = bases[0]
        new_bases[0] = batter_id
        return new_bases, scored, False

    if hit_type == "BB" or hit_type == "HBP":
        # Forced advances only (same as real baseball). HBP advances
        # identically to a walk; the difference is in which counter ticks
        # (handled by the caller).
        if bases[0] and bases[1] and bases[2]:
            # Bases loaded: R3B forced home
            scored.append(bases[2])
            new_bases = [batter_id, bases[0], bases[1]]
        elif bases[0] and bases[1]:
            # R1B+R2B: force to 2B+3B
            new_bases = [batter_id, bases[0], bases[1]]
        elif bases[0]:
            # R1B (possibly R3B): R1B forced to 2B
            new_bases = [batter_id, bases[0], bases[2]]
        else:
            # No force: batter to 1B, others stay
            new_bases = [batter_id, bases[1], bases[2]]
        return new_bases, scored, False

    if hit_type == "OUT":
        # GIDP: ~11% chance with runner on 1B and < 2 outs
        if outs < 2 and bases[0] and random.random() < 0.11:
            # Double play: batter out + runner on 1B out
            new_bases[0] = 0
            # Runners on 2B/3B stay; R3B may score on DP
            if bases[2]:
                if random.random() < 0.50:
                    scored.append(bases[2])
                else:
                    new_bases[2] = bases[2]
            else:
                new_bases[2] = bases[2]
            new_bases[1] = bases[1]
            # Signal extra out via special return (caller adds 1 out, we flag +1)
            return new_bases, scored, True  # True = double play (extra out)

        # Productive out: R3B scores ~50% on non-K outs with <2 outs
        if outs < 2 and bases[2]:
            if random.random() < ADVANCE_PROBS["OUT_r3_scores"]:
                scored.append(bases[2])
            else:
                new_bases[2] = bases[2]
        else:
            new_bases[2] = bases[2]
        # Runner on 2B: 18% advances to 3B on groundout (if 3B open)
        if bases[1]:
            if not new_bases[2] and random.random() < ADVANCE_PROBS["OUT_r2_to_3B"]:
                new_bases[2] = bases[1]
            else:
                new_bases[1] = bases[1]
        # Runner on 1B stays
        if bases[0]:
            new_bases[0] = bases[0]
        return new_bases, scored, False

    # K — no advancement
    return list(bases), [], False


def _maybe_extra_advance(bases: list) -> list:
    """Model WP, PB, SB — ~7% chance per PA with runners of extra advancement.

    Mutates bases in place. Returns list of player IDs that scored.
    Calibrated to ~2.2 events/game (WP + PB + successful SB).
    """
    if not any(bases):
        return []
    if random.random() >= EXTRA_ADVANCE_PROB:
        return []
    scored = []
    # Advance the lead runner one base
    if bases[2]:
        scored.append(bases[2])
        bases[2] = 0
    elif bases[1]:
        bases[2] = bases[1]
        bases[1] = 0
    elif bases[0]:
        bases[1] = bases[0]
        bases[0] = 0
    return scored


def _rbi_credit(outcome: str, runs: int, is_dp: bool) -> int:
    """RBIs credited to the batter for the runs that scored on this PA.

    MLB Rule 9.04: a strikeout drives in no run, and no RBI is credited for a
    run that scores when the batter grounds into a (reverse-)force double play
    (Rule 9.04(b)(1)). The GIDP branch scores at most one run (the runner from
    3B), so exactly that one run is withheld while the run itself still counts.
    """
    if outcome == "K":
        return 0
    if is_dp and runs > 0:
        return runs - 1
    return runs


def simulate_game(
    home_lineup: list,
    away_lineup: list,
    home_pitcher: dict,
    away_pitcher: dict,
    park_factor_runs: float = 1.0,
    park_factor_hr: float = 1.0,
    weather_hr_multiplier: float = 1.0,
) -> GameState:
    """Simulate a full 9-inning game and return the final GameState."""
    state = GameState()
    max_innings = 12

    # Weather effect compounds with park factor for HR rate.
    effective_hr_factor = park_factor_hr * weather_hr_multiplier

    home_batter_idx = 0
    away_batter_idx = 0

    # Current pitchers (may switch to reliever)
    current_home_pitcher = dict(home_pitcher)
    current_away_pitcher = dict(away_pitcher)

    _init_pitcher_stats(home_pitcher["player_id"], state.pitcher_stats)
    _init_pitcher_stats(away_pitcher["player_id"], state.pitcher_stats)

    # Track reliever IDs so we don't collide
    home_reliever_id = home_pitcher["player_id"] + 1000
    away_reliever_id = away_pitcher["player_id"] + 1000
    home_switched = False
    away_switched = False

    for inning in range(1, max_innings + 1):
        state.inning = inning

        for half in ("top", "bottom"):
            state.half = half

            # In bottom of 9th+, if home is already ahead, skip
            if inning >= 9 and half == "bottom" and state.score["home"] > state.score["away"]:
                state.score_by_inning["home"].append(0)
                continue

            state.outs = 0
            state.bases = [0, 0, 0]
            inning_runs = 0

            if half == "top":
                lineup = away_lineup
                batter_idx = away_batter_idx
                pitcher = current_home_pitcher
                pitcher_id = pitcher["player_id"]
                batting_side = "away"
            else:
                lineup = home_lineup
                batter_idx = home_batter_idx
                pitcher = current_away_pitcher
                pitcher_id = pitcher["player_id"]
                batting_side = "home"

            # MLB ghost runner rule: runner on 2B to start extras (10th+)
            if inning >= 10:
                ghost_idx = (batter_idx - 1) % 9
                ghost_id = lineup[ghost_idx]["player_id"]
                state.bases = [0, ghost_id, 0]

            _init_pitcher_stats(pitcher_id, state.pitcher_stats)

            while state.outs < 3:
                batter = lineup[batter_idx % 9]
                batter_id = batter["player_id"]
                _init_batter_stats(batter_id, state.batter_stats)

                # Times-through-the-order: clamp to {0,1,2}. PAs faced by
                # this pitcher BEFORE this one drives the index. Lineup
                # turnover means PAs/9 is a close approximation of true
                # times-through.
                ttop = min(state.pitcher_stats[pitcher_id]["pa_faced"] // 9, 2)
                outcome = sample_pa(
                    batter, pitcher, park_factor_runs, effective_hr_factor,
                    ttop_index=ttop,
                )

                # Pitch count + PA counter (for TTOP on subsequent PAs)
                pitches = PITCHES_PER_PA.get(outcome, 3.5)
                state.pitcher_stats[pitcher_id]["pitches"] += pitches
                state.pitcher_stats[pitcher_id]["pa_faced"] += 1

                # Batter stats
                bs = state.batter_stats[batter_id]
                bs["pa"] += 1

                scored = []  # player IDs that scored this PA
                is_dp = False  # set True only by the OUT/GIDP branch below

                if outcome == "K":
                    state.outs += 1
                    bs["k"] += 1
                    state.pitcher_stats[pitcher_id]["k"] += 1
                    state.pitcher_stats[pitcher_id]["outs"] += 1
                elif outcome == "BB":
                    bs["bb"] += 1
                    state.pitcher_stats[pitcher_id]["bb"] += 1
                    new_bases, scored, _ = advance_runners(
                        state.bases, "BB", state.outs, batter_id)
                    state.bases = new_bases
                elif outcome == "HBP":
                    new_bases, scored, _ = advance_runners(
                        state.bases, "HBP", state.outs, batter_id)
                    state.bases = new_bases
                elif outcome == "OUT":
                    new_bases, scored, is_dp = advance_runners(
                        state.bases, "OUT", state.outs, batter_id)
                    state.outs += 2 if is_dp else 1
                    state.bases = new_bases
                    state.pitcher_stats[pitcher_id]["outs"] += 2 if is_dp else 1
                else:
                    # Hit: 1B, 2B, 3B, HR
                    state.pitcher_stats[pitcher_id]["h"] += 1
                    bs["h"] += 1
                    if outcome == "1B":
                        bs["tb"] += 1
                    elif outcome == "2B":
                        bs["2b"] += 1
                        bs["tb"] += 2
                    elif outcome == "3B":
                        bs["3b"] += 1
                        bs["tb"] += 3
                    elif outcome == "HR":
                        bs["hr"] += 1
                        bs["tb"] += 4

                    new_bases, scored, _ = advance_runners(
                        state.bases, outcome, state.outs, batter_id)
                    state.bases = new_bases

                # Credit individual runner stats and team scoring
                runs = len(scored)
                inning_runs += runs
                for sid in scored:
                    if sid in state.batter_stats:
                        state.batter_stats[sid]["r"] += 1

                # Credit RBI to the batter (MLB Rule 9.04 — no RBI on a
                # strikeout or on a run that scores via a double play).
                bs["rbi"] += _rbi_credit(outcome, runs, is_dp)

                # Extra advancement: WP, PB, SB between PAs
                if state.outs < 3:
                    extra = _maybe_extra_advance(state.bases)
                    if extra:
                        inning_runs += len(extra)
                        for sid in extra:
                            if sid in state.batter_stats:
                                state.batter_stats[sid]["r"] += 1

                batter_idx += 1

                # Walk-off check: bottom of 9th+ and home takes lead
                if (
                    half == "bottom"
                    and inning >= 9
                    and state.score["home"] + inning_runs > state.score["away"]
                ):
                    break

                # Check pitcher switch
                if half == "top" and not home_switched:
                    avg_pc = home_pitcher.get("avg_pitch_count", 90)
                    if state.pitcher_stats[pitcher_id]["pitches"] > avg_pc * 1.1:
                        home_switched = True
                        current_home_pitcher = {
                            **LEAGUE_RELIEVER,
                            "player_id": home_reliever_id,
                        }
                        pitcher = current_home_pitcher
                        pitcher_id = home_reliever_id
                        _init_pitcher_stats(pitcher_id, state.pitcher_stats)
                elif half == "bottom" and not away_switched:
                    avg_pc = away_pitcher.get("avg_pitch_count", 90)
                    if state.pitcher_stats[pitcher_id]["pitches"] > avg_pc * 1.1:
                        away_switched = True
                        current_away_pitcher = {
                            **LEAGUE_RELIEVER,
                            "player_id": away_reliever_id,
                        }
                        pitcher = current_away_pitcher
                        pitcher_id = away_reliever_id
                        _init_pitcher_stats(pitcher_id, state.pitcher_stats)

            # Record earned runs for pitcher
            state.pitcher_stats[pitcher_id]["er"] += inning_runs

            # Update team score
            state.score[batting_side] += inning_runs
            state.score_by_inning[batting_side].append(inning_runs)

            # Save batter index
            if half == "top":
                away_batter_idx = batter_idx
            else:
                home_batter_idx = batter_idx

        # After full inning (9+), check if game is over (not tied)
        if inning >= 9 and state.score["home"] != state.score["away"]:
            break

    return state
