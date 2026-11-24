from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QWidget

from origenerator.gui.header_parts import PartsInARow
from origenerator.gui.thin_divider import THIN_DIVIDER_COLOR


class _Part(QWidget):
    def __init__(self, width: int, height: int):
        super().__init__()
        self._size = QSize(width, height)

    def sizeHint(self):
        return QSize(self._size)

    def minimumSizeHint(self):
        return QSize(self._size)


def _laid_out(qtbot, width: int, *sizes: tuple[int, int]):
    parts = [_Part(*size) for size in sizes]
    row = PartsInARow(*parts)
    qtbot.addWidget(row)
    _lay_out(row, width)
    return row, parts


def _lay_out(row, width: int) -> None:
    row.resize(width, row.heightForWidth(width))
    row.layout().activate()


def _upright(row) -> list:
    return [line for line in row.line_rects() if line.width() == 1]


def _across(row) -> list:
    return [line for line in row.line_rects() if line.height() == 1]


def test_parts_that_fit_sit_left_to_right_on_one_row_each_at_its_own_width(qtbot):
    row, parts = _laid_out(qtbot, 1000, (100, 20), (200, 40), (150, 30))

    assert [part.width() for part in parts] == [100, 200, 150]
    assert [part.y() for part in parts] == [0, 0, 0]
    assert parts[0].x() < parts[1].x() < parts[2].x()
    assert row.heightForWidth(1000) == 40


def test_a_part_that_does_not_fit_moves_down_a_row_whole_rather_than_shrinking(qtbot):
    _, parts = _laid_out(qtbot, 330, (100, 20), (200, 40), (150, 30))

    assert parts[2].width() == 150
    assert parts[2].x() == 0
    assert parts[2].y() > parts[1].y() + parts[1].height()


def test_a_thin_line_parts_two_neighbors_on_a_row_and_none_starts_a_row(qtbot):
    row, parts = _laid_out(qtbot, 330, (100, 20), (200, 40), (150, 30))
    (between,) = _upright(row)

    assert parts[0].x() + parts[0].width() < between.x() < parts[1].x()
    assert between.height() == 40


def test_a_thin_line_runs_between_two_rows(qtbot):
    row, parts = _laid_out(qtbot, 330, (100, 20), (200, 40), (150, 30))
    (across,) = _across(row)

    assert 40 < across.y() < parts[2].y()
    assert across.width() == 330


def test_a_hidden_part_takes_no_room_and_no_line(qtbot):
    row, parts = _laid_out(qtbot, 1000, (100, 20), (200, 40), (150, 30))
    parts[1].hide()
    _lay_out(row, 1000)

    assert parts[2].x() < 200
    assert len(_upright(row)) == 1


def test_the_lines_are_drawn_in_the_thin_dividers_gray(qtbot):
    row, _ = _laid_out(qtbot, 1000, (100, 20), (200, 40))
    (between,) = _upright(row)

    assert row.grab().toImage().pixelColor(between.x(), 10) == THIN_DIVIDER_COLOR
