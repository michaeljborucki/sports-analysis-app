"""Regression tests pinning the ensemble's timeout-escape behavior.

Background: before 2026-04-23, the orchestrator used ``with ThreadPoolExecutor(...)``
which calls ``shutdown(wait=True)`` on exit. When a ``signal.SIGALRM`` fired
in the main thread mid-Phase-2 (e.g. match-timeout at 180s with 24 in-flight
LLM calls), the exception couldn't escape because ``shutdown`` blocked until
every future finished. A single slow match could hold up the pipeline for
40-60 minutes.

Fix: manual executor management with ``shutdown(wait=False, cancel_futures=True)``
in a ``finally`` block. Exceptions propagate immediately; pending futures
are cancelled; running futures complete in the background but don't block
the call tree.

These tests pin the shape so the fix doesn't silently regress.
"""
import inspect

import pytest

from ensemble import orchestrator


def test_phase1_does_not_use_with_threadpoolexecutor():
    """``with ThreadPoolExecutor(...)`` blocks shutdown — never use it inside run_phase1."""
    src = inspect.getsource(orchestrator.run_phase1)
    # Match the actual code pattern (``with ThreadPoolExecutor(...) as executor:``)
    # not references in comments that discuss the bug.
    import re
    assert not re.search(r"\bwith\s+ThreadPoolExecutor\s*\(", src), (
        "run_phase1 must use manual ThreadPoolExecutor + shutdown(cancel_futures=True) "
        "in a finally block so SIGALRM-based per-match timeouts can escape the thread pool."
    )


def test_phase2_does_not_use_with_threadpoolexecutor():
    src = inspect.getsource(orchestrator.run_phase2)
    # Match the actual code pattern (``with ThreadPoolExecutor(...) as executor:``)
    # not references in comments that discuss the bug.
    import re
    assert not re.search(r"\bwith\s+ThreadPoolExecutor\s*\(", src), (
        "run_phase2 must use manual ThreadPoolExecutor + shutdown(cancel_futures=True) "
        "in a finally block so SIGALRM-based per-match timeouts can escape the thread pool."
    )


def test_phase1_calls_shutdown_with_cancel_futures():
    """Phase 1 must call shutdown with cancel_futures=True to abort pending work quickly."""
    src = inspect.getsource(orchestrator.run_phase1)
    assert "cancel_futures=True" in src, (
        "run_phase1 must pass cancel_futures=True to executor.shutdown() so pending "
        "futures are cancelled rather than waited on."
    )
    assert "wait=False" in src, (
        "run_phase1 must pass wait=False to executor.shutdown() so running futures "
        "don't block the exception-propagation path."
    )


def test_phase2_calls_shutdown_with_cancel_futures():
    src = inspect.getsource(orchestrator.run_phase2)
    assert "cancel_futures=True" in src
    assert "wait=False" in src


def test_phase1_wraps_executor_in_try_finally():
    """The shutdown must be in a ``finally`` so it always runs, even on SIGALRM."""
    src = inspect.getsource(orchestrator.run_phase1)
    # Basic structural check: 'finally:' appears somewhere in the phase 1 body
    assert "finally:" in src


def test_phase2_wraps_executor_in_try_finally():
    src = inspect.getsource(orchestrator.run_phase2)
    assert "finally:" in src


def test_game_timeout_is_long_enough_for_phase_1():
    """``GAME_TIMEOUT`` must exceed Phase 1 duration (observed ~100-150s) with headroom
    for Phase 2 expansion (~2-3 min). 300s (5 min) gives comfortable margin."""
    from config import GAME_TIMEOUT
    assert GAME_TIMEOUT >= 240, (
        f"GAME_TIMEOUT={GAME_TIMEOUT} is too tight for Phase 1 (~150s) + potential "
        f"Phase 2 expansion. Bump to at least 240s."
    )


def test_pipeline_timeout_exceeds_max_slate_budget():
    """Pipeline-level timeout must exceed (slate size) × GAME_TIMEOUT with headroom.

    A typical slate is 10 flagged matches; at GAME_TIMEOUT=300 that's 3000s of
    full-sim, plus ~25 min screening = ~75 min. 2-hour pipeline budget gives
    comfortable retry headroom.
    """
    from config import GAME_TIMEOUT
    from agents.daily_runner import PIPELINE_TIMEOUT_SECONDS
    # At least: 10 flagged × GAME_TIMEOUT + 30 min screening overhead
    min_required = 10 * GAME_TIMEOUT + 1800
    assert PIPELINE_TIMEOUT_SECONDS >= min_required, (
        f"PIPELINE_TIMEOUT_SECONDS={PIPELINE_TIMEOUT_SECONDS} is too tight for "
        f"10 flagged matches × GAME_TIMEOUT={GAME_TIMEOUT} plus screening overhead. "
        f"Need at least {min_required}s."
    )
