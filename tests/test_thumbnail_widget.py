from PIL import Image
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt6.QtGui import QColor, QEnterEvent, QMovie
from PyQt6.QtWidgets import QApplication

from origenerator.gui import icons, thumbnail_widget
from origenerator.gui.media_badge import MediaBadge
from origenerator.gui.star_badge import StarBadge
from origenerator.gui.stylesheet import build_stylesheet
from origenerator.gui.thumbnail_widget import ThumbnailWidget, _SELECTED_BG


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


def test_star_badge_shows_only_when_starred(qtbot):
    # An unstarred tile carries the badge widget but keeps it hidden...
    plain = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(plain)
    assert plain.is_starred() is False
    assert all(b.isHidden() for b in plain.findChildren(StarBadge))
    # ...a starred one reveals it (a green star in the corner).
    starred = ThumbnailWidget("p2", None, "label", starred=True)
    qtbot.addWidget(starred)
    assert starred.is_starred() is True
    badges = starred.findChildren(StarBadge)
    assert len(badges) == 1 and not badges[0].isHidden()


def test_set_starred_toggles_the_badge_live(qtbot):
    tw = ThumbnailWidget("p1", None, "label")
    qtbot.addWidget(tw)
    (badge,) = tw.findChildren(StarBadge)
    assert badge.isHidden()
    tw.set_starred(True)
    assert tw.is_starred() is True and not badge.isHidden()
    tw.set_starred(False)
    assert tw.is_starred() is False and badge.isHidden()


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
