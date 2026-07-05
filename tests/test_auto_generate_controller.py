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


def test_stop_all_ends_every_active_loop(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("a")
    auto.start("b")

    auto.stop_all()

    assert not auto.is_active("a") and not auto.is_active("b")
    assert sorted(stopped) == ["a", "b"]
    assert not auto.any_active()


def test_rekey_moves_an_active_loop_to_a_new_key(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    auto.start("old")

    auto.rekey("old", "new")

    assert not auto.is_active("old") and auto.is_active("new")


def test_folders_loop_independently(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    auto.start("a")
    auto.start("b")

    auto.note_finished("a")

    assert launcher.calls == ["a", "b", "a"]  # only a relaunched
    assert auto.is_active("a") and auto.is_active("b")
