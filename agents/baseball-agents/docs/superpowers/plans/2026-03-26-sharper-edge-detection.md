# Sharper Edge Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 5 surgical fixes to the edge calculation pipeline that eliminate systematic precision leaks in vig removal, probability estimation, line selection, confidence weighting, and calibration injection.

**Architecture:** Each fix is independently committable. Fix 1 (power devig) and Fix 4 (confidence weighting) touch different files and can run in parallel. Fixes 2, 3, 5 sequence after Fix 1 since they share `edge.py` or `scrapers/odds.py`.

**Tech Stack:** Python, scipy.optimize.brentq (or hand-rolled bisection), Poisson CDF (math.exp/factorial), pytest

**Spec:** `docs/superpowers/specs/2026-03-26-sharper-edge-detection-design.md`

---

## File Map

| File | Changes | Responsibility |
|------|---------|----------------|
| `scrapers/odds.py` | Fix 1: add `power_devig()`, replace naive normalization. Fix 3: best-line selection | Odds fetching, vig removal, line selection |
| `edge.py` | Fix 1: replace 9 inline vig blocks. Fix 2: F5 Poisson. Fix 5: wire calibration into 12 checkers | Edge detection for all bet types |
| `ensemble/consensus.py` | Fix 4: add `CONFIDENCE_MULTIPLIERS`, modify `weighted_average_prob()` | Ensemble probability averaging |
| `ensemble/orchestrator.py` | Fix 4: pass per-slot confidences. Secondary: fix market_prob logging | Ensemble orchestration and logging |
| `calibrate.py` | Fix 5: add `apply_calibration()` identity function | Calibration injection point |
| `tests/test_odds.py` | Tests for power_devig, best-line selection | |
| `tests/test_edge.py` | Tests for F5 Poisson, calibration wiring | |
| `tests/test_edge_phase1.py` | Verify phase 1 checkers still pass | |
| `tests/test_ensemble_consensus.py` | Tests for confidence-weighted averaging | |
| `tests/test_ensemble_orchestrator.py` | Tests for confidence passing, market_prob fix | |
| `tests/test_calibrate.py` | Tests for `apply_calibration()` identity | |

---

## Task 1: Power Method Vig Removal

**Files:**
- Modify: `scrapers/odds.py` — add `power_devig()` after line 12, replace lines 258-268
- Modify: `edge.py` — replace 9 inline vig blocks, update import at line 5
- Test: `tests/test_odds.py`, `tests/test_edge.py`, `tests/test_edge_phase1.py`

- [ ] **Step 1: Write failing tests for `power_devig()`**

Add to `tests/test_odds.py`:

```python
from scrapers.odds import power_devig

def test_power_devig_sums_to_one():
    """Power devig output must sum to 1.0."""
    # -200/+170 line: raw implied = 0.6667, 0.6299
    a = 200 / 300  # 0.6667
    b = 100 / 270  # 0.3704 (actually +170 = 100/270)
    # Wait, let's use american_to_implied_prob values
    from scrapers.odds import american_to_implied_prob
    a = american_to_implied_prob(-200)  # 0.6667
    b = american_to_implied_prob(170)   # 0.3704
    da, db = power_devig(a, b)
    assert abs(da + db - 1.0) < 1e-6

def test_power_devig_shifts_favorite():
    """Power method shifts favorite less than naive normalization."""
    from scrapers.odds import american_to_implied_prob
    a = american_to_implied_prob(-200)  # 0.6667
    b = american_to_implied_prob(170)   # 0.3704
    da, db = power_devig(a, b)
    # Naive: 0.6667 / (0.6667+0.3704) = 0.6429
    naive_a = a / (a + b)
    # Power should give a LOWER value for favorite than naive
    assert da < naive_a
    assert da > 0.5  # still favorite

def test_power_devig_even_odds():
    """Even odds should remain 50/50."""
    from scrapers.odds import american_to_implied_prob
    a = american_to_implied_prob(-110)
    b = american_to_implied_prob(-110)
    da, db = power_devig(a, b)
    assert abs(da - 0.5) < 1e-4
    assert abs(db - 0.5) < 1e-4

def test_power_devig_no_vig_passthrough():
    """If probabilities already sum to 1, return unchanged."""
    da, db = power_devig(0.6, 0.4)
    assert abs(da - 0.6) < 1e-6
    assert abs(db - 0.4) < 1e-6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_odds.py::test_power_devig_sums_to_one tests/test_odds.py::test_power_devig_shifts_favorite tests/test_odds.py::test_power_devig_even_odds tests/test_odds.py::test_power_devig_no_vig_passthrough -v`
