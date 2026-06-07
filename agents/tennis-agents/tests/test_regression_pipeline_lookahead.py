"""Regression test pinning the pipeline lookahead window.

Added 2026-04-26. Before this change, ``main.py daily`` (without --date)
fetched matches for the next 24 hours, which meant we'd burn ensemble
cost (~$0.30/match) on matches 18+ hours away whose odds and lineups
would shift before they tipped off. Cached predictions on those matches
also went stale before being useful.

Fix: tighten the windowed path to ``PIPELINE_LOOKAHEAD_HOURS`` (default 8).
Specific-date runs (``--date YYYY-MM-DD``) still take the full day's slate,
since the user explicitly asked for that day.
"""
import inspect

from main import daily


def test_daily_uses_pipeline_lookahead_hours_constant():
    """The windowed branch of ``daily`` must reference the config constant
    so future tuning happens in one place."""
    src = inspect.getsource(daily.callback)
    assert "PIPELINE_LOOKAHEAD_HOURS" in src, (
        "daily must use config.PIPELINE_LOOKAHEAD_HOURS for the windowed "
        "lookahead, not a hardcoded number"
    )
    # Specifically: get_upcoming_matches is called with hours= the constant
    assert "hours=PIPELINE_LOOKAHEAD_HOURS" in src


def test_pipeline_lookahead_default_is_eight_hours():
    """Default value pinned at 8h — short enough to keep ensemble cost off
    far-out matches, long enough to cover same-day finals + next-morning ATP."""
    from config import PIPELINE_LOOKAHEAD_HOURS
    assert PIPELINE_LOOKAHEAD_HOURS == 8


def test_daily_does_not_hardcode_24h_lookahead():
    """The previous 24h hardcode must be gone — guard against accidental
    revert."""
    src = inspect.getsource(daily.callback)
    # No "hours=24" call
    assert "hours=24" not in src, (
        "Pipeline still hardcodes hours=24 somewhere. Use "
        "PIPELINE_LOOKAHEAD_HOURS instead so the lookahead is config-driven."
    )


def test_scope_label_reflects_lookahead_constant():
    """The user-facing 'next Xh' label must come from the constant, not a
    hardcoded string — so changing the constant updates the log header too."""
    src = inspect.getsource(daily.callback)
    # The label is built from PIPELINE_LOOKAHEAD_HOURS
    assert 'f"next {PIPELINE_LOOKAHEAD_HOURS}h"' in src or \
           "f'next {PIPELINE_LOOKAHEAD_HOURS}h'" in src
