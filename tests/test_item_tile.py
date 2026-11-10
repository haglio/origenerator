from __future__ import annotations

import time
from io import BytesIO

from PIL import Image
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QEnterEvent, QMovie
from shared_ui.colors import BLUE, TEXT_PRIMARY

from origenerator.gui import corner_buttons, drag_thumbnail, icons, omnipause
from origenerator.gui.corner_buttons import CORNER_INSET
from origenerator.gui.gallery_pane import REROLL_IMAGE, REROLL_VIDEO
from origenerator.gui.inflight import RunReading
from origenerator.gui.item_tile import CornerButton, ItemTile, TileAppearance
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.media import MediaType
from tests.heard_drags import HeardDrags
from tests.tile_drawing import drawn_under_the_app_stylesheet


def _corners(tile):
    return tile._controls.buttons()


def _corner_button_specs():
    return [
        CornerButton(REROLL_VIDEO, icons.reroll_seed_icon(MediaType.VIDEO),
                     "Randomize video seed"),
        CornerButton(REROLL_IMAGE, icons.reroll_seed_icon(MediaType.IMAGE),
                     "Randomize image seed"),
    ]


def _write_looping_webp(path, size=(64, 48)):
    frames = [Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return path


def test_video_thumbnail_plays_a_looping_movie(qtbot, tmp_path):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    tw = ItemTile("v1", None, "label", TileAppearance(movie_path=str(webp)))
    qtbot.addWidget(tw)
    movies = tw.findChildren(QMovie)
    assert len(movies) == 1
    assert movies[0].state() == QMovie.MovieState.Running


def test_thumbnail_without_a_movie_path_stays_a_still(qtbot, tmp_path):
    still = tmp_path / "i1.jpg"
    Image.new("RGB", (64, 48), (0, 0, 255)).save(still)
    tw = ItemTile("i1", str(still), "label")
    qtbot.addWidget(tw)
    assert tw.findChildren(QMovie) == []
    assert tw._image_label.pixmap() is not None
    assert not tw._image_label.pixmap().isNull()


def test_missing_movie_file_falls_back_to_the_still(qtbot, tmp_path):
    still = tmp_path / "i1.jpg"
    Image.new("RGB", (64, 48), (0, 0, 255)).save(still)
    tw = ItemTile("v1", str(still), "label", TileAppearance(movie_path=str(tmp_path / "gone.webp")))
    qtbot.addWidget(tw)
    assert tw.findChildren(QMovie) == []
    assert not tw._image_label.pixmap().isNull()


class _RecordingDrag:
    last = None

    def __init__(self, source):
        self.pixmap = None
        _RecordingDrag.last = self

    def setMimeData(self, mime):
        self.mime = mime

    def setPixmap(self, pixmap):
        self.pixmap = pixmap

    def exec(self, _action):
        return None


def _drag_out(qtbot, tw):
    qtbot.mousePress(tw, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(tw, QPoint(120, 120))


def test_a_dragged_still_trails_its_thumbnail(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(drag_thumbnail, "QDrag", _RecordingDrag)
    _RecordingDrag.last = None
    still = tmp_path / "i1.jpg"
    Image.new("RGB", (64, 48), (0, 0, 255)).save(still)
    tw = ItemTile("i1", str(still), "label")
    qtbot.addWidget(tw)

    _drag_out(qtbot, tw)

    assert _RecordingDrag.last.pixmap is not None
    assert not _RecordingDrag.last.pixmap.isNull()


def test_a_dragged_video_trails_the_frame_it_is_playing(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(drag_thumbnail, "QDrag", _RecordingDrag)
    _RecordingDrag.last = None
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    tw = ItemTile("v1", None, "label", TileAppearance(movie_path=str(webp)))
    qtbot.addWidget(tw)

    _drag_out(qtbot, tw)

    assert _RecordingDrag.last.pixmap is not None
    assert not _RecordingDrag.last.pixmap.isNull()


def test_a_dragged_tile_with_no_preview_trails_nothing(qtbot, monkeypatch):
    monkeypatch.setattr(drag_thumbnail, "QDrag", _RecordingDrag)
    _RecordingDrag.last = None
    tw = ItemTile("p1", None, "label")
    qtbot.addWidget(tw)
    heard = HeardDrags()

    _drag_out(qtbot, tw)

    assert heard.generations() == ["p1"]
    assert _RecordingDrag.last.pixmap is None


def test_a_left_click_picks_and_opens_the_image_and_a_right_click_does_neither(qtbot):
    tw = ItemTile("p1", None, "label")
    qtbot.addWidget(tw)
    picked, opened = [], []
    tw.pressed.connect(lambda prompt_id, _keys: picked.append(prompt_id))
    tw.clicked.connect(opened.append)

    qtbot.mouseClick(tw, Qt.MouseButton.RightButton)
    assert picked == opened == []

    qtbot.mouseClick(tw, Qt.MouseButton.LeftButton)
    assert picked == opened == ["p1"]


def test_a_press_reports_the_keys_held_during_it(qtbot):
    tw = ItemTile("p1", None, "label")
    qtbot.addWidget(tw)
    held = []
    tw.pressed.connect(lambda prompt_id, modifiers: held.append(modifiers))

    qtbot.mouseClick(tw, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier)

    assert held == [Qt.KeyboardModifier.ControlModifier]


def test_double_click_emits_double_clicked_for_left_button_only(qtbot):
    tw = ItemTile("p1", None, "label")
    qtbot.addWidget(tw)
    dbl = []
    tw.double_clicked.connect(dbl.append)

    qtbot.mouseDClick(tw, Qt.MouseButton.RightButton)
    assert dbl == []

    qtbot.mouseDClick(tw, Qt.MouseButton.LeftButton)
    assert dbl == ["p1"]


def test_right_click_requests_a_context_menu_for_this_thumbnail(qtbot):
    tw = ItemTile("p1", None, "label")
    qtbot.addWidget(tw)
    received = []
    tw.context_requested.connect(lambda pid, pos: received.append(pid))

    tw.customContextMenuRequested.emit(QPoint(5, 5))

    assert received == ["p1"]


def test_item_type_icon_appears_only_when_a_type_is_given(qtbot):
    plain = ItemTile("p1", None, "label")
    qtbot.addWidget(plain)
    assert plain.findChildren(ItemTypeIcon) == []
    typed = ItemTile("p2", None, "label", TileAppearance(media_type=MediaType.VIDEO))
    qtbot.addWidget(typed)
    assert len(typed.findChildren(ItemTypeIcon)) == 1


def test_no_corner_buttons_by_default(qtbot):
    tw = ItemTile("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw._corner_buttons == []


def test_corner_buttons_build_hidden_buttons_with_tooltips(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(corner_buttons=_corner_button_specs()))
    qtbot.addWidget(tw)
    assert [b.toolTip() for b in tw._corner_buttons] == [
        "Randomize video seed", "Randomize image seed",
    ]
    assert all(b.isHidden() for b in tw._corner_buttons)


def test_corner_buttons_reveal_on_hover_and_hide_when_the_cursor_leaves(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(corner_buttons=_corner_button_specs()))
    qtbot.addWidget(tw)
    pos = QPointF(1, 1)

    tw.enterEvent(QEnterEvent(pos, pos, pos))
    assert all(not b.isHidden() for b in tw._corner_buttons)

    tw._cursor_over_tile = lambda: False
    tw.leaveEvent(QEvent(QEvent.Type.Leave))
    assert all(b.isHidden() for b in tw._corner_buttons)


def test_corner_buttons_stay_up_while_the_cursor_is_on_a_button(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(corner_buttons=_corner_button_specs()))
    qtbot.addWidget(tw)
    pos = QPointF(1, 1)
    tw.enterEvent(QEnterEvent(pos, pos, pos))

    tw._cursor_over_tile = lambda: True
    tw.leaveEvent(QEvent(QEvent.Type.Leave))
    assert all(not b.isHidden() for b in tw._corner_buttons)


def test_corner_action_click_emits_the_prompt_id_and_action_id(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(corner_buttons=_corner_button_specs()))
    qtbot.addWidget(tw)
    fired = []
    tw.corner_button_triggered.connect(lambda pid, aid: fired.append((pid, aid)))

    tw._corner_buttons[1].click()

    assert fired == [("p1", REROLL_IMAGE)]


def test_every_corner_of_a_tile_is_up_at_rest(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhance=icons.ENHANCE_OPEN))
    qtbot.addWidget(tw)
    assert all(not b.isHidden() for b in _corners(tw)), (
        "the corners are not revealed on hover: each reacts to the cursor on itself, and a "
        "control that only appears once the tile is swept is one the user has to go looking for")


def test_a_favorite_tile_shows_it_in_the_favorite(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(favorite=True))
    qtbot.addWidget(tw)
    star, trash, _plus = _corners(tw)
    assert tw._favorite is True
    assert not star.isHidden()
    assert not trash.isHidden()


def test_an_enhanced_tile_keeps_its_plus_up_and_says_it_is_spent(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhance=icons.ENHANCE_HELD))
    qtbot.addWidget(tw)
    _star, _trash, plus = _corners(tw)
    assert not plus.isHidden()
    assert not plus.isEnabled()


def test_an_enhanced_tile_that_could_take_another_offers_one(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhance=icons.ENHANCE_MORE))
    qtbot.addWidget(tw)
    _star, _trash, plus = _corners(tw)
    assert not plus.isHidden()
    assert plus.isEnabled()


def test_a_video_tile_grows_no_plus_at_all(qtbot):
    tw = ItemTile("v1", None, "label", TileAppearance(enhance=None))
    qtbot.addWidget(tw)
    _star, _trash, plus = _corners(tw)
    assert plus.isHidden()


def test_the_corners_ignore_the_cursor_crossing_the_tile(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhance=icons.ENHANCE_OPEN))
    qtbot.addWidget(tw)
    pos = QPointF(1, 1)
    tw.enterEvent(QEnterEvent(pos, pos, pos))
    assert all(not b.isHidden() for b in _corners(tw))

    tw._cursor_over_tile = lambda: False
    tw.leaveEvent(QEvent(QEvent.Type.Leave))

    assert all(not b.isHidden() for b in _corners(tw))


def test_set_enhance_re_reads_the_plus_without_a_rebuild(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhance=icons.ENHANCE_HELD))
    qtbot.addWidget(tw)
    plus = _corners(tw)[2]
    assert not plus.isEnabled()

    tw.set_enhance(icons.ENHANCE_MORE)

    assert tw.enhance_state() == icons.ENHANCE_MORE
    assert plus.isEnabled(), (
        "a turn of the Enhance pane's settings does this to every item on screen at once")


