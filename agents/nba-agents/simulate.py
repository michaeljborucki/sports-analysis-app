"""Simulation layer: Plan B (direct Kimi) and MiroFish 512-agent."""
import json
import openai
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, KIMI_MODEL


NBA_SYSTEM_PROMPT = """You are an elite NBA prediction system analyzing a game.
Simulate a panel of 6 expert analysts:

1. OFFENSIVE ANALYST: Evaluates offensive efficiency, shot selection, spacing,
   three-point shooting, and how the offense matches up against the defensive scheme.
   Pace-adjusted scoring projections.
2. DEFENSIVE ANALYST: Evaluates defensive rating, rim protection, perimeter defense,
   transition defense, and how the defense matches the opponent's primary actions.
3. PACE & TEMPO ANALYST: Evaluates pace matchup, projected possessions, and how
   tempo affects total scoring. Fast vs slow teams, half-court vs transition.
   Critical for over/under predictions.
4. REST & SCHEDULE ANALYST: Evaluates rest days, back-to-backs, travel distance,
   time zones, and fatigue factors. Teams on 0 rest shoot worse and defend worse.
   This drives spread and total adjustments.
5. MARKET ANALYST: Evaluates the betting lines for value. Where is the
   public money likely flowing? Is the spread reflecting rest/injury adjustments
   properly? Where might the market be inefficient?
6. CONTRARIAN: Challenges the consensus. What narrative is the public overweighting?
   Is a resting team still being priced as full-strength? Is a B2B impact
   already baked into the line?

Respond in valid JSON only with this structure:
{
  "analyst_assessments": [
    {"role": "offensive", "pick": "TEAM", "reasoning": "..."},
    ...
  ],
  "predictions": {
    "moneyline": {
      "home_win_prob": 0.XX,
      "away_win_prob": 0.XX,
      "value_side": "home|away|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "spread": {
      "favorite_cover_prob": 0.XX,
      "value_side": "favorite|underdog|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "total": {
      "projected_total": XXX.X,
      "over_prob": 0.XX,
      "under_prob": 0.XX,
      "value_side": "over|under|none",
      "edge": 0.XX,
      "confidence": "low|medium|high"
    },
    "first_half": {
      "h1_home_win_prob": 0.XX,
      "h1_away_win_prob": 0.XX,
      "h1_projected_total": XX.X,
      "h1_ml_value": "home|away|none",
      "h1_total_value": "over|under|none",
      "confidence": "low|medium|high",
      "h1_favorite_cover_prob": 0.XX,
      "h1_spread_value": "favorite|underdog|none"
    },
    "second_half": {
      "h2_home_win_prob": 0.XX,
      "h2_projected_total": XX.X
    },
    "q1": {
      "q1_home_win_prob": 0.XX,
      "q1_projected_total": XX.X,
      "q1_favorite_cover_prob": 0.XX,
      "q1_ml_value": "home|away|none",
      "q1_spread_value": "favorite|underdog|none",
      "q1_total_value": "over|under|none"
    },
    "team_totals": {
      "home_projected": XXX.X,
      "away_projected": XXX.X,
      "home_value": "over|under|none",
      "away_value": "over|under|none"
    },
    "predicted_score": {"away": XXX, "home": XXX},
    "key_factors": ["factor1", "factor2", "factor3"]
  }
}
No markdown, no backticks, no preamble. JSON only."""


PROP_SYSTEM_PROMPT = """You are an NBA player prop prediction system. Given a game briefing and sportsbook player prop lines, predict whether each player's stat line will go OVER or UNDER their posted line.

Consider: projected minutes, matchup quality, pace, injury context, role/usage changes, defensive matchup (rim protector vs perimeter), and recent form (last 5 games).

Respond in valid JSON only:
{
  "player_props": {
    "Player Name": {
      "points": {"over_prob": 0.XX, "projected": XX.X},
      "rebounds": {"over_prob": 0.XX, "projected": X.X},
      "assists": {"over_prob": 0.XX, "projected": X.X},
      "threes": {"over_prob": 0.XX, "projected": X.X},
      "pra": {"over_prob": 0.XX, "projected": XX.X}
    }
  }
}
No markdown, no backticks, no preamble. JSON only."""


