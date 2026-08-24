"""No test may inherit the objects another test asked Qt to delete.

``deleteLater()`` posts a DeferredDelete event that is only acted on when an
event loop runs.  Almost nothing here runs one — a test calls methods and
asserts — so those deletions pile up all run, and the first test that *does*
pump the loop pays for every test before it.

That is what made
``test_gallery_view.py::test_a_finished_request_queues_the_revision_with_the_same_seed``
the one flake this suite has been seen to have: it waits up to three seconds for
an answer that crosses back from a pool thread, and 1.4 s of that budget went on
delivering the 44,659 DeferredDelete events its neighbours had left behind
(measured; the hop itself is 20 ms, and the bill grows with the number of tests
that ran first).  On a machine running several suites at once it overran, and
the test went red on two runs in five.
"""
from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent, QObject
from PyQt6.QtWidgets import QWidget

from tests.conftest import _deliver_the_deletions_already_scheduled


class _DeferredDeleteCounter(QObject):
    """Counts DeferredDelete events. Installed on the application object, which
    Qt gives every event in this thread, whatever object it was sent to."""

    def __init__(self) -> None:
        super().__init__()
        self.seen = 0

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.DeferredDelete:
            self.seen += 1
        return False


def test_a_widget_asked_to_go_is_gone_once_the_deletions_are_drained(qapp):
    widget = QWidget()
    widget.deleteLater()
    assert not sip.isdeleted(widget), "deleteLater is not supposed to be immediate"

    _deliver_the_deletions_already_scheduled()

    assert sip.isdeleted(widget)


def test_this_test_starts_with_no_deletions_left_over_from_another(qapp):
    """Whatever ran before this, its deletions were its own to pay for."""
    counter = _DeferredDeleteCounter()
    qapp.installEventFilter(counter)
    try:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        qapp.removeEventFilter(counter)

    assert counter.seen == 0, (
        f"{counter.seen} objects were still waiting to be deleted when this test "
        "began — the next test that pumps an event loop pays for all of them"
    )
