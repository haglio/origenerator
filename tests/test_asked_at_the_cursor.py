from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox, QWidget
from shared_ui.testing import questions_answered

from origenerator.gui.asked_at_the_cursor import asked_at, placed_at
from origenerator.gui.inflight import InFlightItem, RunReading
from tests.qt_exec import faking_exec
from tests.shown_job_queue_support import shown_job_queue

SCREEN = QRect(0, 0, 1920, 1080)


def test_a_question_is_centered_on_the_point_it_was_asked_at():
    assert placed_at(QPoint(900, 500), QSize(300, 120), SCREEN) == QPoint(750, 440)


def test_a_question_asked_near_a_screen_edge_stays_wholly_on_that_screen():
    assert placed_at(QPoint(1910, 5), QSize(300, 120), SCREEN) == QPoint(1620, 0)
    assert placed_at(QPoint(-1915, 1075), QSize(300, 120), QRect(-1920, 0, 1920, 1080)) == \
        QPoint(-1920, 960)


def test_cancel_all_asks_its_question_where_the_pointer_is(qtbot, monkeypatch):
    pointer = QGuiApplication.primaryScreen().availableGeometry().center()
    over = QWidget()
    qtbot.addWidget(over)
    item = InFlightItem(key="a", caption="Alpha Workflow › a paper kite",
                        reading=RunReading(status="queued"), reveal=lambda: None,
                        cancel=lambda: None)
    queue = shown_job_queue(lambda **_kw: [item], over, cursor=lambda: pointer)
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


def test_a_question_asked_at_the_pointer_has_yes_as_the_default(qtbot, monkeypatch):
    over = QWidget()
    qtbot.addWidget(over)

    asked = questions_answered(monkeypatch, QMessageBox.StandardButton.No)

    asked_at(QPoint(900, 500), over, "Clear ComfyUI's queue", "Clear it?")

    [box] = asked
    assert box.default == QMessageBox.StandardButton.Yes