def parse_simulation_result(raw: str | None) -> dict | None:
    """Parse JSON response from LLM, handling common issues."""
    if not raw:
        return None
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def run_plan_b(briefing: str, runs: int = 1) -> dict | None:
    """Run direct Kimi call (Plan B) — fast screen at ~$0.06/game.

    If runs > 1, average the probability estimates across runs for stability.
    """
    client = openai.OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE_URL,
    )

    results = []
    for _ in range(runs):
        try:
            response = client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[
                    {"role": "system", "content": NBA_SYSTEM_PROMPT},
                    {"role": "user", "content": briefing},
                ],
                temperature=0.7,
                max_tokens=8192,
            )
            choice = response.choices[0]
            if choice.finish_reason == "length":
                print("[simulate] Warning: response truncated (finish_reason=length)")
            raw = choice.message.content
            parsed = parse_simulation_result(raw)
            if parsed:
                results.append(parsed)
        except Exception as e:
            print(f"[simulate] Plan B error: {e}")

    if not results:
        return None

    if len(results) == 1:
        return results[0]

    # Average probabilities across runs
    return _average_results(results)


def run_mirofish(briefing: str, runs: int = 3, odds: dict = None) -> dict | None:
    """Run multi-model ensemble simulation with Plan B fallback.

    Args:
        odds: Game odds dict for spread consensus normalization.
    """
    try:
        from ensemble import run_ensemble
        result = run_ensemble(briefing, odds=odds)
        if result:
            return result
        print("[simulate] Ensemble returned no result, falling back to Plan B")
    except Exception as e:
        print(f"[simulate] Ensemble failed ({e}), falling back to Plan B")
    return run_plan_b(briefing, runs=runs)


def _average_results(results: list[dict]) -> dict:
    """Average probability fields across multiple simulation runs."""
    base = results[0].copy()
    n = len(results)

    preds = base.get("predictions", {})
    prob_fields = {
        "moneyline": ["home_win_prob", "away_win_prob", "edge"],
        "spread": ["favorite_cover_prob", "edge"],
        "total": ["projected_total", "over_prob", "under_prob", "edge"],
        "first_half": ["h1_home_win_prob", "h1_away_win_prob",
                        "h1_projected_total", "h1_favorite_cover_prob"],
        "second_half": ["h2_home_win_prob", "h2_projected_total"],
        "q1": ["q1_home_win_prob", "q1_projected_total", "q1_favorite_cover_prob"],
        "team_totals": ["home_projected", "away_projected"],
    }

    for section, fields in prob_fields.items():
        if section not in preds:
            continue
        for field in fields:
            values = []
            for r in results:
                val = r.get("predictions", {}).get(section, {}).get(field)
                if val is not None:
                    values.append(float(val))
            if values:
                preds[section][field] = round(sum(values) / len(values), 4)

    base["predictions"] = preds
    base["ensemble_runs"] = n
    return base


def run_prop_ensemble(briefing: str, prop_lines: str) -> dict | None:
    """Run lightweight 3-model ensemble for player prop predictions."""
    from config import PROP_ENSEMBLE_MODELS
    from ensemble.models import MODEL_REGISTRY
    from concurrent.futures import ThreadPoolExecutor, as_completed

    client = openai.OpenAI(api_key=OPENROUTER_API_KEY, base_url=OPENROUTER_BASE_URL)
    user_msg = f"{briefing}\n\n== PLAYER PROP LINES ==\n{prop_lines}"
    results = []

    def _call(model_key):
        spec = MODEL_REGISTRY[model_key]
        try:
            resp = client.chat.completions.create(
                model=spec["id"],
                messages=[
                    {"role": "system", "content": PROP_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.7,
                max_tokens=4096,
            )
            return parse_simulation_result(resp.choices[0].message.content)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(_call, mk): mk for mk in PROP_ENSEMBLE_MODELS}
        for f in as_completed(futures):
            r = f.result(timeout=60)
            if r:
                results.append(r)

    if not results:
        return None
    if len(results) == 1:
        return results[0]
    return _average_prop_results(results)


def _average_prop_results(results: list[dict]) -> dict:
    """Average player prop probability estimates across multiple model runs."""
    if len(results) == 1:
        return results[0]
    base = results[0].copy()
    players = base.get("player_props", {})
    prop_types = ["points", "rebounds", "assists", "threes", "pra"]
    for player in players:
        for prop in prop_types:
            values = []
            projected = []
            for r in results:
                pp = r.get("player_props", {}).get(player, {}).get(prop, {})
                if "over_prob" in pp:
                    values.append(float(pp["over_prob"]))
                if "projected" in pp:
                    projected.append(float(pp["projected"]))
            if values:
                players[player][prop]["over_prob"] = round(sum(values) / len(values), 4)
            if projected:
                players[player][prop]["projected"] = round(sum(projected) / len(projected), 1)
    base["player_props"] = players
    return base
