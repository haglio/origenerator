from __future__ import annotations

import logging
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from PySide6.QtCore import qCritical, qInstallMessageHandler, qWarning

from origenerator.qt_messages import (
    RepeatCollapser,
    install_qt_message_logging,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _probe(_kind, _context, _message):
    pass


@pytest.mark.no_qt_log
def test_between_tests_a_qt_message_still_has_a_python_handler_to_reach():
    in_force = qInstallMessageHandler(_probe)
    qInstallMessageHandler(in_force)

    assert callable(in_force)


@pytest.mark.no_qt_log
def test_what_qt_says_lands_in_the_apps_log(caplog):
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


@pytest.mark.no_qt_log
def test_qts_note_on_taking_its_own_video_player_apart_is_logged_for_debugging(caplog):
    previous = install_qt_message_logging()
    try:
        with caplog.at_level(logging.DEBUG, logger="qt"):
            qWarning("QObject::disconnect: wildcard call disconnects from destroyed signal"
                     " of QFFmpeg::Demuxer::unnamed")
    finally:
        qInstallMessageHandler(previous)

    assert [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "qt"] == [
        (logging.DEBUG, "QObject::disconnect: wildcard call disconnects from destroyed signal"
                        " of QFFmpeg::Demuxer::unnamed")]


@pytest.mark.no_qt_log
def test_a_new_install_never_reports_a_run_an_earlier_one_was_counting(caplog):
    before = install_qt_message_logging()
    try:
        qWarning("an earlier window's complaint")
        qWarning("an earlier window's complaint")
        install_qt_message_logging()
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="qt"):
            qWarning("scene one is not a QObject")
    finally:
        qInstallMessageHandler(before)

    assert [r.getMessage() for r in caplog.records if r.name == "qt"] == [
        "scene one is not a QObject"]


def test_the_qt_this_app_asks_for_says_a_wildcard_disconnect_after_letting_go_of_its_lock():
    # The wildcard-disconnect message has no category, so no filter rule keeps it from the handler; Qt 6.11.1 says it holding the signal/slot lock (QTBUG-145216), 6.11.2 after letting go.
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    qt = [Requirement(line) for line in project["dependencies"]
          if Requirement(line).name == "PySide6"]

    assert [(r.specifier.contains("6.11.1"), r.specifier.contains("6.11.2")) for r in qt] == [
        (False, True)]


def _collapser():
    said = []
    return RepeatCollapser(lambda level, message: said.append((level, message))), said


def test_a_message_that_keeps_arriving_is_said_once_and_counted():
    collapse, said = _collapser()

    for _ in range(4):
        collapse(logging.WARNING, "the audio device went away")
    collapse(logging.WARNING, "something else entirely")

    assert said == [
        (logging.WARNING, "the audio device went away"),
        (logging.WARNING, "the audio device went away (4 of these in all)"),
        (logging.WARNING, "something else entirely"),
    ], (
        "Qt repeats a message as often as the thing it complains about happens, thousands of "
        "times a minute for anything per frame, and a log that keeps four megabytes can hold "
        "weeks of the app's own record or three minutes of one complaint")


def test_a_run_still_arriving_says_how_far_it_has_got_at_each_power_of_ten():
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
