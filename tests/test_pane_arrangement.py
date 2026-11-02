from __future__ import annotations

from origenerator.gui.pane_arrangement import PaneArrangement
from PyQt6.QtWidgets import QWidget


def _arrangement(qtbot):
    parts = {name: QWidget() for name in ("toc", "gallery_pane", "generate_column", "generate_pane", "queue")}
    parts["queue"].setMinimumHeight(90)
    for widget in parts.values():
        qtbot.addWidget(widget)
    return PaneArrangement(**parts), parts


def _taller(qtbot, root, height):
    root.resize(1200, height)
    qtbot.wait(20)


def test_standalone_puts_the_queue_under_the_folders_and_the_generate_column_beside_them(qtbot):
    arrangement, parts = _arrangement(qtbot)
    root = arrangement.standalone()
    root.show()
    qtbot.addWidget(root)
    _taller(qtbot, root, 700)

    assert arrangement.left_column.widget(0) is arrangement.folder_panes
    assert arrangement.left_column.widget(1) is parts["queue"]
    assert root.widget(1) is parts["generate_column"]


def test_standalone_queue_keeps_its_height_when_the_window_grows(qtbot):
    arrangement, parts = _arrangement(qtbot)
    root = arrangement.standalone()
    root.show()
    qtbot.addWidget(root)
    _taller(qtbot, root, 700)
    before = parts["queue"].height()

    _taller(qtbot, root, 1000)

    assert parts["queue"].height() == before


def test_hosted_stacks_generate_then_folders_then_the_queue_across_the_foot(qtbot):
    arrangement, parts = _arrangement(qtbot)
    root = arrangement.hosted()
    qtbot.addWidget(root)

    assert [root.widget(i) for i in range(3)] == [parts["generate_column"], arrangement.panes, parts["queue"]]
    assert arrangement.left_column is None


def test_hosted_queue_keeps_its_height_when_the_rect_grows(qtbot):
    arrangement, parts = _arrangement(qtbot)
    root = arrangement.hosted()
    root.show()
    qtbot.addWidget(root)
    root.resize(600, 900)
    qtbot.wait(20)
    before = parts["queue"].height()

    root.resize(600, 1300)
    qtbot.wait(20)

    assert parts["queue"].height() == before


def test_standalone_leaves_the_generate_pane_no_floor_of_its_own(qtbot):
    arrangement, parts = _arrangement(qtbot)

    qtbot.addWidget(arrangement.standalone())

    assert parts["generate_pane"].minimumWidth() == 0
    assert parts["generate_column"].minimumWidth() == 0
