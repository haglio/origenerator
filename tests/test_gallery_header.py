from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from origenerator.gui.gallery_view import GalleryView
from origenerator.gui.thin_divider import ThinDivider
from tests.gallery_view_support import _image, database_of


def _laid_out(qtbot, rows):
    view = GalleryView(database_of(rows))
    qtbot.addWidget(view)
    view.resize(1600, 1000)
    view.refresh()
    view._tree.setCurrentItem(view.toc.leaf_by_id[rows[0]["prompt_id"]])
    view.layout().activate()
    return view


def _span(view, widget) -> tuple[int, int]:
    top = widget.mapTo(view, QPoint()).y()
    return top, top + widget.height()


def _layout_order(widget) -> list:
    layout = widget.parentWidget().layout()
    return [layout.itemAt(index).widget() for index in range(layout.count())]


def test_the_buttons_path_sort_by_and_actions_share_one_row_in_that_order(qtbot):
    view = _laid_out(qtbot, [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)])
    parts = [view._buttons, view._folder_path, view.sort_by, view._folder_actions]

    assert [_span(view, part)[0] for part in parts] == [_span(view, parts[0])[0]] * 4
    assert [part.mapTo(view, QPoint()).x() for part in parts] == sorted(
        part.mapTo(view, QPoint()).x() for part in parts)


def test_the_sort_dropdown_is_never_narrower_than_its_longest_choice(qtbot):
    view = _laid_out(qtbot, [_image("i1", "a cat", 50, 1)])
    view.resize(500, 1000)
    view.layout().activate()
    dropdown = view.sort_by.dropdown

    assert dropdown.width() >= dropdown.sizeHint().width()


def test_the_actions_name_keeps_its_whole_width_in_a_narrow_gallery(qtbot):
    view = _laid_out(qtbot, [_image("i1", "a cat", 50, 1)])
    view.resize(500, 1000)
    view.layout().activate()

    assert view._folder_actions.width() >= view._folder_actions.minimumSizeHint().width()


def test_a_thin_divider_parts_the_search_from_the_toc(qtbot):
    view = _laid_out(qtbot, [_image("i1", "a cat", 50, 1)])
    order = _layout_order(view._tree)
    at = order.index(view._tree)

    assert isinstance(order[at - 1], ThinDivider)


def test_a_thin_divider_parts_the_header_from_the_gallery(qtbot):
    view = _laid_out(qtbot, [_image("i1", "a cat", 50, 1)])
    order = _layout_order(view._scroll)
    at = order.index(view._scroll)

    assert isinstance(order[at - 1], ThinDivider)


def test_the_gallery_starts_below_every_row_of_the_header_in_a_narrow_window(qtbot):
    view = _laid_out(qtbot, [_image("i1", "a cat", 50, 1)])
    view.resize(500, 1000)
    view.show()
    for _ in range(3):
        QApplication.processEvents()
        view.layout().activate()
    lowest = max(_span(view, part)[1] for part in
                 (view._buttons, view._folder_path, view.sort_by, view._folder_actions)
                 if not part.isHidden())

    assert _span(view, view._scroll)[0] >= lowest