Expected: ImportError — `power_devig` does not exist yet

- [ ] **Step 3: Implement `power_devig()` in `scrapers/odds.py`**

Add after `american_to_implied_prob()` (after line 12):

```python
def power_devig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove vig using the power method. Solves for n where p_a^n + p_b^n = 1.

    Falls back to naive normalization if inputs are degenerate.
    """
    total = prob_a + prob_b
    if total <= 0:
        return (0.5, 0.5)
    # No vig to remove
    if abs(total - 1.0) < 1e-6:
        return (prob_a, prob_b)
    # Guard against degenerate inputs
    if prob_a <= 0.001 or prob_b <= 0.001:
        return (prob_a / total, prob_b / total)

    # Bisection: find n where prob_a^n + prob_b^n = 1
    # When n=1, f(n) = prob_a + prob_b - 1 > 0 (there is vig)
    # As n increases, both prob^n shrink, so f(n) decreases
    lo, hi = 0.01, 20.0
    for _ in range(100):  # ~30 iterations gives 1e-9 precision
        mid = (lo + hi) / 2
        val = prob_a ** mid + prob_b ** mid
        if val > 1.0:
            lo = mid
        else:
            hi = mid
        if abs(val - 1.0) < 1e-10:
            break

    n = (lo + hi) / 2
    return (round(prob_a ** n, 6), round(prob_b ** n, 6))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_odds.py::test_power_devig_sums_to_one tests/test_odds.py::test_power_devig_shifts_favorite tests/test_odds.py::test_power_devig_even_odds tests/test_odds.py::test_power_devig_no_vig_passthrough -v`
Expected: All PASS

- [ ] **Step 5: Replace naive normalization in `scrapers/odds.py` lines 254-268**

Replace moneyline vig removal (lines 256-261):
```python
# Before:
ml_home = american_to_implied_prob(odds_data.moneyline["home"])
ml_away = american_to_implied_prob(odds_data.moneyline["away"])
# Remove vig by normalizing
total_prob = ml_home + ml_away
odds_data.implied_probs["ml_home"] = ml_home / total_prob
odds_data.implied_probs["ml_away"] = ml_away / total_prob
```
```python
# After:
ml_home = american_to_implied_prob(odds_data.moneyline["home"])
ml_away = american_to_implied_prob(odds_data.moneyline["away"])
dv_home, dv_away = power_devig(ml_home, ml_away)
odds_data.implied_probs["ml_home"] = dv_home
odds_data.implied_probs["ml_away"] = dv_away
```

Replace run_line vig removal (lines 263-268):
```python
# Before:
rl_home = american_to_implied_prob(odds_data.run_line.get("home_odds", -110))
rl_away = american_to_implied_prob(odds_data.run_line.get("away_odds", -110))
total_prob = rl_home + rl_away
odds_data.implied_probs["rl_home"] = rl_home / total_prob
odds_data.implied_probs["rl_away"] = rl_away / total_prob
```
```python
# After:
rl_home = american_to_implied_prob(odds_data.run_line.get("home_odds", -110))
rl_away = american_to_implied_prob(odds_data.run_line.get("away_odds", -110))
dv_home, dv_away = power_devig(rl_home, rl_away)
odds_data.implied_probs["rl_home"] = dv_home
odds_data.implied_probs["rl_away"] = dv_away
```

