from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from origenerator.gui.pane_arrangement import PaneArrangement


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


def _widened(qtbot, root, width):
    root.resize(width, 700)
    qtbot.wait(20)


def test_standalone_the_folder_tree_keeps_its_width_and_the_gallery_pane_takes_the_growth(qtbot):
    arrangement, parts = _arrangement(qtbot)
    root = arrangement.standalone()
    root.show()
    qtbot.addWidget(root)
    _widened(qtbot, root, 1200)
    tree_before, gallery_before = parts["toc"].width(), parts["gallery_pane"].width()

    _widened(qtbot, root, 1800)

    assert parts["toc"].width() == tree_before
    assert parts["gallery_pane"].width() > gallery_before


def test_standalone_the_folders_gain_more_of_a_wider_window_than_the_generate_column(qtbot):
    arrangement, parts = _arrangement(qtbot)
    root = arrangement.standalone()
    root.show()
    qtbot.addWidget(root)
    _widened(qtbot, root, 1200)
    folders_before, generate_before = arrangement.left_column.width(), parts["generate_column"].width()

    _widened(qtbot, root, 1800)

    folders_gain = arrangement.left_column.width() - folders_before
    generate_gain = parts["generate_column"].width() - generate_before
    assert generate_gain > 0
    assert folders_gain > generate_gain


def test_hosted_the_folder_tree_sits_beside_the_gallery_pane_and_keeps_its_width(qtbot):
    arrangement, parts = _arrangement(qtbot)
    root = arrangement.hosted()
    root.show()
    qtbot.addWidget(root)
    root.resize(600, 900)
    qtbot.wait(20)
    tree_before = parts["toc"].width()

    root.resize(900, 900)
    qtbot.wait(20)

    assert [arrangement.panes.widget(0), arrangement.panes.widget(1)] == [parts["toc"], arrangement.folder_panes]
    assert parts["toc"].width() == tree_before


def test_hosted_the_folders_row_gains_more_of_a_taller_rect_than_the_generate_tabs(qtbot):
    arrangement, parts = _arrangement(qtbot)
    root = arrangement.hosted()
    root.show()
    qtbot.addWidget(root)
    root.resize(600, 900)
    qtbot.wait(20)
    folders_before, generate_before = arrangement.panes.height(), parts["generate_column"].height()

    root.resize(600, 1500)
    qtbot.wait(20)

    folders_gain = arrangement.panes.height() - folders_before
    generate_gain = parts["generate_column"].height() - generate_before
    assert generate_gain > 0
    assert folders_gain > generate_gain
