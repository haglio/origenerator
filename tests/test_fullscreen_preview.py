from io import BytesIO
from unittest.mock import MagicMock

from PIL import Image
from PyQt6.QtCore import Qt, QUrl, QEvent, QSize
from PyQt6.QtGui import QKeyEvent, QResizeEvent
from PyQt6.QtWidgets import QApplication

from origenerator.funscript import funscript_path_for, synthesize_actions, write_funscript
from origenerator.gui.fullscreen_preview import FullscreenPreview
from origenerator.stroke_engine import Stroke


def _make_png(path):
    Image.new("RGB", (32, 24), (10, 120, 200)).save(path, "PNG")
    return path


def _png_bytes():
    """A streamed in-progress frame: encoded image bytes, no file on disk."""
    buf = BytesIO()
    Image.new("RGB", (32, 24), (10, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def _make_tall_png(path):
    """A tall image whose aspect ratio doesn't match a wide screen, so a correct
    fit touches the short edges and leaves the long ones letterboxed."""
    Image.new("RGB", (24, 60), (10, 120, 200)).save(path, "PNG")
    return path


def _escape(win):
    win.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )


def _press(win, key):
    win.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_shows_the_image(qtbot, tmp_path):
    png = _make_png(tmp_path / "p.png")
    win = FullscreenPreview((png, "image"), player=MagicMock())
    qtbot.addWidget(win)
    assert win._preview._media == (png, "image")
    assert win._preview.is_showing_video() is False


def test_fits_the_image_to_the_screen_without_clipping(qtbot, tmp_path):
    # The image shows as large as it fits the screen with nothing clipped off, and
    # refits when the window grows to fullscreen — the reported "black on all four
    # sides" was the image left scaled at its tiny pre-show size on the full screen.
    win = FullscreenPreview((_make_tall_png(tmp_path / "tall.png"), "image"),
                            player=MagicMock())
    qtbot.addWidget(win)
    label = win._preview._image_label
    old = label.size()
    label.resize(600, 500)  # stand in for the screen the window grows to
    QApplication.sendEvent(label, QResizeEvent(QSize(600, 500), old))
    pm = label.pixmap()
    assert pm.width() <= 600 and pm.height() <= 500        # nothing clipped off
    assert pm.width() == 600 or pm.height() == 500         # as large as it fits


def test_plays_the_video(qtbot, tmp_path):
    win = FullscreenPreview((tmp_path / "c.mp4", "video"), player=MagicMock())
    qtbot.addWidget(win)
    assert win._preview.is_showing_video() is True
    win._preview._player.play.assert_called_once()


def test_escape_closes_it(qtbot, tmp_path):
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.showFullScreen()
    _escape(win)
    assert not win.isVisible()


def test_double_click_on_the_media_closes_it(qtbot, tmp_path):
    # The click lands on the inner preview (the media fills the window), not the
    # window itself — the reported bug was that only Escape closed it.
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.showFullScreen()
    win._preview.mouseDoubleClickEvent(None)
    assert not win.isVisible()


def test_closing_releases_the_video_file(qtbot, tmp_path):
    # A held media handle blocks move-to-trash on Windows, so closing must drop it.
    win = FullscreenPreview((tmp_path / "c.mp4", "video"), player=MagicMock())
    qtbot.addWidget(win)
    win.close()
    win._preview._player.setSource.assert_called_with(QUrl())


def test_a_view_of_a_condemned_file_dismisses_itself(qtbot, tmp_path):
    # Deleting what's up fullscreen: the view holds the file open, which would
    # block the move to trash, and there'd be nothing left to show anyway.
    clip = tmp_path / "c.mp4"
    win = FullscreenPreview((clip, "video"), player=MagicMock())
    qtbot.addWidget(win)
    win.showFullScreen()

    win.release_media([clip])

    assert not win.isVisible()
    win._preview._player.setSource.assert_called_with(QUrl())


def test_a_view_of_another_file_stays_up(qtbot, tmp_path):
    win = FullscreenPreview((tmp_path / "kept.mp4", "video"), player=MagicMock())
    qtbot.addWidget(win)
    win.showFullScreen()

    win.release_media([tmp_path / "doomed.mp4"])

    assert win.isVisible()


def test_the_fullscreen_preview_does_not_nest_another(qtbot, tmp_path):
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    assert win._preview.open_fullscreen() is None


def test_watching_a_scripted_video_fullscreen_shows_its_strip(qtbot, tmp_path):
    vid = tmp_path / "c.mp4"
    write_funscript(funscript_path_for(vid), synthesize_actions(2.0, hz=1.0, loop=False))
    win = FullscreenPreview((vid, "video"), player=MagicMock())
    qtbot.addWidget(win)
    assert win._preview._strip is not None
    assert win._preview._strip.has_script() is True


def test_plays_audio_unlike_the_muted_inline_preview(qtbot, tmp_path):
    # Double-clicking a clip to watch it fullscreen is deliberate, so it's heard.
    win = FullscreenPreview((tmp_path / "c.mp4", "video"), player=MagicMock())
    qtbot.addWidget(win)
    assert win._preview._audio.isMuted() is False


def test_emits_closed_when_dismissed(qtbot, tmp_path):
    # The gallery listens for this to hand the OSR2 back when the view goes away.
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    closed = []
    win.closed.connect(lambda: closed.append(True))
    win.close()
    assert closed == [True]


def test_osr2_drive_target_bundles_the_scripted_video(qtbot, tmp_path):
    vid = tmp_path / "c.mp4"
    write_funscript(funscript_path_for(vid), synthesize_actions(2.0, hz=1.0, loop=False))
    player = MagicMock()
    win = FullscreenPreview((vid, "video"), player=player)
    qtbot.addWidget(win)
    target = win.osr2_drive_target()
    assert target is not None
    path, tgt_player, actions = target
    assert path == vid and tgt_player is player and actions


def test_osr2_drive_target_is_none_for_an_image(qtbot, tmp_path):
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    assert win.osr2_drive_target() is None


def test_osr2_drive_target_is_none_for_an_unscripted_video(qtbot, tmp_path):
    win = FullscreenPreview((tmp_path / "c.mp4", "video"), player=MagicMock())
    qtbot.addWidget(win)
    assert win.osr2_drive_target() is None


def test_left_right_page_through_the_folder(qtbot, tmp_path):
    a = _make_png(tmp_path / "a.png")
    b = _make_png(tmp_path / "b.png")
    c = _make_png(tmp_path / "c.png")
    items = [(a, "image"), (b, "image"), (c, "image")]
    win = FullscreenPreview(items[1], player=MagicMock())  # opened on the middle item
    qtbot.addWidget(win)
    win.set_playlist(items, 1)

    _press(win, Qt.Key.Key_Right)
    assert win._preview._media == (c, "image")
    _press(win, Qt.Key.Key_Left)
    assert win._preview._media == (b, "image")
    _press(win, Qt.Key.Key_Left)
    assert win._preview._media == (a, "image")


def test_paging_wraps_around_the_ends(qtbot, tmp_path):
    a = _make_png(tmp_path / "a.png")
    b = _make_png(tmp_path / "b.png")
    items = [(a, "image"), (b, "image")]
    win = FullscreenPreview(items[0], player=MagicMock())
    qtbot.addWidget(win)
    win.set_playlist(items, 0)

    _press(win, Qt.Key.Key_Left)   # from the first, wrap back to the last
    assert win._preview._media == (b, "image")
    _press(win, Qt.Key.Key_Right)  # and forward off the last, wrap to the first
    assert win._preview._media == (a, "image")


def test_paging_leaves_the_live_generation_behind(qtbot, tmp_path):
    # Paged onto a saved item, the view is no longer the run's — later frames of it
    # must not paint over what the user paged to.
    a = _make_png(tmp_path / "a.png")
    b = _make_png(tmp_path / "b.png")
    win = FullscreenPreview(None, frame=_png_bytes(), player=MagicMock())
    qtbot.addWidget(win)
    win.set_playlist([(a, "image"), (b, "image")], 0)

    _press(win, Qt.Key.Key_Right)

    assert win.is_live() is False
    assert win._preview._media == (b, "image")


def test_paging_is_inert_without_a_playlist(qtbot, tmp_path):
    a = _make_png(tmp_path / "a.png")
    win = FullscreenPreview((a, "image"), player=MagicMock())  # a lone item, never armed
    qtbot.addWidget(win)
    _press(win, Qt.Key.Key_Right)
    assert win._preview._media == (a, "image")


def test_paging_emits_media_changed_to_re_aim_the_osr2(qtbot, tmp_path):
    a = _make_png(tmp_path / "a.png")
    b = _make_png(tmp_path / "b.png")
    win = FullscreenPreview((a, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_playlist([(a, "image"), (b, "image")], 0)
    changed = []
    win.media_changed.connect(lambda: changed.append(True))

    _press(win, Qt.Key.Key_Right)
    assert changed == [True]


# --- opened over a generation still being made ------------------------------

def test_opens_over_a_running_generation_showing_its_frame(qtbot):
    win = FullscreenPreview(None, frame=_png_bytes(), player=MagicMock())
    qtbot.addWidget(win)
    assert win.is_live() is True
    assert win._preview._media is None                    # no file behind it yet
    assert not win._preview._image_label.pixmap().isNull()  # the streamed frame shows


def test_opened_before_the_first_frame_it_says_it_is_generating(qtbot):
    win = FullscreenPreview(None, player=MagicMock())
    qtbot.addWidget(win)
    assert win.is_live() is True
    assert win._preview._image_label.text() == "Generating…"


def test_a_later_frame_replaces_the_one_it_opened_over(qtbot):
    win = FullscreenPreview(None, player=MagicMock())
    qtbot.addWidget(win)
    win.show_frame(_png_bytes())
    assert not win._preview._image_label.pixmap().isNull()


def test_the_landed_file_takes_over_from_the_frames(qtbot, tmp_path):
    # Watching a generation full-screen ends on the finished image, not the last
    # low-res frame it streamed.
    png = _make_png(tmp_path / "done.png")
    win = FullscreenPreview(None, frame=_png_bytes(), player=MagicMock())
    qtbot.addWidget(win)
    changed = []
    win.media_changed.connect(lambda: changed.append(True))

    win.show_landed((png, "image"))

    assert win._preview._media == (png, "image")
    assert win.is_live() is False
    assert changed == [True]  # a landed video is a fresh OSR2 target


def test_frames_are_ignored_once_it_has_landed(qtbot, tmp_path):
    png = _make_png(tmp_path / "done.png")
    win = FullscreenPreview(None, player=MagicMock())
    qtbot.addWidget(win)
    win.show_landed((png, "image"))

    win.show_frame(_png_bytes())  # a later run's frames must not paint over it

    assert win._preview._media == (png, "image")


def test_a_landed_view_pages_the_folder_like_any_other(qtbot, tmp_path):
    a = _make_png(tmp_path / "a.png")
    b = _make_png(tmp_path / "b.png")
    win = FullscreenPreview(None, frame=_png_bytes(), player=MagicMock())
    qtbot.addWidget(win)
    win.show_landed((a, "image"))
    win.set_playlist([(a, "image"), (b, "image")], 0)

    _press(win, Qt.Key.Key_Right)

    assert win._preview._media == (b, "image")


def test_a_live_view_drives_no_device(qtbot):
    # Streamed frames are no video: nothing for the OSR2 to follow.
    win = FullscreenPreview(None, frame=_png_bytes(), player=MagicMock())
    qtbot.addWidget(win)
    assert win.osr2_drive_target() is None


class _FakeStroke:
    """Enough of the stroke driver for the shared keys and the drive panel."""

    def __init__(self):
        self.active = False
        self.calls = []
        self.state = Stroke()

    def toggle(self):
        self.active = not self.active
        self.calls.append(("toggle", self.active))
        return self.active

    def adjust_speed(self, delta):
        self.calls.append(("speed", delta))

    def status_text(self):
        return "OSR2 stub"


def test_the_shared_stroke_keys_work_here_too(qtbot, tmp_path):
    # An image has no funscript, so the app-global stroke is how the device runs
    # over a fullscreen still — wired in by the gallery, standing caption and all.
    win = FullscreenPreview((_make_png(tmp_path / "p.png"), "image"), player=MagicMock())
    qtbot.addWidget(win)
    _press(win, Qt.Key.Key_Space)  # not wired yet: inert, and must not crash
    stroke = _FakeStroke()
    win.set_stroke(stroke)
    assert win._stroke_panel is not None  # the drive panel came with it
    _press(win, Qt.Key.Key_Space)
    _press(win, Qt.Key.Key_J)
    assert stroke.calls == [("toggle", True), ("speed", -5)]


# --- Shift+Left/Right: the versions of the image on screen -------------------

def _shift(win, key):
    win.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key,
                                Qt.KeyboardModifier.ShiftModifier))


def _plain(win, key):
    win.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key,
                                Qt.KeyboardModifier.NoModifier))


