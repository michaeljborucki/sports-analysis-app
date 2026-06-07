# Parallel Game Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parallelize game screening and simulation in the daily pipeline so 15+ game days complete within the 1-hour timeout.

**Architecture:** Replace the two sequential `for` loops in `main.py` (Steps 5 and 6) with `ThreadPoolExecutor` + `as_completed`. Add `threading.Lock` to four shared file resources. Remove `signal.SIGALRM` timeout in favor of `future.result(timeout=...)`.

**Tech Stack:** `concurrent.futures.ThreadPoolExecutor`, `threading.Lock`, existing OpenRouter/MLB APIs.

**Spec:** `docs/superpowers/specs/2026-03-22-parallel-game-processing-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `config.py` | Modify | Add `PARALLEL_GAMES = 4` |
| `tracker.py` | Modify | Add `_csv_lock` around CSV read-modify-write |
| `scrapers/player_stats.py` | Modify | Add `_player_map_lock` around cache + unmatched log |
| `ensemble/logger.py` | Modify | Add `_log_lock` around CSV append |
| `ensemble/weights.py` | Modify | Add `_weights_lock` around load/save |
| `ensemble/orchestrator.py` | Modify | Replace `print()` with `logger.error()` |
| `main.py` | Modify | Extract `_screen_game`/`_simulate_game`, replace loops with ThreadPoolExecutor |
| `tests/test_tracker.py` | Modify | Add concurrent write test |
| `tests/test_player_stats.py` | Modify | Add concurrent resolve test |
| `tests/test_parallel_pipeline.py` | Create | Test parallel screening and simulation |

---

### Task 1: Add `PARALLEL_GAMES` to config

**Files:**
- Modify: `config.py:29` (after `GAME_TIMEOUT`)

- [ ] **Step 1: Add the constant**

In `config.py`, after line 29 (`GAME_TIMEOUT = 300`), add:

```python
PARALLEL_GAMES = 4  # max games processed concurrently (screen + sim)
```

- [ ] **Step 2: Verify import works**

Run: `python3 -c "from config import PARALLEL_GAMES; print(PARALLEL_GAMES)"`
Expected: `4`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add PARALLEL_GAMES config constant"
```

---

### Task 2: Thread-safe bet logging in `tracker.py`

**Files:**
- Modify: `tracker.py`
- Test: `tests/test_tracker.py`

- [ ] **Step 1: Write the failing concurrency test**

Add to `tests/test_tracker.py`:

```python
import threading

def test_concurrent_log_bet(tmp_path):
    """Verify no bets are lost when logging concurrently."""
    csv_path = str(tmp_path / "concurrent_bets.csv")
    bets = [
        {"date": "2026-03-22", "game": f"TEAM{i}@OPP{i}", "bet_type": "moneyline",
         "side": f"TEAM{i}", "odds": -110, "sim_prob": 0.55,
         "edge": 0.05, "kelly_pct": 0.02}
        for i in range(20)
    ]

    threads = [threading.Thread(target=log_bet, args=(b,), kwargs={"csv_path": csv_path}) for b in bets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    df = pd.read_csv(csv_path)
    assert len(df) == 20, f"Expected 20 bets, got {len(df)}"
```

- [ ] **Step 2: Run test to verify it fails (or shows race condition)**

Run: `pytest tests/test_tracker.py::test_concurrent_log_bet -v`
Expected: May pass or fail depending on timing — the point is the code is unsafe without locks.

- [ ] **Step 3: Add threading lock to tracker.py**

Add `import threading` to the imports at line 2, and add the module-level lock after the COLUMNS definition (after line 9):

```python
import threading

_csv_lock = threading.Lock()
```

Modify `log_bet` (lines 20-31) to wrap the entire body (including `_ensure_csv`) under the lock:

