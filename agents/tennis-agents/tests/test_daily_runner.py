"""Tests for daily_runner orchestration decisions."""
from unittest.mock import patch, MagicMock

from agents.daily_runner import run_results


def test_run_results_invokes_main_results_not_grader_module():
    """daily_runner.run_results must go through `main.py results` so Discord
    grade + season notifications fire. Calling `-m agents.results_grader`
    directly silences the Discord hook (bug fixed 2026-04-20)."""
    with patch("agents.daily_runner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", stderr="")
        run_results("2026-04-19", "atp")

    args, kwargs = mock_run.call_args
    cmd = args[0]
    # Must invoke `main.py results` — NOT the module form.
    assert "main.py" in cmd
    assert "results" in cmd
    assert "-m" not in cmd, f"daily_runner should not bypass main.py: {cmd}"
    assert "--date" in cmd
    assert "2026-04-19" in cmd
