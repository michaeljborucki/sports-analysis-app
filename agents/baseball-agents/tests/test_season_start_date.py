"""Season record cutoff: only count bets from SEASON_RECORD_START_DATE onward.

Operator decision (2026-05-17): the model went through a series of fine-
tuning changes that landed in early May (TTOP, platoon, weather, regression).
The pre-2026-05-10 record reflects a model that no longer exists. To give an
honest read of current performance the season totals message should bound
the lower end of its window.

Constant lives in config.SEASON_RECORD_START_DATE. The season notifier
filters `bets.csv` to that date or later before computing the summary.
"""
import importlib
import pandas as pd
import pytest


def test_season_record_start_date_in_config():
    import config
    importlib.reload(config)
    assert hasattr(config, "SEASON_RECORD_START_DATE"), \
        "config.SEASON_RECORD_START_DATE must exist"
    assert config.SEASON_RECORD_START_DATE == "2026-05-10", \
        f"Expected 2026-05-10, got {config.SEASON_RECORD_START_DATE}"


def _make_df(rows):
    return pd.DataFrame(rows, columns=[
        "date", "game", "bet_type", "side", "odds", "result", "profit",
    ])


def test_season_notifier_excludes_old_bets(tmp_path, monkeypatch):
    """A win logged on 2026-04-30 should NOT appear in the summary, but a
    win on 2026-05-10 should. The filter is the cutoff date."""
    from notify import season as season_mod
    import config as cfg_mod

    rows = [
        # Before cutoff — should NOT count
        {"date": "2026-04-30", "game": "AAA@BBB", "bet_type": "moneyline",
         "side": "home", "odds": -110, "result": "W", "profit": 0.91},
        # On cutoff — should count
        {"date": "2026-05-10", "game": "CCC@DDD", "bet_type": "moneyline",
         "side": "home", "odds": -110, "result": "L", "profit": -1.0},
        # After cutoff — should count
        {"date": "2026-05-15", "game": "EEE@FFF", "bet_type": "moneyline",
         "side": "home", "odds": -110, "result": "W", "profit": 0.91},
    ]
    fake_df = _make_df(rows)

    monkeypatch.setattr("notify.season.load_bets", lambda: fake_df)
    monkeypatch.setattr("notify.season.send_discord", lambda url, msgs: 0)
    monkeypatch.setattr("notify.season.discord_season_enabled", lambda cfg: False)

    # Run dry_run to capture the filtered count without sending.
    result = season_mod.send_season_notification(through_date="2026-05-16",
                                                  dry_run=True)
    # We expect only 2 bets (the May 10 and May 15 entries) to be filtered in.
    assert result["bets_filtered"] == 2, \
        f"Expected 2 graded bets in window, got {result['bets_filtered']}"


def test_season_notifier_lower_bound_exact_match(monkeypatch):
    """A bet on the exact cutoff date should be INCLUDED (>= comparison)."""
    from notify import season as season_mod

    rows = [
        {"date": "2026-05-09", "game": "X@Y", "bet_type": "moneyline",
         "side": "home", "odds": -110, "result": "W", "profit": 0.91},
        {"date": "2026-05-10", "game": "X@Y", "bet_type": "moneyline",
         "side": "home", "odds": -110, "result": "W", "profit": 0.91},
    ]
    fake_df = _make_df(rows)
    monkeypatch.setattr("notify.season.load_bets", lambda: fake_df)
    monkeypatch.setattr("notify.season.send_discord", lambda url, msgs: 0)
    monkeypatch.setattr("notify.season.discord_season_enabled", lambda cfg: False)

    result = season_mod.send_season_notification(through_date="2026-05-15",
                                                  dry_run=True)
    assert result["bets_filtered"] == 1, \
        "Bet on exact cutoff date should be included; bet before should be excluded"