```python
def log_bet(bet: dict, csv_path: str = None) -> None:
    """Append a bet to the CSV tracker."""
    csv_path = csv_path or BETS_CSV

    row = {col: bet.get(col, "") for col in COLUMNS}
    row.setdefault("result", "")
    row.setdefault("profit", "")

    with _csv_lock:
        _ensure_csv(csv_path)
        df = pd.read_csv(csv_path)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(csv_path, index=False)
```

Modify `update_result` (lines 41-59) to wrap under the same lock:

```python
def update_result(index: int, result: str, csv_path: str = None) -> None:
    """Update a bet's result (W/L/P) and calculate profit."""
    csv_path = csv_path or BETS_CSV
    with _csv_lock:
        df = pd.read_csv(csv_path, dtype={"result": str, "profit": float})
        df["result"] = df["result"].astype(object)
        df.at[index, "result"] = result

        odds = df.at[index, "odds"]
        if result == "W":
            if odds < 0:
                df.at[index, "profit"] = round(100 / abs(odds), 2)
            else:
                df.at[index, "profit"] = round(odds / 100, 2)
        elif result == "L":
            df.at[index, "profit"] = -1.0
        else:  # Push
            df.at[index, "profit"] = 0.0

        df.to_csv(csv_path, index=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tracker.py -v`
Expected: All tests PASS including `test_concurrent_log_bet`

- [ ] **Step 5: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: add threading lock to tracker CSV operations"
```

---

### Task 3: Thread-safe player map in `scrapers/player_stats.py`

**Files:**
- Modify: `scrapers/player_stats.py`
- Test: `tests/test_player_stats.py`

- [ ] **Step 1: Write the failing concurrency test**

Add to `tests/test_player_stats.py`:

```python
import threading
from unittest.mock import patch

