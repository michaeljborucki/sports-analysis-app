"""Bet-mix roll-up on the accounts page.

Shapes here are taken from a live coral33 pending feed (2026-09-04): the
counts below are the real ticket shapes observed across 8 accounts.
"""
from server.odds.books.coral33.accounts import (
    _classify_leg_status,
    _classify_pending_wagers,
)


def _row(ticket, wager, outcome, *, free="N", picks=1, play=1, game="2026-09-04 19:40:00.000"):
    return {
        "TicketNumber": ticket,
        "WagerNumber": wager,
        "PlayNumber": play,
        "WagerType": "P",
        "TotalPicks": picks,
        "Outcome": outcome,
        "WagerStatus": "O",
        "FreePlayFlag": free,
        "AmountWagered": 500,
        "ToWinAmount": 1500,
        "Description": "Baseball #905 Giants O 10 +270 - For Game",
        "GameDateTime": game,
    }


def test_pending_legs_are_not_pushes():
    # 'P' on a leg whose game is days away cannot be a push.
    assert _classify_leg_status("P") == "pending"
    assert _classify_leg_status("W") == "won"
    assert _classify_leg_status("L") == "lost"
    assert _classify_leg_status("") == "open"


def test_free_plays_are_not_also_counted_as_parlays():
    # 5 free plays must read as 5 free plays and 0 parlays.
    rows = [_row(1000 + i, 1, "P", free="Y") for i in range(5)]
    summary, _ = _classify_pending_wagers(rows)
    assert summary.open_count == 5
    assert summary.free_play_count == 5
    assert summary.parlay_count == 0
    assert summary.straight_count == 0


def test_type_and_progress_buckets_each_partition_open_count():
    rows = [
        # free play, leg pending, second leg not taken
        _row(1, 1, "P", free="Y"),
        # free play, leg won, second leg not taken
        _row(2, 1, "W", free="Y"),
        # free play, leg won + second leg taken -> fulfilled
        _row(3, 1, "W", free="Y", picks=2, play=1),
        _row(3, 1, "P", free="Y", picks=2, play=2),
        # non-free parlay, leg pending
        _row(4, 1, "P"),
    ]
    summary, wagers = _classify_pending_wagers(rows)

    assert summary.open_count == 4
    # Type partition
    assert summary.free_play_count == 3
    assert summary.parlay_count == 1
    assert summary.straight_count == 0
    assert (
        summary.straight_count + summary.parlay_count + summary.free_play_count
        == summary.open_count
    )
    # Progress partition
    assert summary.won_open_slot_count == 1      # ticket 2
    assert summary.pending_open_slot_count == 2  # tickets 1 and 4
    assert summary.fulfilled_count == 1          # ticket 3
    assert (
        summary.won_open_slot_count
        + summary.pending_open_slot_count
        + summary.fulfilled_count
        == summary.open_count
    )
    assert len(wagers) == 4


def test_won_plus_pending_parlay_is_partial_now_that_p_is_pending():
    rows = [
        _row(9, 1, "W", picks=2, play=1),
        _row(9, 1, "P", picks=2, play=2),
    ]
    _, wagers = _classify_pending_wagers(rows)
    w = wagers[0]
    assert w.has_open_legs is True
    assert w.has_graded_legs is True
    assert w.is_partial is True