- [ ] **Step 6: Replace 9 inline vig blocks in `edge.py`**

Update import at line 5:
```python
from scrapers.odds import OddsData, american_to_implied_prob, power_devig
```

Replace each inline vig block. The pattern for each:

**`check_run_line_edge()` lines 104-108:**
```python
# Before:
fav_implied = american_to_implied_prob(fav_odds)
dog_implied = american_to_implied_prob(dog_odds)
total = fav_implied + dog_implied
fav_implied /= total
dog_implied /= total
```
```python
# After:
fav_implied, dog_implied = power_devig(
    american_to_implied_prob(fav_odds),
    american_to_implied_prob(dog_odds),
)
```

**`check_total_edge()` lines 155-159:**
```python
# Before:
over_implied = american_to_implied_prob(over_odds)
under_implied = american_to_implied_prob(under_odds)
total_impl = over_implied + under_implied
over_implied /= total_impl
under_implied /= total_impl
```
```python
# After:
over_implied, under_implied = power_devig(
    american_to_implied_prob(over_odds),
    american_to_implied_prob(under_odds),
)
```

**`check_f5_ml_edge()` lines 208-212** — same pattern as total (h_implied, a_implied)

**`check_f5_total_edge()` lines 269-273** — same pattern (over_implied, under_implied)

**`check_team_total_edge()` lines 340-344** — same pattern (over_implied, under_implied)

**`_check_innings_spread_edge()` lines 401-405** — same pattern (h_implied, a_implied)

**`check_nrfi_edge()` lines 472-476** — same pattern (nrfi_implied, yrfi_implied)

**`check_f3_ml_edge()` lines 524-528** — same pattern (h_implied, a_implied)

**`check_f3_total_edge()` lines 582-586** — same pattern (over_implied, under_implied)

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/test_edge.py tests/test_edge_phase1.py tests/test_odds.py tests/test_odds_phase1.py -v`
Expected: All PASS. If any tests fail due to shifted probability values, update expected values to match power devig outputs.

- [ ] **Step 8: Commit**

```bash
git add scrapers/odds.py edge.py tests/test_odds.py
git commit -m "feat: replace naive vig removal with power method devig

Solves for exponent n where p_a^n + p_b^n = 1 instead of
simple p/sum(p) normalization. Corrects ~1.6% systematic
mispricing on favorites across all 11 vig removal sites."
```

---

## Task 2: Replace F5 Total Heuristic with Poisson

**Files:**
- Modify: `edge.py` lines 275-279
- Test: `tests/test_edge.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_edge.py`:

```python
def test_f5_total_uses_poisson_not_heuristic():
    """F5 total should use Poisson CDF, giving higher probs at extreme deltas."""
    sim = {
        "predictions": {
            "first_5": {
                "f5_projected_total": 6.5,
                "f5_total_value": "over",
                "confidence": "medium",
            }
        }
    }
    odds = {
        "f5_total": {"line": 4.5, "over_odds": -110, "under_odds": -110},
    }
    result = check_f5_total_edge(sim, odds)
    assert result is not None
    # Old heuristic: 0.5 + (6.5-4.5)*0.10 = 0.70
    # Poisson: _poisson_over_prob(6.5, 4.5) ≈ 0.776
    assert result["sim_prob"] > 0.75, f"Expected Poisson prob > 0.75, got {result['sim_prob']}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_edge.py::test_f5_total_uses_poisson_not_heuristic -v`
Expected: FAIL — sim_prob will be ~0.70 under old heuristic

- [ ] **Step 3: Replace heuristic with Poisson**