def test_concurrent_resolve_player(tmp_path):
    """Verify no player IDs are lost when resolving concurrently."""
    map_file = str(tmp_path / "player_map.json")
    names = [f"Player {i}" for i in range(10)]

    def mock_api_search(url, params=None, timeout=None):
        """Return a unique player ID for each name."""
        name = params["names"]
        idx = int(name.split()[-1])
        mock_resp = type("Resp", (), {
            "status_code": 200,
            "json": lambda self: {"people": [{"id": 100000 + idx, "active": True}]}
        })()
        return mock_resp

    with patch("scrapers.player_stats.PLAYER_MAP_FILE", map_file), \
         patch("scrapers.player_stats.requests.get", side_effect=mock_api_search):
        threads = [threading.Thread(target=resolve_player, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    import json
    with open(map_file) as f:
        mapping = json.load(f)
    assert len(mapping) == 10, f"Expected 10 players cached, got {len(mapping)}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_player_stats.py::test_concurrent_resolve_player -v`
Expected: FAIL — concurrent writes lose entries in player_map.json

- [ ] **Step 3: Add threading lock with narrow scope**

Add `import threading` to imports at line 1, and add after the UNMATCHED_LOG constant (after line 9):

```python
import threading

_player_map_lock = threading.Lock()
```

Modify `resolve_player` (lines 36-90) to lock only around cache reads and writes, NOT around the API call:

```python
def resolve_player(name: str, team: str = None) -> int | None:
    """Resolve a player display name to MLB player ID."""
    if not name:
        return None

    # 1. Check cache (locked)
    with _player_map_lock:
        mapping = _load_player_map()
        if name in mapping:
            return mapping[name]

    # 2. MLB Stats API search (unlocked — no lock during network I/O)
    pid = None
    try:
        url = f"{MLB_API_BASE}/people/search"
        resp = requests.get(url, params={"names": name, "limit": 5}, timeout=10)
        if resp.status_code == 200:
            people = resp.json().get("people", [])
            if people:
                for p in people:
                    if p.get("active", False):
                        pid = p["id"]
                        break
                if pid is None:
                    pid = people[0]["id"]
    except Exception:
        pass

    # 3. Fuzzy match against cache (locked)
    if pid is None:
        with _player_map_lock:
            mapping = _load_player_map()
            cached_names = list(mapping.keys())
            if cached_names:
                matches = difflib.get_close_matches(name, cached_names, n=1, cutoff=0.85)
                if matches:
                    pid = mapping[matches[0]]

    # 4. Save to cache if resolved (locked, re-read to avoid lost updates)
    if pid is not None:
        with _player_map_lock:
            mapping = _load_player_map()
            mapping[name] = pid
            _save_player_map(mapping)
        return pid

    # 5. Log unmatched (locked)
    with _player_map_lock:
        try:
            os.makedirs(os.path.dirname(UNMATCHED_LOG), exist_ok=True)
            with open(UNMATCHED_LOG, "a") as f:
                f.write(f"{name} (team={team})\n")
        except Exception:
            pass

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_player_stats.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add scrapers/player_stats.py tests/test_player_stats.py
git commit -m "feat: add threading lock to player map cache"
```

---

### Task 4: Thread-safe ensemble logger and weights

**Files:**
- Modify: `ensemble/logger.py`
- Modify: `ensemble/weights.py`
- Modify: `ensemble/orchestrator.py:373`

- [ ] **Step 1: Add lock to ensemble/logger.py**

Add `import threading` at line 2, add lock after line 9:

```python
import threading

_log_lock = threading.Lock()
```

Modify `log_model_prediction` (lines 16-27) to wrap under the lock:

```python
def log_model_prediction(
    date: str, game: str, model: str, bet_type: str, side: str,
    sim_prob: float, market_prob: float, edge: float,
    temperature: float, run_index: int, csv_path: str = None,
) -> None:
    csv_path = csv_path or MODEL_PREDICTIONS_CSV
    row = {
        "date": date, "game": game, "model": model,
        "bet_type": bet_type, "side": side,
        "sim_prob": round(sim_prob, 4), "market_prob": round(market_prob, 4),
        "edge": round(edge, 4), "temperature": temperature,
        "run_index": run_index,
    }
    with _log_lock:
        _ensure_csv(csv_path)
        df = pd.read_csv(csv_path)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(csv_path, index=False)
```

- [ ] **Step 2: Add lock to ensemble/weights.py**

Add `import threading` at line 2, add lock after line 10:

```python
import threading

_weights_lock = threading.Lock()
```

Modify `load_weights` (lines 17-25) — inline the file write instead of calling `save_weights` to avoid deadlock (Lock is non-reentrant):

```python
def load_weights(path: str = None) -> dict:
    path = path or MODEL_WEIGHTS_FILE
    with _weights_lock:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        w = default_weights()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(w, f, indent=2)
        return w
```

Modify `save_weights` (lines 28-31):

```python
def save_weights(weights: dict, path: str = None) -> None:
    path = path or MODEL_WEIGHTS_FILE
    with _weights_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(weights, f, indent=2)
```

- [ ] **Step 3: Fix print() in ensemble/orchestrator.py**

At line 373 of `ensemble/orchestrator.py`, change:

```python
print(f"[ensemble] Failed to log prediction for {mk}/{slot}: {e}")
```

to:

```python
logger.error("Failed to log prediction for %s/%s: %s", mk, slot, e)
```

The `logger` object is already defined at line 16 as `logging.getLogger("mirofish.ensemble")`.

- [ ] **Step 4: Run existing ensemble tests**

Run: `pytest tests/test_ensemble_logger.py tests/test_ensemble_orchestrator.py tests/test_ensemble_runner.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add ensemble/logger.py ensemble/weights.py ensemble/orchestrator.py
git commit -m "feat: add threading locks to ensemble logger, weights, and fix print()"
```

---

### Task 5: Parallel screening in `main.py` (Step 5)

**Files:**
- Modify: `main.py`
- Test: `tests/test_parallel_pipeline.py` (create)

- [ ] **Step 1: Write the test for `_screen_game`**

Create `tests/test_parallel_pipeline.py`:

```python
"""Tests for parallel game processing in main.py."""
from unittest.mock import patch, MagicMock
from main import _screen_game


def _make_game(away="NYY", home="BOS"):
    return {
        "away_team": away, "home_team": home,
        "away_pitcher": "TestPitcher", "home_pitcher": "TestPitcher",
        "away_team_id": 147, "home_team_id": 111,
    }


def _make_odds(away="NYY", home="BOS"):
    odds = MagicMock()
    odds.moneyline = {"away": -110, "home": 100}
    odds.run_line = {"away": {"line": -1.5, "odds": 150}, "home": {"line": 1.5, "odds": -170}}
    odds.total = {"over": {"line": 8.5, "odds": -110}, "under": {"line": 8.5, "odds": -110}}
    odds.f5_moneyline = {}
    odds.f5_total = {}
    odds.f3_moneyline = {}
    odds.f3_total = {}
    odds.f1_total = {}
    odds.team_total_home = {}
    odds.team_total_away = {}
    odds.implied_probs = {"away": 0.52, "home": 0.48}
    return odds


@patch("main.get_starter_profile", return_value={"name": "TestPitcher", "era": 3.50})
@patch("main.get_team_profile", return_value={"record": "10-5"})
@patch("main.get_game_environment", return_value={"venue": "Test Park"})
@patch("main.get_bullpen_state", return_value={})
@patch("main.build_briefing", return_value="Test briefing")
@patch("main.run_plan_b", return_value={"moneyline": {"away_win": 0.55, "home_win": 0.45}})
@patch("main.analyze_all_edges", return_value=[{"edge": 0.06, "bet_type": "moneyline", "side": "NYY"}])
def test_screen_game_returns_result(mock_edges, mock_planb, mock_brief,
                                     mock_bullpen, mock_env, mock_team, mock_pitcher):
    game = _make_game()
    odds_map = {"NYY@BOS": _make_odds()}
    result = _screen_game(game, odds_map, {}, "2026-03-22")
    assert result is not None
    game_key, brief, game_data, max_edge = result
    assert game_key == "NYY@BOS"
    assert max_edge == 0.06


@patch("main.get_starter_profile", return_value={"name": "TestPitcher"})
@patch("main.get_team_profile", return_value={"record": "10-5"})
@patch("main.get_game_environment", return_value={"venue": "Test Park"})
@patch("main.get_bullpen_state", return_value={})
@patch("main.build_briefing", return_value="Test briefing")
@patch("main.run_plan_b", return_value=None)
def test_screen_game_returns_none_on_failed_screen(mock_planb, mock_brief,
                                                     mock_bullpen, mock_env,
                                                     mock_team, mock_pitcher):
    game = _make_game()
    odds_map = {"NYY@BOS": _make_odds()}
    result = _screen_game(game, odds_map, {}, "2026-03-22")
    assert result is None


def test_screen_game_returns_none_when_no_odds():
    game = _make_game()
    result = _screen_game(game, {}, {}, {}, "2026-03-22")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parallel_pipeline.py -v`
Expected: FAIL — `_screen_game` doesn't exist yet.

- [ ] **Step 3: Extract `_screen_game` and parallelize Step 5**

In `main.py`, make the following changes:

**Update imports** — remove `signal`, add `concurrent.futures` and `PARALLEL_GAMES`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import SCREEN_EDGE_THRESHOLD, GAME_TIMEOUT, PARALLEL_GAMES
```

**Remove** the `GameTimeout` class (lines 29-31) and `_timeout_handler` function (lines 34-35).

**Add `_screen_game` function** before the `daily` command (before `@cli.command()`):

```python
def _screen_game(game, odds_by_teams, injuries_by_team, game_date):
    """Screen a single game for edges. Thread-safe, no signal handling.

    Returns (game_key, brief, game_data, max_edge) or None.
    """
    away = game["away_team"]
    home = game["home_team"]
    game_key = f"{away}@{home}"

    odds = odds_by_teams.get(game_key)
    if not odds:
        return None

    try:
        # Build pitcher profiles
        try:
            away_pitcher = get_starter_profile(
                game["away_pitcher"], season=int(game_date[:4])
            ) if game["away_pitcher"] != "TBD" else {"name": "TBD"}
        except Exception:
            away_pitcher = {"name": game["away_pitcher"]}

        try:
            home_pitcher = get_starter_profile(
                game["home_pitcher"], season=int(game_date[:4])
            ) if game["home_pitcher"] != "TBD" else {"name": "TBD"}
        except Exception:
            home_pitcher = {"name": game["home_pitcher"]}

        away_profile = get_team_profile(away, season=int(game_date[:4]))
        home_profile = get_team_profile(home, season=int(game_date[:4]))
        env = get_game_environment(home, game_date)

        game_data = {
            "away_team": away,
            "home_team": home,
            "away_record": away_profile.get("record", ""),
            "home_record": home_profile.get("record", ""),
            "away_pitcher": away_pitcher,
            "home_pitcher": home_pitcher,
            "odds": {
                "moneyline": odds.moneyline,
                "run_line": odds.run_line,
                "total": odds.total,
                "f5_moneyline": odds.f5_moneyline,
                "f5_total": odds.f5_total,
                "implied_probs": odds.implied_probs,
                "f3_moneyline": odds.f3_moneyline,
                "f3_total": odds.f3_total,
                "f1_total": odds.f1_total,
                "team_total_home": odds.team_total_home,
                "team_total_away": odds.team_total_away,
            },
            "odds_obj": odds,
            "environment": env,
            "away_bullpen": get_bullpen_state(
                game["away_team_id"], game_date
            ) if game.get("away_team_id") else {},
            "home_bullpen": get_bullpen_state(
                game["home_team_id"], game_date
            ) if game.get("home_team_id") else {},
            "away_injuries": injuries_by_team.get(away, []),
            "home_injuries": injuries_by_team.get(home, []),
            "game_pk": game.get("game_pk"),
        }

        brief = build_briefing(game_data)
        screen = run_plan_b(brief)
        if not screen:
            return None

        edges = analyze_all_edges(screen, game_data["odds_obj"])
        max_edge = max((e["edge"] for e in edges), default=0)

        return (game_key, brief, game_data, max_edge)

    except Exception:
        logger.exception("  %s: unexpected error during screening", game_key)
        return None
```

**Replace Step 5 loop** (lines 106-230) with:

```python
    # Step 5: Parallel screening
    click.echo(f"[5/6] Screening {len(games)} games ({PARALLEL_GAMES} at a time)...")
    logger.info("Step 5: screening %d games (%d parallel, timeout=%ds)",
                len(games), PARALLEL_GAMES, GAME_TIMEOUT)
    screened_games = []
    screen_errors = 0

    with ThreadPoolExecutor(max_workers=PARALLEL_GAMES) as pool:
        futures = {
            pool.submit(_screen_game, game, odds_by_teams, injuries_by_team,
                        game_date): game
            for game in games
        }
        for future in as_completed(futures):
            game = futures[future]
            game_key = f"{game['away_team']}@{game['home_team']}"
            try:
                result = future.result(timeout=GAME_TIMEOUT)
                if result is None:
                    odds = odds_by_teams.get(game_key)
                    if not odds:
                        click.echo(f"  {game_key}: No odds, skipped")
                    else:
                        click.echo(f"  {game_key}: No edge found")
                elif result[3] >= SCREEN_EDGE_THRESHOLD:
                    click.echo(f"  {game_key}: FLAGGED — edge {result[3]:.1%}")
                    screened_games.append(result)
                else:
                    click.echo(f"  {game_key}: No edge ({result[3]:.1%})")
            except TimeoutError:
                click.echo(f"  {game_key}: TIMEOUT ({GAME_TIMEOUT}s)")
                screen_errors += 1
            except Exception as e:
                click.echo(f"  {game_key}: ERROR — {e}")
                screen_errors += 1

    click.echo(f"\n  Screened: {len(games)} | Flagged: {len(screened_games)} | Errors: {screen_errors}")
    logger.info("Step 5 complete: %d/%d games flagged, %d errors",
                len(screened_games), len(games), screen_errors)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_parallel_pipeline.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_parallel_pipeline.py
git commit -m "feat: parallelize game screening with ThreadPoolExecutor"
```

---

### Task 6: Parallel simulation in `main.py` (Step 6)

**Files:**
- Modify: `main.py`
- Test: `tests/test_parallel_pipeline.py`

- [ ] **Step 1: Write the test for `_simulate_game`**

Add to `tests/test_parallel_pipeline.py`:

```python
from main import _simulate_game


@patch("main.run_mirofish", return_value={
    "moneyline": {"away_win": 0.58, "home_win": 0.42},
    "ensemble_meta": {"cost_usd": 0.05, "phase_reached": 2, "total_calls": 12},
})
@patch("main.analyze_all_edges", return_value=[
    {"edge": 0.06, "bet_type": "moneyline", "side": "NYY",
     "odds": -110, "kelly_pct": 0.02, "sim_prob": 0.58, "market_prob": 0.52},
])
@patch("main.log_bet")
def test_simulate_game_returns_bets(mock_log, mock_edges, mock_sim):
    game_data = {
        "odds": {"moneyline": {"away": -110}},
        "odds_obj": MagicMock(event_id=None),
        "home_team": "BOS",
        "game_pk": None,
    }
    gk, bets, result = _simulate_game("NYY@BOS", "briefing", game_data, "2026-03-22")
    assert gk == "NYY@BOS"
    assert len(bets) == 1
    assert bets[0]["game"] == "NYY@BOS"
    assert mock_log.called


@patch("main.run_mirofish", return_value=None)
def test_simulate_game_handles_failed_sim(mock_sim):
    game_data = {"odds": {}, "odds_obj": MagicMock(event_id=None),
                 "home_team": "BOS", "game_pk": None}
    gk, bets, result = _simulate_game("NYY@BOS", "briefing", game_data, "2026-03-22")
    assert bets == []
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parallel_pipeline.py::test_simulate_game_returns_bets -v`
Expected: FAIL — `_simulate_game` doesn't exist yet.

- [ ] **Step 3: Add `_simulate_game` and parallelize Step 6**

Add `_simulate_game` function to `main.py` (after `_screen_game`):

```python
def _simulate_game(game_key, brief, game_data, game_date):
    """Run full ensemble simulation on one flagged game. Thread-safe.

    Returns (game_key, bets_list, result_dict).
    """
    sim_start = time.time()
    bets = []
    result = run_mirofish(brief, runs=3, odds=game_data["odds"])
    sim_elapsed = time.time() - sim_start
    if not result:
        logger.warning("  %s: simulation returned None after %.1fs", game_key, sim_elapsed)
        return (game_key, [], None)

    meta = result.get("ensemble_meta", {})
    logger.info("  %s: simulation complete in %.1fs — phase=%d, calls=%d, cost=$%.4f",
                game_key, sim_elapsed, meta.get("phase_reached", 0),
                meta.get("total_calls", 0), meta.get("cost_usd", 0))

    game_bets = analyze_all_edges(result, game_data["odds_obj"])
    for bet in game_bets:
        bet["date"] = game_date
        bet["game"] = game_key
        log_bet(bet)
        bets.append(bet)

    # Monte Carlo prop simulation if lineups confirmed
    try:
        from simulation.monte_carlo import run_monte_carlo
        from simulation.props_edge import get_prop_odds, analyze_all_props
        from scrapers.player_stats import get_lineup, get_batter_stats, get_pitcher_stats
        from config import PARK_FACTORS

        game_pk = game_data.get("game_pk")
        odds_obj = game_data.get("odds_obj")
        if game_pk and odds_obj and odds_obj.event_id:
            lineup_data = get_lineup(game_pk)
            if lineup_data and lineup_data.get("home") and lineup_data.get("away"):
                season = int(game_date[:4])
                home_lineup = [get_batter_stats(pid, season) for pid in lineup_data["home"]]
                away_lineup = [get_batter_stats(pid, season) for pid in lineup_data["away"]]
                hp_stats = get_pitcher_stats(lineup_data["home_pitcher"], season)
                ap_stats = get_pitcher_stats(lineup_data["away_pitcher"], season)

                home_abbrev = game_data["home_team"]
                park = PARK_FACTORS.get(home_abbrev, {})
                mc_results = run_monte_carlo(
                    home_lineup=home_lineup, away_lineup=away_lineup,
                    home_pitcher=hp_stats, away_pitcher=ap_stats,
                    park_factor_runs=park.get("runs", 1.0),
                    park_factor_hr=park.get("hr", 1.0),
                    n_sims=5000,
                )
                logger.info("  %s: MC simulation complete (%d sims)", game_key, 5000)

                prop_odds = get_prop_odds(odds_obj.event_id)
                prop_bets = analyze_all_props(mc_results, prop_odds)
                for bet in prop_bets:
                    bet["date"] = game_date
                    bet["game"] = game_key
                    log_bet(bet)
                    bets.append(bet)
    except Exception as e:
        logger.error("  %s: MC prop simulation failed: %s", game_key, e)

    return (game_key, bets, result)
```

**Replace Step 6 loop** (lines 232-346 of the original) with:

```python
    # Step 6: Parallel full simulation on flagged games
    click.echo(f"\n[6/6] Simulating {len(screened_games)} flagged games ({PARALLEL_GAMES} at a time)...")
    logger.info("Step 6: running full ensemble on %d flagged games (%d parallel)",
                len(screened_games), PARALLEL_GAMES)
    total_bets = 0
    total_sim_cost = 0.0

    with ThreadPoolExecutor(max_workers=PARALLEL_GAMES) as pool:
        futures = {
            pool.submit(_simulate_game, gk, brief, gd, game_date): gk
            for gk, brief, gd, _ in screened_games
        }
        for future in as_completed(futures):
            game_key = futures[future]
            try:
                gk, bets, result = future.result(timeout=GAME_TIMEOUT)
                if result:
                    meta = result.get("ensemble_meta", {})
                    total_sim_cost += meta.get("cost_usd", 0)
                if bets:
                    for bet in bets:
                        click.echo(
                            f"  {gk}: {bet['bet_type']} {bet['side']} @ {bet['odds']} | "
                            f"Edge: {bet['edge']:.1%}"
                        )
                    total_bets += len(bets)
                else:
                    click.echo(f"  {gk}: No bets after full sim")
            except TimeoutError:
                click.echo(f"  {gk}: TIMEOUT ({GAME_TIMEOUT}s)")
            except Exception as e:
                click.echo(f"  {gk}: ERROR — {e}")
                logger.exception("  %s: unexpected error during simulation", game_key)

    pipeline_elapsed = time.time() - pipeline_start
    click.echo(f"\n=== Done. {total_bets} bets logged. (${total_sim_cost:.4f} sim cost, {pipeline_elapsed:.0f}s) ===")
    logger.info("Pipeline complete: %d bets, cost=$%.4f, elapsed=%.0fs",
                total_bets, total_sim_cost, pipeline_elapsed)
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/test_parallel_pipeline.py tests/test_main.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_parallel_pipeline.py
git commit -m "feat: parallelize game simulation with ThreadPoolExecutor"
```

---

### Task 7: Clean up and integration test

**Files:**
- Modify: `main.py` (remove dead code)

- [ ] **Step 1: Verify no remaining references to signal/GameTimeout**

Run: `grep -n "signal\|GameTimeout\|_timeout_handler" main.py`
Expected: No output (all removed)

- [ ] **Step 2: Run full test suite**

Run: `pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Smoke test the CLI help**

Run: `python3 main.py daily --help`
Expected: Shows help with `--date` option, no import errors.

- [ ] **Step 4: Commit any cleanup**

```bash
git add -A
git commit -m "chore: remove signal-based timeout, cleanup dead code"
```
