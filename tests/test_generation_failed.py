from __future__ import annotations

from collections import Counter

from PySide6.QtWidgets import QWidget

from origenerator.gui.generation_failed import TITLE, GenerationFailed, worded
from tests.alert_windows import message_of, open_alerts


def test_each_reason_is_said_once_with_how_many_generations_it_stopped():
    assert worded(Counter({"no such model": 1, "out of memory": 2})) == (
        "no such model\n\nout of memory (2 generations)")


def test_a_failure_is_said_in_the_familys_alert_window(qtbot):
    window = QWidget()
    qtbot.addWidget(window)

    GenerationFailed(window).say("no such model")

    (shown,) = open_alerts(window)
    assert shown.windowTitle() == TITLE
    assert message_of(shown) == "no such model"


def test_failures_while_it_is_open_leave_one_window_saying_them_all(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    generation_failed = GenerationFailed(window)

    for reason in ("no such model", "out of memory", "no such model"):
        generation_failed.say(reason)

    (shown,) = open_alerts(window)
    assert message_of(shown) == "no such model (2 generations)\n\nout of memory"


def test_a_failure_after_the_window_is_dismissed_is_counted_afresh(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    generation_failed = GenerationFailed(window)
    generation_failed.say("no such model")
    generation_failed.say("no such model")
    (first,) = open_alerts(window)

    first.accept()
    generation_failed.say("no such model")

    (second,) = open_alerts(window)
    assert second is not first
    assert message_of(second) == "no such model"
