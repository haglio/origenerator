"""DropZone: a kind-gated drop target for a dragged gallery generation."""
from __future__ import annotations

import pytest
from PIL import Image
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt
from PyQt6.QtGui import QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent, QMovie
from PyQt6.QtWidgets import QApplication
from shared_ui.colors import hovered
from shared_ui.spacing import GAP_SMALL
from shared_ui.testing import ground

from origenerator.gui.drags import under_way
from origenerator.gui.drop_style import AIMED, LIT
from origenerator.gui.drop_zone import DropZone
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.gui.stylesheet import build_stylesheet
from tests.drop_style_seen import worn


def _zone(qtbot, kind="image", lent_by=lambda pid: pid,
          preview=lambda pid: (None, None), placeholder="Drop here", grayscale=False,
          named=lambda name: None, name_of=lambda held: "", browse=None,
          leads_to=lambda held: held):
    zone = DropZone(kind=kind, lent_by=lent_by, preview=preview, placeholder=placeholder,
                    grayscale=grayscale, named=named, name_of=name_of, browse=browse,
                    leads_to=leads_to)
    qtbot.addWidget(zone)
    return zone


def _images_only(pid):
    return pid if pid.startswith("img") else None


def _drop(zone, pid):
    # Hold the QMimeData in a local: the event stores only a C++ pointer to it, so
    # a temporary would be GC'd before dropEvent reads it (a dangling-pointer crash).
    mime = generation_mime(pid)
    ev = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    zone.dropEvent(ev)
    return ev


