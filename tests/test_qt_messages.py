from __future__ import annotations

import logging

import pytest
from PyQt6.QtCore import qCritical, qInstallMessageHandler, qWarning

from origenerator.qt_messages import (
    RepeatCollapser,
    install_qt_message_logging,
)


def _probe(_kind, _context, _message):
    pass


@pytest.mark.no_qt_log
def test_between_tests_a_qt_message_still_has_a_python_handler_to_reach():
    in_force = qInstallMessageHandler(_probe)
    qInstallMessageHandler(in_force)

    assert callable(in_force)


@pytest.mark.no_qt_log
def test_what_qt_says_lands_in_the_apps_log(caplog):
    # Hosted by Fun Time this app's stderr goes nowhere, and faulthandler
    # cannot see a fail-fast abort, so a Qt fatal -- the abort inside Qt6Core
    # that Windows recorded about twenty times over four days -- left no line
    # in any log of ours. Qt says why on its way down; routed through logging,
    # that sentence lands in origenerator.log beside everything else.
    previous = install_qt_message_logging()
    try:
        with caplog.at_level(logging.WARNING, logger="qt"):
            qWarning("scene one is not a QObject")
            qCritical("scene two was destroyed while still running")
    finally:
        qInstallMessageHandler(previous)

    assert [(r.levelno, r.getMessage()) for r in caplog.records
            if r.name == "qt"] == [
        (logging.WARNING, "scene one is not a QObject"),
        (logging.ERROR, "scene two was destroyed while still running"),
    ]


def _collapser():
    said = []
    return RepeatCollapser(lambda level, message: said.append((level, message))), said


def test_a_message_that_keeps_arriving_is_said_once_and_counted():
    # 30,000 of one Qt warning in three minutes spent every rotation of the log
    # and took every older line with it, so nothing could be asked of it after.
    collapse, said = _collapser()

    for _ in range(4):
        collapse(logging.WARNING, "the audio device went away")
    collapse(logging.WARNING, "something else entirely")

    assert said == [
        (logging.WARNING, "the audio device went away"),
        (logging.WARNING, "the audio device went away (4 of these in all)"),
        (logging.WARNING, "something else entirely"),
    ]


def test_a_run_still_arriving_says_how_far_it_has_got_at_each_power_of_ten():
    # The app can be killed mid-flood, and one line then says nothing about how
    # much of the log went.
    collapse, said = _collapser()

    for _ in range(1000):
        collapse(logging.WARNING, "the audio device went away")

    assert [message for _level, message in said] == [
        "the audio device went away",
        "the audio device went away (10 more of these so far)",
        "the audio device went away (100 more of these so far)",
    ]


def test_the_same_words_at_a_different_level_are_a_run_of_their_own():
    collapse, said = _collapser()

    collapse(logging.WARNING, "the audio device went away")
    collapse(logging.ERROR, "the audio device went away")

    assert said == [(logging.WARNING, "the audio device went away"),
                    (logging.ERROR, "the audio device went away")]


def test_messages_that_never_repeat_are_each_said_whole():
    collapse, said = _collapser()

    collapse(logging.WARNING, "scene one is not a QObject")
    collapse(logging.WARNING, "scene two was destroyed while still running")

    assert said == [(logging.WARNING, "scene one is not a QObject"),
                    (logging.WARNING, "scene two was destroyed while still running")]
