from __future__ import annotations

from PySide6.QtCore import QPoint, QSize
from PySide6.QtWidgets import QAbstractItemView, QApplication
from shared_ui.icons import qt_icon
from shared_ui.spacing import BUTTON_GAP, BUTTON_ICON_INSET, BUTTON_SIZE_HUD

from origenerator import ui_scale
from origenerator.gallery.shapes import LANDSCAPE, PORTRAIT
from origenerator.gui.gallery_tree import GROUP_ROLE
from origenerator.gui.split_folder_tree import SplitFolderTree
from tests.test_folder_tree import _folder_row


def _toc_too_long_for_its_height(qtbot, width=400):
    toc = SplitFolderTree(GROUP_ROLE)
    qtbot.addWidget(toc)
    rows = {}
    for shape in (PORTRAIT, LANDSCAPE):
        rows[shape] = [_folder_row(f"folder {n}", f"{shape}/{n}") for n in range(60)]
        toc.root_for(shape).addChildren(rows[shape])
    toc.resize(width, 400)
    toc.show()
    QApplication.processEvents()
    return toc, rows


def _drawn(icon) -> bytes:
    image = icon.pixmap(QSize(48, 48)).toImage()
    return bytes(image.constBits())


def _right_edge(toc, button) -> int:
    return button.mapTo(toc, QPoint()).x() + button.width()


def test_the_row_over_the_toc_ends_with_a_reticle_and_then_an_up_arrow(qtbot):
    toc, _rows = _toc_too_long_for_its_height(qtbot)
    reticle, up_arrow = toc.current_folder_button, toc.top_button

    assert _drawn(reticle.icon()) == _drawn(qt_icon("reticle"))
    assert _drawn(up_arrow.icon()) == _drawn(qt_icon("arrow_up"))
    assert (reticle.toolTip(), up_arrow.toolTip()) == (
        "Scroll the current folder into view", "Scroll to the top")
    assert _right_edge(toc, toc.together_button.parent()) < reticle.mapTo(toc, QPoint()).x()
    assert _right_edge(toc, reticle) < up_arrow.mapTo(toc, QPoint()).x()
    assert _right_edge(toc, up_arrow) == toc.width()
    assert {button.mapTo(toc, QPoint()).y() for button in (
        toc.separate_button, reticle, up_arrow)} == {0}


def test_a_column_too_narrow_for_one_row_keeps_the_two_at_its_right_edge(qtbot):
    toc, _rows = _toc_too_long_for_its_height(qtbot, width=150)

    assert _right_edge(toc, toc.top_button) == toc.width()
    assert toc.current_folder_button.mapTo(toc, QPoint()).y() == 0


def _in_view(tree, row) -> bool:
    place = tree.visualItemRect(row)
    return place.isValid() and tree.viewport().rect().contains(place)


def test_the_reticle_scrolls_the_current_folder_into_view(qtbot):
    toc, rows = _toc_too_long_for_its_height(qtbot)
    current = rows[LANDSCAPE][5]
    toc.setCurrentItem(current)
    tree = current.treeWidget()
    tree.scrollToItem(rows[LANDSCAPE][55], QAbstractItemView.ScrollHint.PositionAtTop)
    assert not _in_view(tree, current)

    toc.current_folder_button.click()

    assert _in_view(tree, current)
    assert current not in tree.frozen_rows()


def test_the_reticle_does_nothing_with_no_current_folder(qtbot):
    toc, rows = _toc_too_long_for_its_height(qtbot)
    tree = rows[PORTRAIT][0].treeWidget()
    tree.verticalScrollBar().setValue(7)

    toc.current_folder_button.click()

    assert tree.verticalScrollBar().value() == 7


def test_the_up_arrow_scrolls_every_list_to_its_top(qtbot):
    toc, rows = _toc_too_long_for_its_height(qtbot)
    for shape in (PORTRAIT, LANDSCAPE):
        rows[shape][0].treeWidget().scrollToBottom()

    toc.top_button.click()

    assert set(toc.scroll_places().values()) == {0}


def test_a_toc_that_offers_no_separate_and_together_offers_neither_button(qtbot):
    toc, _rows = _toc_too_long_for_its_height(qtbot)

    toc.offer_separate_and_together(False)

    assert not toc.current_folder_button.isVisible()
    assert not toc.top_button.isVisible()


def test_the_buttons_over_the_toc_are_the_size_of_the_gallery_pane_buttons(qtbot):
    toc, _rows = _toc_too_long_for_its_height(qtbot)
    square = QSize(BUTTON_SIZE_HUD, BUTTON_SIZE_HUD)
    filling = QSize(BUTTON_SIZE_HUD - 2 * BUTTON_ICON_INSET, BUTTON_SIZE_HUD - 2 * BUTTON_ICON_INSET)

    for button in (toc.separate_button, toc.together_button, toc.current_folder_button, toc.top_button):
        assert (button.size(), button.iconSize()) == (square, filling), button.toolTip()
    gap = toc.top_button.mapTo(toc, QPoint()).x() - _right_edge(toc, toc.current_folder_button)
    assert gap == ui_scale.landing_at_the_huds_scale(BUTTON_GAP, hosted=False)
