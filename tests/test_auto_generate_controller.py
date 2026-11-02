from __future__ import annotations

from origenerator.gui.auto_generate_controller import AutoGenerateController


class FakeLauncher:
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

    assert launcher.calls == ["k", "k"]
    assert auto.is_active("k")


def test_stopping_prevents_further_relaunches(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    auto.start("k")

    auto.stop("k")
    auto.note_finished("k")

    assert launcher.calls == ["k"]
    assert not auto.is_active("k")


def test_cancelling_a_variation_keeps_auto_generate_on_and_tries_another_seed(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("k")

    auto.note_canceled("k")

    assert launcher.calls == ["k", "k"]
    assert auto.is_active("k")
    assert stopped == []


def test_a_cancel_after_the_user_stopped_does_not_relaunch(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    auto.start("k")

    auto.stop("k")
    auto.note_canceled("k")

    assert launcher.calls == ["k"]
    assert not auto.is_active("k")


def test_a_cancel_whose_relaunch_cannot_run_ends_auto_generate(qtbot):
    launcher = FakeLauncher(results=[True, False])
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("k")

    auto.note_canceled("k")

    assert not auto.is_active("k")
    assert stopped == ["k"]


def test_a_failed_variation_ends_auto_generate_and_signals_stopped(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("k")

    auto.note_failed("k")

    assert not auto.is_active("k")
    assert stopped == ["k"]
    auto.note_finished("k")
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
    launcher = FakeLauncher(started=False)
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)

    auto.start("k")

    assert launcher.calls == ["k"]
    assert not auto.is_active("k")
    assert stopped == []


def test_a_relaunch_that_cannot_run_ends_auto_generate(qtbot):
    launcher = FakeLauncher(results=[True, False])
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("k")

    auto.note_finished("k")

    assert launcher.calls == ["k", "k"]
    assert not auto.is_active("k")
    assert stopped == ["k"]


def test_starting_auto_generate_again_in_its_folder_does_not_double_launch(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)

    auto.start("k")
    auto.start("k")

    assert launcher.calls == ["k"]


def test_stop_all_ends_auto_generate_wherever_it_runs(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("a")

    auto.stop_all()

    assert not auto.is_active("a")
    assert stopped == ["a"]
    assert auto.active_key() is None


def test_auto_generating_in_a_new_folder_ends_it_in_the_old_one(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("a")

    auto.start("b")

    assert auto.is_active("b")
    assert not auto.is_active("a")
    assert stopped == ["a"]


def test_the_displaced_folder_launches_nothing_more(qtbot):
    launcher = FakeLauncher()
    auto = AutoGenerateController(launcher)
    auto.start("a")
    auto.start("b")

    auto.note_finished("a")

    assert launcher.calls == ["a", "b"]


def test_a_new_folder_that_cannot_start_leaves_auto_generate_where_it_was(qtbot):
    launcher = FakeLauncher(results=[True, False])
    auto = AutoGenerateController(launcher)
    stopped = []
    auto.stopped.connect(stopped.append)
    auto.start("a")

    auto.start("b")

    assert auto.is_active("a")
    assert not auto.is_active("b")
    assert stopped == []
