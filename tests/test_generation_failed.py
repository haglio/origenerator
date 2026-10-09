from __future__ import annotations

from collections import Counter

from PyQt6.QtWidgets import QMessageBox, QWidget

from origenerator.gui.generation_failed import GenerationFailed, worded


def _open_dialogs(window):
    return [box for box in window.findChildren(QMessageBox) if box.isVisible()]


def test_each_reason_is_said_once_with_how_many_generations_it_stopped():
    assert worded(Counter({"no such model": 1, "out of memory": 2})) == (
        "no such model\n\nout of memory (2 generations)")


def test_a_failure_after_the_dialog_is_dismissed_is_counted_afresh(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    generation_failed = GenerationFailed(window)
    generation_failed.say("no such model")
    generation_failed.say("no such model")
    (first,) = _open_dialogs(window)

    first.done(QMessageBox.StandardButton.Ok)
    generation_failed.say("no such model")

    (second,) = _open_dialogs(window)
    assert second is not first
    assert second.text() == "no such model"