def test_a_corner_control_click_names_the_tile_and_the_act(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhance=icons.ENHANCE_OPEN))
    qtbot.addWidget(tw)
    fired = []
    tw.control_triggered.connect(lambda pid, action: fired.append((pid, action)))

    for button in _corners(tw):
        button.click()

    assert fired == [("p1", corner_buttons.STAR), ("p1", corner_buttons.TRASH),
                     ("p1", corner_buttons.ENHANCE)]


def test_the_corners_sit_one_to_a_corner_of_the_thumbnail(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(favorite=True,
                         enhance=icons.ENHANCE_HELD, media_type=MediaType.IMAGE))
    qtbot.addWidget(tw)
    star, trash, plus = (b.geometry() for b in _corners(tw))
    area = tw._image_label.geometry()
    for corner in (star, trash, plus):
        assert area.contains(corner)
    assert star.left() > area.center().x()
    assert star.top() < area.center().y()
    assert trash.left() < area.center().x()
    assert trash.top() > area.center().y()
    assert plus.left() > area.center().x()
    assert plus.top() > area.center().y()
    (icon,) = tw.findChildren(ItemTypeIcon)
    assert icon.x() < tw.width() // 2
    assert icon.y() < tw.height() // 2
    for corner in (star, trash, plus):
        assert icon.geometry().intersected(corner).isEmpty()


