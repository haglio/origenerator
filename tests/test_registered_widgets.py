"""A widget a test hands ``qtbot.addWidget`` lives until that test is torn down."""
from __future__ import annotations

import gc
import weakref

from PyQt6.QtWidgets import QWidget


def test_a_registered_widget_in_a_reference_cycle_outlives_a_collection(qtbot):
    widget = QWidget()
    widget.itself = widget
    qtbot.addWidget(widget)
    registered = weakref.ref(widget)
    del widget

    gc.collect()

    assert registered() is not None
