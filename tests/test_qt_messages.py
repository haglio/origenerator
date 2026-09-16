from __future__ import annotations

import logging

import pytest
from PyQt6.QtCore import qCritical, qInstallMessageHandler, qWarning

from origenerator.qt_messages import install_qt_message_logging


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
