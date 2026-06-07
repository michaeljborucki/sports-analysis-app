"""Regression test pinning immediate per-match Discord dispatch.

Before this change, ``main.py daily`` only called ``send_notifications`` once
at the very end of the pipeline — after all ~15 full-sims finished (~30-90
min). That meant a bet on an 11 AM MT match wouldn't get Discord-alerted
until ~12:30 PM even though the bet was logged at 11:05. On a real slate,
matches could start before the alert fired.

Fix: dispatch immediately inside the full-sim ``as_completed`` loop, right
after ``_safe_log_bet`` writes the bet. The dispatcher's ``already_sent``
state ensures no double-posts, so the end-of-pipeline notify still runs
safely as a belt-and-suspenders safety net for any bets that slipped
through (e.g. transient Discord 5xx during the per-match call).
"""
import inspect

from main import daily


def test_daily_dispatches_notify_inside_full_sim_loop():
    """The ``daily`` command body must call send_notifications inside the
    match as_completed loop (not just at the end), so bets alert within
    seconds of landing rather than waiting for the whole slate."""
    src = inspect.getsource(daily.callback)
    # There must be a send_notifications call BEFORE the "Step 5" summary,
    # i.e. inside the full-sim loop (or the screening loop). Previously the
    # only call was at the end, after the summary.
    step5_pos = src.find("Step 5: Summary")
    assert step5_pos > 0, "Step 5 summary marker not found"
    pre_step5 = src[:step5_pos]
    assert "send_notifications" in pre_step5, (
        "send_notifications must be invoked BEFORE Step 5 summary — i.e. "
        "inside the per-match loop so Discord alerts fire as bets land "
        "rather than at end-of-pipeline."
    )


def test_daily_preserves_no_notify_flag_in_inline_dispatch():
    """The inline per-match dispatch must still respect --no-notify."""
    src = inspect.getsource(daily.callback)
    # Find the inline dispatch (before Step 5) and verify it's gated on no_notify.
    step5_pos = src.find("Step 5: Summary")
    pre_step5 = src[:step5_pos]
    # The dispatch block should be inside `if not no_notify:`
    assert "if not no_notify" in pre_step5, (
        "Per-match dispatch must be guarded by --no-notify flag"
    )


def test_daily_still_has_end_of_pipeline_dispatch_as_safety_net():
    """Keep the end-of-pipeline dispatch too — it's a belt-and-suspenders
    safety net that catches bets the inline dispatch missed (e.g. transient
    Discord 5xx on the per-match call). The dispatcher's dedup prevents
    double-posting."""
    src = inspect.getsource(daily.callback)
    step5_pos = src.find("Step 5: Summary")
    post_step5 = src[step5_pos:]
    assert "send_notifications" in post_step5, (
        "End-of-pipeline notify dispatch removed — it's needed as a safety "
        "net if per-match dispatch fails transiently (dedup prevents "
        "double-posts)."
    )
