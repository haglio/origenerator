from __future__ import annotations

from PySide6.QtCore import QPoint

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


def test_the_sort_dropdown_shares_the_buttons_row_rather_than_a_row_of_its_own(qtbot):
    view = _laid_out(qtbot, [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)])
    buttons_top, buttons_bottom = _span(view, view._buttons)
    sort_top, sort_bottom = _span(view, view.sort_by)

    assert buttons_top <= sort_top
    assert sort_bottom <= buttons_bottom


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


def _layout_holding(layout, widget):
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is widget:
            return layout, index
        if item.layout() is not None and (found := _layout_holding(item.layout(), widget)):
            return found
    return None


def test_the_divider_beside_actions_goes_when_the_actions_do(qtbot):
    view = _laid_out(qtbot, [_image("i1", "a cat", 50, 1)])
    layout, at = _layout_holding(view._folder_actions.parentWidget().layout(),
                                 view._folder_actions)
    beside = layout.itemAt(at - 1).widget()
    assert isinstance(beside, ThinDivider)
    assert not beside.isHidden()

    view._folder_actions.show_folder(None)

    assert beside.isHidden()
