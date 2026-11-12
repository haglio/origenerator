from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QWidget

from origenerator.gui.warning_mark import WarningMark


def test_a_squeezed_row_never_draws_its_warning_mark_smaller_than_its_own_size(qtbot):
    host = QWidget()
    qtbot.addWidget(host)
    row = QHBoxLayout(host)
    mark = WarningMark()
    row.addWidget(mark)
    mark.warn("Something to fix")
    host.show()
    item = row.itemAt(0)

    assert item.minimumSize() == mark.sizeHint()
