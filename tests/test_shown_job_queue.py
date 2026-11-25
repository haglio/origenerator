from PySide6.QtWidgets import QWidget

from origenerator.comfyui_api import ForeignQueue
from origenerator.gui.inflight import InFlightItem, RunReading
from tests.shown_job_queue_support import shown_job_queue


def _waiting(key: str, *, progress=None) -> InFlightItem:
    return InFlightItem(key=key, caption=f"Alpha Workflow > {key}",
                        reading=RunReading(status="queued", progress=progress),
                        reveal=lambda: None, cancel=lambda: None)


def _told(qtbot, in_flight):
    over = QWidget()
    qtbot.addWidget(over)
    queue = shown_job_queue(in_flight, over)
    told = []
    queue.changed.connect(lambda items, foreign: told.append(([i.key for i in items], foreign)))
    return queue, told


def test_the_job_queue_told_of_the_same_jobs_again_tells_no_one(qtbot):
    queue, told = _told(qtbot, lambda **_kw: [_waiting("a"), _waiting("b")])

    queue.update()
    queue.update()

    assert told == [(["a", "b"], 0)], (
        "the gallery asks after every poll, every second and a half, and each telling "
        "builds every Satellite's HUD again on the window's thread")


def test_the_job_queue_tells_of_a_job_that_moved_on(qtbot):
    progress = [(1, 10)]
    queue, told = _told(qtbot, lambda **_kw: [_waiting("a", progress=progress[0])])
    queue.update()

    progress[0] = (2, 10)
    queue.update()

    assert told == [(["a"], 0), (["a"], 0)]


def test_the_job_queue_tells_of_another_apps_jobs_coming_and_going(qtbot):
    queue, told = _told(qtbot, lambda **_kw: [])
    queue.update()

    queue.take_foreign(ForeignQueue(running=[], pending=["theirs"]))
    queue.update()

    assert told == [([], 0), ([], 1)]