def test_an_enhancing_tile_keeps_its_star_trash_and_plus(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(favorite=True,
                         enhance=icons.ENHANCE_OPEN, enhancing=_run()))
    qtbot.addWidget(tw)

    assert all(not b.isHidden() and b.isEnabled() for b in _corners(tw))


def test_a_collections_own_actions_keep_the_top_left_edge_to_themselves(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhance=icons.ENHANCE_OPEN,
                         corner_buttons=_corner_button_specs()))
    qtbot.addWidget(tw)
    assert tw._corner_buttons[0].x() == tw._image_label.x() + CORNER_INSET
    for button in tw._corner_buttons:
        for corner in _corners(tw):
            assert corner.geometry().intersected(button.geometry()).isEmpty()


def test_thumbnail_starts_unselected(qtbot):
    tw = ItemTile("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw._selected is False
    assert tw.styleSheet() == ""


def _picked_tile_drawn_under_the_app_stylesheet(qtbot):
    def build():
        tw = ItemTile("p1", None, "caption")
        tw.resize(180, 200)
        tw.set_selected(True)
        return tw, tw

    return drawn_under_the_app_stylesheet(qtbot, build)


def test_selecting_fills_the_whole_tile_with_the_familys_blue(qtbot):
    _tile, img = _picked_tile_drawn_under_the_app_stylesheet(qtbot)

    assert img.pixelColor(8, 8) == BLUE
    assert img.pixelColor(8, 182) == BLUE


def test_a_picked_tiles_thumbnail_wears_a_white_frame(qtbot):
    tile, img = _picked_tile_drawn_under_the_app_stylesheet(qtbot)
    area = tile._image_label.geometry()

    assert img.pixelColor(area.left(), area.center().y()) == TEXT_PRIMARY


def test_a_looping_tile_can_be_held_still(qtbot, tmp_path):
    webp = tmp_path / "loop.webp"
    Image.new("RGB", (40, 30)).save(webp)
    tile = ItemTile("p1", None, "a clip", TileAppearance(movie_path=str(webp)))
    qtbot.addWidget(tile)
    movie = tile._image_label.movie()
    assert movie is not None

    omnipause.freeze(True)
    assert movie.state() == QMovie.MovieState.Paused

    later = ItemTile("p3", None, "a clip", TileAppearance(movie_path=str(webp)))
    qtbot.addWidget(later)
    assert later._image_label.movie().state() == QMovie.MovieState.Paused, (
        "held app-wide, not tile by tile: a paused room with the gallery in it must not be a wall "
        "of videos still playing, the ones started since included")

    omnipause.freeze(False)
    assert movie.state() == QMovie.MovieState.Running
    assert later._image_label.movie().state() == QMovie.MovieState.Running


def _run(**kw):
    base = {"status": "running", "frame": None}
    base.update(kw)
    return RunReading(**base)


def _png_bytes(color=(30, 90, 160)):
    buf = BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


def test_a_resting_tile_wears_neither_overlay(qtbot):
    tw = ItemTile("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw._enhancing is None
    assert tw._status_scrim.isHidden()
    assert tw._enhancing_bar.isHidden()


def test_an_enhancing_tile_says_so_over_the_thumbnail_and_on_a_bar(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhancing=_run(
        progress=(10, 20), started_at=time.time() - 90.5, typical_seconds=725.0)))
    qtbot.addWidget(tw)

    assert tw._enhancing is not None
    assert tw._status_scrim.text() == "Enhancing…"
    assert tw._enhancing_bar.caption() == "50% · ~6:02 left"
    assert (tw._enhancing_bar.value(), tw._enhancing_bar.maximum()) == (10, 20)


def test_the_fix_being_applied_gets_the_band_under_the_run_s_own_reading(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhancing=_run(
        progress=(45, 60), pass_progress=(5, 20))))
    qtbot.addWidget(tw)

    assert (tw._enhancing_bar.value(), tw._enhancing_bar.maximum()) == (45, 60)
    assert tw._enhancing_bar.pass_progress() == (5, 20), (
        "an enhancement with fixes is several passes; the bar is the whole of it, and the substep "
        "progress bar along its foot is the fix in hand, the reading that starts over")


