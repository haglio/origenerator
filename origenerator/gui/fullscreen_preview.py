"""A fullscreen view of a single image or video, opened by double-clicking a
preview. Escape or another double-click closes it.

Armed with the folder it was opened from (:meth:`set_playlist`) it is the
slideshow without the shuffling and the clock: Left/Right page through that
folder, Up culls the item on screen and Down keeps it — bookmarking it and asking
for it to be enhanced, exactly as the slideshow's Down does — so the two
fullscreen views are one thing to learn. It wears the slideshow's two furnishings
for the same reason: the "3 / 17" plate over the bottom of the media and the
stills of the items either side of it. Shift+Left/Right is the axis this one
adds: the enhancement levels of the image on screen.

It also opens over a generation that's still running: built with no media, it
shows that generation's streamed low-res frames (:meth:`show_frame`) until the
pane that opened it hands over the finished file (:meth:`show_landed`), at which
point it's an ordinary fullscreen view of that file. So a generation can be
watched full-screen while it's made, not only once it lands.

Reuses :class:`PreviewWidget` (looping, like the inline preview) for the actual
rendering, over a solid black surround. The media is scaled as large as it fits
the screen without cropping, so a shape that doesn't match the screen letterboxes
on two sides at most — never stranded small with black on all four. Opened by
:meth:`PreviewWidget.open_fullscreen`; the opening preview keeps the reference
alive, mirroring how the gallery holds its slideshow window.

Being the deliberate foreground view, it plays sound (the inline preview stays
muted) and exposes its :meth:`osr2_drive_target`, so the gallery can drive the OSR2
off the video on screen for as long as it's up — whenever the global Drive-OSR2
toggle is on, which gates this surface exactly as it gates the inline preview. It
signals :attr:`closed` on dismissal so the device is handed back.
"""

from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from origenerator.gui.neighbor_previews import NeighborPreviews, still_for
from origenerator.gui.osr2_driver import drive_target_for
from origenerator.gui.position_caption import PositionCaption
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.stroke_hud import apply_stroke_key
from origenerator.gui.stroke_panel import StrokePanel

_GENERATING = "Generating…"