In `edge.py`, replace lines 275-279:
```python
# Before:
# Heuristic: estimate probability from projected vs line delta
# Each 0.5 run delta roughly corresponds to ~5% probability shift from 50%
delta = projected - line
over_prob = min(max(0.5 + delta * 0.10, 0.01), 0.99)
under_prob = 1 - over_prob
```
```python
# After:
over_prob = _poisson_over_prob(float(projected), line)
under_prob = 1 - over_prob
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_edge.py tests/test_edge_phase1.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add edge.py tests/test_edge.py
git commit -m "feat: replace F5 total heuristic with Poisson CDF

The linear heuristic (0.5 + delta * 0.10) underestimated edge
at extremes by up to 7.6%. Reuses existing _poisson_over_prob()
already used by team totals and F3 totals."
```

---

## Task 3: Best-Line Selection Across Bookmakers

**Files:**
- Modify: `scrapers/odds.py` — restructure `get_mlb_odds()` lines 207-252, modify `get_additional_odds()` lines 133-136, add `book_sources` to `OddsData`
- Test: `tests/test_odds.py`

- [ ] **Step 1: Add `book_sources` field to `OddsData`**

In `scrapers/odds.py`, add after `f3_spread` field (line 35):
```python
book_sources: dict = field(default_factory=dict)
```

- [ ] **Step 2: Add `_american_to_decimal()` helper**

Add a private helper in `scrapers/odds.py` (to avoid circular import with `edge.py`):
```python
def _american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal odds for comparison."""
    if odds < 0:
        return 100 / abs(odds) + 1
    return odds / 100 + 1
```

- [ ] **Step 3: Write failing tests**

Add to `tests/test_odds.py`:

