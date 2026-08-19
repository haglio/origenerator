from PIL import Image
from PyQt6.QtCore import Qt

from origenerator.gui import queue_thumbs
from origenerator.gui.queue_thumbs import (
    FOLDER_CELLS, QueueThumbs, block_width, folder_pixmap, source_pixmap,
)

CELL = 28  # a queue row's height, less its margins


def _picture(path, color, size=(80, 40)):
    """A flat rectangle standing in for a render — wider than tall, so a cell
    that crops it can be told from a cell that squashed it."""
    Image.new("RGB", size, color).save(path)
    return str(path)


def _color_at(pixmap, x, y):
    # pixelColor, not pixel: an empty cell and a faint slot differ only in alpha,
    # which pixel() throws away.
    return pixmap.toImage().pixelColor(x, y)


def _middle_of_cell(index):
    return index * (CELL + 1) + CELL // 2


def test_a_cell_is_filled_by_the_middle_of_the_picture(qapp, tmp_path):
    # Cover-cropped, not letterboxed: at this size a fitted thumbnail is mostly
    # empty border, and the middle of a frame is where its subject is.
    red = _picture(tmp_path / "a.png", (255, 0, 0))

    block = source_pixmap(red, CELL)

    assert _color_at(block, CELL // 2, CELL // 2).red() > 200


def test_a_missing_file_is_no_picture_rather_than_a_blank_one(qapp, tmp_path):
    # A start frame can be a library file that has moved, or one still rendering.
    assert source_pixmap(tmp_path / "gone.png", CELL) is None
    assert source_pixmap(None, CELL) is None


def test_the_pictures_lie_across_the_row_not_stacked(qapp, tmp_path):
    # Stacked into a 2x2 the cells are half a row's height each, which is small
    # enough that four of them read as one smudge.
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    paths = [_picture(tmp_path / f"{i}.png", c) for i, c in enumerate(colors)]

    block = folder_pixmap(paths, CELL)

    assert (block.width(), block.height()) == (block_width(CELL), CELL)
    assert _color_at(block, _middle_of_cell(0), CELL // 2).red() > 200
    assert _color_at(block, _middle_of_cell(1), CELL // 2).green() > 200
    assert _color_at(block, _middle_of_cell(2), CELL // 2).blue() > 200
    fourth = _color_at(block, _middle_of_cell(3), CELL // 2)
    assert fourth.red() > 200 and fourth.green() > 200


def test_a_folder_view_keeps_its_empty_slots(qapp, tmp_path):
    # A folder holding one item should read as a folder with room in it, not as
    # pictures that failed to arrive — so the cells nothing fills are drawn.
    one = _picture(tmp_path / "only.png", (255, 0, 0))

    block = folder_pixmap([one], CELL)

    assert _color_at(block, _middle_of_cell(0), CELL // 2).red() > 200
    assert _color_at(block, _middle_of_cell(3), CELL // 2).alpha() > 0


def test_a_start_frame_leaves_the_rest_of_the_block_empty(qapp, tmp_path):
    # It is not a folder: there is no second picture missing from it, so drawing
    # slots beside it would claim three that never existed.
    frame = _picture(tmp_path / "frame.png", (255, 0, 0))

    block = source_pixmap(frame, CELL)

    assert _color_at(block, _middle_of_cell(0), CELL // 2).red() > 200
    assert _color_at(block, _middle_of_cell(3), CELL // 2).alpha() == 0


def test_one_picture_takes_the_same_width_as_four(qapp, tmp_path):
    # So the line of text behind the block starts at the same place on every row.
    frame = _picture(tmp_path / "frame.png", (255, 0, 0))
    mates = [_picture(tmp_path / f"m{i}.png", (0, 0, 255)) for i in range(4)]

    assert source_pixmap(frame, CELL).width() == folder_pixmap(mates, CELL).width()


def test_a_folder_view_takes_the_first_four_and_stops(qapp, tmp_path):
    # Four is what fits across without the row's text starting halfway along the
    # strip; the fifth picture of a busy folder has nowhere to go.
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255)]
    paths = [_picture(tmp_path / f"{i}.png", c) for i, c in enumerate(colors)]

    block = folder_pixmap(paths, CELL)

    assert len(paths) > FOLDER_CELLS
    last = _color_at(block, _middle_of_cell(3), CELL // 2)
    assert last.blue() < 60  # the fourth picture, not the fifth


def test_a_scaled_cell_is_only_ever_read_off_disk_once(qapp, tmp_path, monkeypatch):
    # The strip re-renders on every poll and a start frame is a full-size render;
    # decoding one a second and a half apart is work nobody sees.
    picture = _picture(tmp_path / "a.png", (255, 0, 0))
    queue_thumbs._CELLS.clear()
    source_pixmap(picture, CELL)

    reads = []
    monkeypatch.setattr(queue_thumbs, "_crop_to_square",
                        lambda *a: reads.append(a) or None)
    again = source_pixmap(picture, CELL)

    assert reads == []
    assert again is not None  # answered from the cache, not re-cropped to nothing


def test_an_unchanged_push_costs_the_block_nothing(qtbot, tmp_path):
    # Every row is handed a fresh view-model on every poll, and recomposing four
    # scaled cells for a queue that hasn't moved is work nobody sees.
    thumbs = QueueThumbs(CELL)
    qtbot.addWidget(thumbs)
    folder = [_picture(tmp_path / "f.png", (0, 0, 255))]
    thumbs.show_folder(folder)
    first = thumbs.pixmap()

    thumbs.show_folder(folder)

    assert thumbs.pixmap() is first or thumbs.pixmap().cacheKey() == first.cacheKey()


def test_a_source_frame_that_is_not_on_disk_yet_leaves_the_block_to_the_folder(
        qtbot, tmp_path):
    # A video queued behind the image it animates: its start frame is named but
    # not rendered, so the caller is told to fall back rather than draw a blank.
    thumbs = QueueThumbs(CELL)
    qtbot.addWidget(thumbs)

    assert thumbs.show_source(str(tmp_path / "not-yet.png")) is False
    assert thumbs.show_source(None) is False
    assert thumbs.show_source("") is False


def test_a_block_with_nothing_to_show_leaves_the_row(qtbot, tmp_path):
    thumbs = QueueThumbs(CELL)
    qtbot.addWidget(thumbs)
    thumbs.show_folder([_picture(tmp_path / "f.png", (0, 0, 255))])

    thumbs.clear_block()

    assert thumbs.isHidden()


def test_the_block_never_eats_the_rows_click(qtbot):
    # The row it sits in opens the folder on a click and reorders the line on a
    # drag; a child widget under the cursor would swallow both.
    thumbs = QueueThumbs(CELL)
    qtbot.addWidget(thumbs)

    assert thumbs.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
