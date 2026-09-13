from __future__ import annotations

import pytest
from PyQt6.QtCore import qInstallMessageHandler


def _probe(_kind, _context, _message):
    pass


@pytest.mark.no_qt_log
def test_between_tests_a_qt_message_still_has_a_python_handler_to_reach():
    in_force = qInstallMessageHandler(_probe)
    qInstallMessageHandler(in_force)

    assert callable(in_force)
