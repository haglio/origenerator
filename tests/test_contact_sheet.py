"""The wall of a folder's pictures that fills a rewrite tab's preview."""

from PIL import Image

from origenerator.gui.contact_sheet import ContactSheet, row_counts, rows_for


def _picture(path, color=(200, 40, 40), size=(16, 12)):
    Image.new("RGB", size, color).save(path)
    return str(path)


# --- the grid, on its own ---------------------------------------------------

def test_nothing_to_tile_lays_out_no_grid():
    assert rows_for(0, 400, 300) == 0
    assert rows_for(4, 0, 300) == 0
    assert row_counts(4, 0) == []


def test_one_picture_takes_the_whole_pane():
    assert rows_for(1, 400, 300) == 1
    assert row_counts(1, 1) == [1]


def test_the_grid_picks_the_squarest_cells_the_pane_allows():
    # Nine pictures in a 4:3 pane come out 3x3 — square cells. Laid 9x1 or 1x9
    # they would be slivers, which is what the search is for.
    assert rows_for(9, 400, 300) == 3
    assert row_counts(9, 3) == [3, 3, 3]
    # A wide, short pane wants its rows long and few, not square-ish.
    assert rows_for(9, 1200, 100) == 1


def _oblong(count: int, rows: int, width: int, height: int) -> float:
    """How oblong a candidate's cells come out, measured at the row that is
    actually widest -- the row :func:`row_counts` lays, not a column count
    guessed beside it."""
    cell = (width / max(row_counts(count, rows)), height / rows)
    return max(cell) / min(cell)


def test_the_grid_the_search_picks_is_the_grid_that_gets_drawn():
    # Scored against the widest row the layout will really have: the remainder is
    # shared out row by row, so measuring anything else scores a cell shape
    # nothing is drawn at.
    for count in range(1, 40):
        chosen = rows_for(count, 400, 300)
        assert _oblong(count, chosen, 400, 300) == min(
            _oblong(count, rows, 400, 300) for rows in range(1, count + 1))


def test_the_last_rows_share_the_remainder_rather_than_leaving_a_gap():
    # Nine over four rows is 3/2/2/2, so every row reaches both edges — not
    # 3/3/3/0, which would leave a whole empty band at the bottom.
    assert row_counts(9, 4) == [3, 2, 2, 2]
    assert sum(row_counts(17, 5)) == 17


# --- the widget -------------------------------------------------------------

def test_the_sheet_tiles_every_readable_picture(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    sheet.show_pictures([_picture(tmp_path / f"p{n}.png") for n in range(6)])

    assert sheet.count() == 6
    assert len(sheet.cells()) == 6


def test_a_picture_the_library_has_moved_is_left_out_rather_than_drawn_as_a_hole(
        qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    sheet.show_pictures([_picture(tmp_path / "here.png"), str(tmp_path / "gone.png"), None])

    assert sheet.count() == 1


def test_the_tiles_fill_the_pane_edge_to_edge(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    sheet.show_pictures([_picture(tmp_path / f"p{n}.png") for n in range(5)])

    cells = sheet.cells()
    assert min(c.left() for c in cells) == 0
    assert min(c.top() for c in cells) == 0
    assert max(c.right() for c in cells) == 399
    assert max(c.bottom() for c in cells) == 299
    # No gaps and no overlaps: the cells add up to exactly the pane.
    assert sum(c.width() * c.height() for c in cells) == 400 * 300


def test_clearing_the_sheet_lets_go_of_its_pictures(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    sheet.show_pictures([_picture(tmp_path / "p.png")])

    sheet.clear()

    assert sheet.count() == 0
    assert sheet.cells() == []
