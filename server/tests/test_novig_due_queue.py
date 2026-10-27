from datetime import datetime, timedelta, timezone

from server.odds.books.novig import fetcher as fmod


NOW = datetime.now(timezone.utc)


def _t(starts_h, due_s, in_flight=False):
    return fmod._Target(
        market={}, sport="nba", cache_event={}, plan=[],
        starts=NOW + timedelta(hours=starts_h),
        next_due=NOW + timedelta(seconds=due_s), in_flight=in_flight,
    )


class _Stream:
    def __init__(self, live):
        self.live = live

    def covers(self, mid):
        return mid in self.live


def _fetcher(targets, stream=None):
    f = fmod.NovigFetcher.__new__(fmod.NovigFetcher)
    f._targets = targets
    f._stream = stream
    f._due_queue_built = 0.0
    f._next_due_min = None
    return f


def test_queue_is_soonest_game_first_and_skips_busy_streamed_not_due():
    f = _fetcher({
        "late": _t(10, -5), "soon": _t(1, -5), "mid": _t(5, -5),
        "busy": _t(0.5, -5, in_flight=True), "streamed": _t(0.2, -5),
        "later_due": _t(0.1, 30),
    }, stream=_Stream({"streamed"}))
    picks = []
    while (p := f._next_due_target(NOW)) is not None:
        picks.append(p[0])
        p[1].in_flight = True
    assert picks == ["soon", "mid", "late"]
    assert f._next_due_min == NOW + timedelta(seconds=30)


def test_queue_rechecks_targets_changed_since_build():
    f = _fetcher({"a": _t(1, -5), "b": _t(2, -5)})
    f._rebuild_due_queue(NOW)
    f._targets["a"].in_flight = True        # claimed by a sibling worker
    del f._targets["b"]                     # dropped by a catalog refresh
    assert f._next_due_target(NOW) is None
