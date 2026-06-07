"""Regression tests pinning the match-level parallelism contract.

Before 2026-04-23 the daily pipeline processed matches sequentially in a
single for-loop, enforcing per-match timeouts via ``signal.SIGALRM`` (which
only works in the main thread). That approach couldn't exploit parallelism
across matches and made timeouts fragile inside nested ThreadPoolExecutors.

Fix: step 3 (screening) and step 4 (full simulation) now run matches via
``ThreadPoolExecutor`` with bounded concurrency. Per-match timeouts are
enforced by ``future.result(timeout=GAME_TIMEOUT)`` which works cleanly in
worker threads. ``log_bet`` writes are serialized through a module-level
lock so concurrent matches can't race on the CSV.

These tests pin the shape so it doesn't regress.
"""
import inspect
import threading

import main


# ==========================================================================
#  Concurrency constants
# ==========================================================================

def test_screen_workers_is_bounded():
    """Screening concurrency must be > 1 (actually parallel) and reasonable."""
    assert 2 <= main.MATCH_SCREEN_WORKERS <= 8, (
        f"MATCH_SCREEN_WORKERS={main.MATCH_SCREEN_WORKERS} outside reasonable range"
    )


def test_sim_workers_is_bounded():
    """Full-sim concurrency must be > 1 but small — ensemble already runs 6
    models in parallel internally, so outer pool stays tight to avoid flooding
    OpenRouter with rate-limit-triggering bursts."""
    assert 2 <= main.MATCH_SIM_WORKERS <= 4, (
        f"MATCH_SIM_WORKERS={main.MATCH_SIM_WORKERS} outside reasonable range"
    )


# ==========================================================================
#  log_bet thread-safety
# ==========================================================================

def test_log_bet_lock_exists():
    """Module-level lock must exist to serialize CSV writes from match threads."""
    assert isinstance(main._log_bet_lock, type(threading.Lock()))


def test_safe_log_bet_uses_the_lock():
    """The wrapper around log_bet must acquire _log_bet_lock."""
    src = inspect.getsource(main._safe_log_bet)
    assert "_log_bet_lock" in src
    assert "with" in src  # context-managed acquisition


# ==========================================================================
#  Helper functions exist and have expected signatures
# ==========================================================================

def test_screen_one_match_helper_exists():
    assert callable(main._screen_one_match)
    # Core args: match, odds_list, current_tour, game_date_arg.
    # Optional 5th arg (``player_cache``) added 2026-04-24 for abbreviated →
    # full name resolution; default None keeps existing callers working.
    sig = inspect.signature(main._screen_one_match)
    required = [p for p in sig.parameters.values() if p.default is inspect.Parameter.empty]
    assert len(required) == 4


def test_simulate_one_match_helper_exists():
    assert callable(main._simulate_one_match)
    sig = inspect.signature(main._simulate_one_match)
    # Required: match_key, brief, match_data, bet_date, start_time, current_tour.
    # Optional 7th arg (``force_resim``) added 2026-04-24 to bypass the per-day
    # sim cache; default False keeps existing callers working.
    required = [p for p in sig.parameters.values() if p.default is inspect.Parameter.empty]
    assert len(required) == 6


# ==========================================================================
#  Daily uses ThreadPoolExecutor with cancel_futures shutdown
# ==========================================================================

def test_daily_uses_threadpoolexecutor():
    src = inspect.getsource(main.daily.callback)
    assert "ThreadPoolExecutor" in src


def test_daily_uses_cancel_futures_shutdown():
    """Same cancel_futures pattern as the ensemble — hung matches detach
    so the pipeline can continue to step 5 instead of hanging on shutdown."""
    src = inspect.getsource(main.daily.callback)
    assert "cancel_futures=True" in src
    assert "wait=False" in src


def test_daily_uses_future_result_timeout_not_signal_alarm():
    """signal.SIGALRM doesn't work in worker threads. Per-match timeout is
    now enforced via ``future.result(timeout=GAME_TIMEOUT)``."""
    src = inspect.getsource(main.daily.callback)
    assert "signal.alarm" not in src
    assert "future.result(timeout" in src


def test_daily_does_not_import_signal():
    """signal module should no longer be imported at module level — using it
    would be a sign of pre-parallelism leftover code."""
    src = inspect.getsource(main)
    # Allow "signal" inside comments / docstrings, but no import
    assert "\nimport signal" not in src
    assert "\nfrom signal " not in src
