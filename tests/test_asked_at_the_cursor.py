from PySide6.QtCore import QObject, QPoint, QRect, QSize, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox, QWidget

from origenerator.gui.asked_at_the_cursor import placed_at
from origenerator.gui.inflight import InFlightItem, RunReading
from origenerator.gui.shown_job_queue import ShownJobQueue
from tests.qt_exec import faking_exec

SCREEN = QRect(0, 0, 1920, 1080)


def test_a_question_is_centered_on_the_point_it_was_asked_at():
    assert placed_at(QPoint(900, 500), QSize(300, 120), SCREEN) == QPoint(750, 440)


def test_a_question_asked_near_a_screen_edge_stays_wholly_on_that_screen():
    assert placed_at(QPoint(1910, 5), QSize(300, 120), SCREEN) == QPoint(1620, 0)
    assert placed_at(QPoint(-1915, 1075), QSize(300, 120), QRect(-1920, 0, 1920, 1080)) == \
        QPoint(-1920, 960)


class _Jobs(QObject):
    reordered = Signal()
    queue_order: tuple = ()

    def move(self, *_a):
        pass

    def start_now(self):
        pass


class _Starting(QObject):
    changed = Signal()

    def placed_among(self, items, _jobs):
        return items


def test_cancel_all_asks_its_question_where_the_pointer_is(qtbot, monkeypatch):
    pointer = QGuiApplication.primaryScreen().availableGeometry().center()
    over = QWidget()
    qtbot.addWidget(over)
    jobs = _Jobs()
    item = InFlightItem(key="a", caption="Alpha Workflow › a paper kite",
                        reading=RunReading(status="queued"), reveal=lambda: None,
                        cancel=lambda: None)
    queue = ShownJobQueue(jobs, None, starting=_Starting(), in_flight=lambda **_kw: [item],
                          listed=lambda: ([], []), asks_over=over,
                          cursor=lambda: pointer)
    asked_at = []


    def shown(box):
        box.show()
        asked_at.append(box.frameGeometry().center())
        box.close()
        return QMessageBox.StandardButton.No
    faking_exec(monkeypatch, QMessageBox, shown)

    queue.cancel_all()

    [center] = asked_at
    assert (center - pointer).manhattanLength() <= 2, (
        "in a Fun Time session Core sits out of sight, so a question placed over Core "
        "opened where nobody was looking")
