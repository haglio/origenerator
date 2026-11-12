from __future__ import annotations

import shiboken6
from PySide6.QtWidgets import QSplitter, QWidget

from origenerator.gui.item_area import ItemArea


def test_a_share_asked_for_just_before_the_area_goes_is_dropped_with_it(qtbot):
    splitter = QSplitter()
    qtbot.addWidget(splitter)
    area = QWidget()
    splitter.addWidget(area)
    splitter.addWidget(QWidget())
    section = QWidget(area)
    section.hide()
    area.hide()
    ItemArea(area, (section,), splitter, dragged=lambda: False)

    section.show()
    shiboken6.delete(area)

    qtbot.wait(20)