```python
def test_get_mlb_odds_selects_best_line(mock_api_response):
    """Should pick best decimal odds per side across bookmakers."""
    # Build response with 3 bookmakers having different h2h odds
    event = mock_api_response[0]
    event["bookmakers"] = [
        {
            "key": "fanduel",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "New York Yankees", "price": -150},
                {"name": "Boston Red Sox", "price": 130},
            ]}],
        },
        {
            "key": "draftkings",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "New York Yankees", "price": -140},
                {"name": "Boston Red Sox", "price": 125},
            ]}],
        },
        {
            "key": "betmgm",
            "markets": [{"key": "h2h", "outcomes": [
                {"name": "New York Yankees", "price": -145},
                {"name": "Boston Red Sox", "price": 135},
            ]}],
        },
    ]
    # Patch request and run
    with patch("scrapers.odds.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_api_response
        mock_resp.headers = {"x-requests-remaining": "450"}
        mock_get.return_value = mock_resp

        results = get_mlb_odds()
        assert len(results) >= 1
        game = results[0]
        # Best home: -140 (highest decimal = 1.714)
        assert game.moneyline["home"] == -140
        # Best away: +135 (highest decimal = 2.35)
        assert game.moneyline["away"] == 135

def test_get_mlb_odds_tracks_book_sources(mock_api_response):
    """Should record which bookmaker provided each best line."""
    # Same multi-book setup as above
    # ... (setup with patch)
    # Assert book_sources is populated
    assert "h2h_home" in game.book_sources
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `python -m pytest tests/test_odds.py::test_get_mlb_odds_selects_best_line -v`
Expected: FAIL — currently takes first bookmaker

- [ ] **Step 5: Rewrite bookmaker loop in `get_mlb_odds()`**

Replace lines 207-252 with best-line selection logic:

```python
        # Collect best price per side per market across all bookmakers
        best = {}  # (market_key, side_id): (decimal_odds, american_odds, book_name)
        best_points = {}  # (market_key, side_id): point value (for spreads/totals)

        for bk in event.get("bookmakers", []):
            book_name = bk.get("key", "unknown")
            markets = {m["key"]: m for m in bk.get("markets", [])}

            for market_key, market_data in markets.items():
                for outcome in market_data.get("outcomes", []):
                    price = outcome["price"]
                    dec = _american_to_decimal(price)
                    side_id = _team_abbrev(outcome["name"]) if market_key in ("h2h", "spreads", "h2h_1st_5_innings") else outcome["name"]
                    key = (market_key, side_id)

                    if key not in best or dec > best[key][0]:
                        best[key] = (dec, price, book_name)
                        if "point" in outcome:
                            best_points[key] = outcome["point"]

        # Populate odds_data from best lines
        if ("h2h", home) in best:
            odds_data.moneyline["home"] = best[("h2h", home)][1]
            odds_data.book_sources["h2h_home"] = best[("h2h", home)][2]
        if ("h2h", away) in best:
            odds_data.moneyline["away"] = best[("h2h", away)][1]
            odds_data.book_sources["h2h_away"] = best[("h2h", away)][2]

        if ("spreads", home) in best:
            odds_data.run_line["home"] = best_points.get(("spreads", home), -1.5)
            odds_data.run_line["home_odds"] = best[("spreads", home)][1]
            odds_data.book_sources["spreads_home"] = best[("spreads", home)][2]
        if ("spreads", away) in best:
            odds_data.run_line["away"] = best_points.get(("spreads", away), 1.5)
            odds_data.run_line["away_odds"] = best[("spreads", away)][1]
            odds_data.book_sources["spreads_away"] = best[("spreads", away)][2]

        if ("totals", "Over") in best:
            odds_data.total["line"] = best_points.get(("totals", "Over"), 0)
            odds_data.total["over_odds"] = best[("totals", "Over")][1]
            odds_data.book_sources["totals_over"] = best[("totals", "Over")][2]
        if ("totals", "Under") in best:
            odds_data.total["under_odds"] = best[("totals", "Under")][1]
            odds_data.book_sources["totals_under"] = best[("totals", "Under")][2]

        if ("h2h_1st_5_innings", home) in best:
            odds_data.f5_moneyline["home"] = best[("h2h_1st_5_innings", home)][1]
            odds_data.book_sources["f5_ml_home"] = best[("h2h_1st_5_innings", home)][2]
        if ("h2h_1st_5_innings", away) in best:
            odds_data.f5_moneyline["away"] = best[("h2h_1st_5_innings", away)][1]
            odds_data.book_sources["f5_ml_away"] = best[("h2h_1st_5_innings", away)][2]

        if ("totals_1st_5_innings", "Over") in best:
            odds_data.f5_total["line"] = best_points.get(("totals_1st_5_innings", "Over"), 0)
            odds_data.f5_total["over"] = best[("totals_1st_5_innings", "Over")][1]
            odds_data.book_sources["f5_total_over"] = best[("totals_1st_5_innings", "Over")][2]
        if ("totals_1st_5_innings", "Under") in best:
            odds_data.f5_total["under"] = best[("totals_1st_5_innings", "Under")][1]
            odds_data.book_sources["f5_total_under"] = best[("totals_1st_5_innings", "Under")][2]
```

Note: The `break` at old line 252 is simply removed — no early exit.

- [ ] **Step 6: Apply same pattern to `get_additional_odds()`**

Replace lines 133-136:
```python
# Before:
for bk in data.get("bookmakers", []):
    markets = {m["key"]: m for m in bk.get("markets", [])}
    if markets:
        return markets
```
```python
# After — merge best outcomes across all bookmakers:
merged = {}
for bk in data.get("bookmakers", []):
    for m in bk.get("markets", []):
        mk = m["key"]
        if mk not in merged:
            merged[mk] = {"key": mk, "outcomes": []}
        # For each outcome, keep best decimal odds per side
        existing = {_outcome_key(o): o for o in merged[mk].get("outcomes", [])}
        for outcome in m.get("outcomes", []):
            okey = _outcome_key(outcome)
            if okey not in existing or _american_to_decimal(outcome["price"]) > _american_to_decimal(existing[okey]["price"]):
                existing[okey] = outcome
        merged[mk]["outcomes"] = list(existing.values())
return merged if merged else {}
```

Add helper:
```python
def _outcome_key(outcome: dict) -> str:
    """Unique key for an outcome within a market."""
    return f"{outcome.get('name', '')}_{outcome.get('description', '')}"
