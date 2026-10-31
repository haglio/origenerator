"""DropSlot: a kind-gated drop target for a dragged gallery generation."""
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
from origenerator.gui.drop_slot import DropSlot
from origenerator.gui.drop_style import AIMED, LIT
from origenerator.gui.generation_drag import generation_mime
from origenerator.gui.item_type_icon import ItemTypeIcon
from origenerator.gui.stylesheet import build_stylesheet
from tests.drop_style_seen import worn


def _slot(qtbot, kind="image", lent_by=lambda pid: pid,
          preview=lambda pid: (None, None), placeholder="Drop here", grayscale=False,
          named=lambda name: None, name_of=lambda held: "", browse=None,
          leads_to=lambda held: held):
    slot = DropSlot(kind=kind, lent_by=lent_by, preview=preview, placeholder=placeholder,
                    grayscale=grayscale, named=named, name_of=name_of, browse=browse,
                    leads_to=leads_to)
    qtbot.addWidget(slot)
    return slot


def _images_only(pid):
    return pid if pid.startswith("img") else None


def _drop(slot, pid):
    # Hold the QMimeData in a local: the event stores only a C++ pointer to it, so
    # a temporary would be GC'd before dropEvent reads it (a dangling-pointer crash).
    mime = generation_mime(pid)
    ev = QDropEvent(QPointF(1, 1), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    slot.dropEvent(ev)
    return ev


def _drag_enter(slot, pid):
    mime = generation_mime(pid)
    ev = QDragEnterEvent(QPoint(1, 1), Qt.DropAction.CopyAction, mime,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    slot.dragEnterEvent(ev)
    return ev


def _write_looping_webp(path, size=(64, 48)):
    frames = [Image.new("RGB", size, c) for c in ((255, 0, 0), (0, 255, 0))]
    frames[0].save(path, format="WEBP", save_all=True,
                   append_images=frames[1:], duration=100, loop=0)
    return str(path)


def test_dropping_an_allowed_id_fills_the_slot_and_notifies(qtbot):
    slot = _slot(qtbot, lent_by=_images_only)
    seen = []
    slot.changed.connect(lambda: seen.append(slot.current_id()))

    ev = _drop(slot, "img1")

    assert slot.current_id() == "img1"
    assert ev.isAccepted()
    assert seen == ["img1"]


def test_a_dropped_item_is_held_as_what_it_lends_the_slot(qtbot):
    slot = _slot(qtbot, lent_by={"vid1": "img1"}.get)

    ev = _drop(slot, "vid1")

    assert slot.current_id() == "img1"
    assert ev.isAccepted()


def test_dropping_a_disallowed_id_is_ignored(qtbot):
    slot = _slot(qtbot, lent_by=_images_only)

    _drop(slot, "vid9")

    assert slot.current_id() is None  # it lends this slot nothing


def test_drag_enter_accepts_only_allowed_ids(qtbot):
    slot = _slot(qtbot, lent_by=_images_only)

    assert _drag_enter(slot, "img1").isAccepted()
    assert not _drag_enter(slot, "vid1").isAccepted()


def test_clear_empties_the_slot_and_notifies(qtbot):
    slot = _slot(qtbot)
    _drop(slot, "img1")
    seen = []
    slot.changed.connect(lambda: seen.append(slot.current_id()))

    slot.clear()

    assert slot.current_id() is None
    assert seen == [None]


def test_clear_on_an_empty_slot_does_not_notify(qtbot):
    slot = _slot(qtbot)
    seen = []
    slot.changed.connect(lambda: seen.append(1))

    slot.clear()

    assert seen == []  # idempotent: nothing to clear, no spurious change


def test_a_filled_slot_names_its_item_under_its_image(qtbot):
    slot = _slot(qtbot, name_of=lambda held: f"Example Folder {held}")

    _drop(slot, "img1")
    named = slot._caption.text()
    slot.clear()

    assert (named, slot._caption.text()) == ("Example Folder img1", "")


def test_a_held_items_name_sits_as_close_under_its_image_as_under_a_source_thumbnail(qtbot):
    slot = _slot(qtbot, name_of=lambda held: f"Example Folder {held}")
    _drop(slot, "img1")
    slot.resize(240, 240)
    slot.show()
    slot.layout().activate()
    image, name = slot._label, slot._caption

    assert name.y() - (image.y() + image.height()) == GAP_SMALL


def test_clicking_a_filled_slot_goes_to_its_item_and_keeps_it(qtbot):
    slot = _slot(qtbot)
    _drop(slot, "img1")
    went = []
    slot.activated.connect(went.append)

    qtbot.mouseClick(slot, Qt.MouseButton.LeftButton)

    assert went == ["img1"]
    assert slot.current_id() == "img1"


def test_a_click_goes_to_the_gallery_item_the_held_file_belongs_to(qtbot):
    slot = _slot(qtbot, leads_to={"image/scene_00001_.png [output]": "gen-pic"}.get)
    went = []
    slot.activated.connect(went.append)
    slot.set_item("image/scene_00001_.png [output]")

    qtbot.mouseClick(slot, Qt.MouseButton.LeftButton)

    assert went == ["gen-pic"]
    assert slot.cursor().shape() == Qt.CursorShape.PointingHandCursor


@pytest.mark.parametrize(("name", "tip"), [("scene one.png", "scene one.png"), ("", "")])
def test_a_held_file_from_outside_the_gallery_offers_no_way_there(qtbot, name, tip):
    slot = _slot(qtbot, leads_to=lambda held: None, name_of=lambda held: name)
    went = []
    slot.activated.connect(went.append)
    slot.set_item("C:/elsewhere/scene one.png")

    qtbot.mouseClick(slot, Qt.MouseButton.LeftButton)

    assert went == []
    assert slot.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert slot.toolTip() == tip


def test_a_video_preview_animates(qtbot, tmp_path):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    slot = _slot(qtbot, kind="video", preview=lambda pid: (None, webp))

    _drop(slot, "vid1")

    movie = slot._label.movie()
    assert isinstance(movie, QMovie)
    assert movie.state() == QMovie.MovieState.Running  # looping, not a still


def test_emptying_a_slot_stops_the_clip_it_was_looping(qtbot, tmp_path):
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    slot = _slot(qtbot, kind="video", preview=lambda pid: (None, webp))
    _drop(slot, "vid1")
    looping = slot._movie

    slot.clear()

    assert looping.state() == QMovie.MovieState.NotRunning
    assert slot._label.movie() is None


def test_a_grayscale_slot_drains_the_clip_it_holds(qtbot, tmp_path):
    # The video slot holds a source video, not a result: in color it reads as a second
    # subject beside the image it will animate.
    webp = _write_looping_webp(tmp_path / "v1_anim.webp")
    slot = _slot(qtbot, kind="video", preview=lambda pid: (None, webp), grayscale=True)

    _drop(slot, "vid1")

    assert slot._label.movie() is None  # frames come across as pixmaps, drained
    color = slot._label.pixmap().toImage().pixelColor(2, 2)
    assert color.red() == color.green() == color.blue()
    assert slot._movie.state() == QMovie.MovieState.Running  # still looping


def test_a_grayscale_slot_drains_a_still_too(qtbot, tmp_path):
    # An i2v video with no animated preview shows its stored frame; it is held
    # for the same reason and reads the same way.
    still = tmp_path / "thumb.png"
    Image.new("RGB", (40, 30), (200, 30, 30)).save(still)
    slot = _slot(qtbot, kind="video", preview=lambda pid: (str(still), None),
                 grayscale=True)

    _drop(slot, "vid1")

    color = slot._label.pixmap().toImage().pixelColor(2, 2)
    assert color.red() == color.green() == color.blue()


def test_an_ordinary_slot_keeps_its_color(qtbot, tmp_path):
    still = tmp_path / "thumb.png"
    Image.new("RGB", (40, 30), (200, 30, 30)).save(still)
    slot = _slot(qtbot, preview=lambda pid: (str(still), None))

    _drop(slot, "img1")

    assert slot._label.pixmap().toImage().pixelColor(2, 2).red() > 150


def test_a_slot_lights_while_a_drag_it_would_take_is_under_way(qtbot):
    slot = _slot(qtbot, lent_by=_images_only)
    image, video = generation_mime("img1"), generation_mime("vid1")

    under_way.started.emit(image, None)
    assert slot._label.property("dragActive") is True
    under_way.ended.emit()
    assert slot._label.property("dragActive") is False

    under_way.started.emit(video, None)
    assert slot._label.property("dragActive") is False
    under_way.ended.emit()


def test_a_drag_over_the_slot_lights_it_as_where_the_drop_lands(qtbot):
    slot = _slot(qtbot)

    _drag_enter(slot, "img1")
    assert slot._label.property("dropTarget") is True

    slot.dragLeaveEvent(QDragLeaveEvent())
    assert slot._label.property("dropTarget") is False


def test_a_drag_the_slot_would_turn_away_does_not_light_it(qtbot):
    slot = _slot(qtbot, lent_by=_images_only)

    _drag_enter(slot, "vid1")

    assert slot._label.property("dropTarget") is False


def test_a_drag_carrying_no_gallery_item_is_turned_away(qtbot):
    # A file dragged in from outside the app, say.
    slot = _slot(qtbot)
    mime = QMimeData()
    mime.setText("elsewhere.png")
    event = QDragEnterEvent(QPoint(1, 1), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    slot.dragEnterEvent(event)

    assert not event.isAccepted()
    assert slot._label.property("dropTarget") is False


def test_letting_go_over_the_slot_puts_it_out(qtbot):
    slot = _slot(qtbot)
    _drag_enter(slot, "img1")

    _drop(slot, "img1")

    assert slot._label.property("dropTarget") is False


def _shown_in_the_app(qtbot, slot):
    slot.setStyleSheet(build_stylesheet())
    with qtbot.waitExposed(slot):
        slot.show()
    return slot


def _style_worn(slot):
    return worn(slot._label.grab().toImage(), slot._label.rect())


def test_a_slot_a_drag_would_land_in_wears_the_drop_style(qtbot):
    slot = _shown_in_the_app(qtbot, _slot(qtbot))
    assert _style_worn(slot) is None

    under_way.started.emit(generation_mime("img1"), None)

    assert _style_worn(slot) == LIT


def test_the_slot_under_the_drag_sits_one_step_lighter_than_one_only_lit_for_it(qtbot):
    slot = _shown_in_the_app(qtbot, _slot(qtbot))
    under_way.started.emit(generation_mime("img1"), None)
    lit = ground(slot._label)

    _drag_enter(slot, "img1")

    assert ground(slot._label) == hovered(QColor(lit)).name()
    assert _style_worn(slot) == AIMED


def test_accepts_delegates_to_the_predicate(qtbot):
    slot = _slot(qtbot, lent_by=_images_only)

    assert slot.accepts("img1") is True
    assert slot.accepts("vid1") is False


@pytest.mark.parametrize("kind", ["image", "video"])
def test_the_item_type_icon_appears_only_once_filled(qtbot, kind):
    slot = _slot(qtbot, kind=kind)
    icon = slot.findChild(ItemTypeIcon)
    assert icon.media_type == kind      # an item type icon, so you know what goes here
    assert icon.isHidden()               # nothing dropped yet (isHidden works offscreen)

    _drop(slot, "x1")
    assert not icon.isHidden()

    slot.clear()
    assert icon.isHidden()               # back to a bare drop zone


def _actions(slot) -> dict:
    return {action.text(): action for action in slot.menu().actions()}


def test_the_menu_pastes_the_item_the_clipboard_names(qtbot):
    QApplication.clipboard().setText("AB12CD34 007")
    slot = _slot(qtbot, lent_by=_images_only, named={"AB12CD34 007": "img7"}.get)
    paste = _actions(slot)["Paste Origenerator name"]
    assert paste.isEnabled()

    paste.trigger()

    assert slot.current_id() == "img7"


@pytest.mark.parametrize("on_the_clipboard", ["", "a sentence copied elsewhere", "AB12CD34 007"])
def test_paste_is_grayed_while_the_clipboard_names_nothing_the_slot_takes(qtbot, on_the_clipboard):
    QApplication.clipboard().setText(on_the_clipboard)
    slot = _slot(qtbot, lent_by=_images_only, named={"AB12CD34 007": "vid7"}.get)

    paste = _actions(slot)["Paste Origenerator name"]

    assert not paste.isEnabled()


def test_browse_is_offered_only_to_a_slot_that_can_take_a_file(qtbot):
    browsed = []
    with_browse = _slot(qtbot, browse=lambda: browsed.append("asked"))
    without = _slot(qtbot)

    assert "Browse..." not in _actions(without)
    _actions(with_browse)["Browse..."].trigger()

    assert browsed == ["asked"]
    assert list(_actions(with_browse)) == ["Paste Origenerator name", "Browse..."]


def test_a_held_item_is_named_in_the_slots_tooltip(qtbot):
    slot = _slot(qtbot, name_of={"img1": "AB12CD34 001"}.get)

    _drop(slot, "img1")

    assert slot.toolTip() == "AB12CD34 001"
