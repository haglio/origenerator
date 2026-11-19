from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock

from PIL import Image
from PySide6.QtCore import QRect

from origenerator.gui import omnipause
from origenerator.gui.contact_sheet import ContactSheet, row_counts, rows_for
from origenerator.gui.video_surface import VideoSurface
from origenerator.media import MediaType, ShownFile
from tests.media_files import write_mp4

SQUARE = 1.0


def _thumbnail(path, color=(200, 40, 40), size=(16, 12)):
    Image.new("RGB", size, color).save(path)
    return str(path)


def _show_images(sheet, paths):
    sheet.show_files([ShownFile(path, MediaType.IMAGE) for path in paths])


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
    _show_images(sheet, [_thumbnail(tmp_path / f"p{n}.png") for n in range(6)])

    assert sheet.count() == 6
    assert len(sheet.cells()) == 6


def test_two_landscape_thumbnails_are_stacked_into_two_landscape_halves(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    _show_images(sheet, [_thumbnail(tmp_path / f"p{n}.png", size=(32, 18)) for n in range(2)])

    assert [(c.width(), c.height()) for c in sheet.cells()] == [(400, 150), (400, 150)]


def test_two_portrait_thumbnails_stand_side_by_side_in_two_portrait_halves(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    _show_images(sheet, [_thumbnail(tmp_path / f"p{n}.png", size=(18, 32)) for n in range(2)])

    assert [(c.width(), c.height()) for c in sheet.cells()] == [(200, 300), (200, 300)]


def test_a_thumbnail_the_library_has_moved_is_left_out_rather_than_drawn_as_a_gap(
        qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    _show_images(sheet, [_thumbnail(tmp_path / "here.png"), str(tmp_path / "gone.png"), None])

    assert sheet.count() == 1


def test_the_tiles_fill_the_pane_edge_to_edge(qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    _show_images(sheet, [_thumbnail(tmp_path / f"p{n}.png") for n in range(5)])

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
    _show_images(sheet, [_thumbnail(tmp_path / "p.png")])

    sheet.clear()

    assert sheet.count() == 0
    assert sheet.cells() == []


def _banded(path, size):
    width, height = size
    image = Image.new("RGB", size, (200, 40, 40))
    image.paste((40, 40, 200), (0, 0, width, height // 10))
    image.paste((40, 200, 40), (0, height - height // 10, width, height))
    image.save(path)
    return str(path)


def _near(color, rgb) -> bool:
    return max(abs(a - b) for a, b in zip((color.red(), color.green(), color.blue()), rgb, strict=True)) < 40


def test_a_portrait_item_alone_on_a_landscape_sheet_is_drawn_whole_in_its_own_shape(
        qtbot, tmp_path):
    sheet = ContactSheet()
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    _show_images(sheet, [_banded(tmp_path / "tall.png", (90, 160))])

    drawn = sheet.grab().toImage()

    assert (_near(drawn.pixelColor(200, 4), (40, 40, 200)),
            _near(drawn.pixelColor(200, 296), (40, 200, 40)),
            _near(drawn.pixelColor(200, 150), (200, 40, 40)),
            _near(drawn.pixelColor(20, 150), (200, 40, 40))) == (True, True, True, False)


# The real Qt Multimedia backend deadlocks at session shutdown once a player has started
def _sheet_of_players(qtbot):
    players = []

    def make_player(_parent):
        players.append(MagicMock())
        return players[-1]

    sheet = ContactSheet(make_player=make_player)
    qtbot.addWidget(sheet)
    sheet.resize(400, 300)
    return sheet, players


def test_a_video_on_the_sheet_plays_its_own_file_whole_in_its_own_shape(qtbot, tmp_path):
    video = str(write_mp4(tmp_path / "tall.mp4", width=90, height=160))
    sheet, players = _sheet_of_players(qtbot)

    sheet.show_files([ShownFile(video, MediaType.VIDEO, _thumbnail(tmp_path / "tall.jpg",
                                                                   size=(90, 160)))])

    [player] = players
    [surface] = sheet.findChildren(VideoSurface)
    assert (Path(player.setSource.call_args.args[0].toLocalFile()), player.play.called,
            player.setVideoOutput.call_args.args[0] is surface.video_sink(),
            surface.geometry()) == (Path(video), True, True, QRect(116, 0, 168, 300))


def _playing_a_video(qtbot, tmp_path):
    video = write_mp4(tmp_path / "wide.mp4", width=32, height=18)
    sheet, players = _sheet_of_players(qtbot)
    sheet.show_files([ShownFile(str(video), MediaType.VIDEO)])
    return sheet, players[0]


def test_clearing_the_sheet_lets_go_of_its_videos_so_they_can_be_thrown_away(qtbot, tmp_path):
    sheet, player = _playing_a_video(qtbot, tmp_path)

    sheet.clear()

    assert (player.stop.called, player.setSource.call_args.args[0].isEmpty(),
            player.setVideoOutput.call_args.args[0], sheet.count()) == (True, True, None, 0)


def test_the_videos_on_the_sheet_pause_and_play_with_the_whole_room(qtbot, tmp_path):
    _sheet, player = _playing_a_video(qtbot, tmp_path)
    player.reset_mock()

    omnipause.freeze(True)
    try:
        paused = (player.pause.called, player.play.called)
    finally:
        omnipause.freeze(False)

    assert (paused, player.play.called) == ((True, False), True)