```

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/test_odds.py tests/test_odds_phase1.py tests/test_edge.py tests/test_edge_phase1.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add scrapers/odds.py tests/test_odds.py
git commit -m "feat: select best line across all bookmakers per market side

Iterates all bookmakers in the API response and picks the highest
decimal odds per side. Typical gain: 1-2% implied probability on
lines where books disagree. Tracks source book per line."
```

---

## Task 4: Confidence Weighting in Ensemble Averaging

**Files:**
- Modify: `ensemble/consensus.py` — add `CONFIDENCE_MULTIPLIERS`, update `weighted_average_prob()`
- Modify: `ensemble/orchestrator.py` — pass per-slot confidences in `build_ensemble_result()`, fix `_log_all_predictions()` market_prob
- Test: `tests/test_ensemble_consensus.py`, `tests/test_ensemble_orchestrator.py`

- [ ] **Step 1: Write failing tests for confidence weighting**

Add to `tests/test_ensemble_consensus.py`:

```python
def test_weighted_average_prob_with_confidences():
    """High-confidence models should pull average toward their estimate."""
    runs = [
        {"model_key": "kimi", "prob": 0.55},
        {"model_key": "gpt4o", "prob": 0.60},
        {"model_key": "gemini", "prob": 0.50},
    ]
    weights = {"kimi": 1.0, "gpt4o": 1.0, "gemini": 1.0}
    confidences = {"kimi": "high", "gpt4o": "medium", "gemini": "low"}
    avg = weighted_average_prob(runs, weights, confidences)
    # kimi: 1.0*1.3=1.3, gpt4o: 1.0*1.0=1.0, gemini: 1.0*0.7=0.7
    # num = 1.3*0.55 + 1.0*0.60 + 0.7*0.50 = 0.715+0.60+0.35 = 1.665
    # den = 1.3+1.0+0.7 = 3.0 -> avg = 0.555
    assert abs(avg - 0.555) < 0.001

def test_weighted_average_prob_no_confidences_unchanged():
    """Without confidences param, result matches old behavior."""
    runs = [
        {"model_key": "a", "prob": 0.60},
        {"model_key": "b", "prob": 0.40},
    ]
    weights = {"a": 2.0, "b": 1.0}
    # Without confidences
    avg = weighted_average_prob(runs, weights)
    # (2.0*0.60 + 1.0*0.40) / (2.0+1.0) = 1.60/3.0 = 0.5333
    assert abs(avg - 0.5333) < 0.001
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ensemble_consensus.py::test_weighted_average_prob_with_confidences -v`
Expected: FAIL — `weighted_average_prob` doesn't accept `confidences` parameter

- [ ] **Step 3: Implement confidence weighting in `ensemble/consensus.py`**

Add after imports (line 2):
```python
CONFIDENCE_MULTIPLIERS = {"high": 1.3, "medium": 1.0, "low": 0.7}
```

Modify `weighted_average_prob()` at line 64:
```python
def weighted_average_prob(runs: list[dict], weights: dict[str, float],
                          confidences: dict[str, str] = None) -> float:
    """Weighted average of probability estimates across runs.
    Each run dict has: {"model_key": str, "prob": float}
    Optional confidences dict maps model_key -> "high"/"medium"/"low".
    """
    numerator = 0.0
    denominator = 0.0
    for run in runs:
        w = weights.get(run["model_key"], 1.0)
        if confidences:
            conf = confidences.get(run["model_key"], "medium")
            w *= CONFIDENCE_MULTIPLIERS.get(conf, 1.0)
        numerator += w * run["prob"]
        denominator += w
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)
```

- [ ] **Step 4: Run consensus tests**

Run: `python -m pytest tests/test_ensemble_consensus.py -v`
Expected: All PASS (including old `test_weighted_average_prob` unchanged)

- [ ] **Step 5: Pass per-slot confidences in `orchestrator.py:build_ensemble_result()`**

