import pytest

from origenerator.job_queue import JobQueue, pending_etas


class FakePanel:
    def __init__(self):
        self.run_now_calls = 0
        self.queue_status = None

    def run_now(self):
        self.run_now_calls += 1

    def set_queue_status(self, position, eta_seconds):
        self.queue_status = (position, eta_seconds)


class FakeDB:
    def __init__(self, durations=None):
        self._durations = durations or {}

    def recent_durations(self, workflow_name, limit=10):
        return self._durations.get(workflow_name, [])


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return FakeClock()


def _queue(qtbot, durations=None, clock=None):
    q = JobQueue(FakeDB(durations or {}), clock=clock or FakeClock())
    return q


def test_pending_etas_first_waits_for_running_only():
    # Two waiting jobs behind a running one with 100s left: the first starts in
    # 100s, the second after the first's 50s estimate too.
    assert pending_etas(100.0, [50.0, 30.0]) == [100.0, 150.0]


def test_pending_etas_empty_when_nothing_waiting():
    assert pending_etas(100.0, []) == []


def test_pending_etas_clamps_negative_contributions():
    assert pending_etas(-5.0, [10.0]) == [0.0]
    assert pending_etas(0.0, [-3.0, 10.0]) == [0.0, 0.0]


def test_first_submit_runs_immediately(qtbot):
    q = _queue(qtbot)
    a = FakePanel()
    q.submit(a, "sdxl_t2i")
    assert a.run_now_calls == 1
    assert a.queue_status is None  # running, not queued


def test_second_submit_is_queued_with_position_and_eta(qtbot):
    q = _queue(qtbot, durations={"sdxl_t2i": [100.0, 100.0, 100.0]})
    a, b = FakePanel(), FakePanel()
    q.submit(a, "sdxl_t2i")
    q.submit(b, "sdxl_t2i")
    assert b.run_now_calls == 0
    assert b.queue_status == (1, 100.0)  # waits out A's ~100s


def test_third_job_eta_sums_estimates_ahead(qtbot):
    q = _queue(qtbot, durations={"sdxl_t2i": [100.0]})
    a, b, c = FakePanel(), FakePanel(), FakePanel()
    q.submit(a, "sdxl_t2i")
    q.submit(b, "sdxl_t2i")
    q.submit(c, "sdxl_t2i")
    assert b.queue_status == (1, 100.0)
    assert c.queue_status == (2, 200.0)  # A's 100 + B's 100


def test_release_starts_next_in_line(qtbot):
    q = _queue(qtbot, durations={"sdxl_t2i": [100.0]})
    a, b = FakePanel(), FakePanel()
    q.submit(a, "sdxl_t2i")
    q.submit(b, "sdxl_t2i")
    q.release(a)
    assert b.run_now_calls == 1


def test_countdown_decreases_as_running_elapses(qtbot, clock):
    q = _queue(qtbot, durations={"sdxl_t2i": [100.0]}, clock=clock)
    a, b = FakePanel(), FakePanel()
    q.submit(a, "sdxl_t2i")
    q.submit(b, "sdxl_t2i")
    assert b.queue_status == (1, 100.0)
    clock.t = 30.0
    q._refresh()  # a timer tick
    assert b.queue_status == (1, 70.0)


def test_cancel_pending_renumbers_the_rest(qtbot):
    q = _queue(qtbot, durations={"sdxl_t2i": [100.0]})
    a, b, c = FakePanel(), FakePanel(), FakePanel()
    q.submit(a, "sdxl_t2i")
    q.submit(b, "sdxl_t2i")
    q.submit(c, "sdxl_t2i")
    q.cancel(b)
    assert b.run_now_calls == 0
    assert c.queue_status == (1, 100.0)  # promoted to first in line


def test_cancel_running_advances_queue(qtbot):
    q = _queue(qtbot, durations={"sdxl_t2i": [100.0]})
    a, b = FakePanel(), FakePanel()
    q.submit(a, "sdxl_t2i")
    q.submit(b, "sdxl_t2i")
    q.cancel(a)
    assert b.run_now_calls == 1
