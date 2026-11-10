from __future__ import annotations

from origenerator.gui.populate_controller import PopulateController


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
    populate = PopulateController(launcher)

    populate.start("k")

    assert launcher.calls == ["k"]
    assert populate.is_active("k")


def test_finishing_a_variation_launches_the_next_while_active(qtbot):
    launcher = FakeLauncher()
    populate = PopulateController(launcher)
    populate.start("k")

    populate.note_finished("k")

    assert launcher.calls == ["k", "k"]
    assert populate.is_active("k")


def test_stopping_prevents_further_relaunches(qtbot):
    launcher = FakeLauncher()
    populate = PopulateController(launcher)
    populate.start("k")

    populate.stop("k")
    populate.note_finished("k")

    assert launcher.calls == ["k"]
    assert not populate.is_active("k")


def test_cancelling_a_variation_keeps_populate_on_and_tries_another_seed(qtbot):
    launcher = FakeLauncher()
    populate = PopulateController(launcher)
    stopped = []
    populate.stopped.connect(stopped.append)
    populate.start("k")

    populate.note_canceled("k")

    assert launcher.calls == ["k", "k"], (
        "Cancel means not this one, not stop: having to turn Populate on again after every discard "
        "made the button fight the user")
    assert populate.is_active("k")
    assert stopped == []


def test_a_cancel_after_the_user_stopped_does_not_relaunch(qtbot):
    launcher = FakeLauncher()
    populate = PopulateController(launcher)
    populate.start("k")

    populate.stop("k")
    populate.note_canceled("k")

    assert launcher.calls == ["k"]
    assert not populate.is_active("k")


def test_a_cancel_whose_relaunch_cannot_run_ends_populate(qtbot):
    launcher = FakeLauncher(results=[True, False])
    populate = PopulateController(launcher)
    stopped = []
    populate.stopped.connect(stopped.append)
    populate.start("k")

    populate.note_canceled("k")

    assert not populate.is_active("k")
    assert stopped == ["k"]


def test_a_failed_variation_ends_populate_and_signals_stopped(qtbot):
    launcher = FakeLauncher()
    populate = PopulateController(launcher)
    stopped = []
    populate.stopped.connect(stopped.append)
    populate.start("k")

    populate.note_failed("k")

    assert not populate.is_active("k")
    assert stopped == ["k"]
    populate.note_finished("k")
    assert launcher.calls == ["k"]


def test_manual_stop_also_signals_stopped(qtbot):
    launcher = FakeLauncher()
    populate = PopulateController(launcher)
    stopped = []
    populate.stopped.connect(stopped.append)
    populate.start("k")

    populate.stop("k")

    assert stopped == ["k"]


def test_start_does_not_activate_when_the_launch_cannot_run(qtbot):
    launcher = FakeLauncher(started=False)
    populate = PopulateController(launcher)
    stopped = []
    populate.stopped.connect(stopped.append)

    populate.start("k")

    assert launcher.calls == ["k"]
    assert not populate.is_active("k")
    assert stopped == []


def test_a_relaunch_that_cannot_run_ends_populate(qtbot):
    launcher = FakeLauncher(results=[True, False])
    populate = PopulateController(launcher)
    stopped = []
    populate.stopped.connect(stopped.append)
    populate.start("k")

    populate.note_finished("k")

    assert launcher.calls == ["k", "k"]
    assert not populate.is_active("k")
    assert stopped == ["k"]


def test_starting_populate_again_in_its_folder_does_not_double_launch(qtbot):
    launcher = FakeLauncher()
    populate = PopulateController(launcher)

    populate.start("k")
    populate.start("k")

    assert launcher.calls == ["k"]


def test_stop_all_ends_populate_wherever_it_runs(qtbot):
    launcher = FakeLauncher()
    populate = PopulateController(launcher)
    stopped = []
    populate.stopped.connect(stopped.append)
    populate.start("a")

    populate.stop_all()

    assert not populate.is_active("a")
    assert stopped == ["a"]
    assert populate.active_key() is None


def test_populating_in_a_new_folder_ends_it_in_the_old_one(qtbot):
    launcher = FakeLauncher()
    populate = PopulateController(launcher)
    stopped = []
    populate.stopped.connect(stopped.append)
    populate.start("a")

    populate.start("b")

    assert populate.is_active("b")
    assert not populate.is_active("a")
    assert stopped == ["a"], (
        "reported as a hand-stop is, so the folder left behind has its switch cleared in the one "
        "handler every ending goes through")


def test_populate_names_the_folder_it_runs_in_and_none_once_stopped(qtbot):
    populate = PopulateController(FakeLauncher())
    populate.start("a")

    assert populate.active_key() == "a", (
        "a Populate the user has walked away from is the one they need to be told about")
    populate.stop("a")
    assert populate.active_key() is None


def test_the_displaced_folder_launches_nothing_more(qtbot):
    launcher = FakeLauncher()
    populate = PopulateController(launcher)
    populate.start("a")
    populate.start("b")

    populate.note_finished("a")

    assert launcher.calls == ["a", "b"]


def test_a_new_folder_that_cannot_start_leaves_populate_where_it_was(qtbot):
    launcher = FakeLauncher(results=[True, False])
    populate = PopulateController(launcher)
    stopped = []
    populate.stopped.connect(stopped.append)
    populate.start("a")

    populate.start("b")

    assert populate.is_active("a")
    assert not populate.is_active("b")
    assert stopped == []