In `build_ensemble_result()`, within the weighted averaging loop (around line 412-425), extract per-model confidence for the current slot's section and pass to `weighted_average_prob()`:

```python
        for field in fields:
            runs = []
            confidences = {}
            for r in results:
                mk = r["model_key"]
                sec = r["parsed"].get("predictions", {}).get(section_key, {})
                val = sec.get(field)
                if val is not None:
                    try:
                        runs.append({"model_key": mk, "prob": float(val)})
                    except (ValueError, TypeError):
                        continue
                if mk not in confidences:
                    confidences[mk] = sec.get("confidence", "medium")
            if runs:
                avg = weighted_average_prob(runs, slot_weights, confidences=confidences)
                section[field] = avg
```

- [ ] **Step 6: Fix `_log_all_predictions()` market_prob at line 357**

Replace lines 356-358:
```python
# Before:
implied = odds.get("implied_probs", {})
market_prob = implied.get(f"ml_home", 0.5)  # rough fallback
edge = prob - market_prob if prob else 0.0
```
```python
# After:
implied = odds.get("implied_probs", {})
_SLOT_IMPLIED_KEY = {
    "moneyline": "ml_home", "run_line": "rl_home",
}
implied_key = _SLOT_IMPLIED_KEY.get(slot)
market_prob = implied.get(implied_key, 0.5) if implied_key else 0.5
edge = prob - market_prob if prob else 0.0
```

Note: Move `_SLOT_IMPLIED_KEY` to module level (near `PROB_FIELDS` dict) for cleanliness.

- [ ] **Step 7: Run orchestrator tests**

Run: `python -m pytest tests/test_ensemble_orchestrator.py tests/test_ensemble_consensus.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add ensemble/consensus.py ensemble/orchestrator.py tests/test_ensemble_consensus.py
git commit -m "feat: add confidence weighting to ensemble probability averaging

High-confidence models (1.3x) pull average ~8% more toward their
estimate vs low-confidence (0.7x). Also fixes _log_all_predictions
to use correct implied prob key per bet type instead of hardcoded
ml_home for all slots."
```

---

## Task 5: Calibration Identity Hook

**Files:**
- Modify: `calibrate.py` — add `apply_calibration()`
- Modify: `edge.py` — import and apply in all 12 edge checkers
- Test: `tests/test_calibrate.py`, `tests/test_edge.py`

- [ ] **Step 1: Write failing test for `apply_calibration()`**

Add to `tests/test_calibrate.py`:

```python
from calibrate import apply_calibration

def test_apply_calibration_identity():
    """Identity function today — returns input unchanged."""
    assert apply_calibration(0.6, "moneyline") == 0.6
    assert apply_calibration(0.45, "total") == 0.45
    assert apply_calibration(0.0, "") == 0.0
    assert apply_calibration(1.0, "nrfi") == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_calibrate.py::test_apply_calibration_identity -v`
Expected: ImportError — `apply_calibration` doesn't exist

- [ ] **Step 3: Implement `apply_calibration()` in `calibrate.py`**

Add before `calibration_report()` (around line 12):

```python
def apply_calibration(prob: float, bet_type: str = "") -> float:
    """Identity today. Isotonic regression once 200+ bets available."""
    return prob
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_calibrate.py -v`
Expected: All PASS

- [ ] **Step 5: Wire `apply_calibration` into all 12 edge checkers in `edge.py`**

Add import at top of `edge.py`:
```python
from calibrate import apply_calibration
```

Insert calibration calls in each checker — apply to the ensemble/simulation probability BEFORE computing edge:

**`check_moneyline_edge()`** — after lines 37-43 (reading home_prob, away_prob):
```python
    home_prob = apply_calibration(home_prob, "moneyline")
    away_prob = apply_calibration(away_prob, "moneyline")
```

**`check_run_line_edge()`** — after reading fav_prob (~line 83):
```python
    fav_prob = apply_calibration(fav_prob, "run_line")
```