def _drag_enter(zone, pid):
    mime = generation_mime(pid)
    ev = QDragEnterEvent(QPoint(1, 1), Qt.DropAction.CopyAction, mime,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    zone.dragEnterEvent(ev)
    return ev


def _write_looping_webp(path, size=(64, 48)):
    frames = [Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return str(path)


def test_dropping_an_allowed_id_fills_the_zone_and_notifies(qtbot):
    zone = _zone(qtbot, lent_by=_images_only)
    seen = []
    zone.changed.connect(lambda: seen.append(zone.current_id()))

    ev = _drop(zone, "img1")

    assert zone.current_id() == "img1"
    assert ev.isAccepted()
    assert seen == ["img1"]


def test_a_dropped_item_is_held_as_what_it_lends_the_zone(qtbot):
    zone = _zone(qtbot, lent_by={"vid1": "img1"}.get)

    ev = _drop(zone, "vid1")

    assert zone.current_id() == "img1"
    assert ev.isAccepted()


def test_dropping_a_disallowed_id_is_ignored(qtbot):
    zone = _zone(qtbot, lent_by=_images_only)

    _drop(zone, "vid9")

    assert zone.current_id() is None  # it lends this zone nothing


def test_drag_enter_accepts_only_allowed_ids(qtbot):
    zone = _zone(qtbot, lent_by=_images_only)

    assert _drag_enter(zone, "img1").isAccepted()
    assert not _drag_enter(zone, "vid1").isAccepted()


def test_clear_empties_the_zone_and_notifies(qtbot):
    zone = _zone(qtbot)
    _drop(zone, "img1")
    seen = []
    zone.changed.connect(lambda: seen.append(zone.current_id()))

    zone.clear()

    assert zone.current_id() is None
    assert seen == [None]


def test_clear_on_an_empty_zone_does_not_notify(qtbot):
    zone = _zone(qtbot)
    seen = []
    zone.changed.connect(lambda: seen.append(1))

    zone.clear()

    assert seen == []  # idempotent: nothing to clear, no spurious change


def test_a_filled_zone_names_its_item_under_its_image(qtbot):
    zone = _zone(qtbot, name_of=lambda held: f"Example Folder {held}")

    _drop(zone, "img1")
    named = zone._caption.text()
    zone.clear()

    assert (named, zone._caption.text()) == ("Example Folder img1", "")


def test_a_held_items_name_sits_as_close_under_its_image_as_under_a_source_thumbnail(qtbot):
    zone = _zone(qtbot, name_of=lambda held: f"Example Folder {held}")
    _drop(zone, "img1")
    zone.resize(240, 240)
    zone.show()
    zone.layout().activate()
    image, name = zone._label, zone._caption

    assert name.y() - (image.y() + image.height()) == GAP_SMALL


def test_clicking_a_filled_zone_goes_to_its_item_and_keeps_it(qtbot):
    zone = _zone(qtbot)
    _drop(zone, "img1")
    went = []
    zone.activated.connect(went.append)

    qtbot.mouseClick(zone, Qt.MouseButton.LeftButton)

    assert went == ["img1"]
    assert zone.current_id() == "img1"


def test_a_click_goes_to_the_gallery_item_the_held_file_belongs_to(qtbot):
    zone = _zone(qtbot, leads_to={"image/scene_00001_.png [output]": "gen-pic"}.get)
    went = []
    zone.activated.connect(went.append)
    zone.set_item("image/scene_00001_.png [output]")

    qtbot.mouseClick(zone, Qt.MouseButton.LeftButton)

    assert went == ["gen-pic"]
    assert zone.cursor().shape() == Qt.CursorShape.PointingHandCursor


@pytest.mark.parametrize(("name", "tip"), [("scene one.png", "scene one.png"), ("", "")])
def test_a_held_file_from_outside_the_gallery_offers_no_way_there(qtbot, name, tip):
    zone = _zone(qtbot, leads_to=lambda held: None, name_of=lambda held: name)
    went = []
    zone.activated.connect(went.append)
    zone.set_item("C:/elsewhere/scene one.png")

    qtbot.mouseClick(zone, Qt.MouseButton.LeftButton)

    assert went == []
    assert zone.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert zone.toolTip() == tip


def test_a_video_preview_animates(qtbot, tmp_path):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    zone = _zone(qtbot, kind="video", preview=lambda pid: (None, webp))

    _drop(zone, "vid1")

    movie = zone._label.movie()
    assert isinstance(movie, QMovie)
    assert movie.state() == QMovie.MovieState.Running  # looping, not a still


def test_emptying_a_zone_stops_the_clip_it_was_looping(qtbot, tmp_path):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    zone = _zone(qtbot, kind="video", preview=lambda pid: (None, webp))
    _drop(zone, "vid1")
    looping = zone._movie

    zone.clear()

    assert looping.state() == QMovie.MovieState.NotRunning
    assert zone._label.movie() is None


def test_a_grayscale_zone_drains_the_clip_it_holds(qtbot, tmp_path):
    # The video zone holds a source video, not a result: in color it reads as a second
    # subject beside the image it will animate.
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    zone = _zone(qtbot, kind="video", preview=lambda pid: (None, webp), grayscale=True)

    _drop(zone, "vid1")

    assert zone._label.movie() is None  # frames come across as pixmaps, drained
    color = zone._label.pixmap().toImage().pixelColor(2, 2)
    assert color.red() == color.green() == color.blue()
    assert zone._movie.state() == QMovie.MovieState.Running  # still looping


def test_a_grayscale_zone_drains_a_still_too(qtbot, tmp_path):
    # An i2v video with no animated preview shows its stored frame; it is held
    # for the same reason and reads the same way.
    still = tmp_path / "thumb.png"
    Image.new("RGB", (40, 30), (200, 30, 30)).save(still)
    zone = _zone(qtbot, kind="video", preview=lambda pid: (str(still), None),
                 grayscale=True)

    _drop(zone, "vid1")

    color = zone._label.pixmap().toImage().pixelColor(2, 2)
    assert color.red() == color.green() == color.blue()


def test_an_ordinary_zone_keeps_its_color(qtbot, tmp_path):
    still = tmp_path / "thumb.png"
    Image.new("RGB", (40, 30), (200, 30, 30)).save(still)
    zone = _zone(qtbot, preview=lambda pid: (str(still), None))

    _drop(zone, "img1")

    assert zone._label.pixmap().toImage().pixelColor(2, 2).red() > 150


def test_a_zone_lights_while_a_drag_it_would_take_is_under_way(qtbot):
    zone = _zone(qtbot, lent_by=_images_only)
    image, video = generation_mime("img1"), generation_mime("vid1")

    under_way.started.emit(image, None)
    assert zone._label.property("dragActive") is True
    under_way.ended.emit()
    assert zone._label.property("dragActive") is False

    under_way.started.emit(video, None)
    assert zone._label.property("dragActive") is False
    under_way.ended.emit()


def test_a_drag_over_the_zone_lights_it_as_where_the_drop_lands(qtbot):
    zone = _zone(qtbot)

    _drag_enter(zone, "img1")
    assert zone._label.property("dropTarget") is True

    zone.dragLeaveEvent(QDragLeaveEvent())
    assert zone._label.property("dropTarget") is False


def test_a_drag_the_zone_would_turn_away_does_not_light_it(qtbot):
    zone = _zone(qtbot, lent_by=_images_only)

    _drag_enter(zone, "vid1")

    assert zone._label.property("dropTarget") is False


def test_a_drag_carrying_no_gallery_item_is_turned_away(qtbot):
    # A file dragged in from outside the app, say.
    zone = _zone(qtbot)
    mime = QMimeData()
    mime.setText("elsewhere.png")
    event = QDragEnterEvent(QPoint(1, 1), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    zone.dragEnterEvent(event)

    assert not event.isAccepted()
    assert zone._label.property("dropTarget") is False


def test_letting_go_over_the_zone_puts_it_out(qtbot):
    zone = _zone(qtbot)
    _drag_enter(zone, "img1")

    _drop(zone, "img1")

    assert zone._label.property("dropTarget") is False


def _shown_in_the_app(qtbot, zone):
    zone.setStyleSheet(build_stylesheet())
    with qtbot.waitExposed(zone):
        zone.show()
    return zone


def _style_worn(zone):
    return worn(zone._label.grab().toImage(), zone._label.rect())


def test_a_zone_a_drag_would_land_in_wears_the_drop_style(qtbot):
    zone = _shown_in_the_app(qtbot, _zone(qtbot))
    assert _style_worn(zone) is None

    under_way.started.emit(generation_mime("img1"), None)

    assert _style_worn(zone) == LIT


def test_the_zone_under_the_drag_sits_one_step_lighter_than_one_only_lit_for_it(qtbot):
    zone = _shown_in_the_app(qtbot, _zone(qtbot))
    under_way.started.emit(generation_mime("img1"), None)
    lit = ground(zone._label)

    _drag_enter(zone, "img1")

    assert ground(zone._label) == hovered(QColor(lit)).name()
    assert _style_worn(zone) == AIMED


def test_accepts_delegates_to_the_predicate(qtbot):
    zone = _zone(qtbot, lent_by=_images_only)

    assert zone.accepts("img1") is True
    assert zone.accepts("vid1") is False


@pytest.mark.parametrize("kind", ["image", "video"])
def test_the_item_type_icon_appears_only_once_filled(qtbot, kind):
    zone = _zone(qtbot, kind=kind)
    icon = zone.findChild(ItemTypeIcon)
    assert icon.media_type == kind      # an item type icon, so you know what goes here
    assert icon.isHidden()               # nothing dropped yet (isHidden works offscreen)

    _drop(zone, "x1")
    assert not icon.isHidden()

    zone.clear()
    assert icon.isHidden()               # back to a bare drop zone


def _actions(zone) -> dict:
    return {action.text(): action for action in zone.menu().actions()}


def test_the_menu_pastes_the_item_the_clipboard_names(qtbot):
    QApplication.clipboard().setText("AB12CD34 007")
    zone = _zone(qtbot, lent_by=_images_only, named={"AB12CD34 007": "img7"}.get)
    paste = _actions(zone)["Paste Origenerator name"]
    assert paste.isEnabled()

    paste.trigger()

    assert zone.current_id() == "img7"


@pytest.mark.parametrize("on_the_clipboard", ["", "a sentence copied elsewhere", "AB12CD34 007"])
def test_paste_is_grayed_while_the_clipboard_names_nothing_the_zone_takes(qtbot, on_the_clipboard):
    QApplication.clipboard().setText(on_the_clipboard)
    zone = _zone(qtbot, lent_by=_images_only, named={"AB12CD34 007": "vid7"}.get)

    paste = _actions(zone)["Paste Origenerator name"]

    assert not paste.isEnabled()


def test_browse_is_offered_only_to_a_zone_that_can_take_a_file(qtbot):
    browsed = []
    with_browse = _zone(qtbot, browse=lambda: browsed.append("asked"))
    without = _zone(qtbot)

    assert "Browse..." not in _actions(without)
    _actions(with_browse)["Browse..."].trigger()

    assert browsed == ["asked"]
    assert list(_actions(with_browse)) == ["Paste Origenerator name", "Browse..."]


def test_a_held_item_is_named_in_the_zones_tooltip(qtbot):
    zone = _zone(qtbot, name_of={"img1": "AB12CD34 001"}.get)

    _drop(zone, "img1")

    assert zone.toolTip() == "AB12CD34 001"
