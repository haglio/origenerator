from __future__ import annotations

import math

from PIL import Image

from origenerator.gui.contact_sheet import ContactSheet, row_counts, rows_for

SQUARE = 1.0


def _thumbnail(path, color=(200, 40, 40), size=(16, 12)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def test_nothing_to_tile_lays_out_no_grid():
    assert rows_for(0, 400, 300, shape=SQUARE) == 0
    assert rows_for(4, 0, 300, shape=SQUARE) == 0
    assert row_counts(4, 0) == []


def test_one_thumbnail_takes_the_whole_pane():
    assert rows_for(1, 400, 300, shape=SQUARE) == 1
    assert row_counts(1, 1) == [1]


def test_square_thumbnails_get_the_squarest_cells_the_pane_allows():
    assert rows_for(9, 400, 300, shape=SQUARE) == 3
    assert row_counts(9, 3) == [3, 3, 3]
    assert rows_for(9, 1200, 100, shape=SQUARE) == 1


def _mismatch(count: int, rows: int, width: int, height: int, shape: float) -> float:
    cell_shape = (width / max(row_counts(count, rows))) / (height / rows)
    return abs(math.log(cell_shape / shape))


def test_the_grid_the_search_picks_is_the_grid_that_gets_drawn():
    for shape in (9 / 16, SQUARE, 16 / 9):
        for count in range(1, 40):
            chosen = rows_for(count, 400, 300, shape=shape)
            assert _mismatch(count, chosen, 400, 300, shape) == min(
                _mismatch(count, rows, 400, 300, shape) for rows in range(1, count + 1))


def test_the_last_rows_share_the_remainder_rather_than_leaving_a_gap():
    assert row_counts(9, 4) == [3, 2, 2, 2]
    assert sum(row_counts(17, 5)) == 17


def test_the_sheet_tiles_every_readable_thumbnail(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    sheet.show_thumbnails([_thumbnail(tmp_path / f"p{n}.png") for n in range(6)])

    assert sheet.count() == 6
    assert len(sheet.cells()) == 6


def test_two_landscape_thumbnails_are_stacked_into_two_landscape_halves(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    sheet.show_thumbnails([_thumbnail(tmp_path / f"p{n}.png", size=(32, 18)) for n in range(2)])

    assert [(c.width(), c.height()) for c in sheet.cells()] == [(400, 150), (400, 150)]


def test_two_portrait_thumbnails_stand_side_by_side_in_two_portrait_halves(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    sheet.show_thumbnails([_thumbnail(tmp_path / f"p{n}.png", size=(18, 32)) for n in range(2)])

    assert [(c.width(), c.height()) for c in sheet.cells()] == [(200, 300), (200, 300)]


def test_a_thumbnail_the_library_has_moved_is_left_out_rather_than_drawn_as_a_gap(
        qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    sheet.show_thumbnails([_thumbnail(tmp_path / "here.png"), str(tmp_path / "gone.png"), None])

    assert sheet.count() == 1


def test_the_tiles_fill_the_pane_edge_to_edge(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    sheet.show_thumbnails([_thumbnail(tmp_path / f"p{n}.png") for n in range(5)])

    cells = sheet.cells()
    assert min(c.left() for c in cells) == 0
    assert min(c.top() for c in cells) == 0
    assert max(c.right() for c in cells) == 399
    assert max(c.bottomLeft().y() for c in cells) == 299
    assert sum(c.width() * c.height() for c in cells) == 400 * 300


def test_clearing_the_sheet_lets_go_of_its_thumbnails(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    sheet.show_thumbnails([_thumbnail(tmp_path / "p.png")])

    sheet.clear()

    assert sheet.count() == 0
    assert sheet.cells() == []
