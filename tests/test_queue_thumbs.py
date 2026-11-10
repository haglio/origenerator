from __future__ import annotations

import os

from PIL import Image
from PyQt6.QtCore import Qt

from origenerator.gui import queue_thumbs
from origenerator.gui.combination import Combination
from origenerator.gui.queue_thumbs import (
    FOLDER_CELLS,
    QueueThumbs,
    block_width,
    fitted_cell,
    folder_pixmap,
    source_pixmap,
)

CELL = 28


def _thumbnail(path, color, size=(80, 40)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def _color_at(pixmap, x, y):
    # Qt: pixel() throws the alpha away, and alpha is all that tells an empty cell from a faint one.
    return pixmap.toImage().pixelColor(x, y)


def _middle_of_cell(index):
    return index * (CELL + 1) + CELL // 2


def test_a_cell_shows_the_whole_image_letterboxed(qapp, tmp_path):
    red = _thumbnail(tmp_path / "a.png", (255, 0, 0))

    block = source_pixmap(Combination(red), CELL)

    assert _color_at(block, CELL // 2, CELL // 2).red() > 200
    assert _color_at(block, CELL // 2, 0).alpha() == 0, (
        "a crop takes off the edges, and an off-center subject becomes an image of something else")
    assert _color_at(block, CELL // 2, CELL - 1).alpha() == 0


def test_a_tall_thumbnail_is_pillarboxed_instead(qapp, tmp_path):
    tall = _thumbnail(tmp_path / "tall.png", (255, 0, 0), size=(40, 80))

    block = source_pixmap(Combination(tall), CELL)

    assert _color_at(block, CELL // 2, CELL // 2).red() > 200
    assert _color_at(block, 0, CELL // 2).alpha() == 0


def test_a_missing_file_is_no_thumbnail_rather_than_a_blank_one(qapp, tmp_path):
    assert source_pixmap(Combination(tmp_path / "gone.png"), CELL) is None, (
        "a start frame can have moved and a thumbnail can be half written: neither is a fault")
    assert source_pixmap(Combination(), CELL) is None


def test_a_combine_draws_the_frame_then_its_source_video_in_gray(qapp, tmp_path):
    frame = _thumbnail(tmp_path / "frame.png", (255, 0, 0))
    video = _thumbnail(tmp_path / "source.png", (0, 0, 255))

    block = source_pixmap(Combination(frame, video), CELL)

    lead = _color_at(block, _middle_of_cell(0), CELL // 2)
    assert lead.red() > 200
    assert lead.blue() < 60
    follow = _color_at(block, _middle_of_cell(1), CELL // 2)
    assert follow.red() == follow.green() == follow.blue(), (
        "gray because it is not what is being made: in full color the row reads as a job that is "
        "that video")


def _source_video_columns(block, video):
    drained = fitted_cell(video, CELL, gray=True).toImage().pixelColor(CELL // 2, CELL // 2)
    image = block.toImage()
    return [x for x in range(image.width()) if image.pixelColor(x, CELL // 2) == drained]


def test_a_combine_row_puts_a_plus_between_the_frame_and_its_source_video(qapp, tmp_path):
    frame = _thumbnail(tmp_path / "frame.png", (255, 0, 0))
    video = _thumbnail(tmp_path / "source.png", (0, 0, 255))

    block = source_pixmap(Combination(frame, video), CELL)

    assert _painted(block.toImage(), CELL, _source_video_columns(block, video)[0])


def test_a_source_video_keeps_its_cell_when_the_frame_has_not_rendered(qapp, tmp_path):
    video = _thumbnail(tmp_path / "source.png", (0, 0, 255))

    block = source_pixmap(Combination(tmp_path / "not-yet.png", video), CELL)

    assert _color_at(block, _middle_of_cell(0), CELL // 2).alpha() == 0, (
        "each keeps its own cell, so the two read as one column down the line: a frame that has "
        "not landed does not move the source video into its place")
    follow = _color_at(block, _middle_of_cell(1), CELL // 2)
    assert follow.blue() > 0
    assert follow.red() == follow.blue()


def test_a_source_video_whose_prompt_was_edited_stands_in_parentheses_on_its_row(qapp, tmp_path):
    frame = _thumbnail(tmp_path / "frame.png", (255, 0, 0))
    video = _thumbnail(tmp_path / "source.png", (0, 0, 255))
    as_made = source_pixmap(Combination(frame, video), CELL)
    edited = source_pixmap(Combination(frame, video, prompt_edited=True), CELL)

    made_at, edited_at = _source_video_columns(as_made, video), _source_video_columns(edited, video)

    assert edited_at[0] > made_at[0]
    assert _painted(edited.toImage(), made_at[0], edited_at[0])
    assert _painted(edited.toImage(), edited_at[-1] + 1, block_width(CELL))


def _painted(image, left, right):
    return any(image.pixelColor(x, y).alpha() > 0
               for x in range(left, right) for y in range(image.height()))


def test_neither_half_on_disk_is_still_no_thumbnail(qapp, tmp_path):
    assert source_pixmap(Combination(tmp_path / "gone.png", tmp_path / "also-gone.png"),
                         CELL) is None


def test_the_thumbnails_lie_across_the_row_not_stacked(qapp, tmp_path):
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    paths = [_thumbnail(tmp_path / f"{i}.png", c) for i, c in enumerate(colors)]

    block = folder_pixmap(paths, CELL)

    assert (block.width(), block.height()) == (block_width(CELL), CELL), (
        "stacked two by two, each cell is half a row high and four read as one smudge")
    assert _color_at(block, _middle_of_cell(0), CELL // 2).red() > 200
    assert _color_at(block, _middle_of_cell(1), CELL // 2).green() > 200
    assert _color_at(block, _middle_of_cell(2), CELL // 2).blue() > 200
    fourth = _color_at(block, _middle_of_cell(3), CELL // 2)
    assert fourth.red() > 200
    assert fourth.green() > 200


def test_a_folder_view_keeps_its_empty_slots(qapp, tmp_path):
    one = _thumbnail(tmp_path / "only.png", (255, 0, 0))

    block = folder_pixmap([one], CELL)

    assert _color_at(block, _middle_of_cell(0), CELL // 2).red() > 200
    assert _color_at(block, _middle_of_cell(3), CELL // 2).alpha() > 0, (
        "drawn faint, an unfilled cell reads as a folder with room, not a thumbnail that failed to load")


def test_a_start_frame_leaves_the_rest_of_the_block_empty(qapp, tmp_path):
    frame = _thumbnail(tmp_path / "frame.png", (255, 0, 0))

    block = source_pixmap(Combination(frame), CELL)

    assert _color_at(block, _middle_of_cell(0), CELL // 2).red() > 200
    assert _color_at(block, _middle_of_cell(3), CELL // 2).alpha() == 0, (
        "a start frame's block has nothing missing from it")


def test_one_thumbnail_takes_the_same_width_as_four(qapp, tmp_path):
    frame = _thumbnail(tmp_path / "frame.png", (255, 0, 0))
    mates = [_thumbnail(tmp_path / f"m{i}.png", (0, 0, 255)) for i in range(4)]

    assert source_pixmap(Combination(frame), CELL).width() == folder_pixmap(mates, CELL).width(), (
        "so the text beside the block starts at the same place on every line, whether the block "
        "holds one thumbnail or four")


def test_a_folder_view_takes_the_first_four_and_stops(qapp, tmp_path):
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255)]
    paths = [_thumbnail(tmp_path / f"{i}.png", c) for i, c in enumerate(colors)]

    block = folder_pixmap(paths, CELL)

    assert len(paths) > FOLDER_CELLS
    last = _color_at(block, _middle_of_cell(3), CELL // 2)
    assert last.blue() < 60


def test_a_scaled_cell_is_only_ever_read_off_disk_once(qapp, tmp_path, monkeypatch):
    thumbnail = _thumbnail(tmp_path / "a.png", (255, 0, 0))
    queue_thumbs._CELLS.clear()
    source_pixmap(Combination(thumbnail), CELL)

    reads = []
    monkeypatch.setattr(queue_thumbs, "_fitted",
                        lambda *a: reads.append(a) or None)
    again = source_pixmap(Combination(thumbnail), CELL)

    assert reads == [], (
        "the queue redraws at every poll, and a start frame is a full-size render")
    assert again is not None


def test_the_cells_held_stop_at_a_bound_letting_go_of_the_longest_unused(
        qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(queue_thumbs, "_MOST_CELLS", 2)
    queue_thumbs._CELLS.clear()
    a, b, c = (_thumbnail(tmp_path / f"{name}.png", (255, 0, 0)) for name in "abc")
    for path in (a, b, a, c):
        fitted_cell(path, CELL)

    reads = []
    monkeypatch.setattr(queue_thumbs, "_fitted",
                        lambda *args: reads.append(args[0]) or None)
    for path in (a, c, b):
        fitted_cell(path, CELL)

    assert len(reads) == 1, (
        "the seed dropdown draws a cell for every seed scrolled past, "
        "which over a session can be the whole library")


def test_a_cell_follows_a_file_re_rendered_in_place(qapp, tmp_path):
    thumbnail = _thumbnail(tmp_path / "a.png", (255, 0, 0))
    queue_thumbs._CELLS.clear()
    assert _color_at(source_pixmap(Combination(thumbnail), CELL), CELL // 2, CELL // 2).red() > 200

    _thumbnail(tmp_path / "a.png", (0, 0, 255))
    later = os.stat(thumbnail).st_mtime_ns + 2_000_000_000
    os.utime(thumbnail, ns=(later, later))

    assert _color_at(source_pixmap(Combination(thumbnail), CELL), CELL // 2, CELL // 2).blue() > 200


def test_an_unchanged_push_costs_the_block_nothing(qtbot, tmp_path):
    thumbs = QueueThumbs(CELL)
    qtbot.addWidget(thumbs)
    folder = [_thumbnail(tmp_path / "f.png", (0, 0, 255))]
    thumbs.show_folder(folder)
    first = thumbs.pixmap()

    thumbs.show_folder(folder)

    assert thumbs.pixmap() is first or thumbs.pixmap().cacheKey() == first.cacheKey(), (
        "the queue hands every row a fresh reading at every poll")


def test_a_source_frame_that_is_not_on_disk_yet_leaves_the_block_to_the_folder(
        qtbot, tmp_path):
    thumbs = QueueThumbs(CELL)
    qtbot.addWidget(thumbs)

    assert thumbs.show_source(Combination(str(tmp_path / "not-yet.png"))) is False
    assert thumbs.show_source(Combination()) is False


def test_a_block_with_nothing_to_show_leaves_the_row(qtbot, tmp_path):
    thumbs = QueueThumbs(CELL)
    qtbot.addWidget(thumbs)
    thumbs.show_folder([_thumbnail(tmp_path / "f.png", (0, 0, 255))])

    thumbs.clear_block()

    assert thumbs.isHidden(), "an empty block would say there was a thumbnail to show"


def test_the_block_never_eats_the_rows_click(qtbot):
    thumbs = QueueThumbs(CELL)
    qtbot.addWidget(thumbs)

    assert thumbs.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