def test_an_enhance_still_queued_draws_no_band(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhancing=_run(
        status="queued", progress=(45, 60), pass_progress=(5, 20))))
    qtbot.addWidget(tw)

    assert tw._enhancing_bar.pass_progress() is None


def test_the_bar_sits_along_the_foot_of_the_thumbnail(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhancing=_run()))
    qtbot.addWidget(tw)
    area, bar = tw._image_label.geometry(), tw._enhancing_bar.geometry()

    assert area.contains(bar)
    assert bar.top() > area.center().y()
    assert tw.size() == ItemTile("p2", None, "label").size()


def test_an_enhancing_tiles_bar_leaves_its_lower_corners_clear(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhance=icons.ENHANCE_OPEN,
                         enhancing=_run()))
    qtbot.addWidget(tw)
    _star, trash, plus = _corners(tw)
    bar = tw._enhancing_bar.geometry()

    assert bar.intersected(trash.geometry()).isEmpty()
    assert bar.intersected(plus.geometry()).isEmpty()


def test_an_enhancing_tiles_corners_are_drawn_over_its_scrim(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhance=icons.ENHANCE_OPEN,
                         enhancing=_run()))
    qtbot.addWidget(tw)

    tw.set_enhancing(_run(frame=_png_bytes()))

    order = tw.children()
    for corner in _corners(tw):
        assert order.index(corner) > order.index(tw._status_scrim)


