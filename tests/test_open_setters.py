from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from origenerator.gui.open_setters import OpenSetters


class _Window(QObject):
    closed = pyqtSignal()

    def __init__(self, *, in_front: bool):
        super().__init__()
        self.in_front = in_front
        self.heard = []

    def isActiveWindow(self):  # noqa: N802 -- Qt's name
        return self.in_front

    def knows(self, text):
        return text == "skip"

    def hear(self, text):
        if not self.knows(text):
            return False
        self.heard.append(text)
        return True


def test_the_setter_tool_in_front_hears_the_words_it_knows():
    setters, behind, front = OpenSetters(), _Window(in_front=False), _Window(in_front=True)
    setters.hold(behind)
    setters.hold(front)

    assert (setters.knows("skip"), setters.hear("skip")) == (True, True)
    assert (front.heard, behind.heard) == (["skip"], [])


def test_words_it_does_not_know_are_left_for_the_rest_of_the_app():
    setters, front = OpenSetters(), _Window(in_front=True)
    setters.hold(front)

    assert (setters.knows("go to recents"), setters.hear("go to recents"), front.heard) == (
        False, False, [])


def test_a_setter_tool_behind_another_window_hears_nothing():
    setters, behind = OpenSetters(), _Window(in_front=False)
    setters.hold(behind)

    assert (setters.knows("skip"), setters.hear("skip"), behind.heard) == (False, False, [])


def test_a_closed_setter_tool_hears_nothing():
    setters, window = OpenSetters(), _Window(in_front=True)
    setters.hold(window)

    window.closed.emit()

    assert setters.hear("skip") is False