class FullscreenPreview(QWidget):
    closed = pyqtSignal()  # the view was dismissed (Esc, a double-click, or close)
    media_changed = pyqtSignal()  # paged to a different item (re-aim the OSR2 drive)
    delete_requested = pyqtSignal(str)  # Up on an item (prompt_id): trash it
    star_requested = pyqtSignal(str)    # Down on an item (prompt_id): bookmark it

    def __init__(self, media: tuple | None, *, frame: bytes | None = None,
                 player=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview")
        # The navigable folder: a lone item until set_playlist arms Left/Right to
        # page across the folder the view was opened from. Empty while following a
        # running generation — it has no file to page from yet.
        self._items: list[tuple] = [media] if media is not None else []
        self._index = 0
        # The enhancement levels of each item that has any, keyed by the file
        # the folder lists it under, so Shift+Left/Right steps the versions of
        # whatever is on screen. The base path is remembered separately: once
        # you have stepped onto a level, the file showing is no longer the key.
        self._levels_by_path: dict[str, list[tuple]] = {}
        self._level_base: str | None = None
        self._level_index = 0
        # Asking for an enhancement from here, as the slideshow does: the
        # prompt id of each item the folder shows, the callback that decides
        # whether a run is wanted, and which images have one in flight.
        self._ids_by_path: dict[str, str] = {}
        self._on_enhance = None
        self._enhance_enabled = False
        self._enhancing: set[str] = set()
        # Following a generation still in flight: no media of its own, so the pane
        # that opened it feeds the frames and hands over the file that lands.
        self._live = media is None
        # The gallery hands its app-global stroke driver in via set_stroke once
        # this view announces itself; until then the stroke keys are inert.
        self._stroke = None
        self._stroke_panel: StrokePanel | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(True)  # a solid black surround behind the media
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("black"))
        self.setPalette(palette)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # This preview *is* the fullscreen view, so it opts out of opening another —
        # and a double-click on it (the media fills the window) dismisses the view. It
        # plays sound (mute_audio=False), unlike the muted inline preview.
        self._preview = PreviewWidget(player=player, allow_fullscreen=False,
                                      show_funscript_strip=True, mute_audio=False,
                                      on_double_click=self.close)
        layout.addWidget(self._preview, 1)
        # A caption along the bottom: which version of this image is on screen
        # and how many there are, and "Enhancing…" while one is being made.
        # Stepping levels is invisible without it — two versions of one picture
        # differ by texture, which is exactly what you cannot tell apart from
        # memory. Bottom center, where a view's word about what it is showing
        # goes; the top-left corner is genau's console's, and a caption there
        # lands on top of it.
        self._note = QLabel(self)
        self._note.setStyleSheet(
            "color: white; background: rgba(0, 0, 0, 160);"
            " padding: 6px 12px; border-radius: 4px;"
        )
        self._note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._note.hide()
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self._refresh_note)
        # The same two furnishings the slideshow floats over its media: where in
        # the folder this one is, and the items either side of it.
        self._counter = PositionCaption(self)
        self._counter.hide()  # nothing to count until a playlist is armed
        self._neighbors = NeighborPreviews(self)
        self._preview.media_resized.connect(self._reposition_neighbors)
        if media is not None:
            self._preview.show_media(media[0], media[1])
        elif frame is not None:
            self._preview.show_frame(frame)  # the frame the double-click landed on
        else:
            self._preview.show_message(_GENERATING)  # opened before the first one

    def is_live(self) -> bool:
        """Whether this view is still following a generation in flight — the pane
        that opened it checks before feeding it another frame or its result."""
        return self._live

    def show_frame(self, data: bytes) -> None:
        """One more streamed frame of the generation being followed. Ignored once
        it has landed (or the view has paged away), which is no longer this run."""
        if self._live:
            self._preview.show_frame(data)

    def show_landed(self, media: tuple) -> None:
        """The followed generation finished: show the saved file in place of its
        frames, and become an ordinary fullscreen view of it — a finished video is
        a fresh OSR2 target, hence ``media_changed``."""
        if not self._live:
            return
        self._live = False
        self._items = [media]
        self._index = 0
        self._preview.show_media(media[0], media[1])
        self._show_surroundings()
        self.media_changed.emit()

    def set_playlist(self, items: list[tuple], index: int) -> None:
        """Arm Left/Right to page across the folder the view was opened from.

        ``items`` is the folder's media in shown order as ``(path, media_type)``,
        optionally followed by its ``prompt_id`` — what Up and Down act on, so a
        folder can be culled and bookmarked without leaving the view — and its
        stored thumbnail, the only still a video has for the neighbor previews.
        ``index`` is the one already on screen. Until this is called the view holds
        a lone item and paging is inert.
        """
        self._items = list(items)
        self._index = index
        self._show_surroundings()

    def _show_surroundings(self) -> None:
        """Say where in the folder this is, and draw the items either side of it.

        Nothing to say for a folder of one — or for a view following a generation
        still being made, which has no place among the folder's files until an
        arrow leaves it for one.
        """
        if len(self._items) < 2 or self._live:
            self._counter.hide()
            self._neighbors.set_neighbors(None, None)
            return
        self._counter.show()
        self._counter.show_position(self._index + 1, len(self._items))
        self._neighbors.set_neighbors(
            still_for(self._items[(self._index - 1) % len(self._items)]),
            still_for(self._items[(self._index + 1) % len(self._items)]),
            media_rect=self._media_rect(),
        )

    def _reposition_neighbors(self) -> None:
        self._neighbors.reposition(self._media_rect())

    def _media_rect(self):
        """Where the media is drawn, in this view's coordinates."""
        rect = self._preview.media_rect()
        rect.moveTopLeft(self._preview.mapTo(self, rect.topLeft()))
        return rect

    def set_levels(self, levels_by_path: dict) -> None:
        """Arm Shift+Left/Right to step an image's enhancement levels.

        ``levels_by_path`` maps the file the folder shows an image under to that
        image's versions, newest first, as ``(path, media_type, label)``. Plain
        Left/Right still pages the folder; the shifted pair moves within the one
        image — its own axis, because a version is not a neighbor.
        """
        self._levels_by_path = {str(k): list(v) for k, v in levels_by_path.items()}
        self._refresh_note()

    def set_enhance(self, on_enhance, ids_by_path: dict) -> None:
        """Wire Down to ask for the image on screen to be enhanced.

        The same gesture the slideshow uses, for the same reason — stopping on a
        picture is what says you want it, and here you have already stopped. The
        gallery decides whether a run is wanted (it holds the settings and the
        levels); ``True`` back means one started. ``E`` turns it off.
        """
        self._on_enhance = on_enhance
        self._ids_by_path = {str(k): v for k, v in ids_by_path.items()}
        self._enhance_enabled = on_enhance is not None

    def note_enhanced(self, prompt_id: str, path, media_type: str = "image") -> None:
        """An enhancement asked for from here landed: show it in place, if this
        view is still on the image that asked."""
        self._enhancing.discard(prompt_id)
        if self._current_prompt_id() == prompt_id:
            self._level_base = None  # its versions are a level deeper now
            self._level_index = 0
            self._preview.show_media(path, media_type)
            self.media_changed.emit()
        self._refresh_note()

    def _current_prompt_id(self) -> str | None:
        base = self._level_base
        if base is None and self._items:
            base = str(self._items[self._index][0])
        return self._ids_by_path.get(base or "")

    def _enhance_current(self) -> None:
        if self._on_enhance is None or not self._enhance_enabled:
            return
        prompt_id = self._current_prompt_id()
        if prompt_id is None or prompt_id in self._enhancing:
            return
        if self._on_enhance(prompt_id):
            self._enhancing.add(prompt_id)
            self._refresh_note()

    def _toggle_enhance(self) -> None:
        if self._on_enhance is None:
            return
        self._enhance_enabled = not self._enhance_enabled
        self._flash_note(
            "Enhance on Down: on" if self._enhance_enabled else "Enhance on Down: off"
        )

    # --- the corner caption -------------------------------------------------

    def _refresh_note(self) -> None:
        """Say which version is on screen, of how many — or that one is cooking."""
        prompt_id = self._current_prompt_id()
        if prompt_id is not None and prompt_id in self._enhancing:
            self._show_note("Enhancing…")
            return
        levels = self._levels_by_path.get(self._level_base or self._current_base()) or []
        if len(levels) <= 1:
            self._note.hide()
            return
        level = levels[self._level_index]
        label = level[2] if len(level) > 2 else f"Version {self._level_index + 1}"
        self._show_note(f"{label} — {self._level_index + 1} of {len(levels)}")

    def _current_base(self) -> str:
        return str(self._items[self._index][0]) if self._items else ""

    def _show_note(self, text: str) -> None:
        self._note.setText(text)
        self._note.show()
        self._reposition_note()

    def _reposition_note(self) -> None:
        """Centered just above the position plate, exactly as the slideshow
        stacks its own — everything a fullscreen view says about the item on
        screen reads as one group at the bottom, clear of genau's console in the
        top-left corner."""
        self._note.adjustSize()
        self._counter.adjustSize()
        floor = self._counter.height() if not self._counter.isHidden() else 0
        self._note.move((self.width() - self._note.width()) // 2,
                        max(0, self.height() - floor - self._note.height() - 30))
        self._note.raise_()

    def _flash_note(self, text: str, ms: int = 1500) -> None:
        self._show_note(text)
        self._note_timer.start(ms)

    # --- culling and keeping, the slideshow's two verticals ------------------

    def _current_id(self) -> str | None:
        """The prompt id of the item on screen, when the playlist carries one."""
        if not self._items or self._index >= len(self._items):
            return None
        item = self._items[self._index]
        return item[2] if len(item) > 2 else None

    def _delete_current(self) -> None:
        """Up: hand the item on screen to the gallery to trash, then page off it.

        The view holds no database, so the deletion is asked for; what it does own
        is what is on screen, and a culled item must not stay there.
        """
        prompt_id = self._current_id()
        if prompt_id is None:
            return
        del self._items[self._index]
        self.delete_requested.emit(prompt_id)
        if not self._items:
            self.close()
            return
        self._index %= len(self._items)
        self._preview.show_media(*self._items[self._index][:2])
        self._show_surroundings()
        self.media_changed.emit()

    def _star_current(self) -> None:
        """Bookmark the item on screen. It stays up — starring is not a move."""
        prompt_id = self._current_id()
        if prompt_id is not None:
            self.star_requested.emit(prompt_id)

    def _hold_current(self) -> None:
        """Down: bookmark the image on screen, and ask for it to be enhanced.

        The slideshow's Down does both off one press (there it locks the slide
        too, which is the only thing this view has no clock to hold against), and
        the two fullscreen views are meant to be one thing to learn — so stopping
        on a picture says you want it in exactly the same two ways here.
        """
        self._star_current()
        self._enhance_current()

    def set_stroke(self, stroke) -> None:
        """Wire the shared OSR2 stroke keys and genau's drive panel in — so the
        device can run over a fullscreen image, which has no script."""
        self._stroke = stroke
        if self._stroke_panel is None and stroke is not None:
            self._stroke_panel = StrokePanel(stroke, self)
            self._stroke_panel.reposition()
            self._stroke_panel.show()

    def release_media(self, paths) -> None:
        """Dismiss the view when what it's showing is about to be deleted: its
        video holds the file open, which would block the delete, and a
        fullscreen view of a file that's going is nothing to keep up."""
        if self._preview.is_showing_any(paths):
            self.close()  # closeEvent clears the preview, releasing the file

    def osr2_drive_target(self):
        """``(video_path, player, actions)`` for the video on screen, or ``None`` for
        an image or a video with no funscript — mirrors the config panel's target so
        the view can point its one driver at whichever surface is foreground."""
        return drive_target_for(self._preview.current_video_path(), self._preview.player())

    def keyPressEvent(self, event):
        key = event.key()
        shifted = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key == Qt.Key.Key_Left:
            self._step_level(-1) if shifted else self._step(-1)
        elif key == Qt.Key.Key_Right:
            self._step_level(1) if shifted else self._step(1)
        elif key == Qt.Key.Key_Up:
            self._delete_current()   # cull this one, as the slideshow's Up does
        elif key == Qt.Key.Key_Down:
            self._hold_current()     # keep it, as the slideshow's Down does
        elif key == Qt.Key.Key_E:
            self._toggle_enhance()
        elif apply_stroke_key(self._stroke, key):
            self._stroke_panel.refresh()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._counter.reposition()
        self._reposition_neighbors()
        if self._stroke_panel is not None:
            self._stroke_panel.reposition()
        if not self._note.isHidden():
            self._reposition_note()

    def _step(self, delta: int) -> None:
        """Page ``delta`` items through the folder, wrapping at either end."""
        if len(self._items) <= 1:
            return
        self._live = False  # paged off a live generation: its frames stop landing here
        self._index = (self._index + delta) % len(self._items)
        self._level_base = None  # a new image, so its own versions from the top
        self._level_index = 0
        self._preview.show_media(*self._items[self._index][:2])
        self._refresh_note()
        self._show_surroundings()
        self.media_changed.emit()  # a different clip may need the OSR2 re-aimed

    def _step_level(self, delta: int) -> None:
        """Step ``delta`` enhancement levels within the image on screen.

        A no-op for an image with one version, and for a video — there is
        nothing to compare it against, and silently doing nothing is better
        than paging the folder when the shift was the whole point.
        """
        base = self._level_base
        if base is None:
            if not self._items:
                return
            base = str(self._items[self._index][0])
        levels = self._levels_by_path.get(base) or []
        if len(levels) <= 1:
            return
        self._live = False
        self._level_base = base
        self._level_index = (self._level_index + delta) % len(levels)
        self._preview.show_media(*levels[self._level_index][:2])
        self._refresh_note()

    def mouseDoubleClickEvent(self, event):
        self.close()  # a second double-click dismisses the fullscreen view

    def closeEvent(self, event):
        self._preview.clear()  # release any held video file so it can be deleted
        self.closed.emit()     # the view hands the OSR2 back to the toggle (or stops)
        super().closeEvent(event)