def test_an_enhance_still_queued_leaves_the_bar_sweeping(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhancing=_run(status="queued", progress=(0, 0))))
    qtbot.addWidget(tw)

    assert tw._enhancing_bar.caption() == ""
    assert tw._enhancing_bar.maximum() == 0
    assert not tw._enhancing_tick.isActive(), (
        "ticking a queued run would only redraw a line that cannot change")


def test_a_fresh_run_updates_the_overlays_in_place(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhancing=_run(status="queued")))
    qtbot.addWidget(tw)

    tw.set_enhancing(_run(progress=(5, 20), started_at=time.time() - 30.5,
                          typical_seconds=100.0))

    assert tw._enhancing_bar.caption().startswith("25% · ")
    assert tw._enhancing_tick.isActive()


def test_the_clock_advances_between_polls(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhancing=_run(started_at=time.time() - 5.5,
                                        typical_seconds=100.0)))
    qtbot.addWidget(tw)
    assert tw._enhancing_bar.caption() == "~1:34 left"

    tw._enhancing.started_at -= 3
    tw._enhancing_tick.timeout.emit()
    assert tw._enhancing_bar.caption() == "~1:31 left"


def test_a_streamed_frame_paints_the_thumbnail_under_the_overlays(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhancing=_run()))
    qtbot.addWidget(tw)

    tw.set_enhancing(_run(frame=_png_bytes()))

    assert not tw._image_label.pixmap().isNull()
    assert tw._status_scrim.text() == "Enhancing…"
    assert not tw._enhancing_bar.isHidden()


def test_the_run_ending_puts_the_tiles_own_thumbnail_back(qtbot, tmp_path):
    thumbnail = tmp_path / "i1.png"
    thumbnail.write_bytes(_png_bytes(color=(200, 40, 40)))
    tw = ItemTile("p1", str(thumbnail), "label")
    qtbot.addWidget(tw)
    resting = tw._image_label.pixmap().toImage()
    tw.set_enhancing(_run(frame=_png_bytes()))
    assert tw._image_label.pixmap().toImage() != resting

    tw.set_enhancing(None)

    assert tw._image_label.pixmap().toImage() == resting, (
        "the frames streamed onto the tile were a partial render of a file that does not exist "
        "yet, so the tile shows its own thumbnail again once the run ends")


def test_the_run_ending_takes_both_overlays_away(qtbot):
    tw = ItemTile("p1", None, "label", TileAppearance(enhancing=_run(frame=_png_bytes())))
    qtbot.addWidget(tw)

    tw.set_enhancing(None)

    assert tw._enhancing is None
    assert tw._status_scrim.isHidden()
    assert tw._enhancing_bar.isHidden()
    assert not tw._enhancing_tick.isActive()
