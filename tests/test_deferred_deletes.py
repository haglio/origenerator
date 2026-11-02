"""Qt acts on deleteLater() only when an event loop runs, so a test that pumps one pays for every
deletion the tests before it left queued; no test may inherit them."""
from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QWidget

from tests.conftest import _deliver_deferred_deletes, _deliver_the_deletions_already_scheduled


def test_a_widget_asked_to_go_is_gone_once_the_deletions_are_drained(qapp):
    widget = QWidget()
    widget.deleteLater()
    assert not sip.isdeleted(widget), "deleteLater is not supposed to be immediate"

    _deliver_the_deletions_already_scheduled()

    assert sip.isdeleted(widget)


def test_the_deletions_a_drain_sets_off_are_carried_out_too(qapp):
    sender = QObject()
    sender.objectNameChanged.connect(lambda name: None)
    sender.deleteLater()

    _deliver_the_deletions_already_scheduled()
    qapp.processEvents()

    assert _deliver_deferred_deletes() == 0


def test_this_test_starts_with_no_deletions_left_over_from_another(qapp):
    left_over = _deliver_deferred_deletes()

    assert left_over == 0, (
        f"{left_over} objects were still waiting to be deleted when this test "
        "began — the next test that pumps an event loop pays for all of them"
    )
