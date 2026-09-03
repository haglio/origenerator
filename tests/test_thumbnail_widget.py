import time

from PIL import Image
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QColor, QEnterEvent, QMovie
from PyQt6.QtWidgets import QApplication

from origenerator.gui import corner_controls, icons, thumbnail_widget
from origenerator.gui.corner_controls import CORNER_INSET
from origenerator.gui.inflight import EnhancingRun
from origenerator.gui.media_badge import MediaBadge
from origenerator.gui.stylesheet import build_stylesheet
from PyQt6.QtGui import QMovie
from origenerator.gui.thumbnail_widget import ThumbnailWidget, _SELECTED_BG


def _corners(tile):
    """A tile's three corner controls, in the order they are laid out: the star,
    the trash can, the plus."""
    return tile._controls.buttons()


def _corner_actions():
    return [
        ("video", icons.reroll_seed_icon("video"), "Randomize video seed"),
        ("image", icons.reroll_seed_icon("image"), "Randomize image seed"),
    ]


def _write_looping_webp(path, size=(64, 48)):
    """A tiny two-frame looping WebP, the shape a video thumbnail animates."""
    frames = [Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return path


def test_video_thumbnail_plays_a_looping_movie(qtbot, tmp_path):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    tw = ThumbnailWidget("v1", None, "label", movie_path=str(webp))
    qtbot.addWidget(tw)
    movies = tw.findChildren(QMovie)
    assert len(movies) == 1
    assert movies[0].state() == QMovie.MovieState.Running  # animating, not paused


def test_thumbnail_without_a_movie_path_stays_a_still(qtbot, tmp_path):
    still = tmp_path / "i1.jpg"
    Image.new("RGB", (64, 48), (0, 0, 255)).save(still)
    tw = ThumbnailWidget("i1", str(still), "label")  # image row: no movie_path
    qtbot.addWidget(tw)
    assert tw.findChildren(QMovie) == []
    assert tw._image_label.pixmap() is not None and not tw._image_label.pixmap().isNull()


def test_missing_movie_file_falls_back_to_the_still(qtbot, tmp_path):
    still = tmp_path / "i1.jpg"
    Image.new("RGB", (64, 48), (0, 0, 255)).save(still)
    tw = ThumbnailWidget("v1", str(still), "label", movie_path=str(tmp_path / "gone.webp"))
    qtbot.addWidget(tw)
    assert tw.findChildren(QMovie) == []  # the WebP is gone; show the still instead
    assert not tw._image_label.pixmap().isNull()


class _RecordingDrag:
    """Stands in for QDrag, remembering the picture hung under the cursor."""

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
    """Press then travel far enough past the threshold to start a drag."""
    qtbot.mousePress(tw, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    qtbot.mouseMove(tw, QPoint(120, 120))


def test_a_dragged_still_trails_its_picture(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnail_widget, "QDrag", _RecordingDrag)
    _RecordingDrag.last = None
    still = tmp_path / "i1.jpg"
    Image.new("RGB", (64, 48), (0, 0, 255)).save(still)
    tw = ThumbnailWidget("i1", str(still), "label")
    qtbot.addWidget(tw)

    _drag_out(qtbot, tw)

    assert _RecordingDrag.last.pixmap is not None
    assert not _RecordingDrag.last.pixmap.isNull()


def test_a_dragged_video_trails_the_frame_it_is_playing(qtbot, tmp_path, monkeypatch):
    # A video tile shows a looping WebP, so its label has no pixmap of its own;
    # asked only for that, the drag used to trail nothing at all while an image
    # dragged from the tile beside it trailed a picture.
    monkeypatch.setattr(thumbnail_widget, "QDrag", _RecordingDrag)
    _RecordingDrag.last = None
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    tw = ThumbnailWidget("v1", None, "label", movie_path=str(webp))
    qtbot.addWidget(tw)

    _drag_out(qtbot, tw)

    assert _RecordingDrag.last.pixmap is not None
    assert not _RecordingDrag.last.pixmap.isNull()


def test_a_dragged_tile_with_no_preview_trails_nothing(qtbot, monkeypatch):
    # No picture is the one case with nothing to show; the drag still goes.
    monkeypatch.setattr(thumbnail_widget, "QDrag", _RecordingDrag)
    _RecordingDrag.last = None
    tw = ThumbnailWidget("p1", None, "label")  # "No preview"
    qtbot.addWidget(tw)
    started = []
    tw.drag_started.connect(started.append)

    _drag_out(qtbot, tw)

    assert started == ["p1"]
    assert _RecordingDrag.last.pixmap is None


def test_left_click_emits_clicked_but_right_click_does_not(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    clicks = []
    tw.clicked.connect(clicks.append)

    qtbot.mouseClick(tw, Qt.MouseButton.RightButton)
    assert clicks == []  # right-click is for the menu; it must not re-select

    qtbot.mouseClick(tw, Qt.MouseButton.LeftButton)
    assert clicks == ["p1"]


def test_double_click_emits_double_clicked_for_left_button_only(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    dbl = []
    tw.double_clicked.connect(dbl.append)

    qtbot.mouseDClick(tw, Qt.MouseButton.RightButton)
    assert dbl == []  # a right double-click is not an "open" gesture

    qtbot.mouseDClick(tw, Qt.MouseButton.LeftButton)
    assert dbl == ["p1"]


def test_right_click_requests_a_context_menu_for_this_thumbnail(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    received = []
    tw.context_requested.connect(lambda pid, pos: received.append(pid))

    # What a right-click on the tile triggers (custom context-menu policy).
    tw.customContextMenuRequested.emit(QPoint(5, 5))

    assert received == ["p1"]


def test_media_badge_appears_only_when_a_type_is_given(qtbot):
    # Inside a single-type folder the kind is obvious, so a bare tile wears none...
    plain = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(plain)
    assert plain.findChildren(MediaBadge) == []
    # ...but a Recents tile, which mixes kinds, is told its type and shows a badge.
    badged = ThumbnailWidget("p2", None, "label", media_type="video")
    qtbot.addWidget(badged)
    assert len(badged.findChildren(MediaBadge)) == 1


def test_no_corner_actions_by_default(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw._corner_buttons == []


def test_corner_actions_build_hidden_buttons_with_tooltips(qtbot):
    tw = ThumbnailWidget("p1", None, "label", corner_actions=_corner_actions())
    qtbot.addWidget(tw)
    assert [b.toolTip() for b in tw._corner_buttons] == [
        "Randomize video seed", "Randomize image seed",
    ]
    assert all(b.isHidden() for b in tw._corner_buttons)  # revealed only on hover


def test_corner_actions_reveal_on_hover_and_hide_when_the_cursor_leaves(qtbot):
    tw = ThumbnailWidget("p1", None, "label", corner_actions=_corner_actions())
    qtbot.addWidget(tw)
    pos = QPointF(1, 1)

    tw.enterEvent(QEnterEvent(pos, pos, pos))
    assert all(not b.isHidden() for b in tw._corner_buttons)

    tw._cursor_over_tile = lambda: False  # the cursor has truly left the tile
    tw.leaveEvent(QEvent(QEvent.Type.Leave))
    assert all(b.isHidden() for b in tw._corner_buttons)


def test_corner_actions_stay_up_while_the_cursor_is_on_a_button(qtbot):
    # Moving onto a corner button fires the tile's leaveEvent; the buttons must
    # stay up (else they'd vanish under the cursor — a hover/hide flicker loop).
    tw = ThumbnailWidget("p1", None, "label", corner_actions=_corner_actions())
    qtbot.addWidget(tw)
    pos = QPointF(1, 1)
    tw.enterEvent(QEnterEvent(pos, pos, pos))

    tw._cursor_over_tile = lambda: True  # still within the tile (over a button)
    tw.leaveEvent(QEvent(QEvent.Type.Leave))
    assert all(not b.isHidden() for b in tw._corner_buttons)


def test_corner_action_click_emits_the_prompt_id_and_action_id(qtbot):
    tw = ThumbnailWidget("p1", None, "label", corner_actions=_corner_actions())
    qtbot.addWidget(tw)
    fired = []
    tw.corner_action_triggered.connect(lambda pid, aid: fired.append((pid, aid)))

    tw._corner_buttons[1].click()

    assert fired == [("p1", "image")]  # carries the tile's id and the chosen action


# --- the three corner controls ------------------------------------------------

def test_every_corner_of_a_tile_is_up_at_rest(qtbot):
    # They are not hover-revealed: each reacts to the cursor on itself, and a
    # control that only appears once you sweep the tile is one you have to go
    # looking for.
    tw = ThumbnailWidget("p1", None, "label", enhance=icons.ENHANCE_OPEN)
    qtbot.addWidget(tw)
    assert all(not b.isHidden() for b in _corners(tw))


def test_a_starred_tile_shows_it_in_the_star(qtbot):
    tw = ThumbnailWidget("p1", None, "label", starred=True)
    qtbot.addWidget(tw)
    star, trash, _plus = _corners(tw)
    assert tw._starred is True
    assert not star.isHidden() and not trash.isHidden()


def test_an_enhanced_tile_keeps_its_plus_up_and_says_it_is_spent(qtbot):
    # Holding the very version the panel describes is a finished statement, not
    # an offer: pressing would spend a generation arriving at the picture already
    # there, so the plus reports and does not act.
    tw = ThumbnailWidget("p1", None, "label", enhance=icons.ENHANCE_HELD)
    qtbot.addWidget(tw)
    _star, _trash, plus = _corners(tw)
    assert not plus.isHidden()
    assert not plus.isEnabled()


def test_an_enhanced_tile_that_could_take_another_offers_one(qtbot):
    tw = ThumbnailWidget("p1", None, "label", enhance=icons.ENHANCE_MORE)
    qtbot.addWidget(tw)
    _star, _trash, plus = _corners(tw)
    assert not plus.isHidden() and plus.isEnabled()


def test_a_video_tile_grows_no_plus_at_all(qtbot):
    # There is no video enhancer, so the corner has nothing to offer or report.
    tw = ThumbnailWidget("v1", None, "label", enhance=None)
    qtbot.addWidget(tw)
    _star, _trash, plus = _corners(tw)
    assert plus.isHidden()


def test_the_corners_ignore_the_cursor_crossing_the_tile(qtbot):
    # Hovering the tile reveals a shelf's own actions and nothing else — the
    # three corners were already up and stay up.
    tw = ThumbnailWidget("p1", None, "label", enhance=icons.ENHANCE_OPEN)
    qtbot.addWidget(tw)
    pos = QPointF(1, 1)
    tw.enterEvent(QEnterEvent(pos, pos, pos))
    assert all(not b.isHidden() for b in _corners(tw))

    tw._cursor_over_tile = lambda: False
    tw.leaveEvent(QEvent(QEvent.Type.Leave))

    assert all(not b.isHidden() for b in _corners(tw))


def test_set_enhance_re_reads_the_plus_without_a_rebuild(qtbot):
    # A knob turned on the Enhance panel changes what every picture on screen
    # would get from a press, and none of those tiles were touched.
    tw = ThumbnailWidget("p1", None, "label", enhance=icons.ENHANCE_HELD)
    qtbot.addWidget(tw)
    plus = _corners(tw)[2]
    assert not plus.isEnabled()

    tw.set_enhance(icons.ENHANCE_MORE)

    assert tw.enhance_state() == icons.ENHANCE_MORE
    assert plus.isEnabled()


def test_a_corner_control_click_names_the_tile_and_the_act(qtbot):
    tw = ThumbnailWidget("p1", None, "label", enhance=icons.ENHANCE_OPEN)
    qtbot.addWidget(tw)
    fired = []
    tw.control_triggered.connect(lambda pid, action: fired.append((pid, action)))

    for button in _corners(tw):
        button.click()

    assert fired == [("p1", corner_controls.STAR), ("p1", corner_controls.TRASH),
                     ("p1", corner_controls.ENHANCE)]


def test_the_corners_sit_one_to_a_corner_of_the_picture(qtbot):
    # Star top-right, trash bottom-left, plus bottom-right — and the media badge
    # keeps the top-left it has always had, so all four can coexist.
    tw = ThumbnailWidget("p1", None, "label", starred=True,
                         enhance=icons.ENHANCE_HELD, media_type="image")
    qtbot.addWidget(tw)
    star, trash, plus = (b.geometry() for b in _corners(tw))
    picture = tw._image_label.geometry()
    for corner in (star, trash, plus):
        assert picture.contains(corner)
    assert star.left() > picture.center().x() and star.top() < picture.center().y()
    assert trash.left() < picture.center().x() and trash.top() > picture.center().y()
    assert plus.left() > picture.center().x() and plus.top() > picture.center().y()
    (badge,) = tw.findChildren(MediaBadge)
    assert badge.x() < tw.width() // 2 and badge.y() < tw.height() // 2
    for corner in (star, trash, plus):
        assert badge.geometry().intersected(corner).isEmpty()


def test_a_tile_with_a_run_cooking_on_it_drops_its_corners(qtbot):
    # The progress bar is laid along the picture's foot, right over two of them —
    # a control there would be a button nobody can see and everybody can press.
    tw = ThumbnailWidget("p1", None, "label", starred=True,
                         enhance=icons.ENHANCE_HELD, enhancing=_run())
    qtbot.addWidget(tw)
    assert all(b.isHidden() for b in _corners(tw))

    tw.set_enhancing(None)  # the run ends and the tile is an item again

    star, _trash, plus = _corners(tw)
    assert not star.isHidden() and not plus.isHidden()


def test_a_tile_can_decline_the_corner_controls_entirely(qtbot):
    # The Trash shelf's tiles: their item is already deleted, so there is nothing
    # to bookmark, bin or enhance, and their own two acts take the corners.
    tw = ThumbnailWidget("p1", None, "label", controls=False,
                         corner_actions=_corner_actions())
    qtbot.addWidget(tw)
    assert tw._controls is None


def test_a_shelfs_own_actions_keep_the_top_left_edge_to_themselves(qtbot):
    # Keep/reject (and the per-seed re-rolls) run along the edge the three corner
    # controls stay off, so neither set lands on the other.
    tw = ThumbnailWidget("p1", None, "label", enhance=icons.ENHANCE_OPEN,
                         corner_actions=_corner_actions())
    qtbot.addWidget(tw)
    assert tw._corner_buttons[0].x() == tw._image_label.x() + CORNER_INSET
    for button in tw._corner_buttons:
        for corner in _corners(tw):
            assert corner.geometry().intersected(button.geometry()).isEmpty()


def test_thumbnail_starts_unselected(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw.is_selected() is False
    assert tw.styleSheet() == ""  # no selection fill at rest


def test_selecting_lightens_the_whole_tile_behind_image_and_caption(qtbot):
    """The fill must reach behind the image and the caption, not just the margin.

    Rendered with the app stylesheet, which paints bare QLabels opaque — the
    exact reason an earlier fill showed only as a frame. Sampling real pixels
    (not the stylesheet string) is what catches that.
    """
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    try:
        tw = ThumbnailWidget("p1", None, "caption")
        qtbot.addWidget(tw)
        tw.resize(180, 200)
        tw.set_selected(True)
        tw.show()
        qtbot.waitExposed(tw)
        img = tw.grab().toImage()
        fill = QColor(_SELECTED_BG)
        assert img.pixelColor(8, 8) == fill     # behind the image
        assert img.pixelColor(8, 182) == fill    # behind the caption text
    finally:
        app.setStyleSheet(prior)


def test_a_looping_tile_can_be_held_still(qtbot, tmp_path):
    """The hosting session's OmniPause reaches these: a paused room with the
    gallery in it must not be a wall of clips still playing.

    Held app-wide rather than tile by tile — the tile has no switch of its own,
    because a switch per widget is how three of the four kinds of looping
    preview were missed (see origenerator.gui.looping_preview).
    """
    from origenerator.gui.looping_preview import set_previews_paused
    webp = tmp_path / "loop.webp"
    Image.new("RGB", (40, 30)).save(webp)
    tile = ThumbnailWidget("p1", None, "a clip", movie_path=str(webp))
    qtbot.addWidget(tile)
    movie = tile._image_label.movie()
    assert movie is not None

    set_previews_paused(True)
    assert movie.state() == QMovie.MovieState.Paused

    # And a tile BUILT during the freeze comes up already held: the grid is
    # rebuilt constantly, and a rebuild mid-pause used to start it moving again.
    later = ThumbnailWidget("p3", None, "a clip", movie_path=str(webp))
    qtbot.addWidget(later)
    assert later._image_label.movie().state() == QMovie.MovieState.Paused

    set_previews_paused(False)
    assert movie.state() == QMovie.MovieState.Running
    assert later._image_label.movie().state() == QMovie.MovieState.Running


# --- the enhancement being made of this image --------------------------------

def _run(**kw):
    base = dict(status="running", frame=None)
    base.update(kw)
    return EnhancingRun(**base)


def _png_bytes(color=(30, 90, 160)):
    from io import BytesIO

    buf = BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


def test_a_resting_tile_wears_neither_overlay(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    assert tw._enhancing is None
    assert tw._enhancing_overlay.isHidden()
    assert tw._enhancing_bar.isHidden()


def test_an_enhancing_tile_says_so_over_the_picture_and_on_a_bar(qtbot):
    # The same pair an in-flight card wears: the stage on a dimming scrim, and
    # how far along the run is on a bar at the picture's foot. The tile used to
    # get the scrim alone, so the one thing it couldn't say was how long.
    tw = ThumbnailWidget("p1", None, "label", enhancing=_run(
        progress=(10, 20), started_at=time.time() - 90.5, typical_seconds=725.0))
    qtbot.addWidget(tw)

    assert tw._enhancing is not None
    assert tw._enhancing_overlay.text() == "Enhancing…"
    assert tw._enhancing_bar.caption() == "50% · ~6:02 left"
    assert (tw._enhancing_bar.value(), tw._enhancing_bar.maximum()) == (10, 20)


def test_the_fix_being_applied_gets_the_band_under_the_run_s_own_reading(qtbot):
    # An enhance with detail fixes is several sampler passes, and this tile is
    # where the user watches one. The bar is the whole enhancement; the band
    # along its foot is the fix in hand — which is the reading that restarts,
    # and used to be the only one there was.
    tw = ThumbnailWidget("p1", None, "label", enhancing=_run(
        progress=(45, 60), pass_progress=(5, 20)))
    qtbot.addWidget(tw)

    assert (tw._enhancing_bar.value(), tw._enhancing_bar.maximum()) == (45, 60)
    assert tw._enhancing_bar.pass_progress() == (5, 20)


def test_an_enhance_still_queued_draws_no_band(qtbot):
    # Nothing is being sampled yet, so there is no pass to be part-way through.
    tw = ThumbnailWidget("p1", None, "label", enhancing=_run(
        status="queued", progress=(45, 60), pass_progress=(5, 20)))
    qtbot.addWidget(tw)

    assert tw._enhancing_bar.pass_progress() is None


def test_the_bar_sits_along_the_foot_of_the_picture(qtbot):
    # Overlaid rather than laid out beneath, so an enhancing tile is the same
    # size and shape as a resting one and still flows with them.
    tw = ThumbnailWidget("p1", None, "label", enhancing=_run())
    qtbot.addWidget(tw)
    picture, bar = tw._image_label.geometry(), tw._enhancing_bar.geometry()

    assert picture.contains(bar)
    assert bar.top() > picture.center().y()
    assert tw.size() == ThumbnailWidget("p2", None, "label").size()


def test_an_enhance_still_queued_leaves_the_bar_sweeping(qtbot):
    # Nothing has begun, so there is no percentage and no clock: a determinate
    # bar parked at 0% would say it had started and gone nowhere.
    tw = ThumbnailWidget("p1", None, "label",
                         enhancing=_run(status="queued", progress=(0, 0)))
    qtbot.addWidget(tw)

    assert tw._enhancing_bar.caption() == ""
    assert tw._enhancing_bar.maximum() == 0
    assert not tw._enhancing_tick.isActive()


def test_a_fresh_run_updates_the_overlays_in_place(qtbot):
    tw = ThumbnailWidget("p1", None, "label", enhancing=_run(status="queued"))
    qtbot.addWidget(tw)

    tw.set_enhancing(_run(progress=(5, 20), started_at=time.time() - 30.5,
                          typical_seconds=100.0))

    assert tw._enhancing_bar.caption().startswith("25% · ")
    assert tw._enhancing_tick.isActive()


def test_the_clock_advances_between_polls(qtbot):
    # The gallery reconciles on its own schedule, which would make a countdown
    # skip; the tile re-reads the clock itself so it moves a second at a time.
    tw = ThumbnailWidget("p1", None, "label",
                         enhancing=_run(started_at=time.time() - 5.5,
                                        typical_seconds=100.0))
    qtbot.addWidget(tw)
    assert tw._enhancing_bar.caption() == "~1:34 left"

    tw._enhancing.started_at -= 3  # as if three seconds had gone by
    tw._enhancing_tick.timeout.emit()
    assert tw._enhancing_bar.caption() == "~1:31 left"


def test_a_streamed_frame_paints_the_picture_under_the_overlays(qtbot):
    tw = ThumbnailWidget("p1", None, "label", enhancing=_run())
    qtbot.addWidget(tw)

    tw.set_enhancing(_run(frame=_png_bytes()))

    assert not tw._image_label.pixmap().isNull()
    assert tw._enhancing_overlay.text() == "Enhancing…"  # still not the finished file
    assert not tw._enhancing_bar.isHidden()


def test_the_run_ending_takes_both_overlays_away(qtbot):
    tw = ThumbnailWidget("p1", None, "label", enhancing=_run(frame=_png_bytes()))
    qtbot.addWidget(tw)

    tw.set_enhancing(None)

    assert tw._enhancing is None
    assert tw._enhancing_overlay.isHidden()
    assert tw._enhancing_bar.isHidden()
    assert not tw._enhancing_tick.isActive()