**`check_total_edge()`** — after lines 150-151 (reading over_prob, under_prob):
```python
    over_prob = apply_calibration(over_prob, "total")
    under_prob = apply_calibration(under_prob, "total")
```

**`check_f5_ml_edge()`** — after lines 214-215 (reading h_prob, a_prob):
```python
    h_prob = apply_calibration(h_prob, "first_5_ml")
    a_prob = apply_calibration(a_prob, "first_5_ml")
```

**`check_f5_total_edge()`** — after Poisson computation (post-Fix 2):
```python
    over_prob = apply_calibration(over_prob, "first_5_total")
    under_prob = apply_calibration(under_prob, "first_5_total")
```

**`check_team_total_edge()`** — after line 336:
```python
    over_prob = apply_calibration(over_prob, bet_type)
    under_prob = apply_calibration(under_prob, bet_type)
```

**`_check_innings_spread_edge()`** — after lines 394-397 (composite probs computed):
```python
    home_minus_prob = apply_calibration(home_minus_prob, bet_type)
    away_plus_prob = apply_calibration(away_plus_prob, bet_type)
    away_minus_prob = apply_calibration(away_minus_prob, bet_type)
    home_plus_prob = apply_calibration(home_plus_prob, bet_type)
```

**`check_nrfi_edge()`** — after lines 467-468:
```python
    nrfi_prob = apply_calibration(nrfi_prob, "nrfi")
    yrfi_prob = apply_calibration(yrfi_prob, "nrfi")
```

**`check_f3_ml_edge()`** — after lines 530-531:
```python
    h_prob = apply_calibration(h_prob, "first_3_ml")
    a_prob = apply_calibration(a_prob, "first_3_ml")
```

**`check_f3_total_edge()`** — after line 577-578:
```python
    over_prob = apply_calibration(over_prob, "first_3_total")
    under_prob = apply_calibration(under_prob, "first_3_total")
```

- [ ] **Step 6: Write test verifying calibration is called**

Add to `tests/test_edge.py`:

```python
from unittest.mock import patch

def test_edge_calls_apply_calibration():
    """Verify calibration hook is wired into edge checkers."""
    sim = {
        "predictions": {
            "moneyline": {"home_win_prob": 0.62, "away_win_prob": 0.38, "confidence": "medium"},
        }
    }
    odds = {
        "moneyline": {"home": -150, "away": 130},
        "implied_probs": {"ml_home": 0.565, "ml_away": 0.435},
    }
    with patch("edge.apply_calibration", side_effect=lambda p, bt: p) as mock_cal:
        check_moneyline_edge(sim, odds)
        assert mock_cal.call_count >= 1
        # Verify it was called with the probability and bet type
        calls = mock_cal.call_args_list
        bet_types = [c[0][1] for c in calls]
        assert "moneyline" in bet_types
```

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/test_edge.py tests/test_edge_phase1.py tests/test_calibrate.py -v`
Expected: All PASS (identity function = no behavioral change)

- [ ] **Step 8: Commit**

```bash
git add calibrate.py edge.py tests/test_calibrate.py tests/test_edge.py
git commit -m "feat: add calibration identity hook to all 12 edge checkers

apply_calibration() returns prob unchanged today. Provides clean
injection point for future isotonic regression calibration without
requiring shotgun surgery across edge checkers."
```

---

## Verification

After all 5 tasks are complete:

- [ ] **Run full test suite:** `python -m pytest tests/ -v`
- [ ] **Verify no regressions:** All pre-existing tests pass
- [ ] **Spot-check power devig output:** Run `python -c "from scrapers.odds import power_devig, american_to_implied_prob; print(power_devig(american_to_implied_prob(-200), american_to_implied_prob(170)))"` — should output values summing to 1.0 with the favorite ~0.556 (not 0.643 from naive)
- [ ] **Spot-check F5 Poisson:** Run `python -c "from edge import _poisson_over_prob; print(_poisson_over_prob(6.5, 4.5))"` — should output ~0.776 (not 0.70 from heuristic)
