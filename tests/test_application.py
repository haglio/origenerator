from __future__ import annotations

import importlib.util
import logging
import weakref

from PyQt6 import sip
from PyQt6.QtCore import QObject, QThread
from PyQt6.QtWidgets import QWidget

from origenerator.gui.application import delete_what_python_still_owns


class _Gone:
    pass


def test_a_weak_proxy_whose_object_is_gone_is_passed_over(qapp):
    gone = _Gone()
    proxy = weakref.proxy(gone)
    del gone
    window = QWidget()

    delete_what_python_still_owns(qapp, candidates=lambda: [proxy, window])

    assert sip.isdeleted(window)


class _StillRunning(QThread):
    def isRunning(self) -> bool:
        return True


def test_a_thread_still_running_is_left_running(qapp):
    thread = _StillRunning()

    delete_what_python_still_owns(qapp, candidates=lambda: [thread])

    assert not sip.isdeleted(thread)


def test_the_windows_go_before_what_they_were_using(qapp):
    used = QObject()
    window = QWidget()
    still_there = []
    window.destroyed.connect(lambda: still_there.append(not sip.isdeleted(used)))

    delete_what_python_still_owns(qapp, candidates=lambda: [used, window])

    assert still_there == [True]


def test_what_went_with_an_earlier_deletion_is_passed_over(qapp):
    window = QWidget()
    taken_along = QWidget()
    taken_along.setParent(window)
    sip.transferback(taken_along)

    delete_what_python_still_owns(qapp, candidates=lambda: [window, taken_along])

    assert sip.isdeleted(taken_along)


def test_what_qt_owns_is_left_to_its_parent(qapp):
    window = QWidget()
    child = QWidget(window)

    delete_what_python_still_owns(qapp, candidates=lambda: [child])

    assert not sip.isdeleted(child)


def test_the_application_itself_is_left_alone(qapp):
    delete_what_python_still_owns(qapp, candidates=lambda: [qapp])

    assert not sip.isdeleted(qapp)


def test_the_log_says_how_many_it_deleted(qapp, caplog):
    windows = [QWidget(), QWidget()]

    with caplog.at_level(logging.INFO, logger="origenerator.gui.application"):
        delete_what_python_still_owns(qapp, candidates=lambda: windows)

    assert "Deleted 2 object(s) Python still owned" in caplog.text


def test_this_copy_goes_once_the_pinned_shared_ui_carries_the_familys():
    assert importlib.util.find_spec("shared_ui.application") is None, (
        "shared_ui now carries application(): make main take it from there, and "
        "delete origenerator/gui/application.py and this file")