def test_shift_arrows_step_the_versions_of_the_image_on_screen(qtbot, tmp_path):
    enhanced, original = tmp_path / "e1.png", tmp_path / "src.png"
    for path in (enhanced, original):
        _make_png(path)
    win = FullscreenPreview((enhanced, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_levels({str(enhanced): [(enhanced, "image"), (original, "image")]})

    _shift(win, Qt.Key.Key_Right)
    assert win._preview._media[0] == original
    # And back round: two versions wrap, so the pair is a toggle.
    _shift(win, Qt.Key.Key_Right)
    assert win._preview._media[0] == enhanced


def test_shift_arrows_do_nothing_for_an_image_with_one_version(qtbot, tmp_path):
    lone = tmp_path / "only.png"
    _make_png(lone)
    win = FullscreenPreview((lone, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_levels({})

    _shift(win, Qt.Key.Key_Right)

    # Silently nothing, rather than paging the folder when the shift was the
    # whole point of the press.
    assert win._preview._media[0] == lone


def test_paging_to_another_image_starts_its_versions_from_the_top(qtbot, tmp_path):
    first, second, second_base = (tmp_path / n for n in
                                  ("a.png", "b.png", "b_base.png"))
    for path in (first, second, second_base):
        _make_png(path)
    win = FullscreenPreview((first, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_playlist([(first, "image"), (second, "image")], 0)
    win.set_levels({str(second): [(second, "image"), (second_base, "image")]})

    _plain(win, Qt.Key.Key_Right)          # onto the second image
    _shift(win, Qt.Key.Key_Right)          # its own versions, from the top

    assert win._preview._media[0] == second_base


def test_the_corner_says_which_version_is_on_screen(qtbot, tmp_path):
    # Two versions of one picture differ by texture, which is exactly what you
    # cannot tell apart from memory — so the view has to say which one this is.
    enhanced, original = tmp_path / "e1.png", tmp_path / "src.png"
    for path in (enhanced, original):
        _make_png(path)
    win = FullscreenPreview((enhanced, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_levels({str(enhanced): [(enhanced, "image", "Enhance 1"),
                                    (original, "image", "Original")]})

    assert win._note.text() == "Enhance 1 — 1 of 2"
    _shift(win, Qt.Key.Key_Right)
    assert win._note.text() == "Original — 2 of 2"


def test_an_image_with_one_version_says_nothing(qtbot, tmp_path):
    lone = _make_png(tmp_path / "only.png")
    win = FullscreenPreview((lone, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_levels({})
    assert win._note.isHidden()


def test_down_asks_for_the_image_on_screen_to_be_enhanced(qtbot, tmp_path):
    shown = _make_png(tmp_path / "a.png")
    asked = []
    win = FullscreenPreview((shown, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_enhance(lambda pid: asked.append(pid) or True, {str(shown): "id-a"})

    _plain(win, Qt.Key.Key_Down)

    assert asked == ["id-a"]
    assert win._note.text() == "Enhancing…"


def test_the_gallery_can_refuse_and_the_corner_stays_quiet(qtbot, tmp_path):
    shown = _make_png(tmp_path / "a.png")
    win = FullscreenPreview((shown, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_enhance(lambda pid: False, {str(shown): "id-a"})

    _plain(win, Qt.Key.Key_Down)

    assert win._note.isHidden()


def test_e_turns_the_enhance_gesture_off(qtbot, tmp_path):
    shown = _make_png(tmp_path / "a.png")
    asked = []
    win = FullscreenPreview((shown, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_enhance(lambda pid: asked.append(pid) or True, {str(shown): "id-a"})

    _plain(win, Qt.Key.Key_E)
    _plain(win, Qt.Key.Key_Down)
    assert asked == []
    assert "off" in win._note.text()


def test_the_enhanced_version_replaces_what_is_on_screen(qtbot, tmp_path):
    shown = _make_png(tmp_path / "a.png")
    better = _make_png(tmp_path / "a_enhanced.png")
    win = FullscreenPreview((shown, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_enhance(lambda pid: True, {str(shown): "id-a"})
    _plain(win, Qt.Key.Key_Down)

    win.note_enhanced("id-a", better)

    assert win._preview._media[0] == better
    assert win._note.isHidden()


def test_an_enhancement_for_something_else_leaves_the_screen_alone(qtbot, tmp_path):
    shown = _make_png(tmp_path / "a.png")
    win = FullscreenPreview((shown, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.set_enhance(lambda pid: True, {str(shown): "id-a"})

    win.note_enhanced("id-b", _make_png(tmp_path / "b_enhanced.png"))

    assert win._preview._media[0] == shown


def test_the_caption_keeps_clear_of_the_drive_console(qtbot, tmp_path):
    # The top-left corner is genau's console's — a caption there lands on top
    # of it — so this view's word about what it is showing goes along the
    # bottom, where the slideshow keeps its counter.
    enhanced, original = tmp_path / "e1.png", tmp_path / "src.png"
    for path in (enhanced, original):
        _make_png(path)
    win = FullscreenPreview((enhanced, "image"), player=MagicMock())
    qtbot.addWidget(win)
    win.resize(800, 600)
    win.set_levels({str(enhanced): [(enhanced, "image", "Enhance 1"),
                                    (original, "image", "Original")]})

    note = win._note.geometry()
    assert note.top() > win.height() // 2          # bottom half, not the top
    assert abs(note.center().x() - win.width() // 2) <= 1   # centered

# --- Up culls and Down bookmarks, as they do in the slideshow ----------------

def _armed(qtbot, index=0):
    """A fullscreen view paging a three-item folder that carries prompt ids."""
    view = FullscreenPreview(("a.png", "image"), player=MagicMock())
    qtbot.addWidget(view)
    view.set_playlist([("a.png", "image", "gen-a"),
                       ("b.png", "image", "gen-b"),
                       ("c.png", "image", "gen-c")], index)
    return view


def test_up_asks_for_the_shown_item_to_be_deleted_and_pages_off_it(qtbot):
    view = _armed(qtbot)
    asked = []
    view.delete_requested.connect(asked.append)

    _press(view, Qt.Key.Key_Up)

    assert asked == ["gen-a"]
    assert view._items == [("b.png", "image", "gen-b"), ("c.png", "image", "gen-c")]
    assert view._index == 0  # the one that followed it is on screen now


def test_deleting_the_last_item_closes_the_view(qtbot):
    view = FullscreenPreview(("a.png", "image"), player=MagicMock())
    qtbot.addWidget(view)
    view.set_playlist([("a.png", "image", "gen-a")], 0)
    view.show()

    _press(view, Qt.Key.Key_Up)

    assert not view.isVisible()


def test_down_bookmarks_the_shown_item_and_leaves_it_up(qtbot):
    view = _armed(qtbot, index=1)
    asked = []
    view.star_requested.connect(asked.append)

    _press(view, Qt.Key.Key_Down)

    assert asked == ["gen-b"]
    assert view._index == 1  # starring is not a move


def test_a_playlist_with_no_ids_ignores_up_and_down(qtbot):
    # A lone item, or a folder armed without ids: nothing to name, nothing to do.
    view = FullscreenPreview(("a.png", "image"), player=MagicMock())
    qtbot.addWidget(view)
    view.set_playlist([("a.png", "image"), ("b.png", "image")], 0)
    asked = []
    view.delete_requested.connect(asked.append)
    view.star_requested.connect(asked.append)

    _press(view, Qt.Key.Key_Up)
    _press(view, Qt.Key.Key_Down)

    assert asked == []
    assert len(view._items) == 2


def test_left_and_right_still_page_a_playlist_carrying_ids(qtbot):
    view = _armed(qtbot)
    _press(view, Qt.Key.Key_Right)
    assert view._index == 1
    _press(view, Qt.Key.Key_Left)
    assert view._index == 0
