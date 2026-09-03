"""AutoGenerateController — the gallery re-roll on a loop until stopped."""

from origenerator.gui.auto_generate_controller import AutoGenerateController


class FakeLauncher:
    """Stands in for GalleryView._start_reroll: records each launched key and
    reports whether a job actually started (a launch can no-op with no client)."""

    def __init__(self, started=True, results=None):
        self.calls = []
        self._started = started
        self._results = list(results) if results is not None else None

    def __call__(self, key):
        self.calls.append(key)
        if self._results:
            return self._results.pop(0)
        return self._started


def test_start_launches_once_and_marks_the_folder_active(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)

    auto.start("k")

    assert launcher.calls == ["k"]
    assert auto.is_active("k")


def test_finishing_a_variation_launches_the_next_while_active(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    auto.start("k")

    auto.note_finished("k")

    assert launcher.calls == ["k", "k"]  # relaunched
    assert auto.is_active("k")


def test_stopping_prevents_further_relaunches(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    auto.start("k")

    auto.stop("k")
    auto.note_finished("k")  # the in-flight job finishes after the user stopped

    assert launcher.calls == ["k"]  # not relaunched
    assert not auto.is_active("k")


def test_cancelling_a_variation_keeps_the_loop_and_tries_another_seed(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("k")

    auto.note_canceled("k")  # the user threw away the seed being made

    assert launcher.calls == ["k", "k"]  # another seed, at once
    assert auto.is_active("k")           # and the loop is still on
    assert stopped == []


def test_a_cancel_after_the_user_stopped_does_not_relaunch(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    auto.start("k")

    auto.stop("k")
    auto.note_canceled("k")  # the stopped loop's in-flight job is cancelled after

    assert launcher.calls == ["k"]
    assert not auto.is_active("k")


def test_a_cancel_whose_relaunch_cannot_run_ends_the_loop(qtbot):
    launcher = FakeLauncher(results=[True, False])  # starts, then next won't run
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("k")

    auto.note_canceled("k")  # nothing running and nothing launchable: a dead loop

    assert not auto.is_active("k")
    assert stopped == ["k"]


def test_a_failed_variation_ends_the_loop_and_signals_stopped(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("k")

    auto.note_failed("k")

    assert not auto.is_active("k")
    assert stopped == ["k"]
    auto.note_finished("k")  # a late finish for the failed key must not relaunch
    assert launcher.calls == ["k"]


def test_manual_stop_also_signals_stopped(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("k")

    auto.stop("k")

    assert stopped == ["k"]


def test_start_does_not_activate_when_the_launch_cannot_run(qtbot):
    launcher = FakeLauncher(started=False)  # e.g. no ComfyUI client
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)

    auto.start("k")

    assert launcher.calls == ["k"]   # attempted
    assert not auto.is_active("k")   # but no dead loop with nothing running
    assert stopped == []             # never started, so nothing to signal


def test_a_relaunch_that_cannot_run_ends_the_loop(qtbot):
    launcher = FakeLauncher(results=[True, False])  # starts, then next won't run
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("k")

    auto.note_finished("k")  # the relaunch attempt fails to start

    assert launcher.calls == ["k", "k"]
    assert not auto.is_active("k")
    assert stopped == ["k"]


def test_starting_an_already_looping_folder_does_not_double_launch(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)

    auto.start("k")
    auto.start("k")

    assert launcher.calls == ["k"]  # the second start is a no-op


def test_stop_all_ends_the_loop_that_is_running(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("a")

    auto.stop_all()

    assert not auto.is_active("a")
    assert stopped == ["a"]
    assert auto.active_key() is None


def test_rekey_moves_an_active_loop_to_a_new_key(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    auto.start("old")

    auto.rekey("old", "new")

    assert not auto.is_active("old") and auto.is_active("new")


def test_looping_a_new_folder_ends_the_one_that_was_looping(qtbot):
    # One folder at a time: two loops would only take turns on the machine, each
    # waiting out the other's render, and the voice steering that follows the loop
    # would have two prompts to answer to.
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("a")

    auto.start("b")

    assert auto.is_active("b") and not auto.is_active("a")
    assert stopped == ["a"]  # reported, so its switch and voice steering clean up


def test_the_displaced_folder_launches_nothing_more(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    auto.start("a")
    auto.start("b")

    auto.note_finished("a")  # a's in-flight variation still lands

    assert launcher.calls == ["a", "b"]  # but nothing further goes into it


def test_a_new_folder_that_cannot_start_leaves_the_loop_where_it_was(qtbot):
    # Otherwise a refused launch would stop one loop and start none, leaving the
    # machine idle and both switches off.
    launcher = FakeLauncher(results=[True, False])
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("a")

    auto.start("b")

    assert auto.is_active("a") and not auto.is_active("b")
    assert stopped == []
