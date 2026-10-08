"""No test may inherit the objects another test asked Qt to delete.

``deleteLater()`` posts a DeferredDelete event that is only acted on when an
event loop runs.  Almost nothing here runs one — a test calls methods and
asserts — so those deletions pile up all run, and the first test that *does*
pump the loop pays for every test before it.

That is what made
``test_gallery_view.py::test_a_finished_request_queues_the_revision_with_the_same_seed``
the one flake this suite has been seen to have: it waits up to three seconds for
an answer that crosses back from a pool thread, and 1.4 s of that budget went on
delivering the 44,659 DeferredDelete events its neighbours had left over
(measured; the hop itself is 20 ms, and the bill grows with the number of tests
that ran first).  On a machine running several suites at once it overran, and
the test went red on two runs in five.
"""
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
    """Whatever ran before this, its deletions were its own to pay for."""
    left_over = _deliver_deferred_deletes()

    assert left_over == 0, (
        f"{left_over} objects were still waiting to be deleted when this test "
        "began — the next test that pumps an event loop pays for all of them"
    )
